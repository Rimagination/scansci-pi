from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from scansci_html.research_runs import ResearchRunStore, StageSpec
from scansci_html.research_agent import _DurableModelClient
from scansci_html.webapp import NotebookWebApp


def _legacy_run_database(path: Path) -> None:
    """Create the pre-ScientificEvent schema used by the shipped preview."""

    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            create table research_runs (
              run_id text primary key, notebook_id text not null, workflow_type text not null,
              title text not null, status text not null, current_stage text not null,
              progress real not null, input_json text not null, output_artifact_id text not null,
              cancel_requested integer not null, error_code text not null, error_message text not null,
              model_provider_id text not null, model_id text not null, created_at text not null,
              updated_at text not null, started_at text not null, completed_at text not null,
              metadata_json text not null, archived_at text not null default '',
              parent_run_id text not null default '', branch_from_message_id text not null default '',
              background integer not null default 1, interaction_json text not null default '{}',
              recovery_json text not null default '{}', task_contract_json text not null default '{}'
            );
            create table research_stages (
              stage_id text primary key, run_id text not null, stage_key text not null,
              position integer not null, title text not null, kind text not null, tool_name text not null,
              status text not null, attempt integer not null, started_at text not null,
              completed_at text not null, summary text not null, error_message text not null,
              input_json text not null, output_json text not null, unique(run_id, stage_key)
            );
            create table research_tool_calls (
              tool_call_id text primary key, run_id text not null, stage_id text not null,
              tool_name text not null, status text not null, input_json text not null,
              output_json text not null, error_message text not null, started_at text not null,
              completed_at text not null, duration_ms integer not null
            );
            create table research_artifacts (
              artifact_id text primary key, run_id text not null, notebook_id text not null,
              artifact_type text not null, schema_version text not null, title text not null,
              summary text not null, payload_json text not null, file_path text not null, created_at text not null
            );
            create table research_evidence_links (
              evidence_link_id text primary key, artifact_id text not null, run_id text not null,
              evidence_id text not null, doc_id text not null, html_anchor text not null,
              source_href text not null, relationship text not null, quote_snapshot text not null,
              metadata_json text not null
            );
            create table research_run_messages (
              message_id text primary key, run_id text not null, role text not null,
              content text not null, usage_json text not null, processing_ms integer not null, created_at text not null
            );
            create table research_run_events (
              event_id text primary key, run_id text not null, event_type text not null,
              summary text not null, payload_json text not null, created_at text not null
            );
            insert into research_runs values (
              'run_legacy', 'nb_legacy', 'ask', 'Legacy', 'queued', 'execute', 0,
              '{"question":"keep"}', '', 0, '', '', '', '',
              '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '', '', '{}', '', '', '', 1, '{}', '{}', '{}'
            );
            insert into research_stages values (
              'stage_legacy', 'run_legacy', 'execute', 0, 'Execute', 'tool', '',
              'pending', 0, '', '', '', '', '{}', '{}'
            );
            insert into research_run_events values (
              'event_legacy', 'run_legacy', 'task.created', 'created', '{}', '2026-01-01T00:00:00+00:00'
            );
            """
        )


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"select count(*) from {table}").fetchone()[0])
            for table in (
                "research_runs",
                "research_stages",
                "research_run_events",
                "research_tool_calls",
                "research_artifacts",
                "research_evidence_links",
                "research_run_messages",
            )
        }


def _store(tmp_path: Path) -> ResearchRunStore:
    return ResearchRunStore(tmp_path / "workspace.sqlite")


def _run(store: ResearchRunStore, *, idempotency_key: str = "") -> dict[str, object]:
    return store.create_run(
        notebook_id="nb",
        workflow_type="ask",
        title="Scientific event smoke",
        input_payload={"question": "What changed?"},
        stages=[StageSpec("execute", "Execute", "tool")],
        idempotency_key=idempotency_key,
    )


def test_old_database_migration_preserves_counts_and_is_repeatable(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    _legacy_run_database(database)
    before = _counts(database)

    store = ResearchRunStore(database)
    after_first = _counts(database)
    reopened = ResearchRunStore(database)
    after_second = _counts(database)

    assert before == after_first == after_second
    assert reopened.schema_status() == {
        "schema_name": "research_runs",
        "schema_version": 2,
        "target_version": 2,
    }
    migrated = reopened.get_run("run_legacy")
    assert migrated["input"] == {"question": "keep"}
    assert migrated["events"][0]["schema_version"] == "scientific_event.v1"
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from schema_migrations where schema_name = 'research_runs'").fetchone()[0] == 2
        assert connection.execute("select count(*) from research_run_events where sequence = 1").fetchone()[0] == 1


def test_event_sequence_replay_snapshot_and_terminal_event_exactly_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run(store)
    store.begin_run(str(run["run_id"]))
    store.start_stage(str(run["run_id"]), "execute")
    store.append_event(str(run["run_id"]), event_type="model.request.started", summary="model", request_id="request-1")
    store.append_event(str(run["run_id"]), event_type="model.request.completed", summary="model done", request_id="request-1", output_value={"ok": True})
    completed = store.complete_run(str(run["run_id"]))
    repeated = store.complete_run(str(run["run_id"]))
    stale_failure = store.fail_stage(str(run["run_id"]), "execute", RuntimeError("late worker failure"))
    stale_cancel = store.mark_cancelled(str(run["run_id"]))

    events = completed["events"]
    assert [int(event["sequence"]) for event in events] == list(range(1, len(events) + 1))
    assert all(event["schema_version"] == "scientific_event.v1" for event in events)
    assert sum(bool(event["terminal"]) for event in events) == 1
    assert [event["canonical_type"] for event in events][-1] == "run.completed"
    assert repeated["event_count"] == completed["event_count"]
    assert stale_failure["status"] == "completed"
    assert stale_cancel["status"] == "completed"
    assert stale_cancel["event_count"] == completed["event_count"]
    replay = store.events_after(str(run["run_id"]), after_sequence=1)
    snapshot = store.snapshot(str(run["run_id"]), after_sequence=1)
    assert [event["sequence"] for event in replay] == [event["sequence"] for event in snapshot["events"]]
    assert snapshot["snapshot"]["status"] == "completed"
    assert snapshot["last_sequence"] == completed["last_event_sequence"]


def test_duplicate_idempotency_key_returns_one_run(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _run(store, idempotency_key="submit-1")
    second = _run(store, idempotency_key="submit-1")
    assert first["run_id"] == second["run_id"]
    assert len(store.list_runs(notebook_id="nb", archived=None)) == 1


def test_expired_lease_can_be_taken_over_and_checkpoint_survives_reopen(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run(store)
    run_id = str(run["run_id"])
    store.begin_run(run_id)
    store.start_stage(run_id, "execute")
    checkpoint = store.checkpoint_stage(
        run_id,
        "execute",
        checkpoint_key="source-1",
        state={"cursor": 3, "partial": ["a", "b"]},
        input_value={"source": "file-a"},
    )
    first = store.acquire_worker_lease(run_id, "execute", worker_id="worker-a", ttl_seconds=30)
    with sqlite3.connect(tmp_path / "workspace.sqlite") as connection:
        connection.execute("update research_worker_leases set expires_at = '2000-01-01T00:00:00+00:00' where lease_id = ?", (first["lease_id"],))
        connection.commit()
    taken = store.acquire_worker_lease(run_id, "execute", worker_id="worker-b", ttl_seconds=30)
    reopened = ResearchRunStore(tmp_path / "workspace.sqlite")
    restored = reopened.list_checkpoints(run_id)[0]
    assert taken["lease_id"] == first["lease_id"]
    assert taken["worker_id"] == "worker-b"
    assert restored["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert restored["state"] == {"cursor": 3, "partial": ["a", "b"]}


def test_side_effect_receipt_is_reusable_without_duplicate_receipt_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run(store)
    run_id = str(run["run_id"])
    first = store.record_side_effect_receipt(
        run_id,
        effect_type="download",
        effect_key="doi:10.1234/demo",
        status="completed",
        result={"path": "papers/demo.pdf"},
        input_value={"doi": "10.1234/demo"},
    )
    second = store.record_side_effect_receipt(
        run_id,
        effect_type="download",
        effect_key="doi:10.1234/demo",
        status="completed",
        result={"path": "papers/demo.pdf"},
        input_value={"doi": "10.1234/demo"},
    )
    with sqlite3.connect(tmp_path / "workspace.sqlite") as connection:
        row_count = connection.execute("select count(*) from research_side_effect_receipts").fetchone()[0]
    assert first["receipt_id"] == second["receipt_id"]
    assert row_count == 1
    assert store.get_side_effect_receipt(run_id, effect_type="download", effect_key="doi:10.1234/demo")["status"] == "completed"


def test_model_request_trace_records_hashes_and_classifies_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run(store)
    run_id = str(run["run_id"])
    store.begin_run(run_id)
    started = store.start_stage(run_id, "execute")

    class FakeClient:
        def __init__(self) -> None:
            self.fail = False

        def complete_json(self, messages, *, schema_name, **_kwargs):
            if self.fail:
                raise RuntimeError("HTTP 429 rate limit")
            return {"schema": schema_name, "answer": "grounded"}

    fake = FakeClient()
    client = _DurableModelClient(
        fake,
        store=store,
        run_id=run_id,
        stage_id=str(started["stage_id"]),
        stage_key="execute",
    )
    result = client.complete_json([{"role": "user", "content": "private question"}], schema_name="answer")
    fake.fail = True
    try:
        client.complete_json([{"role": "user", "content": "second"}], schema_name="answer")
    except RuntimeError:
        pass

    events = store.get_run(run_id)["events"]
    model_events = [event for event in events if event["type"].startswith("model.request.")]
    assert result["answer"] == "grounded"
    assert [event["type"] for event in model_events] == [
        "model.request.started",
        "model.request.completed",
        "model.request.started",
        "model.request.failed",
    ]
    assert model_events[0]["input_hash"]
    assert model_events[0]["input_hash"] == model_events[1]["input_hash"]
    assert model_events[1]["output_hash"]
    assert model_events[-1]["error_category"] == "rate_limited"
    assert "private question" not in json.dumps(model_events, ensure_ascii=False)


def test_http_after_sequence_and_frontend_refresh_contract(tmp_path: Path) -> None:
    app = NotebookWebApp(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    run = _run(app.research_agent.store)
    run_id = str(run["run_id"])
    app.research_agent.store.append_event(run_id, event_type="tool.started", summary="read", tool_id="tool-1")
    response = app.dispatch("GET", f"/api/runs/{run_id}/events?after_sequence=1&limit=10")
    payload = json.loads(response.body.decode("utf-8"))
    frontend = (Path(__file__).parents[1] / "src/scansci_html/web/app.js").read_text(encoding="utf-8")

    assert response.status == 200
    assert payload["snapshot"]["run_id"] == run_id
    assert all(int(event["sequence"]) > 1 for event in payload["events"])
    assert "/events?after_sequence=" in frontend
    assert "replayedEvents" in frontend
    assert "last_sequence" in frontend
    assert "hasMore" in frontend
