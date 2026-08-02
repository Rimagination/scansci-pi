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
import re
import sqlite3
from typing import Any, Iterable, Sequence
from uuid import uuid4

from .agent_capabilities import artifact_uri, evidence_uri, run_uri


RUN_STATUSES = {
    "draft",
    "queued",
    "planning",
    "running",
    "needs_confirmation",
    "waiting_input",
    "paused",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}
STAGE_STATUSES = {"pending", "running", "paused", "completed", "failed", "cancelled", "skipped"}
ACTIVE_RUN_STATUSES = {"queued", "planning", "running", "verifying"}
RESUMABLE_RUN_STATUSES = {"paused", "failed", "cancelled", "needs_confirmation", "waiting_input"}

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)"
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"
    r"|(?:sk-|key-)[A-Za-z0-9_-]{12,}"
    r"|((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
    r"(?:%3[dD]|=|:)\s*)[^&\s,;\"']+"
)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
}


def redact_sensitive_text(value: object) -> str:
    """Remove credential-shaped values before errors reach UI or durable logs."""

    text = str(value or "")

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1) or match.group(2) or ""
        return f"{prefix}[REDACTED]"

    return _SENSITIVE_VALUE_PATTERN.sub(replace, text)


def _redact_sensitive_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 8:
        return "[TRUNCATED]"
    normalized_key = key.strip().lower().replace("-", "_")
    if normalized_key in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(nested_key): _redact_sensitive_value(item, key=str(nested_key), depth=depth + 1)
            for nested_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


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
        task_contract: dict[str, Any] | None = None,
        parent_run_id: str = "",
        branch_from_message_id: str = "",
        background: bool = True,
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
                  started_at, completed_at, metadata_json, parent_run_id,
                  branch_from_message_id, background, interaction_json, recovery_json,
                  task_contract_json
                ) values (?, ?, ?, ?, 'queued', ?, 0, ?, '', 0, '', '', ?, ?, ?, ?, '', '', ?, ?, ?, ?, '{}', '{}', ?)
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
                    str(parent_run_id),
                    str(branch_from_message_id),
                    1 if background else 0,
                    _json_dumps(_redact_sensitive_value(dict(task_contract or {}))),
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
            self._append_event(
                connection,
                run_id,
                event_type="task.created",
                summary="任务已创建",
                payload={
                    "workflow_type": str(workflow_type),
                    "background": bool(background),
                    "routing": dict(metadata or {}).get("routing", {}),
                },
                created_at=now,
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
            connection.execute("delete from research_run_events where run_id = ?", (run_id,))
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
            payload["interaction"] = _json_loads(row["interaction_json"])
            payload["recovery"] = _json_loads(row["recovery_json"])
            payload["task_contract"] = _json_loads(row["task_contract_json"])
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
            payload["events"] = [
                self._event_payload(item)
                for item in connection.execute(
                    """
                    select * from research_run_events
                    where run_id = ? order by created_at, rowid limit 80
                    """,
                    (run_id,),
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

    def fork_run(
        self,
        source_run_id: str,
        *,
        branch_from_message_id: str = "",
        title: str = "",
        input_overrides: dict[str, Any] | None = None,
        background: bool = True,
    ) -> dict[str, Any]:
        """Create an independent durable branch while preserving the source task."""

        source = self.get_run(source_run_id)
        branch_input = {**dict(source.get("input", {}) or {}), **dict(input_overrides or {})}
        stages = [
            StageSpec(
                str(stage.get("key", "")),
                str(stage.get("title", "")),
                str(stage.get("kind", "")),
                str(stage.get("tool_name", "")),
            )
            for stage in list(source.get("stages", []) or [])
        ]
        metadata = {
            **dict(source.get("metadata", {}) or {}),
            "branch": {
                "parent_run_id": source_run_id,
                "branch_from_message_id": str(branch_from_message_id),
                "created_at": _utc_now(),
            },
        }
        branch = self.create_run(
            notebook_id=str(source.get("notebook_id", "")),
            workflow_type=str(source.get("workflow_type", "")),
            title=str(title).strip() or f"{str(source.get('title', '研究任务'))} · 分支",
            input_payload=branch_input,
            stages=stages,
            model_provider_id=str(dict(source.get("model", {}) or {}).get("provider_id", "")),
            model_id=str(dict(source.get("model", {}) or {}).get("model_id", "")),
            metadata=metadata,
            task_contract=dict(source.get("task_contract", {}) or {}),
            parent_run_id=source_run_id,
            branch_from_message_id=str(branch_from_message_id),
            background=background,
        )
        copied: list[dict[str, Any]] = []
        for message in list(source.get("messages", []) or []):
            copied.append(message)
            if branch_from_message_id and str(message.get("message_id", "")) == str(branch_from_message_id):
                break
        for message in copied:
            self.append_message(
                str(branch["run_id"]),
                role=str(message.get("role", "")),
                content=str(message.get("content", "")),
                usage=dict(message.get("usage", {}) or {}),
                processing_ms=int(message.get("processing_ms", 0) or 0),
            )
        return self.get_run(str(branch["run_id"]))

    def set_interaction(self, run_id: str, interaction: dict[str, Any]) -> dict[str, Any]:
        """Persist a blocking AskUser/Plan request so it survives UI navigation."""

        payload = dict(interaction or {})
        kind = str(payload.get("kind", payload.get("interaction_kind", "ask_user")))
        status = "needs_confirmation" if kind == "plan" else "waiting_input"
        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            self._require_run(connection, run_id)
            connection.execute(
                """
                update research_runs
                set status = ?, interaction_json = ?, updated_at = ?
                where run_id = ?
                """,
                (status, _json_dumps(payload), now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def resolve_interaction(
        self,
        run_id: str,
        *,
        interaction_id: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        """Record the user's decision and leave the task ready to continue."""

        now = _utc_now()
        with self._connect() as connection:
            self._initialize_schema(connection)
            row = self._require_run(connection, run_id)
            interaction = _json_loads(row["interaction_json"])
            expected = str(interaction.get("interaction_id", ""))
            if expected and expected != str(interaction_id):
                raise ValueError("This interaction is no longer pending")
            metadata = _json_loads(row["metadata_json"])
            decisions = list(metadata.get("interaction_decisions", []) or [])
            decisions.append(
                {
                    "interaction_id": str(interaction_id),
                    "kind": str(interaction.get("kind", "")),
                    "response": dict(response or {}),
                    "resolved_at": now,
                }
            )
            metadata["interaction_decisions"] = decisions[-50:]
            connection.execute(
                """
                update research_runs
                set status = 'paused', interaction_json = '{}', metadata_json = ?, updated_at = ?
                where run_id = ?
                """,
                (_json_dumps(metadata), now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def set_recovery(self, run_id: str, recovery: dict[str, Any]) -> dict[str, Any]:
        """Persist structured failure classification and recovery actions."""

        with self._connect() as connection:
            self._initialize_schema(connection)
            self._require_run(connection, run_id)
            connection.execute(
                "update research_runs set recovery_json = ?, updated_at = ? where run_id = ?",
                (_json_dumps(_redact_sensitive_value(dict(recovery or {}))), _utc_now(), run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def set_task_contract(self, run_id: str, task_contract: dict[str, Any]) -> dict[str, Any]:
        """Attach or replace the host-owned autonomy contract for one task."""

        with self._connect() as connection:
            self._initialize_schema(connection)
            self._require_run(connection, run_id)
            connection.execute(
                "update research_runs set task_contract_json = ? where run_id = ?",
                (
                    _json_dumps(_redact_sensitive_value(dict(task_contract or {}))),
                    run_id,
                ),
            )
            connection.commit()
        return self.get_run(run_id)

    def task_registry(self, *, limit: int = 200) -> dict[str, Any]:
        """Return one control-plane snapshot for foreground, background, and branched tasks."""

        runs = self.list_runs(limit=limit, archived=None)
        branch_counts: dict[str, int] = {}
        for run in runs:
            parent = str(run.get("parent_run_id", ""))
            if parent:
                branch_counts[parent] = branch_counts.get(parent, 0) + 1
        items = [
            {
                **run,
                "branch_count": branch_counts.get(str(run.get("run_id", "")), 0),
                "blocked": str(run.get("status", "")) in {"needs_confirmation", "waiting_input"},
            }
            for run in runs
        ]
        return {
            "tasks": items,
            "counts": {
                "total": len(items),
                "active": sum(str(item.get("status", "")) in ACTIVE_RUN_STATUSES for item in items),
                "background": sum(bool(item.get("background")) for item in items),
                "blocked": sum(bool(item.get("blocked")) for item in items),
                "branches": sum(bool(item.get("parent_run_id")) for item in items),
            },
        }

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
            # Serialize ownership before reading status. This prevents two
            # runtime instances from both executing the same durable run.
            connection.execute("begin immediate")
            row = self._require_run(connection, run_id)
            status = str(row["status"])
            if status not in {"queued", "paused", "failed", "cancelled"}:
                raise ValueError(f"Research run cannot start from status: {status}")
            updated = connection.execute(
                """
                update research_runs
                set status = 'running', cancel_requested = 0, error_code = '', error_message = '',
                    started_at = case when started_at = '' then ? else started_at end,
                    completed_at = '', updated_at = ?
                where run_id = ? and status in ('queued', 'paused', 'failed', 'cancelled')
                """,
                (now, now, run_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Research run ownership changed before execution began")
            self._append_event(
                connection,
                run_id,
                event_type="task.started",
                summary="任务开始执行",
                created_at=now,
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

    def mark_needs_confirmation(self, run_id: str, *, summary: str = "计划已生成，等待确认") -> dict[str, Any]:
        """Transition the run to needs_confirmation without touching stages."""
        now = _utc_now()
        with self._connect() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                """
                update research_runs
                set status = 'needs_confirmation', updated_at = ?
                where run_id = ?
                """,
                (now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def prepare_stage_retry(self, run_id: str, stage_key: str, error: Exception, *, attempt: int = 1) -> None:
        """Reset a single failed stage to pending for auto-retry with context."""
        now = _utc_now()
        with self._connect() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                """
                update research_stages
                set status = 'pending', started_at = '', completed_at = '',
                    summary = '', error_message = ?
                where run_id = ? and stage_key = ?
                """,
                (
                    redact_sensitive_text(
                        f"[重试 {attempt}/2] {type(error).__name__}: {str(error)[:200]}"
                    ),
                    run_id,
                    stage_key,
                ),
            )
            connection.execute(
                """
                update research_runs
                set status = 'queued', updated_at = ?, error_code = '', error_message = ''
                where run_id = ?
                """,
                (now, run_id),
            )
            connection.commit()

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
                    completed_at = '', error_code = '', error_message = '',
                    interaction_json = '{}', recovery_json = '{}', updated_at = ?
                where run_id = ?
                """,
                (next_stage["stage_key"], now, run_id),
            )
            self._refresh_progress(connection, run_id)
            connection.commit()
        return self.get_run(run_id)

    def prepare_restart(self, run_id: str) -> dict[str, Any]:
        """Reset a terminal task in place so a short “重来” keeps its thread.

        Restarting is intentionally different from resuming: a completed task
        starts again from its first stage, while the existing run id and
        conversation messages remain intact.  Prior artifacts and tool calls
        stay in the database for auditability; clearing ``output_artifact_id``
        prevents the UI from showing stale output while the new attempt runs.
        """

        now = _utc_now()
        with self._connect() as connection:
            row = self._require_run(connection, run_id)
            status = str(row["status"])
            if status not in {"completed", "failed", "paused", "cancelled"}:
                raise ValueError(f"Research run is not restartable from status: {status}")
            first_stage = connection.execute(
                "select stage_key from research_stages where run_id = ? order by position limit 1",
                (run_id,),
            ).fetchone()
            if first_stage is None:
                raise ValueError("Research run has no stage to restart")
            connection.execute(
                """
                update research_stages
                set status = 'pending', started_at = '', completed_at = '',
                    summary = '', error_message = '', output_json = '{}'
                where run_id = ?
                """,
                (run_id,),
            )
            connection.execute(
                """
                update research_runs
                set status = 'queued', current_stage = ?, progress = 0,
                    output_artifact_id = '', cancel_requested = 0,
                    error_code = '', error_message = '', completed_at = '', updated_at = ?
                where run_id = ?
                """,
                (str(first_stage["stage_key"]), now, run_id),
            )
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
            self._append_event(
                connection,
                run_id,
                event_type="stage.started",
                summary=str(stage["title"]),
                payload={"stage_key": stage_key, "attempt": int(stage["attempt"] or 0) + 1},
                created_at=now,
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
            self._append_event(
                connection,
                run_id,
                event_type="stage.completed",
                summary=str(summary).strip() or str(stage_key),
                payload={"stage_key": stage_key},
                created_at=now,
            )
            connection.commit()
        return self.get_run(run_id)

    def update_stage_progress(
        self,
        run_id: str,
        stage_key: str,
        *,
        fraction: float,
        summary: str = "",
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist observable progress for a long-running stage.

        Stage status remains ``running`` until the worker explicitly completes
        or cancels it.  This makes partial vector-cache builds safe to resume
        without falsely presenting them as finished.
        """

        stage_fraction = max(0.0, min(1.0, float(fraction)))
        now = _utc_now()
        with self._connect() as connection:
            stage = self._require_stage(connection, run_id, stage_key)
            if str(stage["status"]) != "running":
                return self.get_run(run_id)
            completed = int(
                connection.execute(
                    "select count(*) from research_stages where run_id = ? and status = 'completed'",
                    (run_id,),
                ).fetchone()[0]
                or 0
            )
            total = int(
                connection.execute(
                    "select count(*) from research_stages where run_id = ?",
                    (run_id,),
                ).fetchone()[0]
                or 0
            )
            progress = (completed + stage_fraction) / total if total else stage_fraction
            connection.execute(
                """
                update research_stages
                set summary = ?, output_json = ?
                where run_id = ? and stage_key = ?
                """,
                (str(summary), _json_dumps(output or {}), run_id, stage_key),
            )
            connection.execute(
                "update research_runs set progress = ?, updated_at = ? where run_id = ?",
                (progress, now, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def fail_stage(
        self,
        run_id: str,
        stage_key: str,
        error: Exception,
        *,
        output_artifact_id: str = "",
    ) -> dict[str, Any]:
        now = _utc_now()
        message = redact_sensitive_text(str(error) or error.__class__.__name__)
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
                    output_artifact_id = case when ? != '' then ? else output_artifact_id end,
                    completed_at = ?, updated_at = ? where run_id = ?
                """,
                (message, str(output_artifact_id), str(output_artifact_id), now, now, run_id),
            )
            self._refresh_progress(connection, run_id)
            self._append_event(
                connection,
                run_id,
                event_type="stage.failed",
                summary=message,
                payload={"stage_key": stage_key},
                created_at=now,
            )
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
            self._append_event(
                connection,
                run_id,
                event_type="task.completed",
                summary="任务已完成",
                payload={"output_artifact_id": str(output_artifact_id)},
                created_at=now,
            )
            connection.commit()
        return self.get_run(run_id)

    def stage_output(self, run_id: str, stage_key: str) -> dict[str, Any]:
        with self._connect() as connection:
            stage = self._require_stage(connection, run_id, stage_key)
            return _json_loads(stage["output_json"])

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an auditable, redacted task event without changing task state."""

        now = _utc_now()
        with self._connect() as connection:
            self._require_run(connection, run_id)
            event_id = self._append_event(
                connection,
                run_id,
                event_type=event_type,
                summary=summary,
                payload=payload,
                created_at=now,
            )
            connection.execute("update research_runs set updated_at = ? where run_id = ?", (now, run_id))
            connection.commit()
            row = connection.execute(
                "select * from research_run_events where event_id = ?", (event_id,)
            ).fetchone()
            return self._event_payload(row)

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
                (
                    call_id,
                    run_id,
                    stage["stage_id"],
                    str(tool_name),
                    _json_dumps(_redact_sensitive_value(input_payload)),
                    now,
                ),
            )
            self._append_event(
                connection,
                run_id,
                event_type="tool.started",
                summary=str(tool_name),
                payload={"stage_key": stage_key, "tool_call_id": call_id},
                created_at=now,
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
                (_json_dumps(_redact_sensitive_value(output)), now, duration, tool_call_id),
            )
            self._append_event(
                connection,
                str(row["run_id"]),
                event_type="tool.completed",
                summary=str(row["tool_name"]),
                payload={"tool_call_id": tool_call_id, "duration_ms": duration},
                created_at=now,
            )
            connection.commit()
            return self._tool_call_payload(self._require_tool_call(connection, tool_call_id))

    def fail_tool_call(self, tool_call_id: str, error: Exception) -> dict[str, Any]:
        now = _utc_now()
        message = redact_sensitive_text(str(error) or error.__class__.__name__)
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
            self._append_event(
                connection,
                str(row["run_id"]),
                event_type="tool.failed",
                summary=message,
                payload={"tool_call_id": tool_call_id, "tool_name": str(row["tool_name"])},
                created_at=now,
            )
            connection.commit()
            return self._tool_call_payload(self._require_tool_call(connection, tool_call_id))

    def cancel_tool_call(self, tool_call_id: str, output: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record a cooperative tool cancellation without converting it to failure."""

        now = _utc_now()
        with self._connect() as connection:
            row = self._require_tool_call(connection, tool_call_id)
            duration = _duration_ms(str(row["started_at"]), now)
            connection.execute(
                """
                update research_tool_calls
                set status = 'cancelled', output_json = ?, completed_at = ?, duration_ms = ?, error_message = ''
                where tool_call_id = ?
                """,
                (_json_dumps(_redact_sensitive_value(output or {})), now, duration, tool_call_id),
            )
            self._append_event(
                connection,
                str(row["run_id"]),
                event_type="tool.cancelled",
                summary=str(row["tool_name"]),
                payload={"tool_call_id": tool_call_id, "duration_ms": duration},
                created_at=now,
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
              archived_at text not null default '',
              parent_run_id text not null default '',
              branch_from_message_id text not null default '',
              background integer not null default 1,
              interaction_json text not null default '{}',
              recovery_json text not null default '{}',
              task_contract_json text not null default '{}'
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
            create table if not exists research_run_events (
              event_id text primary key,
              run_id text not null,
              event_type text not null,
              summary text not null,
              payload_json text not null,
              created_at text not null,
              foreign key(run_id) references research_runs(run_id)
            );
            create index if not exists idx_research_runs_notebook on research_runs(notebook_id, updated_at);
            create index if not exists idx_research_stages_run on research_stages(run_id, position);
            create index if not exists idx_research_calls_run on research_tool_calls(run_id, started_at);
            create index if not exists idx_research_artifacts_run on research_artifacts(run_id, created_at);
            create index if not exists idx_research_evidence_artifact on research_evidence_links(artifact_id);
            create index if not exists idx_research_messages_run on research_run_messages(run_id, created_at);
            create index if not exists idx_research_events_run on research_run_events(run_id, created_at);
            """
        )
        columns = {str(row["name"]) for row in connection.execute("pragma table_info(research_runs)")}
        if "archived_at" not in columns:
            connection.execute("alter table research_runs add column archived_at text not null default ''")
        if "parent_run_id" not in columns:
            connection.execute("alter table research_runs add column parent_run_id text not null default ''")
        if "branch_from_message_id" not in columns:
            connection.execute("alter table research_runs add column branch_from_message_id text not null default ''")
        if "background" not in columns:
            connection.execute("alter table research_runs add column background integer not null default 1")
        if "interaction_json" not in columns:
            connection.execute("alter table research_runs add column interaction_json text not null default '{}'")
        if "recovery_json" not in columns:
            connection.execute("alter table research_runs add column recovery_json text not null default '{}'")
        if "task_contract_json" not in columns:
            connection.execute("alter table research_runs add column task_contract_json text not null default '{}'")
        connection.execute(
            "create index if not exists idx_research_runs_archived on research_runs(archived_at, updated_at)"
        )
        connection.execute(
            "create index if not exists idx_research_runs_parent on research_runs(parent_run_id, updated_at)"
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
        event_count = connection.execute(
            "select count(*) from research_run_events where run_id = ?", (row["run_id"],)
        ).fetchone()[0]
        return {
            "run_id": str(row["run_id"]),
            "uri": run_uri(row["run_id"]),
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
            "parent_run_id": str(row["parent_run_id"]),
            "branch_from_message_id": str(row["branch_from_message_id"]),
            "background": bool(row["background"]),
            "interaction": _json_loads(row["interaction_json"]),
            "recovery": _json_loads(row["recovery_json"]),
            "task_contract": _json_loads(row["task_contract_json"]),
            "stage_counts": {
                "total": int(stage_counts["total"] or 0),
                "completed": int(stage_counts["completed"] or 0),
            },
            "event_count": int(event_count or 0),
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
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        created_at: str,
    ) -> str:
        event_id = _new_id("event")
        connection.execute(
            """
            insert into research_run_events (
              event_id, run_id, event_type, summary, payload_json, created_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(run_id),
                str(event_type),
                redact_sensitive_text(str(summary or ""))[:600],
                _json_dumps(_redact_sensitive_value(dict(payload or {}))),
                str(created_at),
            ),
        )
        return event_id

    @staticmethod
    def _event_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "run_id": str(row["run_id"]),
            "type": str(row["event_type"]),
            "summary": str(row["summary"]),
            "payload": _json_loads(row["payload_json"]),
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
            "uri": artifact_uri(run_id=row["run_id"], artifact_id=row["artifact_id"]),
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
                    "uri": evidence_uri(
                        doc_id=link["doc_id"],
                        evidence_id=link["evidence_id"],
                        anchor=link["html_anchor"],
                    ),
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
