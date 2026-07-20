from __future__ import annotations

import json
from datetime import date
from hashlib import blake2b
from html import escape
from pathlib import Path
from typing import Any


def generate_mistake_cases(
    details: dict[str, Any],
    *,
    gold_rows: list[dict[str, Any]] | None = None,
    details_path: str | Path = "",
    gold_path: str | Path = "",
    created_at: str | None = None,
    max_cases: int = 0,
) -> list[dict[str, Any]]:
    created = created_at or date.today().isoformat()
    metrics = dict(details.get("metrics", {}) or {})
    gold_texts = _gold_evidence_texts(gold_rows or [])
    cases: list[dict[str, Any]] = []
    for question in list(details.get("questions", []) or []):
        if not isinstance(question, dict):
            continue
        if not bool(question.get("answerable", True)):
            continue
        gold_ids = _string_list(question.get("gold_evidence_ids", []))
        if not gold_ids:
            continue
        missing_gold = _string_list(question.get("missing_gold_evidence_ids", []))
        unmapped_gold = _string_list(question.get("unmapped_gold_evidence_ids", []))
        if not missing_gold and not unmapped_gold:
            continue
        retrieved_gold = _string_list(question.get("retrieved_gold_evidence_ids", []))
        retrieved = _string_list(question.get("retrieved_evidence_ids", []))
        tags = _mistake_tags(
            question=question,
            gold_ids=gold_ids,
            missing_gold=missing_gold,
            unmapped_gold=unmapped_gold,
            retrieved_gold=retrieved_gold,
            retrieved=retrieved,
            gold_texts=gold_texts,
        )
        failure_type = _failure_type(tags=tags, retrieved_gold=retrieved_gold)
        case = {
            "id": _mistake_id(question, created),
            "created_at": created,
            "updated_at": created,
            "status": "open",
            "severity": "P1",
            "area": "bench",
            "failure_type": failure_type,
            "title": _case_title(question, tags),
            "symptom": _case_symptom(question, missing_gold=missing_gold, unmapped_gold=unmapped_gold),
            "evidence": _case_evidence(
                question,
                metrics=metrics,
                missing_gold=missing_gold,
                unmapped_gold=unmapped_gold,
            ),
            "root_cause": _root_cause(tags=tags, retrieved_gold=retrieved_gold),
            "fix": "Not fixed yet. Use this case to drive retrieval, parsing, reranking, or citation changes.",
            "regression_guard": "Keep this benchmark detail row or promote it into a local gold-set regression.",
            "next_action": _next_action(tags=tags),
            "links": [str(path) for path in (details_path, gold_path) if str(path)],
            "question": str(question.get("question", "")),
            "gold_evidence": gold_ids,
            "predicted_evidence": retrieved,
            "answer_expected": "",
            "answer_actual": "",
            "metric_before": {
                "gold_evidence_recall_at_k": float(question.get("gold_evidence_recall_at_k", 0.0) or 0.0),
            },
            "metric_after": {},
            "tags": tags,
        }
        cases.append(case)
        if max_cases > 0 and len(cases) >= int(max_cases):
            break
    return cases


