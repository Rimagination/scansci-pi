from __future__ import annotations

import json
from pathlib import Path

from scansci_html import cli
from scansci_html.capability_doctor import doctor_capabilities
from scansci_html.checkpoints import CheckpointStore
from scansci_html.context_policy import prune_stale_tool_results
from scansci_html.prefix_diagnostics import build_prefix_shape, cache_metrics, prefix_change_reason
from scansci_html.subagent_profiles import SubagentProfile, plan_parallel_batches, validate_parallel_write_isolation
from scansci_html.task_contract import TaskContract
from scansci_html.run_manifest import RunManifest, load_manifest


PROJECT_ROOT = Path(__file__).parents[1]


def test_prefix_shape_is_stable_redacted_and_cache_metrics_are_normalized() -> None:
    first = build_prefix_shape(
        provider="openai",
        model="gpt-test",
        api_surface="responses",
        system_prompt="secret system prompt",
        tool_set=["b", "a"],
        selected_skills=["skill-a"],
    )
    second = build_prefix_shape(
        provider="openai",
        model="gpt-test",
        api_surface="responses",
        system_prompt="secret system prompt",
        tool_set=["a", "b"],
        selected_skills=["skill-a"],
    )
    assert first["hash"] == second["hash"]
    assert "secret system prompt" not in json.dumps(first)
    assert cache_metrics({"tokens": {"cacheRead": 80, "cacheWrite": 20, "input": 100, "output": 8}})["cache_hit_rate"] == 0.8
    changed = dict(first)
    changed["components"] = {**dict(first["components"]), "tool_set_hash": "changed"}
    assert prefix_change_reason(first, changed) == "changed:tool_set_hash"


def test_stale_tool_results_are_pruned_but_recent_results_are_kept() -> None:
    messages = [
        {"role": "user", "content": "one"},
        {"role": "toolResult", "name": "search", "content": [{"type": "text", "text": "old" * 500}]},
        {"role": "user", "content": "two"},
        {"role": "user", "content": "three"},
        {"role": "toolResult", "name": "search", "content": "recent"},
    ]
    cleaned, report = prune_stale_tool_results(messages, keep_recent_turns=2)
    assert report.pruned_tool_results == 1
    assert cleaned[1]["_scansci_context_pruned"] is True
    assert cleaned[4]["content"] == "recent"
    assert report.to_dict()["saved_chars"] > 0


def test_task_contract_is_explicit_and_serializable() -> None:
    contract = TaskContract.from_payload(
        {"constraints": ["do not invent sources"], "required_evidence": ["DOI"]},
        request="Compare two papers",
        task_mode="research",
    )
    payload = contract.to_dict()
    assert payload["goal"] == "Compare two papers"
    assert payload["required_evidence"] == ["DOI"]
    assert "Pause policy:" in contract.prompt_block()


def test_checkpoint_store_restores_files_and_can_fork(tmp_path: Path) -> None:
    target = tmp_path / "notes" / "draft.md"
    target.parent.mkdir()
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    checkpoint = store.begin(turn_id="turn-1", label="before edit")
    store.capture(checkpoint.checkpoint_id, target)
    target.write_text("after", encoding="utf-8")
    restored = store.restore(checkpoint.checkpoint_id)
    assert restored["restored_files"] == ["notes/draft.md"]
    assert target.read_text(encoding="utf-8") == "before"
    fork = store.fork(checkpoint.checkpoint_id, label="branch")
    assert fork.checkpoint_id != checkpoint.checkpoint_id
    assert len(store.list()) == 2


def test_parallel_subagent_profiles_reject_overlapping_writes(tmp_path: Path) -> None:
    scout = SubagentProfile(name="scout", write_paths=("reports/a",))
    writer = SubagentProfile(name="writer", write_paths=("reports",))
    errors = validate_parallel_write_isolation([scout, writer], root=tmp_path)
    assert any("overlap" in error for error in errors)
    plan = plan_parallel_batches(
        [{"id": "a", "profile": "scout"}, {"id": "b", "profile": "writer"}],
        [scout, SubagentProfile(name="writer", write_paths=("reports/b",))],
        root=tmp_path,
    )
    assert plan["valid"] is True
    assert len(plan["batches"]) == 1


def test_capability_doctor_is_read_only(tmp_path: Path) -> None:
    report = doctor_capabilities(tmp_path)
    assert report["external_processes_started"] is False
    assert report["network_calls_made"] is False
    assert {item["name"] for item in report["harnesses"]} >= {"pydanticai", "openai-agents", "langgraph"}


def test_manifest_and_cli_expose_the_new_diagnostics(tmp_path: Path, capsys) -> None:
    prefix = build_prefix_shape(provider="gateway", model="m", api_surface="chat_completions", system_prompt="system")
    manifest = RunManifest.start(
        tmp_path,
        harness="pi",
        provider="gateway",
        model="m",
        api_surface="chat_completions",
        prefix_shape=prefix,
    )
    manifest.record_context_stats({"tokens": {"cacheRead": 10, "cacheWrite": 2}, "contextBreakdown": {"message": 3}}, prefix_shape=prefix)
    payload = load_manifest(manifest.path)
    assert payload["metrics"]["cache_read_tokens"] == 10
    assert payload["metrics"]["context_breakdown"]["message"] == 3

    exit_code = cli.main(["doctor", "capabilities", "--root", str(tmp_path), "--json"])
    output = json.loads(capsys.readouterr().out)
    assert exit_code in {0, 1}
    assert output["schema_version"] == "scansci.capability-doctor.v1"


def test_pi_capability_matrix_has_unique_cases_and_release_thresholds() -> None:
    payload = json.loads((PROJECT_ROOT / "bench" / "pi_capability_tasks.json").read_text(encoding="utf-8"))
    axes = {str(item["id"]): item for item in payload["axes"]}

    assert payload["schema_version"] == 2
    assert set(axes) == {
        "routing", "dynamic_tools", "parallelism", "long_context", "skills",
        "subagents", "mcp", "multimodal", "safety", "observability",
    }
    assert axes["routing"]["threshold"] >= 40
    assert axes["dynamic_tools"]["threshold"] >= 10
    assert axes["parallelism"]["threshold"] >= 3
    assert axes["skills"]["threshold"] >= 20
    assert axes["multimodal"]["threshold"] >= 10
    assert axes["safety"]["threshold"] >= 100
    observability = axes["observability"]["requirements"]
    assert set(observability["kind_selectors"]) == {"run", "effect", "subagent", "compaction"}
    assert all(observability["kind_selectors"].values())
    assert all(axis["requirements"]["proof_batches"] for axis in axes.values())
    assert {
        batch["source"]
        for axis in axes.values()
        for batch in axis["requirements"]["proof_batches"]
    } == {"junit", "runtime"}
    case_ids = [str(case["id"]) for axis in axes.values() for case in axis["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert all(len(axis["cases"]) >= int(axis["threshold"]) for axis in axes.values())


def test_pi_capability_matrix_requires_real_provider_for_serialization_and_multimodal() -> None:
    payload = json.loads((PROJECT_ROOT / "bench" / "pi_capability_tasks.json").read_text(encoding="utf-8"))
    by_id = {str(item["id"]): item for item in payload["axes"]}

    assert by_id["dynamic_tools"]["provider_real_required"] is True
    assert by_id["multimodal"]["provider_real_required"] is True
    assert by_id["parallelism"]["requirements"]["timing_rounds"] == 3
    assert by_id["long_context"]["requirements"]["minimum_tokens"] >= 100_000
    assert by_id["long_context"]["requirements"]["sentinel_recovery"] == "20/20"
