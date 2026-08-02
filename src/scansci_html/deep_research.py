"""Evidence-first academic deep-research orchestration helpers.

The durable run state lives in :mod:`research_runs`; this module owns the
research-specific planning, iterative discovery, gap analysis, and the honest
discovery-only fallback used when no full text can be verified.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from .academic_search import FederatedAcademicSearch
from .text_tokenization import lexical_tokens


def plan_deep_research(topic: str, *, chat_client: Any | None = None, max_queries: int = 5) -> dict[str, Any]:
    clean = " ".join(str(topic or "").split())
    if not clean:
        raise ValueError("question is required")
    fallback = _fallback_plan(clean, max_queries=max_queries)
    if chat_client is None:
        return fallback
    messages = [
        {
            "role": "system",
            "content": (
                "You plan rigorous academic literature research. Return JSON only. "
                "Decompose the question into distinct perspectives and high-recall scholarly search queries. "
                "Do not invent papers, DOIs, findings, or citations. Queries should be concise and usable with "
                "OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, and arXiv."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Research question: {clean}\n"
                f"Return: title, objective, perspectives[title, question, keywords], search_queries, "
                f"inclusion_criteria, exclusion_criteria. Use at most {max_queries} search_queries and 5 perspectives."
            ),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="academic_deep_research_plan") or {}
        return _normalize_plan(clean, raw, fallback=fallback, max_queries=max_queries)
    except Exception as error:  # planning failure must not erase deterministic research ability
        fallback["planner"] = "deterministic-fallback"
        fallback["planner_error"] = f"{type(error).__name__}: {error}"[:500]
        return fallback


def run_discovery_loop(
    question: str,
    plan: dict[str, Any],
    *,
    searcher: FederatedAcademicSearch,
    result_limit: int = 36,
    per_source: int = 10,
    year_from: int | None = None,
    max_rounds: int = 2,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Search planned queries, measure perspective coverage, then fill gaps."""

    cancelled = cancel_requested or (lambda: False)
    # Provider APIs expect compact scholarly queries, not an entire
    # conversational question. Long natural-language questions can be
    # rejected even when the planned keyword queries are valid.
    planned_queries = _unique_strings(list(plan.get("search_queries", []) or []) or [question])[:6]
    rounds: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    provider_errors: dict[str, str] = {}
    total_queries = len(planned_queries) + max(0, int(max_rounds) - 1) * len(list(plan.get("perspectives", []) or []))
    completed_queries = 0

    current_queries = planned_queries
    for round_index in range(max(1, min(3, int(max_rounds)))):
        if not current_queries:
            break
        round_record: dict[str, Any] = {"round": round_index + 1, "queries": [], "reason": "initial" if round_index == 0 else "coverage_gaps"}
        for query in current_queries:
            if cancelled():
                raise InterruptedError("deep research discovery cancelled")
            result = searcher.search(
                str(query),
                limit=max(12, min(60, int(result_limit))),
                per_source=max(3, min(25, int(per_source))),
                year_from=year_from,
                cancel_requested=cancelled,
            )
            all_items.extend(list(result.get("items", []) or []))
            provider_errors.update(dict(result.get("provider_errors", {}) or {}))
            query_record = {
                "query": str(query),
                "count": int(result.get("count", 0) or 0),
                "providers_succeeded": list(result.get("providers_succeeded", []) or []),
                "latency_ms": int(result.get("latency_ms", 0) or 0),
            }
            round_record["queries"].append(query_record)
            completed_queries += 1
            if progress_callback:
                progress_callback(completed_queries, max(completed_queries, total_queries), query_record)
        rounds.append(round_record)
        merged = _merge_query_results(all_items)
        coverage = _perspective_coverage(plan, merged)
        gaps = [item for item in coverage if int(item.get("matching_papers", 0) or 0) < 2]
        if not gaps or round_index + 1 >= max_rounds:
            break
        current_queries = _unique_strings(
            [
                f"{question} {gap.get('title', '')} {' '.join(gap.get('keywords', []))}".strip()
                for gap in gaps
            ]
        )[:3]

    merged = _merge_query_results(all_items)
    coverage = _perspective_coverage(plan, merged)
    unresolved = [item for item in coverage if int(item.get("matching_papers", 0) or 0) < 2]
    return {
        "question": question,
        "plan": plan,
        "items": merged[: max(1, min(100, int(result_limit)))],
        "count": min(len(merged), max(1, min(100, int(result_limit)))),
        "candidate_count": len(all_items),
        "deduplicated_count": len(merged),
        "rounds": rounds,
        "coverage": coverage,
        "unresolved_gaps": unresolved,
        "provider_errors": provider_errors,
        "evidence_status": "discovery_leads",
        "evidence_notice": "Discovery records must be backed by indexed full text before they support report claims.",
    }


