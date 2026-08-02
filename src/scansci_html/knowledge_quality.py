"""Regression gates for source-grounded catalogue and evidence retrieval.

The gate intentionally evaluates retrieval before any generative model is
called.  It catches the failure mode where a fluent answer looks plausible but
the selected document or exact evidence span is wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingProvider
from .retrieval import search_evidence_store


def load_gold_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases", payload if isinstance(payload, list) else [])
    if not isinstance(cases, list):
        raise ValueError("gold retrieval cases must be a list")
    return [dict(case) for case in cases if isinstance(case, dict)]


def evaluate_retrieval_gold_set(
    db_path: str | Path,
    cases: list[dict[str, Any]],
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Evaluate doc recall, evidence recall and bounded serving behaviour."""

    results: list[dict[str, Any]] = []
    for case in cases:
        query = str(case.get("query", "")).strip()
        trace: list[dict[str, Any]] = []
        hits = search_evidence_store(
            db_path,
            query,
            limit=max(1, int(case.get("limit", 5) or 5)),
            embedding_provider=embedding_provider,
            trace=trace,
        )
        actual_documents = {str(hit.get("doc_id", "")) for hit in hits if str(hit.get("doc_id", ""))}
        actual_evidence = {str(hit.get("evidence_id", "")) for hit in hits if str(hit.get("evidence_id", ""))}
        expected_documents = {str(item) for item in list(case.get("expected_doc_ids", []) or []) if str(item)}
        expected_evidence = {str(item) for item in list(case.get("expected_evidence_ids", []) or []) if str(item)}
        route = _trace_route(trace)
        expected_route = str(case.get("expected_route", "")).strip()
        expects_empty = bool(case.get("expect_empty", False))
        document_recall = _set_recall(expected_documents, actual_documents)
        evidence_recall = _set_recall(expected_evidence, actual_evidence)
        card_first = any(item.get("strategy") == "document-card-first" for item in trace)
        passed = (
            (not expects_empty or not hits)
            and (not expected_documents or document_recall == 1.0)
            and (not expected_evidence or evidence_recall == 1.0)
            and (not expected_route or route == expected_route)
            and card_first
        )
        results.append(
            {
                "id": str(case.get("id", query[:80] or "case")),
                "passed": passed,
                "query": query,
                "expected_route": expected_route,
                "actual_route": route,
                "document_recall": document_recall,
                "evidence_recall": evidence_recall,
                "returned_hits": len(hits),
                "document_card_first": card_first,
                "trace": trace,
            }
        )
    return {
        "case_count": len(results),
        "passed": bool(results) and all(bool(result["passed"]) for result in results),
        "document_recall": _mean([float(result["document_recall"]) for result in results]),
        "evidence_recall": _mean([float(result["evidence_recall"]) for result in results]),
        "card_first_rate": _mean([1.0 if result["document_card_first"] else 0.0 for result in results]),
        "results": results,
    }


def assert_retrieval_quality_gate(report: dict[str, Any]) -> None:
    """Fail CI when a gold case loses evidence, route or bounded retrieval."""

    if not bool(report.get("passed", False)):
        failed = [str(item.get("id", "case")) for item in list(report.get("results", []) or []) if not item.get("passed")]
        raise AssertionError(f"knowledge retrieval quality gate failed: {', '.join(failed) or 'no passing cases'}")


def _trace_route(trace: list[dict[str, Any]]) -> str:
    for item in reversed(trace):
        route = str(item.get("query_route", "")).strip()
        if route:
            return route
    return ""


def _set_recall(expected: set[str], actual: set[str]) -> float:
    return 1.0 if not expected else len(expected & actual) / len(expected)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
