"""Persistent research-run state for the ScanSci desktop agent.

The notebook workspace owns durable research execution state.  This module is
deliberately model- and tool-agnostic: the web application executes tools while
the store records stages, calls, artifacts, evidence links, and recovery state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence
from uuid import uuid4


RUN_STATUSES = {
    "draft",
    "queued",
    "planning",
    "running",
    "needs_confirmation",
    "paused",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}
STAGE_STATUSES = {"pending", "running", "paused", "completed", "failed", "cancelled", "skipped"}
ACTIVE_RUN_STATUSES = {"queued", "planning", "running", "verifying"}
RESUMABLE_RUN_STATUSES = {"paused", "failed", "cancelled"}


@dataclass(frozen=True)
class StageSpec:
    key: str
    title: str
    kind: str
    tool_name: str = ""


class ResearchRunStore:
    """SQLite-backed state machine shared by the UI and research workers."""

    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace = Path(workspace_path)
        self.workspace.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._initialize_schema(connection)
            connection.commit()

    def create_run(
        self,
        *,
        notebook_id: str,
        workflow_type: str,
        title: str,
        input_payload: dict[str, Any],
        stages: Sequence[StageSpec],
        model_provider_id: str = "",
        model_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not stages:
            raise ValueError("A research run requires at least one stage")
        run_id = _new_id("run")
        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            connection.execute(
                """
                insert into research_runs (
                  run_id, notebook_id, workflow_type, title, status,
                  current_stage, progress, input_json, output_artifact_id,
                  cancel_requested, error_code, error_message,
                  model_provider_id, model_id, created_at, updated_at,
                  started_at, completed_at, metadata_json
                ) values (?, ?, ?, ?, 'queued', ?, 0, ?, '', 0, '', '', ?, ?, ?, ?, '', '', ?)
                """,
                (
                    run_id,
                    str(notebook_id),
                    str(workflow_type),
                    str(title).strip() or "未命名研究任务",
                    stages[0].key,
                    _json_dumps(input_payload),
                    str(model_provider_id),
                    str(model_id),
                    now,
                    now,
                    _json_dumps(metadata or {}),
                ),
            )
            for position, stage in enumerate(stages):
                connection.execute(
                    """
                    insert into research_stages (
                      stage_id, run_id, stage_key, position, title, kind,
                      tool_name, status, attempt, started_at, completed_at,
                      summary, error_message, input_json, output_json
                    ) values (?, ?, ?, ?, ?, ?, ?, 'pending', 0, '', '', '', '', '{}', '{}')
                    """,
                    (
                        _new_id("stage"),
                        run_id,
                        stage.key,
                        position,
                        stage.title,
                        stage.kind,
                        stage.tool_name,
                    ),
                )
            connection.commit()
        return self.get_run(run_id)

    def list_runs(
        self,
        *,
        notebook_id: str = "",
        limit: int = 50,
        archived: bool | None = False,
    ) -> list[dict[str, Any]]:
        limit_value = min(200, max(1, int(limit)))
        with self._connect() as connection:
            self._initialize_schema(connection)
            conditions: list[str] = []
            values: list[Any] = []
            if notebook_id:
                conditions.append("notebook_id = ?")
                values.append(str(notebook_id))
            if archived is True:
                conditions.append("archived_at <> ''")
            elif archived is False:
                conditions.append("archived_at = ''")
            where = f"where {' and '.join(conditions)}" if conditions else ""
            rows = connection.execute(
                f"""
                select * from research_runs
                {where}
                order by updated_at desc, created_at desc
                limit ?
                """,
                (*values, limit_value),
            ).fetchall()
            return [self._run_summary(connection, row) for row in rows]

    def archive_run(self, run_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            row = self._require_manageable_run(connection, run_id)
            if str(row["archived_at"]):
                return self.get_run(run_id)
            connection.execute(
                "update research_runs set archived_at = ?, updated_at = ? where run_id = ?",
                (now, now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def restore_run(self, run_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            self._require_run(connection, run_id)
            connection.execute(
                "update research_runs set archived_at = '', updated_at = ? where run_id = ?",
                (now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def delete_run(self, run_id: str) -> dict[str, Any]:
        """Permanently remove one conversation while preserving exported files."""

        with self._connect() as connection:
            self._initialize_schema(connection)
            row = self._require_manageable_run(connection, run_id)
            title = str(row["title"])
            connection.execute("delete from research_evidence_links where run_id = ?", (run_id,))
            connection.execute("delete from research_tool_calls where run_id = ?", (run_id,))
            connection.execute("delete from research_run_messages where run_id = ?", (run_id,))
            connection.execute("delete from research_artifacts where run_id = ?", (run_id,))
            connection.execute("delete from research_stages where run_id = ?", (run_id,))
            connection.execute("delete from research_runs where run_id = ?", (run_id,))
            connection.commit()
        return {"ok": True, "run_id": run_id, "title": title, "deleted": True}

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            self._initialize_schema(connection)
            row = connection.execute("select * from research_runs where run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise FileNotFoundError(f"Research run does not exist: {run_id}")
            payload = self._run_summary(connection, row)
            payload["input"] = _json_loads(row["input_json"])
            payload["metadata"] = _json_loads(row["metadata_json"])
            payload["stages"] = [
                self._stage_payload(stage)
                for stage in connection.execute(
                    "select * from research_stages where run_id = ? order by position", (run_id,)
                ).fetchall()
            ]
            payload["tool_calls"] = [
                self._tool_call_payload(call)
                for call in connection.execute(
                    "select * from research_tool_calls where run_id = ? order by started_at, tool_call_id", (run_id,)
                ).fetchall()
            ]
            payload["messages"] = [
                self._message_payload(message)
                for message in connection.execute(
                    "select * from research_run_messages where run_id = ? order by rowid", (run_id,)
                ).fetchall()
            ]
            artifacts = [
                self._artifact_payload(connection, artifact)
                for artifact in connection.execute(
                    "select * from research_artifacts where run_id = ? order by created_at", (run_id,)
                ).fetchall()
            ]
            payload["artifacts"] = artifacts
            payload["output_artifact"] = next(
                (item for item in artifacts if item["artifact_id"] == payload["output_artifact_id"]), None
            )
            return payload

    def append_message(
        self,
        run_id: str,
        *,
        role: str,
        content: str,
        usage: dict[str, Any] | None = None,
        processing_ms: int = 0,
    ) -> dict[str, Any]:
        """Persist a follow-up turn against an existing research task.

        A task can therefore remain the single source of truth for its output
        artifact and all conversations that refine or explain that output.
        """

        normalized_role = str(role).strip().lower()
        normalized_content = str(content).strip()
        if normalized_role not in {"user", "assistant"}:
            raise ValueError("Research-run messages must be user or assistant messages")
        if not normalized_content:
            raise ValueError("Research-run message content is required")
        now = _utc_now()
        message_id = _new_id("message")
        with self._connect() as connection:
            self._initialize_schema(connection)
            self._require_run(connection, run_id)
            connection.execute(
                """
                insert into research_run_messages (
                  message_id, run_id, role, content, usage_json, processing_ms, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    run_id,
                    normalized_role,
                    normalized_content,
                    _json_dumps(usage or {}),
                    max(0, int(processing_ms or 0)),
                    now,
                ),
            )
            # A follow-up should also move the original task to the top of the
            # history list; it must never create a second pseudo-conversation.
            connection.execute("update research_runs set updated_at = ? where run_id = ?", (now, run_id))
            connection.commit()
        return {
            "message_id": message_id,
            "run_id": run_id,
            "role": normalized_role,
            "content": normalized_content,
            "usage": usage or {},
            "processing_ms": max(0, int(processing_ms or 0)),
            "created_at": now,
        }

    def recover_interrupted_runs(self) -> int:
        """Pause active runs left behind by an application restart."""
        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
            rows = connection.execute(
                f"select run_id from research_runs where status in ({placeholders})", tuple(ACTIVE_RUN_STATUSES)
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            if run_ids:
                run_placeholders = ",".join("?" for _ in run_ids)
                connection.execute(
                    f"""
                    update research_runs
                    set status = 'paused', updated_at = ?, error_code = 'app_restarted',
                        error_message = '应用已重启，可从当前阶段继续。'
                    where run_id in ({run_placeholders})
                    """,
                    (now, *run_ids),
                )
                connection.execute(
                    f"""
                    update research_stages
                    set status = 'paused', summary = '应用重启后等待继续'
                    where run_id in ({run_placeholders}) and status = 'running'
                    """,
                    tuple(run_ids),
                )
            connection.commit()
            return len(run_ids)

    def begin_run(self, run_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            row = self._require_run(connection, run_id)
            status = str(row["status"])
            if status not in {"queued", "paused", "failed", "cancelled"}:
                raise ValueError(f"Research run cannot start from status: {status}")
            connection.execute(
                """
                update research_runs
                set status = 'running', cancel_requested = 0, error_code = '', error_message = '',
                    started_at = case when started_at = '' then ? else started_at end,
                    completed_at = '', updated_at = ?
                where run_id = ?
                """,
                (now, now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def request_cancel(self, run_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            row = self._require_run(connection, run_id)
            status = str(row["status"])
            if status in {"completed", "failed", "cancelled"}:
                return self.get_run(run_id)
            connection.execute(
                "update research_runs set cancel_requested = 1, updated_at = ? where run_id = ?",
                (now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def cancel_requested(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = self._require_run(connection, run_id)
            return bool(row["cancel_requested"])

    def mark_cancelled(self, run_id: str, *, summary: str = "任务已停止") -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                """
                update research_stages set status = 'cancelled', completed_at = ?, summary = ?
                where run_id = ? and status in ('pending', 'running', 'paused')
                """,
                (now, summary, run_id),
            )
            connection.execute(
                """
                update research_runs
                set status = 'cancelled', cancel_requested = 0, completed_at = ?, updated_at = ?,
                    error_code = '', error_message = ?
                where run_id = ?
                """,
                (now, now, summary, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def prepare_resume(self, run_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            row = self._require_run(connection, run_id)
            status = str(row["status"])
            if status not in RESUMABLE_RUN_STATUSES:
                raise ValueError(f"Research run is not resumable from status: {status}")
            connection.execute(
                """
                update research_stages
                set status = 'pending', started_at = '', completed_at = '', summary = '', error_message = ''
                where run_id = ? and status in ('running', 'paused', 'failed', 'cancelled')
                """,
                (run_id,),
            )
            next_stage = connection.execute(
                """
                select stage_key from research_stages
                where run_id = ? and status != 'completed'
                order by position limit 1
                """,
                (run_id,),
            ).fetchone()
            if next_stage is None:
                raise ValueError("Research run has no remaining stage to resume")
            connection.execute(
                """
                update research_runs
                set status = 'queued', current_stage = ?, cancel_requested = 0,
                    completed_at = '', error_code = '', error_message = '', updated_at = ?
                where run_id = ?
                """,
                (next_stage["stage_key"], now, run_id),
            )
            self._refresh_progress(connection, run_id)
            connection.commit()
        return self.get_run(run_id)

    def start_stage(self, run_id: str, stage_key: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            stage = self._require_stage(connection, run_id, stage_key)
            if str(stage["status"]) == "completed":
                return self._stage_payload(stage)
            run_status = {
                "planner": "planning",
                "verification": "verifying",
            }.get(str(stage["kind"]), "running")
            connection.execute(
                """
                update research_stages
                set status = 'running', attempt = attempt + 1, started_at = ?, completed_at = '',
                    summary = '', error_message = ''
                where run_id = ? and stage_key = ?
                """,
                (now, run_id, stage_key),
            )
            connection.execute(
                "update research_runs set status = ?, current_stage = ?, updated_at = ? where run_id = ?",
                (run_status, stage_key, now, run_id),
            )
            connection.commit()
            return self._stage_payload(self._require_stage(connection, run_id, stage_key))

    def complete_stage(
        self,
        run_id: str,
        stage_key: str,
        *,
        summary: str = "",
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            self._require_stage(connection, run_id, stage_key)
            connection.execute(
                """
                update research_stages
                set status = 'completed', completed_at = ?, summary = ?, output_json = ?, error_message = ''
                where run_id = ? and stage_key = ?
                """,
                (now, str(summary), _json_dumps(output or {}), run_id, stage_key),
            )
            self._refresh_progress(connection, run_id)
            connection.execute("update research_runs set updated_at = ? where run_id = ?", (now, run_id))
            connection.commit()
        return self.get_run(run_id)

    def fail_stage(self, run_id: str, stage_key: str, error: Exception) -> dict[str, Any]:
        now = _utc_now()
        message = str(error) or error.__class__.__name__
        with self._connect() as connection:
            self._require_stage(connection, run_id, stage_key)
            connection.execute(
                """
                update research_stages
                set status = 'failed', completed_at = ?, error_message = ?
                where run_id = ? and stage_key = ?
                """,
                (now, message, run_id, stage_key),
            )
            connection.execute(
                """
                update research_runs
                set status = 'failed', error_code = 'stage_failed', error_message = ?,
                    completed_at = ?, updated_at = ? where run_id = ?
                """,
                (message, now, now, run_id),
            )
            self._refresh_progress(connection, run_id)
            connection.commit()
        return self.get_run(run_id)

    def complete_run(self, run_id: str, *, output_artifact_id: str = "") -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                """
                update research_runs
                set status = 'completed', progress = 1, current_stage = '', output_artifact_id = ?,
                    cancel_requested = 0, error_code = '', error_message = '', completed_at = ?, updated_at = ?
                where run_id = ?
                """,
                (str(output_artifact_id), now, now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def stage_output(self, run_id: str, stage_key: str) -> dict[str, Any]:
        with self._connect() as connection:
            stage = self._require_stage(connection, run_id, stage_key)
            return _json_loads(stage["output_json"])

    def begin_tool_call(
        self,
        run_id: str,
        stage_key: str,
        *,
        tool_name: str,
        input_payload: dict[str, Any],
    ) -> str:
        call_id = _new_id("call")
        now = _utc_now()
        with self._connect() as connection:
            stage = self._require_stage(connection, run_id, stage_key)
            connection.execute(
                """
                insert into research_tool_calls (
                  tool_call_id, run_id, stage_id, tool_name, status,
                  input_json, output_json, error_message, started_at, completed_at, duration_ms
                ) values (?, ?, ?, ?, 'running', ?, '{}', '', ?, '', 0)
                """,
                (call_id, run_id, stage["stage_id"], str(tool_name), _json_dumps(input_payload), now),
            )
            connection.commit()
        return call_id

    def complete_tool_call(self, tool_call_id: str, output: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            row = self._require_tool_call(connection, tool_call_id)
            duration = _duration_ms(str(row["started_at"]), now)
            connection.execute(
                """
                update research_tool_calls
                set status = 'completed', output_json = ?, completed_at = ?, duration_ms = ?, error_message = ''
                where tool_call_id = ?
                """,
                (_json_dumps(output), now, duration, tool_call_id),
            )
            connection.commit()
            return self._tool_call_payload(self._require_tool_call(connection, tool_call_id))

    def fail_tool_call(self, tool_call_id: str, error: Exception) -> dict[str, Any]:
        now = _utc_now()
        message = str(error) or error.__class__.__name__
        with self._connect() as connection:
            row = self._require_tool_call(connection, tool_call_id)
            duration = _duration_ms(str(row["started_at"]), now)
            connection.execute(
                """
                update research_tool_calls
                set status = 'failed', completed_at = ?, duration_ms = ?, error_message = ?
                where tool_call_id = ?
                """,
                (now, duration, message, tool_call_id),
            )
            connection.commit()
            return self._tool_call_payload(self._require_tool_call(connection, tool_call_id))

    def create_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        title: str,
        summary: str,
        payload: dict[str, Any],
        evidence_links: Iterable[dict[str, Any]] = (),
        file_path: str = "",
        schema_version: str = "research_artifact.v1",
    ) -> dict[str, Any]:
        artifact_id = _new_id("artifact")
        now = _utc_now()
        with self._connect() as connection:
            run = self._require_run(connection, run_id)
            connection.execute(
                """
                insert into research_artifacts (
                  artifact_id, run_id, notebook_id, artifact_type, schema_version,
                  title, summary, payload_json, file_path, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    run["notebook_id"],
                    str(artifact_type),
                    str(schema_version),
                    str(title),
                    str(summary),
                    _json_dumps(payload),
                    str(file_path),
                    now,
                ),
            )
            for link in evidence_links:
                item = dict(link)
                connection.execute(
                    """
                    insert into research_evidence_links (
                      evidence_link_id, artifact_id, run_id, evidence_id, doc_id,
                      html_anchor, source_href, relationship, quote_snapshot, metadata_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("evidence"),
                        artifact_id,
                        run_id,
                        str(item.get("evidence_id", "")),
                        str(item.get("doc_id", "")),
                        str(item.get("html_anchor", "")),
                        str(item.get("source_href", "") or item.get("reader_url", "")),
                        str(item.get("relationship", "supports")),
                        str(item.get("exact_quote", "") or item.get("quote_snapshot", "")),
                        _json_dumps(dict(item.get("metadata", {}) or {})),
                    ),
                )
            connection.commit()
            row = connection.execute(
                "select * from research_artifacts where artifact_id = ?", (artifact_id,)
            ).fetchone()
            return self._artifact_payload(connection, row)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.workspace, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute("pragma busy_timeout = 15000")
        return connection

    @staticmethod
    def _initialize_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            create table if not exists research_runs (
              run_id text primary key,
              notebook_id text not null,
              workflow_type text not null,
              title text not null,
              status text not null,
              current_stage text not null,
              progress real not null,
              input_json text not null,
              output_artifact_id text not null,
              cancel_requested integer not null,
              error_code text not null,
              error_message text not null,
              model_provider_id text not null,
              model_id text not null,
              created_at text not null,
              updated_at text not null,
              started_at text not null,
              completed_at text not null,
              metadata_json text not null,
              archived_at text not null default ''
            );
            create table if not exists research_stages (
              stage_id text primary key,
              run_id text not null,
              stage_key text not null,
              position integer not null,
              title text not null,
              kind text not null,
              tool_name text not null,
              status text not null,
              attempt integer not null,
              started_at text not null,
              completed_at text not null,
              summary text not null,
              error_message text not null,
              input_json text not null,
              output_json text not null,
              unique(run_id, stage_key),
              foreign key(run_id) references research_runs(run_id)
            );
            create table if not exists research_tool_calls (
              tool_call_id text primary key,
              run_id text not null,
              stage_id text not null,
              tool_name text not null,
              status text not null,
              input_json text not null,
              output_json text not null,
              error_message text not null,
              started_at text not null,
              completed_at text not null,
              duration_ms integer not null,
              foreign key(run_id) references research_runs(run_id),
              foreign key(stage_id) references research_stages(stage_id)
            );
            create table if not exists research_artifacts (
              artifact_id text primary key,
              run_id text not null,
              notebook_id text not null,
              artifact_type text not null,
              schema_version text not null,
              title text not null,
              summary text not null,
              payload_json text not null,
              file_path text not null,
              created_at text not null,
              foreign key(run_id) references research_runs(run_id)
            );
            create table if not exists research_evidence_links (
              evidence_link_id text primary key,
              artifact_id text not null,
              run_id text not null,
              evidence_id text not null,
              doc_id text not null,
              html_anchor text not null,
              source_href text not null,
              relationship text not null,
              quote_snapshot text not null,
              metadata_json text not null,
              foreign key(artifact_id) references research_artifacts(artifact_id),
              foreign key(run_id) references research_runs(run_id)
            );
            create table if not exists research_run_messages (
              message_id text primary key,
              run_id text not null,
              role text not null,
              content text not null,
              usage_json text not null,
              processing_ms integer not null,
              created_at text not null,
              foreign key(run_id) references research_runs(run_id)
            );
            create index if not exists idx_research_runs_notebook on research_runs(notebook_id, updated_at);
            create index if not exists idx_research_stages_run on research_stages(run_id, position);
            create index if not exists idx_research_calls_run on research_tool_calls(run_id, started_at);
            create index if not exists idx_research_artifacts_run on research_artifacts(run_id, created_at);
            create index if not exists idx_research_evidence_artifact on research_evidence_links(artifact_id);
            create index if not exists idx_research_messages_run on research_run_messages(run_id, created_at);
            """
        )
        columns = {str(row["name"]) for row in connection.execute("pragma table_info(research_runs)")}
        if "archived_at" not in columns:
            connection.execute("alter table research_runs add column archived_at text not null default ''")
        connection.execute(
            "create index if not exists idx_research_runs_archived on research_runs(archived_at, updated_at)"
        )

    def _run_summary(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        stage_counts = connection.execute(
            """
            select count(*) as total,
                   sum(case when status = 'completed' then 1 else 0 end) as completed
            from research_stages where run_id = ?
            """,
            (row["run_id"],),
        ).fetchone()
        return {
            "run_id": str(row["run_id"]),
            "notebook_id": str(row["notebook_id"]),
            "workflow_type": str(row["workflow_type"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "current_stage": str(row["current_stage"]),
            "progress": float(row["progress"]),
            "output_artifact_id": str(row["output_artifact_id"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "error": {
                "code": str(row["error_code"]),
                "message": str(row["error_message"]),
            },
            "model": {
                "provider_id": str(row["model_provider_id"]),
                "model_id": str(row["model_id"]),
            },
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"]),
            "archived_at": str(row["archived_at"]),
            "archived": bool(row["archived_at"]),
            "stage_counts": {
                "total": int(stage_counts["total"] or 0),
                "completed": int(stage_counts["completed"] or 0),
            },
            "resumable": str(row["status"]) in RESUMABLE_RUN_STATUSES,
            "cancellable": str(row["status"]) in ACTIVE_RUN_STATUSES,
        }

    @staticmethod
    def _require_manageable_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = ResearchRunStore._require_run(connection, run_id)
        if str(row["status"]) in ACTIVE_RUN_STATUSES | {"needs_confirmation"}:
            raise ValueError("运行中的对话不能归档或删除，请先等待任务结束或停止任务。")
        return row

    @staticmethod
    def _stage_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "stage_id": str(row["stage_id"]),
            "run_id": str(row["run_id"]),
            "key": str(row["stage_key"]),
            "position": int(row["position"]),
            "title": str(row["title"]),
            "kind": str(row["kind"]),
            "tool_name": str(row["tool_name"]),
            "status": str(row["status"]),
            "attempt": int(row["attempt"]),
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"]),
            "summary": str(row["summary"]),
            "error_message": str(row["error_message"]),
            "input": _json_loads(row["input_json"]),
            "output": _json_loads(row["output_json"]),
        }

    @staticmethod
    def _tool_call_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "tool_call_id": str(row["tool_call_id"]),
            "run_id": str(row["run_id"]),
            "stage_id": str(row["stage_id"]),
            "tool_name": str(row["tool_name"]),
            "status": str(row["status"]),
            "input": _json_loads(row["input_json"]),
            "output": _json_loads(row["output_json"]),
            "error_message": str(row["error_message"]),
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"]),
            "duration_ms": int(row["duration_ms"]),
        }

    @staticmethod
    def _message_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": str(row["message_id"]),
            "run_id": str(row["run_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "usage": _json_loads(row["usage_json"]),
            "processing_ms": int(row["processing_ms"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _artifact_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        links = connection.execute(
            "select * from research_evidence_links where artifact_id = ? order by evidence_link_id",
            (row["artifact_id"],),
        ).fetchall()
        return {
            "artifact_id": str(row["artifact_id"]),
            "run_id": str(row["run_id"]),
            "notebook_id": str(row["notebook_id"]),
            "artifact_type": str(row["artifact_type"]),
            "schema_version": str(row["schema_version"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "payload": _json_loads(row["payload_json"]),
            "file_path": str(row["file_path"]),
            "created_at": str(row["created_at"]),
            "evidence_links": [
                {
                    "evidence_link_id": str(link["evidence_link_id"]),
                    "evidence_id": str(link["evidence_id"]),
                    "doc_id": str(link["doc_id"]),
                    "html_anchor": str(link["html_anchor"]),
                    "source_href": str(link["source_href"]),
                    "relationship": str(link["relationship"]),
                    "quote_snapshot": str(link["quote_snapshot"]),
                    "metadata": _json_loads(link["metadata_json"]),
                }
                for link in links
            ],
        }

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("select * from research_runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(f"Research run does not exist: {run_id}")
        return row

    @staticmethod
    def _require_stage(connection: sqlite3.Connection, run_id: str, stage_key: str) -> sqlite3.Row:
        row = connection.execute(
            "select * from research_stages where run_id = ? and stage_key = ?", (run_id, stage_key)
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Research stage does not exist: {run_id}/{stage_key}")
        return row

    @staticmethod
    def _require_tool_call(connection: sqlite3.Connection, tool_call_id: str) -> sqlite3.Row:
        row = connection.execute(
            "select * from research_tool_calls where tool_call_id = ?", (tool_call_id,)
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Research tool call does not exist: {tool_call_id}")
        return row

    @staticmethod
    def _refresh_progress(connection: sqlite3.Connection, run_id: str) -> None:
        counts = connection.execute(
            """
            select count(*) as total,
                   sum(case when status = 'completed' then 1 else 0 end) as completed
            from research_stages where run_id = ?
            """,
            (run_id,),
        ).fetchone()
        total = int(counts["total"] or 0)
        completed = int(counts["completed"] or 0)
        progress = completed / total if total else 0
        connection.execute("update research_runs set progress = ? where run_id = ?", (progress, run_id))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _json_loads(value: object) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _duration_ms(started_at: str, completed_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at)
        completed = datetime.fromisoformat(completed_at)
    except ValueError:
        return 0
    return max(0, int((completed - started).total_seconds() * 1000))