def enrich_deep_research_result(
    result: dict[str, Any],
    *,
    plan: dict[str, Any],
    discovery: dict[str, Any],
    acquisition: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(result)
    enriched["deep_research_plan"] = plan
    enriched["discovery"] = discovery
    enriched["acquisition"] = acquisition
    task_evidence = dict(acquisition.get("task_evidence", {}) or {})
    task_index = dict(task_evidence.get("index", {}) or {})
    task_quality = dict(task_evidence.get("quality", {}) or {})
    enriched["research_trace"] = {
        "query_count": sum(len(list(round_.get("queries", []) or [])) for round_ in list(discovery.get("rounds", []) or [])),
        "candidate_count": int(discovery.get("candidate_count", 0) or 0),
        "deduplicated_count": int(discovery.get("deduplicated_count", 0) or 0),
        "fulltext_acquired": int(acquisition.get("acquired_count", 0) or 0),
        "fulltext_failed": int(acquisition.get("failed_count", 0) or 0),
        "fulltext_indexed_documents": int(task_index.get("documents", 0) or 0),
        "fulltext_evidence_spans": int(task_index.get("spans", 0) or 0),
        "fulltext_structure_verified": bool(task_quality.get("passed", False)),
        "unresolved_gap_count": len(list(discovery.get("unresolved_gaps", []) or [])),
    }
    return enriched


def discovery_only_result(
    question: str,
    *,
    plan: dict[str, Any],
    discovery: dict[str, Any],
    acquisition: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Return a useful dossier without laundering metadata into evidence."""

    limitation = (
        "The search found bibliographic leads, but ScanSci could not establish enough indexed full-text evidence "
        f"for a claim-level report. {reason}".strip()
    )
    return {
        "phase": "discovery_only",
        "question": question,
        "review_document": {
            "title": str(plan.get("title") or question),
            "abstract": {"text": "", "citation_ids": [], "sentences": []},
            "sections": [],
            "comparison_table": {"columns": [], "rows": []},
            "controversies": [],
            "open_questions": [],
            "limitations": [limitation],
            "references": [],
        },
        "reader_answer": {"text": "", "sentences": [], "citations": [], "citation_count": 0},
        "answer": {
            "question": question,
            "answer": [],
            "limitations": [limitation],
            "insufficient_evidence": True,
        },
        "adequacy": {
            "is_sufficient": False,
            "quote_count": 0,
            "document_count": 0,
            "followup_reason": limitation,
            "profile": "deep_research",
        },
        "citation_verification": {
            "passed": True,
            "claim_count": 0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "reason": "No unsupported scientific claim was emitted.",
        },
        "verification": {"passed": True, "supported_claims": []},
        "evidence_table": [],
        "deep_research_plan": plan,
        "discovery": discovery,
        "acquisition": acquisition,
        "research_trace": {
            "query_count": sum(len(list(round_.get("queries", []) or [])) for round_ in list(discovery.get("rounds", []) or [])),
            "candidate_count": int(discovery.get("candidate_count", 0) or 0),
            "deduplicated_count": int(discovery.get("deduplicated_count", 0) or 0),
            "fulltext_acquired": int(acquisition.get("acquired_count", 0) or 0),
            "fulltext_failed": int(acquisition.get("failed_count", 0) or 0),
            "unresolved_gap_count": len(list(discovery.get("unresolved_gaps", []) or [])),
        },
    }


def _fallback_plan(question: str, *, max_queries: int) -> dict[str, Any]:
    topic = _topic_phrase(question)
    perspectives = [
        {"title": "Core findings", "question": f"What findings directly answer {question}?", "keywords": [topic]},
        {"title": "Methods and evidence", "question": f"Which methods and datasets support the findings about {topic}?", "keywords": [topic, "methods", "dataset"]},
        {"title": "Limitations and disagreement", "question": f"What limitations or conflicting evidence exist for {topic}?", "keywords": [topic, "limitations", "conflicting"]},
        {"title": "Reviews and synthesis", "question": f"What systematic reviews synthesize evidence about {topic}?", "keywords": [topic, "systematic review", "meta-analysis"]},
    ]
    queries = _unique_strings(
        [
            question,
            f"{topic} systematic review meta-analysis",
            f"{topic} methods evidence dataset",
            f"{topic} limitations controversy",
            f"{topic} recent advances",
        ]
    )[: max(2, int(max_queries))]
    return {
        "title": question[:120],
        "objective": question,
        "perspectives": perspectives,
        "search_queries": queries,
        "inclusion_criteria": ["Directly relevant to the research question", "Traceable scholarly metadata", "Full text preferred for final claims"],
        "exclusion_criteria": ["Duplicate versions", "Records without enough metadata", "Search snippets used as evidence"],
        "planner": "deterministic",
    }


def _normalize_plan(
    question: str,
    raw: Any,
    *,
    fallback: dict[str, Any],
    max_queries: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return fallback
    perspectives: list[dict[str, Any]] = []
    for value in list(raw.get("perspectives", []) or [])[:5]:
        if not isinstance(value, dict):
            continue
        title = " ".join(str(value.get("title", "")).split())
        prompt = " ".join(str(value.get("question", "")).split())
        keywords = _unique_strings(list(value.get("keywords", []) or []))[:8]
        if title and (prompt or keywords):
            perspectives.append({"title": title, "question": prompt or title, "keywords": keywords})
    queries = _unique_strings(list(raw.get("search_queries", []) or []))[: max(2, int(max_queries))]
    if len(perspectives) < 2 or len(queries) < 2:
        return fallback
    return {
        "title": " ".join(str(raw.get("title") or fallback["title"]).split())[:160],
        "objective": " ".join(str(raw.get("objective") or question).split()),
        "perspectives": perspectives,
        "search_queries": queries,
        "inclusion_criteria": _unique_strings(list(raw.get("inclusion_criteria", []) or []))[:8],
        "exclusion_criteria": _unique_strings(list(raw.get("exclusion_criteria", []) or []))[:8],
        "planner": "llm",
    }


def _merge_query_results(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        candidate = dict(item)
        doi = str(candidate.get("doi", "")).casefold().strip()
        title_key = "".join(character for character in str(candidate.get("title", "")).casefold() if character.isalnum())
        key = f"doi:{doi}" if doi else f"title:{title_key}:{candidate.get('year') or ''}"
        if key not in merged:
            candidate["query_hit_count"] = 1
            merged[key] = candidate
            continue
        current = merged[key]
        current["query_hit_count"] = int(current.get("query_hit_count", 1) or 1) + 1
        current["score"] = max(float(current.get("score", 0.0) or 0.0), float(candidate.get("score", 0.0) or 0.0))
        current["sources"] = _unique_strings([*current.get("sources", []), *candidate.get("sources", [])])
        current["source_records"] = [*list(current.get("source_records", []) or []), *list(candidate.get("source_records", []) or [])]
        if len(str(candidate.get("abstract", ""))) > len(str(current.get("abstract", ""))):
            current["abstract"] = candidate["abstract"]
        for field_name in ("doi", "url", "oa_url", "arxiv_id", "year", "venue"):
            if not current.get(field_name) and candidate.get(field_name):
                current[field_name] = candidate[field_name]
    for item in merged.values():
        item["score"] = round(float(item.get("score", 0.0) or 0.0) + min(0.4, 0.08 * (int(item.get("query_hit_count", 1)) - 1)), 6)
    return sorted(
        merged.values(),
        key=lambda item: (-float(item.get("score", 0.0)), -int(item.get("query_hit_count", 1)), str(item.get("title", ""))),
    )


def _perspective_coverage(plan: dict[str, Any], items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for perspective in list(plan.get("perspectives", []) or []):
        keywords = _unique_strings([*list(perspective.get("keywords", []) or []), str(perspective.get("title", ""))])
        terms = set(token for keyword in keywords for token in lexical_tokens(keyword) if len(token) > 1)
        matched: list[str] = []
        for item in items:
            haystack = set(
                lexical_tokens(
                    f"{item.get('title', '')} {item.get('abstract', '')} {' '.join(item.get('keywords', []))}"
                )
            )
            if terms and len(terms & haystack) >= min(2, len(terms)):
                matched.append(str(item.get("doi") or item.get("source_id") or item.get("title", "")))
        coverage.append(
            {
                "title": str(perspective.get("title", "")),
                "question": str(perspective.get("question", "")),
                "keywords": keywords,
                "matching_papers": len(matched),
                "sample_ids": matched[:5],
            }
        )
    return coverage


def _topic_phrase(question: str) -> str:
    clean = re.sub(r"[?？!！]", " ", question)
    return " ".join(clean.split())[:160]


def _unique_strings(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = " ".join(str(value or "").split())
        if not clean or clean.casefold() in seen:
            continue
        seen.add(clean.casefold())
        result.append(clean)
    return result
