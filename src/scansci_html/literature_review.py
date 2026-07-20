"""Evidence-grounded, section-level literature review generation.

This module deliberately separates retrieval from writing.  The local evidence
engine gathers exact, anchorable quotations for every planned section; a
configured writing model then synthesizes those quotations into a review.  It
never falls back to presenting retrieval snippets as if they were review prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .llm import ChatJsonClient
from .qa.agent import answer_question


_MAX_SECTIONS = 6
_MAX_QUERIES_PER_SECTION = 2
_MAX_EVIDENCE_ROWS = 42


def retrieve_review_evidence(
    db_path: str | Path,
    question: str,
    *,
    chat_client: ChatJsonClient,
    limit: int = 14,
) -> dict[str, Any]:
    """Plan a review and retrieve evidence independently for every section."""

    topic = str(question or "").strip()
    if not topic:
        raise ValueError("question is required")
    plan = plan_literature_review(topic, chat_client=chat_client)
    global_evidence: list[dict[str, Any]] = []
    evidence_index: dict[tuple[str, str], str] = {}
    section_results: list[dict[str, Any]] = []

    for section in list(plan["sections"]):
        section_citations: list[str] = []
        query_traces: list[dict[str, Any]] = []
        for query in list(section["queries"])[:_MAX_QUERIES_PER_SECTION]:
            result = answer_question(
                db_path,
                query,
                limit=max(8, min(20, int(limit))),
                max_quotes=7,
                min_quotes=1,
                min_documents=1,
                adequacy_profile="manual",
                agentic_profile="custom",
                query_variants=2,
                max_followup_queries=1,
                paper_recall_limit=0,
                per_document_limit=3,
                answer_provider="local",
                verification_provider="local",
            )
            added = 0
            for row in list(result.get("evidence_table", []) or []):
                normalized = _normalize_evidence_row(row)
                if not normalized["evidence_id"] or not normalized["exact_quote"]:
                    continue
                key = (normalized["evidence_id"], normalized["exact_quote"])
                citation_id = evidence_index.get(key)
                if citation_id is None:
                    if len(global_evidence) >= _MAX_EVIDENCE_ROWS:
                        continue
                    citation_id = str(len(global_evidence) + 1)
                    evidence_index[key] = citation_id
                    normalized["citation_id"] = citation_id
                    global_evidence.append(normalized)
                    added += 1
                if citation_id not in section_citations:
                    section_citations.append(citation_id)
            query_traces.append(
                {
                    "query": query,
                    "evidence_count": len(result.get("evidence_table", []) or []),
                    "new_evidence_count": added,
                    "document_count": int(dict(result.get("adequacy", {}) or {}).get("document_count", 0) or 0),
                    "retrieval_queries": list(result.get("retrieval_queries", []) or []),
                }
            )
        section_results.append(
            {
                **section,
                "citation_ids": section_citations,
                "evidence_count": len(section_citations),
                "document_count": len(
                    {
                        row["doc_id"]
                        for row in global_evidence
                        if row["citation_id"] in section_citations and row["doc_id"]
                    }
                ),
                "query_traces": query_traces,
            }
        )

    document_count = len({row["doc_id"] for row in global_evidence if row["doc_id"]})
    if len(global_evidence) < 3 or document_count < 2:
        raise ValueError(
            "当前资料库不足以生成可信综述：至少需要 2 篇文献和 3 条可回跳证据。"
            "请先导入更多相关文献，或缩小综述问题的范围。"
        )
    return {
        "phase": "retrieval",
        "question": topic,
        "review_plan": {**plan, "sections": section_results},
        "section_results": section_results,
        "evidence": global_evidence,
        "retrieval_summary": {
            "section_count": len(section_results),
            "query_count": sum(len(section["query_traces"]) for section in section_results),
            "evidence_count": len(global_evidence),
            "document_count": document_count,
        },
    }


def plan_literature_review(question: str, *, chat_client: ChatJsonClient) -> dict[str, Any]:
    """Ask the writing model for a bounded outline and section search queries."""

    messages = [
        {
            "role": "system",
            "content": (
                "你是科研综述的检索规划器。把用户问题拆成 3 到 6 个互不重复、共同构成论证链的主题章节。"
                "每章给出 objective 和 1 到 2 条适合学术资料库检索的具体 query。"
                "不要写正文，不要虚构研究结论。返回 JSON："
                "{title, scope, sections:[{id,title,objective,queries:[...]}]}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"review_question": question}, ensure_ascii=False),
        },
    ]
    raw = chat_client.complete_json(messages, schema_name="literature_review_plan") or {}
    return _normalize_review_plan(question, raw)


def synthesize_literature_review(
    research: dict[str, Any],
    *,
    chat_client: ChatJsonClient,
    reader_url_builder: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Generate and strictly validate one evidence-linked review document."""

    question = str(research.get("question", "")).strip()
    plan = dict(research.get("review_plan", {}) or {})
    evidence = [dict(row) for row in list(research.get("evidence", []) or [])]
    known_ids = {str(row.get("citation_id", "")) for row in evidence if str(row.get("citation_id", ""))}
    if not question or not plan.get("sections") or len(known_ids) < 3:
        raise ValueError("综述检索结果不完整，无法进入写作阶段")

    prompt_evidence = [
        {
            "citation_id": str(row.get("citation_id", "")),
            "paper": str(row.get("paper", "")),
            "section": str(row.get("section", "")),
            "doi": str(row.get("doi", "")),
            "exact_quote": str(row.get("exact_quote", "")),
        }
        for row in evidence
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是严谨的学术综述作者。请跨论文归纳共同发现、方法差异、冲突、局限与研究空白，"
                "而不是逐条复述摘要。所有事实性句子只能来自 evidence，且每个段落必须列出 citation_ids；"
                "citation_ids 只能使用 evidence 中已有编号。区分已有结论与作者推断，不补充外部知识。"
                "输出与用户问题相同语言。返回 JSON："
                "{title,abstract:{text,citation_ids},sections:[{id,title,paragraphs:[{text,citation_ids}]}],"
                "comparison_table:{columns:[...],rows:[{cells:[...],citation_ids:[...]}]},"
                "controversies:[{text,citation_ids}],open_questions:[{text,basis,citation_ids}],limitations:[...]}。"
                "sections 必须遵循 plan；comparison_table 至少比较研究对象、方法、主要发现和局限。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "review_question": question,
                    "plan": plan,
                    "evidence": prompt_evidence,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat_client.complete_json(messages, schema_name="evidence_grounded_literature_review") or {}
    document = _normalize_review_document(question, plan, raw, known_ids=known_ids)
    document, references = _compact_document_citations(
        document,
        evidence,
        reader_url_builder=reader_url_builder,
    )
    document["references"] = references
    reader_answer = _review_reader_answer(document, references)
    verification = _verify_review_document(document, references)
    if not verification["passed"]:
        raise ValueError("写作模型返回的综述未通过引用完整性校验，请重试或更换写作模型")
    claims = [
        {
            "claim_id": sentence["claim_id"],
            "text": sentence["text"],
            "quote_ids": sentence["citation_ids"],
            "support_status": "supported",
        }
        for sentence in reader_answer["sentences"]
    ]
    return {
        "phase": "synthesis",
        "question": question,
        "review_plan": plan,
        "review_document": document,
        "reader_answer": reader_answer,
        "answer": {
            "question": question,
            "answer": claims,
            "limitations": list(document.get("limitations", []) or []),
            "insufficient_evidence": False,
            "citation_verification": verification,
        },
        "adequacy": {
            "is_sufficient": True,
            "quote_count": len(references),
            "document_count": len({item["doc_id"] for item in references if item.get("doc_id")}),
            "min_quotes": 3,
            "min_documents": 2,
            "profile": "literature_review",
            "followup_reason": "",
        },
        "citation_verification": verification,
        "verification": {
            "passed": verification["passed"],
            "supported_claims": [claim["claim_id"] for claim in claims],
        },
        "evidence_table": references,
        "retrieval_summary": dict(research.get("retrieval_summary", {}) or {}),
        "section_results": list(research.get("section_results", []) or []),
    }


def _normalize_review_plan(question: str, raw: object) -> dict[str, Any]:
    payload = dict(raw) if isinstance(raw, dict) else {}
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    sections: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, value in enumerate(raw_sections[:_MAX_SECTIONS]):
        if not isinstance(value, dict):
            continue
        title = str(value.get("title", "")).strip()
        objective = str(value.get("objective", "")).strip()
        queries = [str(item).strip() for item in list(value.get("queries", []) or []) if str(item).strip()]
        if not title or not objective or not queries:
            continue
        section_id = _unique_slug(str(value.get("id", "")) or title, used_ids, fallback=f"section-{index + 1}")
        sections.append(
            {
                "id": section_id,
                "title": title[:120],
                "objective": objective[:500],
                "queries": queries[:_MAX_QUERIES_PER_SECTION],
            }
        )
    if len(sections) < 3:
        raise ValueError("写作模型没有生成合格的综述检索提纲（至少需要 3 个主题章节）")
    return {
        "title": str(payload.get("title", "")).strip()[:180] or question[:180],
        "scope": str(payload.get("scope", "")).strip()[:800] or f"围绕“{question}”综合当前资料库证据。",
        "sections": sections,
    }


def _normalize_review_document(
    question: str,
    plan: dict[str, Any],
    raw: object,
    *,
    known_ids: set[str],
) -> dict[str, Any]:
    payload = dict(raw) if isinstance(raw, dict) else {}
    abstract = _normalized_cited_text(payload.get("abstract"), known_ids=known_ids, field="摘要")
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    sections: list[dict[str, Any]] = []
    for index, planned in enumerate(list(plan.get("sections", []) or [])):
        supplied = raw_sections[index] if index < len(raw_sections) and isinstance(raw_sections[index], dict) else {}
        paragraphs_source = supplied.get("paragraphs") if isinstance(supplied.get("paragraphs"), list) else []
        paragraphs = [
            _normalized_cited_text(item, known_ids=known_ids, field=f"章节“{planned['title']}”")
            for item in paragraphs_source
        ]
        if not paragraphs:
            raise ValueError(f"写作模型没有为章节“{planned['title']}”生成带引用的正文")
        sections.append(
            {
                "id": str(planned.get("id", f"section-{index + 1}")),
                "title": str(planned.get("title", f"主题 {index + 1}")),
                "objective": str(planned.get("objective", "")),
                "paragraphs": paragraphs,
            }
        )

    table = _normalize_comparison_table(payload.get("comparison_table"), known_ids=known_ids)
    controversies = [
        _normalized_cited_text(item, known_ids=known_ids, field="研究争议")
        for item in list(payload.get("controversies", []) or [])
    ]
    open_questions: list[dict[str, Any]] = []
    for item in list(payload.get("open_questions", []) or []):
        normalized = _normalized_cited_text(item, known_ids=known_ids, field="开放问题")
        normalized["basis"] = str(item.get("basis", "")).strip() if isinstance(item, dict) else ""
        open_questions.append(normalized)
    if not open_questions:
        raise ValueError("写作模型没有基于证据提出开放问题")
    limitations = [str(item).strip() for item in list(payload.get("limitations", []) or []) if str(item).strip()]
    if not limitations:
        limitations = ["本综述只覆盖当前 ScanSci 项目资料库中具有可回跳原文锚点的证据。"]
    return {
        "title": str(payload.get("title", "")).strip()[:180] or str(plan.get("title", "")).strip() or question,
        "scope": {"question": question, "description": str(plan.get("scope", ""))},
        "abstract": abstract,
        "sections": sections,
        "comparison_table": table,
        "controversies": controversies,
        "open_questions": open_questions,
        "limitations": limitations,
    }


def _normalized_cited_text(value: object, *, known_ids: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field}必须包含正文和 citation_ids")
    text = str(value.get("text", "")).strip()
    citation_ids = _validated_citation_ids(value.get("citation_ids"), known_ids=known_ids, field=field)
    if not text:
        raise ValueError(f"{field}正文为空")
    return {"text": text, "citation_ids": citation_ids}


def _validated_citation_ids(value: object, *, known_ids: set[str], field: str) -> list[str]:
    ids: list[str] = []
    for item in list(value or []) if isinstance(value, list) else []:
        citation_id = str(item).strip().strip("[]")
        if citation_id and citation_id not in ids:
            ids.append(citation_id)
    if not ids:
        raise ValueError(f"{field}缺少 citation_ids")
    unknown = [citation_id for citation_id in ids if citation_id not in known_ids]
    if unknown:
        raise ValueError(f"{field}引用了不存在的证据编号：{', '.join(unknown)}")
    return ids


def _normalize_comparison_table(value: object, *, known_ids: set[str]) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    columns = [str(item).strip() for item in list(payload.get("columns", []) or []) if str(item).strip()]
    if len(columns) < 4:
        raise ValueError("研究对比表至少需要 4 列")
    rows: list[dict[str, Any]] = []
    for item in list(payload.get("rows", []) or []):
        if not isinstance(item, dict):
            continue
        cells = [str(cell).strip() for cell in list(item.get("cells", []) or [])]
        if len(cells) != len(columns):
            continue
        rows.append(
            {
                "cells": cells,
                "citation_ids": _validated_citation_ids(item.get("citation_ids"), known_ids=known_ids, field="研究对比表"),
            }
        )
    if not rows:
        raise ValueError("写作模型没有生成可核验的研究对比表")
    return {"columns": columns, "rows": rows}


def _compact_document_citations(
    document: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    reader_url_builder: Callable[[str, str], str] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ordered = _document_citation_order(document)
    mapping = {old: str(index + 1) for index, old in enumerate(ordered)}
    _remap_document_citations(document, mapping)
    evidence_by_id = {str(row.get("citation_id", "")): row for row in evidence}
    references: list[dict[str, Any]] = []
    for old in ordered:
        source = dict(evidence_by_id[old])
        source["citation_id"] = mapping[old]
        doc_id = str(source.get("doc_id", ""))
        anchor = str(source.get("html_anchor", ""))
        source["reader_url"] = reader_url_builder(doc_id, anchor) if reader_url_builder and doc_id else ""
        references.append(source)
    return document, references


def _document_citation_order(document: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    items: list[dict[str, Any]] = [dict(document.get("abstract", {}) or {})]
    for section in list(document.get("sections", []) or []):
        items.extend(list(dict(section).get("paragraphs", []) or []))
    items.extend(list(document.get("controversies", []) or []))
    items.extend(list(document.get("open_questions", []) or []))
    items.extend(list(dict(document.get("comparison_table", {}) or {}).get("rows", []) or []))
    for item in items:
        for citation_id in list(dict(item).get("citation_ids", []) or []):
            value = str(citation_id)
            if value not in ordered:
                ordered.append(value)
    return ordered


def _remap_document_citations(document: dict[str, Any], mapping: dict[str, str]) -> None:
    targets: list[dict[str, Any]] = [document["abstract"]]
    for section in document["sections"]:
        targets.extend(section["paragraphs"])
    targets.extend(document["controversies"])
    targets.extend(document["open_questions"])
    targets.extend(document["comparison_table"]["rows"])
    for target in targets:
        target["citation_ids"] = [mapping[str(item)] for item in target["citation_ids"]]


def _review_reader_answer(document: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = [document["abstract"]]
    for section in document["sections"]:
        source_items.extend(section["paragraphs"])
    source_items.extend(document["controversies"])
    source_items.extend(document["open_questions"])
    for index, item in enumerate(source_items, start=1):
        ids = list(item.get("citation_ids", []) or [])
        text = str(item.get("text", ""))
        sentences.append(
            {
                "claim_id": f"review-{index:04d}",
                "text": text,
                "quote_ids": ids,
                "citation_ids": ids,
                "support_status": "supported",
                "verification_score": 1.0,
                "rendered_text": f"{text} {' '.join(f'[{item}]' for item in ids)}".strip(),
            }
        )
    return {
        "style": "evidence_grounded_literature_review",
        "text": " ".join(item["rendered_text"] for item in sentences),
        "sentences": sentences,
        "citations": references,
        "citation_count": len(references),
    }


def _verify_review_document(document: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = [document["abstract"]]
    for section in document["sections"]:
        items.extend(section["paragraphs"])
    items.extend(document["comparison_table"]["rows"])
    items.extend(document["controversies"])
    items.extend(document["open_questions"])
    uncited = [index + 1 for index, item in enumerate(items) if not item.get("citation_ids")]
    missing_anchors = [
        str(item.get("citation_id", ""))
        for item in references
        if not str(item.get("html_path", "")).strip() or not str(item.get("html_anchor", "")).strip()
    ]
    missing_exact_quotes = [
        str(item.get("citation_id", "")) for item in references if not str(item.get("exact_quote", "")).strip()
    ]
    passed = bool(items) and bool(references) and not uncited and not missing_anchors and not missing_exact_quotes
    return {
        "passed": passed,
        "claim_count": len(items),
        "supported_claim_count": len(items) - len(uncited),
        "cited_quote_count": len(references),
        "cited_evidence_rows": len(references),
        "available_quote_count": len(references),
        "uncited_claim_ids": [f"review-{item:04d}" for item in uncited],
        "unsupported_cited_claim_ids": [],
        "missing_quote_ids": [],
        "missing_source_anchor_evidence_ids": missing_anchors,
        "missing_exact_quote_evidence_ids": missing_exact_quotes,
    }


def _normalize_evidence_row(value: object) -> dict[str, Any]:
    row = dict(value) if isinstance(value, dict) else {}
    return {
        "citation_id": "",
        "quote_id": str(row.get("quote_id", "")),
        "paper": str(row.get("paper", "")),
        "doc_id": str(row.get("doc_id", "")),
        "section": str(row.get("section", "")),
        "section_kind": str(row.get("section_kind", "")),
        "doi": str(row.get("doi", "")),
        "evidence_id": str(row.get("evidence_id", "")),
        "exact_quote": str(row.get("exact_quote", "")).strip(),
        "context_text": str(row.get("context_text", "")),
        "html_path": str(row.get("html_path", "")),
        "html_anchor": str(row.get("html_anchor", "")),
        "confidence": row.get("confidence", 0.0),
    }


def _unique_slug(value: str, used: set[str], *, fallback: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")[:64] or fallback
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base[:58]}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
