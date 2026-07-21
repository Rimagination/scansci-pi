from pathlib import Path

import pytest

from scansci_html.research_runs import ResearchRunStore, StageSpec


def _stages() -> list[StageSpec]:
    return [
        StageSpec("plan", "理解任务", "planner"),
        StageSpec("retrieve", "检索证据", "tool", "scansci.evidence.ask"),
        StageSpec("verify", "核验证据", "verification", "scansci.evidence.verify"),
        StageSpec("deliver", "交付结果", "delivery"),
    ]


def test_research_run_persists_stages_calls_artifacts_and_evidence(tmp_path: Path):
    store = ResearchRunStore(tmp_path / "workspace.sqlite")
    created = store.create_run(
        notebook_id="review",
        workflow_type="ask",
        title="What changed?",
        input_payload={"question": "What changed?"},
        stages=_stages(),
        model_provider_id="local-evidence",
        model_id="grounded-retrieval",
    )

    assert created["status"] == "queued"
    assert created["stage_counts"] == {"total": 4, "completed": 0}
    assert [stage["key"] for stage in created["stages"]] == ["plan", "retrieve", "verify", "deliver"]

    run_id = created["run_id"]
    store.begin_run(run_id)
    store.start_stage(run_id, "plan")
    store.complete_stage(run_id, "plan", summary="问题与资料边界已确认")
    store.start_stage(run_id, "retrieve")
    call_id = store.begin_tool_call(
        run_id,
        "retrieve",
        tool_name="scansci.evidence.ask",
        input_payload={"question": "What changed?"},
    )
    store.complete_tool_call(call_id, {"reader_answer": {"text": "It changed [1]."}})
    store.complete_stage(run_id, "retrieve", summary="找到 1 条证据", output={"answer": "It changed [1]."})
    store.start_stage(run_id, "verify")
    store.complete_stage(run_id, "verify", summary="引用核验通过", output={"passed": True})
    store.start_stage(run_id, "deliver")
    artifact = store.create_artifact(
        run_id,
        artifact_type="evidence_answer",
        title="What changed?",
        summary="It changed [1].",
        payload={"reader_answer": {"text": "It changed [1]."}},
        evidence_links=[
            {
                "evidence_id": "doc.s0001",
                "doc_id": "doc",
                "html_anchor": "results-s0001",
                "source_href": "paper.html#results-s0001",
                "exact_quote": "It changed.",
            }
        ],
    )
    store.complete_stage(run_id, "deliver", summary="已生成证据回答", output={"artifact_id": artifact["artifact_id"]})
    completed = store.complete_run(run_id, output_artifact_id=artifact["artifact_id"])

    assert completed["status"] == "completed"
    assert completed["progress"] == 1
    assert completed["output_artifact"]["artifact_type"] == "evidence_answer"
    assert completed["output_artifact"]["evidence_links"][0]["evidence_id"] == "doc.s0001"
    assert completed["tool_calls"][0]["status"] == "completed"
    assert store.list_runs(notebook_id="review")[0]["run_id"] == run_id


def test_research_run_cancel_and_resume_preserves_completed_stages(tmp_path: Path):
    store = ResearchRunStore(tmp_path / "workspace.sqlite")
    run = store.create_run(
        notebook_id="review",
        workflow_type="ask",
        title="Resume me",
        input_payload={"question": "Resume me"},
        stages=_stages(),
    )
    run_id = run["run_id"]
    store.begin_run(run_id)
    store.start_stage(run_id, "plan")
    store.complete_stage(run_id, "plan", summary="done")
    requested = store.request_cancel(run_id)

    assert requested["cancel_requested"] is True
    cancelled = store.mark_cancelled(run_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["resumable"] is True

    resumed = store.prepare_resume(run_id)
    assert resumed["status"] == "queued"
    assert resumed["current_stage"] == "retrieve"
    assert resumed["stages"][0]["status"] == "completed"
    assert resumed["stages"][1]["status"] == "pending"


def test_research_run_recovers_interrupted_process_as_paused(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="review",
        workflow_type="ask",
        title="Interrupted",
        input_payload={"question": "Interrupted"},
        stages=_stages(),
    )
    store.begin_run(run["run_id"])
    store.start_stage(run["run_id"], "plan")

    reopened = ResearchRunStore(workspace)
    assert reopened.recover_interrupted_runs() == 1
    recovered = reopened.get_run(run["run_id"])
    assert recovered["status"] == "paused"
    assert recovered["stages"][0]["status"] == "paused"
    assert recovered["error"]["code"] == "app_restarted"


def test_research_run_follow_up_messages_stay_with_the_original_run(tmp_path: Path):
    store = ResearchRunStore(tmp_path / "workspace.sqlite")
    run = store.create_run(
        notebook_id="",
        workflow_type="pdf_to_ppt",
        title="Deck from paper",
        input_payload={"question": "Create a deck"},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )

    user_message = store.append_message(run["run_id"], role="user", content="Can you explain slide 3?")
    assistant_message = store.append_message(
        run["run_id"],
        role="assistant",
        content="Slide 3 compares the reported evidence.",
        usage={"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
        processing_ms=321,
    )
    reopened = ResearchRunStore(tmp_path / "workspace.sqlite").get_run(run["run_id"])

    assert [item["message_id"] for item in reopened["messages"]] == [user_message["message_id"], assistant_message["message_id"]]
    assert reopened["messages"][1]["usage"]["total_tokens"] == 17
    assert reopened["messages"][1]["processing_ms"] == 321
    assert store.list_runs()[0]["run_id"] == run["run_id"]


def test_research_run_archive_restore_and_delete_are_persistent(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="",
        workflow_type="ask",
        title="Conversation to organize",
        input_payload={"question": "Keep the exported files"},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )

    with pytest.raises(ValueError, match="运行中的对话不能归档或删除"):
        store.archive_run(run["run_id"])

    store.append_message(run["run_id"], role="user", content="Keep this until I delete the conversation")
    artifact = store.create_artifact(
        run["run_id"],
        artifact_type="evidence_answer",
        title="Saved answer",
        summary="Saved locally",
        payload={"text": "Answer"},
        evidence_links=[{"evidence_id": "doc.s0001", "doc_id": "doc", "exact_quote": "Answer"}],
    )
    store.complete_run(run["run_id"], output_artifact_id=artifact["artifact_id"])
    archived = store.archive_run(run["run_id"])
    assert archived["archived"] is True
    assert store.list_runs() == []
    assert store.list_runs(archived=True)[0]["run_id"] == run["run_id"]

    restored = ResearchRunStore(workspace).restore_run(run["run_id"])
    assert restored["archived"] is False
    assert store.list_runs()[0]["run_id"] == run["run_id"]

    deleted = store.delete_run(run["run_id"])
    assert deleted == {
        "ok": True,
        "run_id": run["run_id"],
        "title": "Conversation to organize",
        "deleted": True,
    }
    with pytest.raises(FileNotFoundError):
        store.get_run(run["run_id"])
