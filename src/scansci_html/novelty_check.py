"""Evidence-grounded prior-art overlap assessment.

This module intentionally does not claim to *prove* novelty.  Discovery
metadata creates leads; only indexed, traceable full-text excerpts may support
the structured overlap assessment.  Model memory is never accepted as a paper
record or citation source.
"""

from __future__ import annotations

from collections import defaultdict
import json
from typing import Any, Sequence

from .text_tokenization import lexical_tokens


AXIS_KEYS = ("problem_framing", "core_mechanism", "key_insight", "application_domain")
AXIS_LABELS = {
    "problem_framing": "问题设定",
    "core_mechanism": "核心机制",
    "key_insight": "关键洞见",
    "application_domain": "应用领域",
}
AXIS_STATUSES = {"match", "partial", "differ", "unknown"}


def plan_novelty_check(
    problem: str,
    novelty: str,
    *,
    chat_client: Any | None = None,
    max_queries: int = 5,
) -> dict[str, Any]:
    """Decompose a claim and build bounded prior-art searches."""

    clean_problem = " ".join(str(problem).split())
    clean_novelty = " ".join(str(novelty).split())
    if not clean_problem or not clean_novelty:
        raise ValueError("problem and novelty are required")
    fallback = _fallback_plan(clean_problem, clean_novelty, max_queries=max_queries)
    if chat_client is None:
        return fallback
    messages = [
        {
            "role": "system",
            "content": (
                "你是学术查新规划器。只拆解用户主张并生成检索式，不判断新颖性，不列举记忆中的论文。"
                "把主张拆成 problem_framing、core_mechanism、key_insight、application_domain 四轴；"
                "每轴给出 statement 和可检索 terms。生成 3 到 5 条彼此互补的 prior-art queries。"
                "返回 JSON：{axes:{axis:{statement,terms:[...]}},search_queries:[...]}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"problem": clean_problem, "claimed_novelty": clean_novelty}, ensure_ascii=False),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="novelty_check_plan") or {}
        return _normalize_plan(clean_problem, clean_novelty, raw, fallback=fallback, max_queries=max_queries)
    except Exception as error:
        return {**fallback, "planning_error": f"{type(error).__name__}: {error}"[:500]}


def assess_novelty_evidence(
    plan: dict[str, Any],
    discovery: dict[str, Any],
    research: dict[str, Any],
    *,
    chat_client: Any | None = None,
) -> dict[str, Any]:
    """Assess overlap using indexed evidence only and return a citable artifact."""

    evidence = [dict(row) for row in list(research.get("evidence", []) or [])]
    known = {
        str(row.get("citation_id", "")): row
        for row in evidence
        if str(row.get("citation_id", "")).strip() and str(row.get("exact_quote", "")).strip()
    }
    document_count = len({str(row.get("doc_id", "")) for row in known.values() if str(row.get("doc_id", ""))})
    adequacy = {
        "sufficient": len(known) >= 3 and document_count >= 2,
        "citation_count": len(known),
        "document_count": document_count,
        "minimum_citations": 3,
        "minimum_documents": 2,
    }
    base = {
        "phase": "novelty_assessment",
        "problem": str(plan.get("problem", "")),
        "claimed_novelty": str(plan.get("claimed_novelty", "")),
        "axes": dict(plan.get("axes", {}) or {}),
        "search_queries": list(plan.get("search_queries", []) or []),
        "coverage": _coverage(discovery, research),
        "evidence_adequacy": adequacy,
        "discovery_candidates": [_discovery_lead(item) for item in list(discovery.get("items", []) or [])[:20]],
        "provenance_policy": {
            "model_recall_allowed_as_evidence": False,
            "discovery_metadata_citable": False,
            "fulltext_evidence_required": True,
        },
    }
    if not adequacy["sufficient"]:
        reason = "可回跳全文证据少于 3 条或覆盖文献少于 2 篇，不能据此判断新颖性。"
        return _unresolved_result(base, reason=reason)

    raw: dict[str, Any] = {}
    assessment_mode = "lexical_fallback"
    if chat_client is not None:
        try:
            raw = chat_client.complete_json(
                _assessment_messages(plan, list(known.values())),
                schema_name="novelty_evidence_assessment",
            ) or {}
            assessment_mode = "model_evidence_assessment"
        except Exception as error:
            raw = {"limitations": [f"模型评估失败：{type(error).__name__}: {error}"[:300]]}
    prior_works = _normalize_prior_works(raw, known, plan=plan)
    if not prior_works:
        prior_works = _lexical_prior_works(plan, list(known.values()))
        assessment_mode = "lexical_fallback"

    used_ids = _unique_strings(
        citation_id
        for work in prior_works
        for citation_id in list(work.get("citation_ids", []) or [])
        if citation_id in known
    )
    if not used_ids:
        return _unresolved_result(base, reason="全文证据存在，但尚未形成可引用的逐论文重合判断。")

    strongest = max(prior_works, key=lambda item: int(item.get("matching_axis_count", 0) or 0))
    max_matches = int(strongest.get("matching_axis_count", 0) or 0)
    if assessment_mode != "model_evidence_assessment":
        citations = [_citation_payload(known[citation_id]) for citation_id in used_ids]
        reason = "当前仅完成全文证据上的词汇级重合筛查；尚未完成语义四轴审查，不能给出新颖性等级。"
        return {
            **base,
            "status": "provisional",
            "assessment_mode": assessment_mode,
            "verdict": {
                "level": None,
                "code": "unresolved",
                "label": "潜在重合线索，等待语义核验",
                "not_proof_of_novelty": True,
            },
            "closest_prior_work": strongest,
            "prior_works": prior_works,
            "delta_statement": "",
            "limitations": [
                reason,
                "未检出强重合不等于证明新颖；结论受数据源、检索式、全文可得性和截止时间限制。",
            ],
            "reader_answer": {"text": reason, "citation_count": len(citations), "citations": citations},
            "citation_verification": {
                "passed": bool(citations) and all(citation.get("evidence_id") for citation in citations),
                "claim_count": len(prior_works),
                "supported_claim_count": len(prior_works),
                "unsupported_claim_count": 0,
                "used_citation_ids": used_ids,
            },
        }
    level = 5 - max(0, min(4, max_matches))
    verdict = _verdict(level, assessment_mode=assessment_mode)
    limitations = _unique_strings(
        [
            *list(raw.get("limitations", []) or []),
            "未检出强重合不等于证明新颖；结论受数据源、检索式、全文可得性和截止时间限制。",
            "摘要或书目记录仅用于召回候选，最终重合判断只引用已索引全文片段。",
        ]
    )
    citations = [_citation_payload(known[citation_id]) for citation_id in used_ids]
    delta = str(raw.get("delta_statement", "")).strip()
    if not delta:
        differing = [AXIS_LABELS[key] for key, value in strongest["axes"].items() if value == "differ"]
        if differing:
            delta = f"与最接近的“{strongest['paper']}”相比，当前主张仍需在{'、'.join(differing)}上提供可检验差异。"
        else:
            delta = "当前证据尚不足以形成稳健的一句话差异陈述。"
    summary = (
        f"最接近的已核验工作为“{strongest['paper']}”，四轴中有 {max_matches} 轴显示重合风险；"
        f"当前判定为 {verdict['label']}。"
    )
    return {
        **base,
        "status": "assessed" if assessment_mode == "model_evidence_assessment" else "provisional",
        "assessment_mode": assessment_mode,
        "verdict": verdict,
        "closest_prior_work": strongest,
        "prior_works": prior_works,
        "delta_statement": delta,
        "limitations": limitations,
        "reader_answer": {
            "text": summary,
            "citation_count": len(citations),
            "citations": citations,
        },
        "citation_verification": {
            "passed": bool(citations) and all(citation.get("evidence_id") for citation in citations),
            "claim_count": len(prior_works),
            "supported_claim_count": len(prior_works),
            "unsupported_claim_count": 0,
            "used_citation_ids": used_ids,
        },
    }


def _fallback_plan(problem: str, novelty: str, *, max_queries: int) -> dict[str, Any]:
    axes = {
        "problem_framing": {"label": AXIS_LABELS["problem_framing"], "statement": problem, "terms": _terms(problem)},
        "core_mechanism": {"label": AXIS_LABELS["core_mechanism"], "statement": novelty, "terms": _terms(novelty)},
        "key_insight": {"label": AXIS_LABELS["key_insight"], "statement": novelty, "terms": _terms(novelty)},
        "application_domain": {"label": AXIS_LABELS["application_domain"], "statement": problem, "terms": _terms(problem)},
    }
    queries = _unique_strings(
        [
            f'"{novelty}"',
            f"{problem} {novelty}",
            f"{problem} prior work method",
            f"{problem} alternative approach comparison",
            f"{novelty} limitations evaluation",
        ]
    )[: max(3, min(8, int(max_queries)))]
    return {
        "problem": problem,
        "claimed_novelty": novelty,
        "axes": axes,
        "search_queries": queries,
        "perspectives": [
            {
                "title": value["label"],
                "question": value["statement"],
                "keywords": value["terms"],
            }
            for value in axes.values()
        ],
        "planner": "deterministic",
    }


def _normalize_plan(
    problem: str,
    novelty: str,
    raw: Any,
    *,
    fallback: dict[str, Any],
    max_queries: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return fallback
    raw_axes = dict(raw.get("axes") or {})
    axes: dict[str, dict[str, Any]] = {}
    for key in AXIS_KEYS:
        value = dict(raw_axes.get(key) or {})
        statement = " ".join(str(value.get("statement") or fallback["axes"][key]["statement"]).split())
        terms = _unique_strings(list(value.get("terms", []) or []))[:12] or fallback["axes"][key]["terms"]
        axes[key] = {"label": AXIS_LABELS[key], "statement": statement, "terms": terms}
    queries = _unique_strings(list(raw.get("search_queries", []) or []))[: max(3, min(8, int(max_queries)))]
    if len(queries) < 3:
        queries = fallback["search_queries"]
    return {
        "problem": problem,
        "claimed_novelty": novelty,
        "axes": axes,
        "search_queries": queries,
        "perspectives": [
            {"title": value["label"], "question": value["statement"], "keywords": value["terms"]}
            for value in axes.values()
        ],
        "planner": "llm",
    }


def _assessment_messages(plan: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact = [
        {
            "citation_id": str(row.get("citation_id", "")),
            "paper": str(row.get("paper", "")),
            "doc_id": str(row.get("doc_id", "")),
            "section": str(row.get("section", "")),
            "exact_quote": str(row.get("exact_quote", ""))[:1200],
        }
        for row in evidence[:50]
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是保守的学术查新审查员。只能使用给定全文引文；不得加入记忆中的论文、不得把摘要或搜索结果当证据。"
                "按四轴比较每篇有证据的工作。状态只能是 match、partial、differ、unknown；"
                "每篇判断必须给 citation_ids，且编号必须来自输入。证据不能证明差异时使用 unknown。"
                "返回 JSON：{prior_works:[{paper,doc_id,axes:{problem_framing,core_mechanism,key_insight,application_domain},"
                "citation_ids:[...],summary}],delta_statement,limitations:[...]}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "problem": plan.get("problem"),
                    "claimed_novelty": plan.get("claimed_novelty"),
                    "axes": plan.get("axes"),
                    "fulltext_evidence": compact,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _normalize_prior_works(
    raw: dict[str, Any],
    known: dict[str, dict[str, Any]],
    *,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for citation_id, row in known.items():
        grouped[str(row.get("doc_id") or row.get("paper") or "")].add(citation_id)
    results: list[dict[str, Any]] = []
    for value in list(raw.get("prior_works", []) or [])[:20]:
        if not isinstance(value, dict):
            continue
        citation_ids = _unique_strings(list(value.get("citation_ids", []) or []))
        citation_ids = [citation_id for citation_id in citation_ids if citation_id in known]
        if not citation_ids:
            continue
        actual_doc_ids = {str(known[citation_id].get("doc_id", "")) for citation_id in citation_ids}
        requested_doc_id = str(value.get("doc_id", ""))
        if requested_doc_id and requested_doc_id not in actual_doc_ids:
            continue
        first = known[citation_ids[0]]
        axes_value = dict(value.get("axes") or {})
        axes = {
            key: str(axes_value.get(key, "unknown")) if str(axes_value.get(key, "unknown")) in AXIS_STATUSES else "unknown"
            for key in AXIS_KEYS
        }
        matching = sum(status in {"match", "partial"} for status in axes.values())
        results.append(
            {
                "paper": str(first.get("paper") or value.get("paper") or "未命名文献"),
                "doc_id": str(first.get("doc_id") or requested_doc_id),
                "axes": axes,
                "matching_axis_count": matching,
                "citation_ids": citation_ids,
                "summary": " ".join(str(value.get("summary", "")).split()),
            }
        )
    return results


def _lexical_prior_works(plan: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        grouped[str(row.get("doc_id") or row.get("paper") or "")].append(row)
    results: list[dict[str, Any]] = []
    for rows in grouped.values():
        text_terms = set(_terms(" ".join(str(row.get("exact_quote", "")) for row in rows)))
        axes: dict[str, str] = {}
        for key in AXIS_KEYS:
            axis = dict(dict(plan.get("axes", {}) or {}).get(key) or {})
            terms = set(_terms(" ".join([str(axis.get("statement", "")), *list(axis.get("terms", []) or [])])))
            overlap = len(terms & text_terms) / max(1, len(terms))
            axes[key] = "partial" if overlap >= 0.2 else "unknown"
        citations = [str(row.get("citation_id", "")) for row in rows if str(row.get("citation_id", ""))][:4]
        results.append(
            {
                "paper": str(rows[0].get("paper") or "未命名文献"),
                "doc_id": str(rows[0].get("doc_id") or ""),
                "axes": axes,
                "matching_axis_count": sum(value == "partial" for value in axes.values()),
                "citation_ids": citations,
                "summary": "词汇级回退只用于标记潜在重合，不能证明语义等价或差异。",
            }
        )
    return results


def _unresolved_result(base: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        **base,
        "status": "insufficient_evidence",
        "assessment_mode": "none",
        "verdict": {"level": None, "code": "unresolved", "label": "证据不足，无法判断"},
        "closest_prior_work": None,
        "prior_works": [],
        "delta_statement": "",
        "limitations": [reason, "未检出结果不等于证明新颖。"],
        "reader_answer": {"text": reason, "citation_count": 0, "citations": []},
        "citation_verification": {
            "passed": True,
            "claim_count": 0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "reason": "没有输出未经证据支持的重合结论。",
        },
    }


def _coverage(discovery: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
    rounds = list(discovery.get("rounds", []) or [])
    return {
        "query_count": sum(len(list(round_.get("queries", []) or [])) for round_ in rounds),
        "providers_succeeded": _unique_strings(
            source
            for item in list(discovery.get("items", []) or [])
            for source in list(item.get("sources", []) or [])
        ),
        "candidate_count": int(discovery.get("candidate_count", 0) or 0),
        "deduplicated_count": int(discovery.get("deduplicated_count", 0) or 0),
        "indexed_evidence_count": len(list(research.get("evidence", []) or [])),
        "indexed_document_count": int(dict(research.get("retrieval_summary", {}) or {}).get("document_count", 0) or 0),
        "unresolved_gaps": list(discovery.get("unresolved_gaps", []) or []),
        "provider_errors": dict(discovery.get("provider_errors", {}) or {}),
    }


def _discovery_lead(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("title", "doi", "year", "venue", "authors", "url", "oa_url", "sources", "score"):
        value = item.get(key)
        if value is not None and value != "" and value != []:
            result[key] = value
    return result


def _citation_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key, "")
        for key in (
            "citation_id",
            "evidence_id",
            "doc_id",
            "paper",
            "section",
            "exact_quote",
            "html_path",
            "html_anchor",
            "reader_url",
            "doi",
        )
    }


def _verdict(level: int, *, assessment_mode: str) -> dict[str, Any]:
    labels = {
        1: ("full_overlap_risk", "四轴重合风险"),
        2: ("high_overlap_risk", "高重合风险"),
        3: ("medium_overlap_risk", "中等重合风险"),
        4: ("low_overlap_risk", "低重合风险"),
        5: ("no_strong_overlap_found", "当前证据未发现强重合"),
    }
    code, label = labels[level]
    if assessment_mode != "model_evidence_assessment":
        label = f"初步线索：{label}"
    return {"level": level, "code": code, "label": label, "not_proof_of_novelty": True}


def _terms(value: str) -> list[str]:
    return _unique_strings(token for token in lexical_tokens(str(value)) if len(token) > 1)[:24]


def _unique_strings(values: Sequence[Any] | Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = " ".join(str(value or "").split())
        folded = clean.casefold()
        if not clean or folded in seen:
            continue
        seen.add(folded)
        result.append(clean)
    return result
