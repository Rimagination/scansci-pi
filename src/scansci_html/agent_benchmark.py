"""Outcome-level acceptance checks for the scientific-agent benchmark suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .agent_advisor import review_research_run


BENCHMARK_SCHEMA_VERSION = "scansci.agent-benchmark.v1"


def grade_harness_case(run: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Grade one durable run against a declarative harness case.

    This is deliberately an outcome/trace check rather than an LLM judge.  It
    verifies that the expected capability was actually used and that evidence
    requirements were not silently bypassed.  Semantic answer quality remains
    covered by the evidence retrieval and citation benchmark suites.
    """

    advisor = review_research_run(run)
    required_tool = str(case.get("required_tool", "") or "")
    completed_tools = {
        str(item.get("tool_name", ""))
        for item in list(run.get("tool_calls", []) or [])
        if isinstance(item, dict) and str(item.get("status", "")) == "completed"
    }
    checks: list[dict[str, Any]] = [
        {
            "id": "run_completed",
            "passed": str(run.get("status", "")) == "completed",
            "actual": str(run.get("status", "")),
        },
        {
            "id": "required_tool",
            "passed": not required_tool or required_tool in completed_tools,
            "expected": required_tool,
            "actual": sorted(completed_tools),
        },
    ]
    expect_gap = bool(case.get("expect_gap", False))
    if expect_gap:
        checks.append(
            {
                "id": "gap_not_overclaimed",
                "passed": advisor["verdict"] in {"insufficient", "needs_review"} or not bool(run.get("output_artifact")),
                "actual": advisor["verdict"],
            }
        )
    elif str(dict(run.get("task_contract", {}) or {}).get("task_profile", {}).get("evidence_policy", "")) in {"required", "strict"}:
        checks.append(
            {
                "id": "evidence_links_present",
                "passed": bool(list(dict(run.get("output_artifact", {}) or {}).get("evidence_links", []) or [])),
                "actual": len(list(dict(run.get("output_artifact", {}) or {}).get("evidence_links", []) or [])),
            }
        )
    passed = all(bool(item["passed"]) for item in checks)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "case_id": str(case.get("id", "")),
        "run_id": str(run.get("run_id", "")),
        "passed": passed,
        "checks": checks,
        "advisor": advisor,
    }


def summarize_harness_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in results if isinstance(item, dict)]
    passed = sum(bool(item.get("passed", False)) for item in rows)
    categories: dict[str, dict[str, int]] = {}
    for row in rows:
        category = str(row.get("category", "uncategorized"))
        bucket = categories.setdefault(category, {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(bool(row.get("passed", False)))
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
        "by_category": categories,
    }


def load_harness_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate declarative agent acceptance cases without a model call."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Agent harness cases must be a non-empty JSON array")
    cases = [dict(item) for item in payload if isinstance(item, dict)]
    if len(cases) != len(payload):
        raise ValueError("Every agent harness case must be a JSON object")
    ids = [str(item.get("id", "")).strip() for item in cases]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Agent harness case ids must be non-empty and unique")
    for case in cases:
        if not str(case.get("category", "")).strip() or not str(case.get("prompt", "")).strip():
            raise ValueError(f"Harness case {case['id']} must define category and prompt")
        if not isinstance(case.get("expect_gap", False), bool):
            raise ValueError(f"Harness case {case['id']} expect_gap must be boolean")
    return cases


def grade_harness_records(
    cases: Iterable[dict[str, Any]],
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Grade durable run records keyed by harness case id.

    Missing records are explicit failed results.  This avoids a deceptively
    high pass rate when an expensive or unsafe case was silently skipped.
    """

    by_case = {
        str(item.get("case_id", item.get("id", ""))): dict(item.get("run", item))
        for item in records
        if isinstance(item, dict) and str(item.get("case_id", item.get("id", "")))
    }
    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        run = by_case.get(case_id)
        if run is None:
            results.append(
                {
                    "schema_version": BENCHMARK_SCHEMA_VERSION,
                    "case_id": case_id,
                    "category": str(case.get("category", "uncategorized")),
                    "run_id": "",
                    "passed": False,
                    "checks": [{"id": "run_record_present", "passed": False, "actual": "missing"}],
                    "advisor": {},
                }
            )
            continue
        result = grade_harness_case(run, case)
        results.append({**result, "category": str(case.get("category", "uncategorized"))})
    return results


__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "grade_harness_case",
    "grade_harness_records",
    "load_harness_cases",
    "summarize_harness_results",
]
