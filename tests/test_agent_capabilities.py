from __future__ import annotations

from scansci_html.agent_advisor import classify_failure, review_research_run, run_metrics
from scansci_html.agent_benchmark import grade_harness_case, grade_harness_records, summarize_harness_results
from scansci_html.agent_capabilities import (
    artifact_uri,
    capability_catalog,
    compile_capability_lease,
    evidence_uri,
    paper_uri,
    parse_resource_uri,
    run_uri,
)
from scansci_html.research_subagents import validate_subagent_result


def test_research_resource_uris_are_opaque_and_round_trip() -> None:
    paper = paper_uri(doi="10.1000/example value")
    evidence = evidence_uri(doc_id="doc/1", evidence_id="s 1")
    artifact = artifact_uri(run_id="run-1", artifact_id="artifact-1")

    assert paper == "scansci://paper/10.1000%2Fexample%20value"
    assert parse_resource_uri(paper) == {
        "uri": paper,
        "kind": "paper",
        "segments": ["10.1000/example value"],
    }
    assert evidence.startswith("scansci://evidence/")
    assert artifact == "scansci://artifact/run-1/artifact-1"
    assert run_uri("run-1") == "scansci://run/run-1"


def test_capability_catalog_projects_mcp_risk_and_activation_mode(tmp_path) -> None:
    catalog = capability_catalog(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        plugins=[],
        mcp_servers=[
            {
                "id": "papers",
                "name": "Paper MCP",
                "enabled": True,
                "allow_write": False,
                "deferred": True,
                "transport": "stdio",
            }
        ],
    )

    mcp = next(item for item in catalog["capabilities"] if item["id"] == "mcp:papers")
    assert catalog["schema_version"] == "scansci.capability.v1"
    assert catalog["resource_uri_scheme"] == "scansci://"
    assert mcp["risk_level"] == "read_only"
    assert mcp["activation_mode"] == "deferred"
    assert mcp["subagent_allowed"] is True


def test_capability_lease_is_catalog_authoritative_and_blocks_child_writes(tmp_path) -> None:
    catalog = capability_catalog(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        plugins=[],
        mcp_servers=[{"id": "readonly", "enabled": True}, {"id": "disabled", "enabled": False}],
    )

    lease = compile_capability_lease(
        catalog,
        ["inspect_workspace", "create_document", "not_a_tool"],
        requested_mcp_server_ids=["readonly", "disabled"],
        subagent=True,
    )

    assert lease["allowed_tools"] == ["inspect_workspace"]
    assert set(lease["unavailable_tools"]) == {"create_document", "not_a_tool"}
    assert lease["allowed_mcp_servers"] == ["readonly"]
    assert lease["unavailable_mcp_servers"] == ["disabled"]


def test_subagent_handoff_requires_json_role_and_scansci_uris() -> None:
    valid = validate_subagent_result(
        '{"role":"literature_scout","findings":["candidate"],"evidence_uris":["scansci://paper/10.1%2Fx"],"uncertainties":[],"recommended_next_action":"verify DOI"}',
        role_id="literature_scout",
    )
    invalid = validate_subagent_result("A prose response", role_id="literature_scout")

    assert valid["valid"] is True
    assert valid["result"]["evidence_uris"] == ["scansci://paper/10.1%2Fx"]
    assert invalid == {"valid": False, "errors": ["handoff_not_json"], "result": None}


def test_contract_advisor_reports_evidence_gaps_without_side_effects() -> None:
    run = {
        "run_id": "run-1",
        "status": "completed",
        "stage_counts": {"total": 3, "completed": 3},
        "task_contract": {
            "required_tool_groups": [["search_local_evidence"]],
            "task_profile": {"evidence_policy": "required"},
        },
        "tool_calls": [
            {"tool_name": "search_local_evidence", "status": "completed", "duration_ms": 12},
            {"tool_name": "build_verified_answer", "status": "failed", "duration_ms": 8, "error_message": "citation evidence insufficient"},
        ],
        "output_artifact": {"artifact_id": "artifact-1", "evidence_links": []},
        "events": [],
        "error": {},
    }

    report = review_research_run(run)
    metrics = run_metrics(run)

    assert report["verdict"] == "insufficient"
    assert report["recommended_next_action"] == "run_evidence_verification"
    assert {item["code"] for item in report["findings"]} >= {"evidence_links_missing", "tool_failures_present"}
    assert metrics["tool_calls"]["failed"] == 1
    assert metrics["failure_categories"] == {"evidence_insufficient": 1}
    assert classify_failure("403 forbidden") == "permission_denied"


def test_harness_grading_checks_trace_and_evidence_requirements() -> None:
    run = {
        "run_id": "run-benchmark",
        "status": "completed",
        "stage_counts": {"total": 2, "completed": 2},
        "task_contract": {"task_profile": {"evidence_policy": "required"}},
        "tool_calls": [{"tool_name": "build_verified_answer", "status": "completed", "duration_ms": 5}],
        "events": [],
        "error": {},
        "output_artifact": {"artifact_id": "answer", "evidence_links": [{"evidence_id": "doc.s1"}]},
    }

    result = grade_harness_case(
        run,
        {"id": "verified-answer", "category": "single_document", "required_tool": "build_verified_answer"},
    )

    assert result["passed"] is True
    summary = summarize_harness_results([{**result, "category": "single_document"}])
    assert summary == {
        "schema_version": "scansci.agent-benchmark.v1",
        "total": 1,
        "passed": 1,
        "failed": 0,
        "pass_rate": 1.0,
        "by_category": {"single_document": {"total": 1, "passed": 1}},
    }

    records = grade_harness_records(
        [{"id": "verified-answer", "category": "single_document", "prompt": "x", "required_tool": "build_verified_answer"}, {"id": "missing", "category": "safety", "prompt": "y"}],
        [{"case_id": "verified-answer", "run": run}],
    )
    assert records[0]["passed"] is True
    assert records[1]["checks"] == [{"id": "run_record_present", "passed": False, "actual": "missing"}]