def render_mistake_cases_report(cases: list[dict[str, Any]], *, title: str = "ScanSci Mistake Cases") -> str:
    summary = summarize_mistake_cases(cases)
    rows = "\n".join(_render_case(case, index=index) for index, case in enumerate(cases, start=1))
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 2rem; color: #17202a; }",
            "    main { max-width: 1120px; margin: 0 auto; }",
            "    article { border-top: 1px solid #d7dee8; padding: 1rem 0; }",
            "    h2 { font-size: 1.05rem; margin-bottom: .35rem; }",
            "    .meta { display: flex; flex-wrap: wrap; gap: .5rem; color: #455466; }",
            "    .tag { border: 1px solid #cbd5e1; border-radius: 999px; padding: .08rem .45rem; background: #f8fafc; }",
            "    code { white-space: pre-wrap; overflow-wrap: anywhere; }",
            "    ul { margin-top: .35rem; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            f"  <p>{len(cases)} cases</p>",
            _render_summary(summary),
            rows,
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def summarize_mistake_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    failure_type_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for case in cases:
        failure_type = str(case.get("failure_type", "")).strip() or "unknown"
        severity = str(case.get("severity", "")).strip() or "unknown"
        failure_type_counts[failure_type] = failure_type_counts.get(failure_type, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        for tag in case.get("tags", []) or []:
            tag_value = str(tag).strip()
            if not tag_value:
                continue
            tag_counts[tag_value] = tag_counts.get(tag_value, 0) + 1
    return {
        "total_cases": len(cases),
        "failure_type_counts": dict(sorted(failure_type_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
    }


def _render_summary(summary: dict[str, Any]) -> str:
    rows = [
        ("Failure Types", summary.get("failure_type_counts", {})),
        ("Tags", summary.get("tag_counts", {})),
        ("Severity", summary.get("severity_counts", {})),
    ]
    sections = []
    for label, value in rows:
        items = _dict_count_items(value)
        sections.append(f"    <h2>{escape(label)}</h2>")
        sections.append(f"    <ul>{items}</ul>" if items else "    <p>None.</p>")
    return "\n".join(['  <section aria-label="Mistake summary">', *sections, "  </section>"])


def _dict_count_items(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return "".join(f"<li>{escape(str(key))}: {escape(str(value[key]))}</li>" for key in sorted(value))


def _render_case(case: dict[str, Any], *, index: int) -> str:
    tags = "".join(f'<span class="tag">{escape(str(tag))}</span>' for tag in case.get("tags", []) or [])
    gold = "".join(f"<li><code>{escape(str(item))}</code></li>" for item in case.get("gold_evidence", []) or [])
    predicted = "".join(
        f"<li><code>{escape(str(item))}</code></li>" for item in case.get("predicted_evidence", []) or []
    )
    return "\n".join(
        [
            f'  <article id="{escape(str(case.get("id", "")))}">',
            f"    <h2>{index}. {escape(str(case.get('title', 'Untitled mistake')))}</h2>",
            '    <div class="meta">',
            f"      <span>{escape(str(case.get('failure_type', '')))}</span>",
            f"      <span>{escape(str(case.get('severity', '')))}</span>",
            tags,
            "    </div>",
            f"    <p><code>{escape(str(case.get('question', '')))}</code></p>",
            f"    <p>{escape(str(case.get('symptom', '')))}</p>",
            "    <h3>Gold Evidence</h3>",
            f"    <ul>{gold}</ul>",
            "    <h3>Predicted Evidence</h3>",
            f"    <ul>{predicted}</ul>",
            "  </article>",
        ]
    )


def _gold_evidence_texts(gold_rows: list[dict[str, Any]]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for row in gold_rows:
        if not isinstance(row, dict):
            continue
        for candidate in row.get("candidate_evidence", []) or []:
            if not isinstance(candidate, dict):
                continue
            evidence_id = str(candidate.get("evidence_id", "")).strip()
            text = str(candidate.get("text", "")).strip()
            if evidence_id and text:
                texts[evidence_id] = text
    return texts


def _mistake_tags(
    *,
    question: dict[str, Any],
    gold_ids: list[str],
    missing_gold: list[str],
    unmapped_gold: list[str],
    retrieved_gold: list[str],
    retrieved: list[str],
    gold_texts: dict[str, str],
) -> list[str]:
    tags: list[str] = []
    if any(_looks_like_float_or_table(gold_texts.get(gold_id, "")) for gold_id in gold_ids):
        tags.append("float_or_table_evidence")
    if retrieved_gold and missing_gold:
        tags.append("partial_retrieval")
    elif missing_gold:
        tags.append("retrieval_miss")
    if unmapped_gold:
        tags.append("unmapped_gold")
    tags.extend(_trace_diagnostic_tags(question, retrieved_gold=retrieved_gold, retrieved=retrieved))
    return tags


def _failure_type(*, tags: list[str], retrieved_gold: list[str]) -> str:
    if "float_or_table_evidence" in tags or "unmapped_gold" in tags:
        return "format_loss"
    for trace_failure in ("wrong_scope", "under_search", "wrong_route", "bad_query_variant", "over_search"):
        if trace_failure in tags:
            return trace_failure
    if retrieved_gold:
        return "wrong_ranking"
    return "retrieval_miss"


def _case_title(question: dict[str, Any], tags: list[str]) -> str:
    question_id = str(question.get("question_id", "")).strip() or "unknown-question"
    if "float_or_table_evidence" in tags:
        return f"Float/table gold evidence was not recovered for {question_id}"
    if "under_search" in tags:
        return f"Search produced too few candidates for {question_id}"
    if "wrong_route" in tags:
        return f"Retriever surfaced non-gold evidence for {question_id}"
    if "wrong_scope" in tags:
        return f"Retrieval scope may be excluding evidence for {question_id}"
    if "partial_retrieval" in tags:
        return f"Only part of gold evidence was recovered for {question_id}"
    return f"Gold evidence was missed for {question_id}"


def _case_symptom(question: dict[str, Any], *, missing_gold: list[str], unmapped_gold: list[str]) -> str:
    parts = []
    if missing_gold:
        parts.append(f"Missing gold evidence: {', '.join(missing_gold)}.")
    if unmapped_gold:
        parts.append(f"Unmapped gold evidence: {', '.join(unmapped_gold)}.")
    if not parts:
        parts.append("Benchmark detail row indicates a retrieval failure.")
    recall = question.get("gold_evidence_recall_at_k", "")
    if recall != "":
        parts.append(f"Gold evidence recall for this question is {recall}.")
    return " ".join(parts)


def _case_evidence(
    question: dict[str, Any],
    *,
    metrics: dict[str, Any],
    missing_gold: list[str],
    unmapped_gold: list[str],
) -> list[str]:
    values = [
        f"question_id={question.get('question_id', '')}",
        f"k={metrics.get('k', '')}",
        f"dataset={metrics.get('dataset', '')}",
    ]
    if missing_gold:
        values.append(f"missing_gold_evidence_ids={','.join(missing_gold)}")
    if unmapped_gold:
        values.append(f"unmapped_gold_evidence_ids={','.join(unmapped_gold)}")
    for key in ("retrieval_queries", "retrieved_route_counts", "retrieval_trace_summary"):
        if key in question:
            values.append(f"{key}={_compact_json(question.get(key))}")
    return values


def _root_cause(*, tags: list[str], retrieved_gold: list[str]) -> str:
    if "float_or_table_evidence" in tags:
        return "Likely parser/index gap for float, table, figure, or caption evidence."
    if "unmapped_gold" in tags:
        return "Gold evidence could not be aligned to raw evidence spans."
    if "wrong_scope" in tags:
        return "Retrieval was constrained to a document scope but produced no usable mapped gold evidence."
    if "under_search" in tags:
        return "The search step produced no candidates or no returned hits, so reranking never saw the gold evidence."
    if "wrong_route" in tags:
        return "Retrieval routes returned plausible non-gold evidence, suggesting route weighting or reranking is misdirected."
    if "bad_query_variant" in tags:
        return "Generated query variants did not add useful candidate evidence for this question."
    if "over_search" in tags:
        return "Multiple search calls were issued after evidence was already partially found, suggesting inefficient search control."
    if retrieved_gold:
        return "Retriever found some supporting evidence but not the full required evidence set."
    return "Retriever did not surface any mapped gold evidence within the evaluated cutoff."


def _next_action(*, tags: list[str]) -> str:
    if "float_or_table_evidence" in tags:
        return "Add table/float serialization or dedicated float evidence indexing, then rerun the same case."
    if "unmapped_gold" in tags:
        return "Inspect gold-to-raw span alignment and source parsing for this document."
    if "wrong_scope" in tags:
        return "Check scope filters against the gold document IDs and rerun with a broader scope for this case."
    if "under_search" in tags:
        return "Improve exact term extraction or query expansion before increasing reranker complexity."
    if "wrong_route" in tags:
        return "Compare FTS, dense, and hybrid route candidates; adjust route weights or candidate pooling."
    if "bad_query_variant" in tags:
        return "Inspect generated query variants and add a variant that preserves entities, measurements, and answer type."
    if "over_search" in tags:
        return "Add a stop rule or process-reward check so extra search calls only run when current evidence is insufficient."
    if "partial_retrieval" in tags:
        return "Try query expansion, parent context, or larger candidate pools for this question type."
    return "Inspect first-stage recall and reranker ordering for this question."


def _trace_diagnostic_tags(
    question: dict[str, Any],
    *,
    retrieved_gold: list[str],
    retrieved: list[str],
) -> list[str]:
    if not _has_retrieval_trace(question):
        return []
    summary = _trace_summary(question)
    route_counts = _trace_route_counts(question, summary=summary)
    search_calls = _int_metric(summary, "search_calls", _search_event_count(question))
    queries = _int_metric(summary, "queries", search_calls)
    fts_candidates = _int_metric(summary, "fts_candidates", _sum_trace_field(question, "fts_candidates"))
    dense_candidates = _int_metric(summary, "dense_candidates", _sum_trace_field(question, "dense_candidates"))
    unique_candidates = _int_metric(summary, "unique_candidates", _sum_trace_field(question, "unique_candidates"))
    returned_hits = _int_metric(summary, "returned_hits", len(retrieved))
    total_candidates = max(unique_candidates, fts_candidates + dense_candidates)

    tags: list[str] = []
    if _scope_looks_too_narrow(question) and not retrieved_gold:
        tags.append("wrong_scope")
    if total_candidates == 0 or returned_hits == 0:
        tags.append("under_search")
    if queries > 1 and (total_candidates == 0 or _query_variants_do_not_contribute(route_counts, queries=queries)):
        tags.append("bad_query_variant")
    if retrieved and not retrieved_gold and route_counts and "under_search" not in tags:
        tags.append("wrong_route")
    if search_calls > 1 and retrieved_gold and _has_search_after_first_gold_route(route_counts):
        tags.append("over_search")
    return tags


def _has_retrieval_trace(question: dict[str, Any]) -> bool:
    return isinstance(question.get("retrieval_trace_summary"), dict) or isinstance(question.get("retrieval_trace"), list)


def _trace_summary(question: dict[str, Any]) -> dict[str, Any]:
    value = question.get("retrieval_trace_summary")
    return value if isinstance(value, dict) else {}


def _trace_route_counts(question: dict[str, Any], *, summary: dict[str, Any]) -> dict[str, int]:
    for value in (question.get("retrieved_route_counts"), summary.get("route_counts")):
        if not isinstance(value, dict):
            continue
        counts: dict[str, int] = {}
        for key, count in value.items():
            route = str(key).strip()
            if route:
                counts[route] = counts.get(route, 0) + int(count or 0)
        if counts:
            return counts
    return {}


def _search_events(question: dict[str, Any]) -> list[dict[str, Any]]:
    trace = question.get("retrieval_trace")
    if not isinstance(trace, list):
        return []
    return [event for event in trace if isinstance(event, dict) and str(event.get("stage", "")) == "search"]


def _search_event_count(question: dict[str, Any]) -> int:
    return len(_search_events(question))


def _sum_trace_field(question: dict[str, Any], field: str) -> int:
    return sum(int(event.get(field, 0) or 0) for event in _search_events(question))


def _int_metric(summary: dict[str, Any], field: str, fallback: int) -> int:
    try:
        return int(summary.get(field, fallback) or 0)
    except (TypeError, ValueError):
        return int(fallback)


def _scope_looks_too_narrow(question: dict[str, Any]) -> bool:
    events = _search_events(question)
    scoped_events = [event for event in events if "scope_doc_count" in event]
    if not scoped_events:
        return False
    empty_scope = all(int(event.get("scope_doc_count", 0) or 0) == 0 for event in scoped_events)
    no_results = all(
        int(event.get("returned_hits", 0) or 0) == 0 and int(event.get("unique_candidates", 0) or 0) == 0
        for event in scoped_events
    )
    return empty_scope and no_results


def _query_variants_do_not_contribute(route_counts: dict[str, int], *, queries: int) -> bool:
    if queries <= 1:
        return False
    query_routes = [route for route in route_counts if route.startswith("query-")]
    if not query_routes:
        return True
    return all(route_counts.get(f"query-{index}", 0) == 0 for index in range(2, queries + 1))


def _has_search_after_first_gold_route(route_counts: dict[str, int]) -> bool:
    return any(route.startswith("query-") and route != "query-1" and count > 0 for route, count in route_counts.items())


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _looks_like_float_or_table(text: str) -> bool:
    value = text.strip().lower()
    return value.startswith("float selected") or " table " in f" {value} " or value.startswith("table ")


def _mistake_id(question: dict[str, Any], created_at: str) -> str:
    compact_date = created_at.replace("-", "")
    raw_id = str(question.get("question_id", "")).strip() or str(question.get("question", "")).strip()
    slug = _slug(raw_id)
    if not slug:
        digest = blake2b(raw_id.encode("utf-8"), digest_size=4).hexdigest().upper()
        slug = f"Q{digest}"
    return f"SS-BENCH-{compact_date}-{slug[:48]}"


def _slug(value: str) -> str:
    chars = []
    for char in value.upper():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    return "".join(chars).strip("-")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
