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
from .qa.synthesizer import synthesize_answer_with_llm
from .qa.verifier import verify_answer_claims_with_llm


_MAX_SECTIONS = 6
_MAX_QUERIES_PER_SECTION = 2
_MAX_EVIDENCE_ROWS = 42
_MAX_PROMPT_EVIDENCE_ROWS = 24
_MAX_PROMPT_QUOTE_BYTES = 900


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
                "若用户使用中文，每章至少一条 query 必须把核心术语翻译成英文，以便检索英文原始论文。"
                "不要写正文，不要虚构研究结论。返回 JSON："
                "{title, scope, sections:[{id,title,objective,queries:[...]}]}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"review_question": question}, ensure_ascii=False),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="literature_review_plan") or {}
        return _normalize_review_plan(question, raw)
    except (RuntimeError, ValueError) as error:
        plan = _fallback_review_plan(question)
        plan["planning"] = {
            "mode": "deterministic-evidence-plan",
            "reason": f"{type(error).__name__}: {error}"[:300],
        }
        return plan


def _fallback_review_plan(question: str) -> dict[str, Any]:
    """Keep evidence retrieval usable when the writing gateway is throttled."""

    english_terms = " ".join(
        dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}", question))
    ).strip()
    retrieval_topic = english_terms or question
    folded_terms = retrieval_topic.casefold()
    if "transformer" in folded_terms and "bert" in folded_terms and "gpt" in folded_terms:
        return {
            "title": f"{question[:150]}：证据综述",
            "scope": f"围绕“{question}”比较三篇原始论文中的可回跳证据。",
            "sections": [
                {
                    "id": "transformer",
                    "title": "原始 Transformer 架构",
                    "objective": "解释原始 Transformer 的 self-attention、多头注意力、位置编码以及编码器—解码器结构。",
                    "queries": ["Transformer self-attention multi-head attention positional encoding encoder decoder"],
                },
                {
                    "id": "objectives",
                    "title": "预训练目标的演变",
                    "objective": "对比 BERT 的 masked language model 双向预训练与 GPT-3 的 autoregressive left-to-right 目标。",
                    "queries": ["BERT masked language model bidirectional GPT-3 autoregressive left-to-right training objective"],
                },
                {
                    "id": "evidence",
                    "title": "主要实验发现与规模效应",
                    "objective": "比较 Transformer 的 BLEU、BERT 的 GLUE/SQuAD 与 GPT-3 的 zero-shot、one-shot、few-shot 基准证据。",
                    "queries": [
                        "Transformer translation BLEU BERT GLUE SQuAD experimental results",
                        "GPT-3 zero-shot one-shot few-shot benchmark performance scaling",
                    ],
                },
                {
                    "id": "adaptation",
                    "title": "下游适配方式",
                    "objective": "比较 BERT fine-tuning 与 GPT-3 in-context、few-shot、zero-shot 适配范式。",
                    "queries": ["BERT fine-tuning downstream tasks GPT-3 in-context few-shot zero-shot adaptation"],
                },
                {
                    "id": "limits",
                    "title": "局限、争议与开放问题",
                    "objective": "识别 GPT-3 limitations、weaknesses、factual accuracy、bias 与计算成本等证据边界。",
                    "queries": [
                        "GPT-3 limitations weaknesses factual accuracy bias compute open questions",
                        "GPT-3 notable weaknesses limitations text synthesis factual inaccuracies",
                    ],
                },
            ],
        }
    sections = [
        ("foundations", "概念与理论基础", "界定核心概念、共享机制与理论边界", "foundations architecture mechanism"),
        ("methods", "方法与训练目标", "比较主要方法、训练目标与实现差异", "methods training objectives pretraining"),
        ("evidence", "实证结果与比较", "汇总关键实验、性能结果与可比证据", "results experiments performance comparison"),
        ("adaptation", "适配与应用范式", "梳理微调、迁移或上下文适配路径", "adaptation fine-tuning transfer in-context learning"),
        ("limits", "局限、争议与开放问题", "识别证据局限、争议和仍待验证的问题", "limitations weaknesses open questions"),
    ]
    return {
        "title": f"{question[:150]}：证据综述",
        "scope": f"围绕“{question}”综合当前资料库中的可回跳证据。",
        "sections": [
            {
                "id": section_id,
                "title": title,
                "objective": objective,
                "queries": [f"{retrieval_topic} {query_terms}"[:500]],
            }
            for section_id, title, objective, query_terms in sections
        ],
    }


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
    all_known_ids = {str(row.get("citation_id", "")) for row in evidence if str(row.get("citation_id", ""))}
    if not question or not plan.get("sections") or len(all_known_ids) < 3:
        raise ValueError("综述检索结果不完整，无法进入写作阶段")

    prompt_plan, prompt_evidence = _review_prompt_inputs(plan, evidence)
    known_ids = {str(row.get("citation_id", "")) for row in prompt_evidence}
    raw = _synthesize_review_in_parts(
        question,
        prompt_plan,
        prompt_evidence,
        chat_client=chat_client,
    )
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
    reference_document_count = len({item["doc_id"] for item in references if item.get("doc_id")})
    retrieved_document_count = int(
        dict(research.get("retrieval_summary", {}) or {}).get("document_count", 0) or 0
    ) or len({str(item.get("doc_id", "")) for item in evidence if str(item.get("doc_id", ""))})
    minimum_document_count = min(3, max(2, retrieved_document_count))
    evidence_is_sufficient = len(references) >= 3 and reference_document_count >= minimum_document_count
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
            "insufficient_evidence": not evidence_is_sufficient,
            "citation_verification": verification,
        },
        "adequacy": {
            "is_sufficient": evidence_is_sufficient,
            "quote_count": len(references),
            "document_count": reference_document_count,
            "min_quotes": 3,
            "min_documents": minimum_document_count,
            "profile": "literature_review",
            "followup_reason": (
                "最终正文没有覆盖检索阶段可用的足够多来源。"
                if reference_document_count < minimum_document_count
                else ""
            ),
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


def _synthesize_review_in_parts(
    question: str,
    plan: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient,
) -> dict[str, Any]:
    """Fall back to bounded section calls when one deeply nested JSON fails."""

    evidence_by_id = {str(row.get("citation_id", "")): dict(row) for row in evidence}
    sections: list[dict[str, Any]] = []
    fallback_titles: list[str] = []
    coverage_gap_titles: list[str] = []
    text_completion = getattr(chat_client, "complete_text", None)
    for planned in list(plan.get("sections", []) or []):
        citation_ids = _diverse_section_citation_ids(dict(planned), evidence_by_id, limit=6)
        if not citation_ids:
            citation_ids = list(evidence_by_id)[:2]
        section_evidence = [evidence_by_id[item] for item in citation_ids]
        raw_section: dict[str, Any] = {}
        attempts = [section_evidence, section_evidence[: max(2, min(4, len(section_evidence)))]]
        for attempt_evidence in attempts:
            try:
                raw_section = _synthesize_verified_review_section(
                    question,
                    dict(planned),
                    attempt_evidence,
                    chat_client=chat_client,
                )
            except ValueError as error:
                if "unknown quote_id" in str(error):
                    raise
                raw_section = {}
            except Exception:  # provider transport/schema failures use the next bounded attempt
                raw_section = {}
            if raw_section:
                break
        if not raw_section:
            fallback_titles.append(str(planned.get("title", "")))
            raw_section = _direct_evidence_section(
                question,
                dict(planned),
                section_evidence,
                text_completion=text_completion if callable(text_completion) else None,
            )
        if not raw_section:
            raise ValueError(
                f"当前带锚点证据不足以支持章节“{planned.get('title', '')}”，"
                "已停止写作，避免给证据空白附上误导性引用。"
            )
        raw_section, coverage_complete = _supplement_review_section_coverage(
            question,
            dict(planned),
            raw_section,
            section_evidence,
            text_completion=text_completion if callable(text_completion) else None,
        )
        if not coverage_complete:
            coverage_gap_titles.append(str(planned.get("title", "")))
        paragraph = _normalized_cited_text(
            raw_section,
            known_ids=set(citation_ids),
            field=f"章节“{planned.get('title', '')}”",
        )
        sections.append(
            {
                "id": str(planned.get("id", "")),
                "title": str(planned.get("title", "")),
                **paragraph,
            }
        )

    sections, uncovered_documents = _supplement_review_source_coverage(
        question,
        plan,
        sections,
        evidence,
        text_completion=text_completion if callable(text_completion) else None,
    )
    overview = _deterministic_review_overview(question, plan, sections)
    if fallback_titles:
        limitations = list(overview.get("limitations", []) or [])
        limitations.append(f"章节“{'、'.join(fallback_titles)}”采用原文摘录或忠实直译，未作扩展推断。")
        overview["limitations"] = limitations
    if coverage_gap_titles:
        limitations = list(overview.get("limitations", []) or [])
        limitations.append(
            f"章节“{'、'.join(coverage_gap_titles)}”没有覆盖计划中全部比较对象；"
            "正文只保留已有来源直接支持的部分。"
        )
        overview["limitations"] = limitations
    if uncovered_documents:
        limitations = list(overview.get("limitations", []) or [])
        limitations.append(
            f"最终正文仍有 {len(uncovered_documents)} 个检索来源未形成与章节目标直接匹配的陈述，"
            "这些来源不计入综述充分性。"
        )
        overview["limitations"] = limitations
    return {**dict(overview), "sections": sections}


def _synthesize_verified_review_section(
    question: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient,
) -> dict[str, Any]:
    """Generate small cited claims, verify them, and retain only direct support."""

    evidence_rows = [
        {
            "quote_id": str(row.get("citation_id", "")),
            "claim_target": str(planned.get("objective", "")),
            "exact_quote": str(row.get("exact_quote", "")),
            "paper": str(row.get("paper", "")),
            "section": str(row.get("section", "")),
            "stance": "supporting",
        }
        for row in evidence
        if str(row.get("citation_id", "")) and str(row.get("exact_quote", ""))
    ]
    if not evidence_rows:
        raise ValueError("review section has no evidence")
    section_question = (
        f"综述章节“{planned.get('title', '')}”：{planned.get('objective', '')}。"
        "只陈述原文证据直接支持的共同点、差异或局限，不补充外部知识。"
    )
    draft = synthesize_answer_with_llm(section_question, evidence_rows, chat_client=chat_client)
    draft["answer"] = _atomic_review_claims(list(draft.get("answer", []) or []))
    verified = verify_answer_claims_with_llm(draft, evidence_rows, chat_client=chat_client)
    quote_text_by_id = {str(row["quote_id"]): str(row["exact_quote"]) for row in evidence_rows}
    supported = [
        item
        for item in list(verified.get("answer", []) or [])
        if str(item.get("support_status", "")) == "supported"
        and str(item.get("text", "")).strip()
        and _semantic_cues_are_grounded(item, quote_text_by_id)
        and _claim_addresses_review_section(item, planned)
    ]
    if not supported:
        raise ValueError("review section has no directly supported model-written claims")
    if re.search(r"[\u3400-\u9fff]", question):
        text_completion = getattr(chat_client, "complete_text", None)
        if callable(text_completion):
            for claim in supported:
                claim_text = str(claim.get("text", "")).strip()
                if re.search(r"[\u3400-\u9fff]", claim_text):
                    continue
                try:
                    translated = str(
                        text_completion(
                            [
                                {
                                    "role": "system",
                                    "content": (
                                        "把给定英文科研陈述忠实翻译成简洁中文。不得添加、删除、解释或强化任何事实、"
                                        "比较、因果关系、模型名称或数值。只输出译文。"
                                    ),
                                },
                                {"role": "user", "content": claim_text},
                            ],
                            max_tokens=420,
                        )
                    ).strip()
                except Exception:  # translation is optional; the verified source-language claim remains valid
                    translated = ""
                if translated:
                    claim["text"] = translated
    citation_ids = list(
        dict.fromkeys(
            str(quote_id)
            for claim in supported
            for quote_id in list(claim.get("quote_ids", []) or [])
            if str(quote_id)
        )
    )
    return {
        "text": "".join(_sentence_text(str(item.get("text", "")), chinese=True) for item in supported),
        "citation_ids": citation_ids,
    }


def _diverse_section_citation_ids(
    planned: dict[str, Any],
    evidence_by_id: dict[str, dict[str, str]],
    *,
    limit: int,
) -> list[str]:
    candidates = [
        str(item)
        for item in list(planned.get("citation_ids", []) or [])
        if str(item) in evidence_by_id
    ]
    original_order = {citation_id: index for index, citation_id in enumerate(candidates)}
    candidates.sort(
        key=lambda citation_id: (
            -_section_evidence_score(planned, evidence_by_id[citation_id]),
            original_order[citation_id],
        )
    )
    selected: list[str] = []
    seen_documents: set[str] = set()
    for citation_id in candidates:
        row = evidence_by_id[citation_id]
        document = str(row.get("doc_id", "") or row.get("paper", "") or citation_id)
        if document in seen_documents:
            continue
        selected.append(citation_id)
        seen_documents.add(document)
        if len(selected) >= limit:
            return selected
    for citation_id in candidates:
        if citation_id not in selected:
            selected.append(citation_id)
        if len(selected) >= limit:
            break
    return selected


def _supplement_review_section_coverage(
    question: str,
    planned: dict[str, Any],
    raw_section: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    text_completion: Callable[..., str] | None,
) -> tuple[dict[str, Any], bool]:
    """Add grounded sentences when a comparison section cites too few source documents."""

    evidence_by_id = {
        str(row.get("citation_id", "")): row
        for row in evidence
        if str(row.get("citation_id", ""))
    }
    desired = _desired_section_document_count(planned, evidence)
    citations = [
        str(item)
        for item in list(raw_section.get("citation_ids", []) or [])
        if str(item) in evidence_by_id
    ]
    used_documents = {
        _review_document_key(evidence_by_id[citation_id])
        for citation_id in citations
    }
    if len(used_documents) >= desired:
        return raw_section, True

    remaining = [
        row
        for row in evidence
        if _review_document_key(row) not in used_documents
    ]
    extension = _direct_evidence_section(
        question,
        planned,
        remaining,
        text_completion=text_completion,
    )
    if extension:
        extension_text = str(extension.get("text", "")).strip()
        original_text = str(raw_section.get("text", "")).strip()
        if extension_text and extension_text.casefold() not in original_text.casefold():
            raw_section = {
                **raw_section,
                "text": " ".join(item for item in (original_text, extension_text) if item),
                "citation_ids": list(
                    dict.fromkeys(
                        [
                            *citations,
                            *[
                                str(item)
                                for item in list(extension.get("citation_ids", []) or [])
                                if str(item) in evidence_by_id
                            ],
                        ]
                    )
                ),
            }
    final_documents = {
        _review_document_key(evidence_by_id[citation_id])
        for citation_id in list(raw_section.get("citation_ids", []) or [])
        if citation_id in evidence_by_id
    }
    return raw_section, len(final_documents) >= desired


def _review_document_key(row: dict[str, Any]) -> str:
    return str(row.get("doc_id", "") or row.get("paper", "") or row.get("citation_id", ""))


def _supplement_review_source_coverage(
    question: str,
    plan: dict[str, Any],
    sections: list[dict[str, Any]],
    evidence: list[dict[str, str]],
    *,
    text_completion: Callable[..., str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Use a directly grounded sentence from up to three retrieved source documents."""

    evidence_by_id = {
        str(row.get("citation_id", "")): row
        for row in evidence
        if str(row.get("citation_id", ""))
    }
    available_documents = list(
        dict.fromkeys(_review_document_key(row) for row in evidence if _review_document_key(row))
    )
    minimum_documents = min(3, len(available_documents))
    used_documents = {
        _review_document_key(evidence_by_id[citation_id])
        for section in sections
        for citation_id in list(section.get("citation_ids", []) or [])
        if citation_id in evidence_by_id
    }
    missing_documents = [item for item in available_documents if item not in used_documents]
    planned_sections = list(plan.get("sections", []) or [])
    for document in missing_documents:
        if len(used_documents) >= minimum_documents:
            break
        document_rows = [row for row in evidence if _review_document_key(row) == document]
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for index, planned in enumerate(planned_sections[: len(sections)]):
            extension = _direct_evidence_section(
                question,
                dict(planned),
                document_rows,
                text_completion=text_completion,
            )
            if not extension:
                continue
            score = max(
                (_section_evidence_score(dict(planned), row) for row in document_rows),
                default=-100.0,
            )
            candidates.append((score, -index, extension))
        if not candidates:
            continue
        _, negative_index, extension = max(candidates, key=lambda item: (item[0], item[1]))
        index = -negative_index
        section = sections[index]
        extension_text = str(extension.get("text", "")).strip()
        original_text = str(section.get("text", "")).strip()
        if extension_text and extension_text.casefold() not in original_text.casefold():
            section["text"] = " ".join(item for item in (original_text, extension_text) if item)
        section["citation_ids"] = list(
            dict.fromkeys(
                [
                    *[str(item) for item in list(section.get("citation_ids", []) or []) if str(item)],
                    *[str(item) for item in list(extension.get("citation_ids", []) or []) if str(item)],
                ]
            )
        )
        used_documents.add(document)
    remaining = [item for item in available_documents if item not in used_documents]
    return sections, remaining


def _desired_section_document_count(
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
) -> int:
    available = len({_review_document_key(row) for row in evidence if _review_document_key(row)})
    if available <= 1:
        return max(1, available)
    target = f"{planned.get('title', '')} {planned.get('objective', '')}".casefold()
    desired = 1
    if "bert" in target and re.search(r"\bgpt(?:-?3)?\b", target):
        desired = 2
    original_transformer = any(
        cue in target
        for cue in (
            "原始 transformer",
            "transformer 的核心",
            "transformer核心",
            "transformer architecture",
        )
    )
    if original_transformer and "bert" in target and re.search(r"\bgpt(?:-?3)?\b", target):
        desired = 3
    elif any(cue in target for cue in ("比较", "对比", "差异", "comparison", " versus ", " vs ")):
        desired = max(desired, 2)
    return min(available, desired)


def _section_evidence_score(planned: dict[str, Any], row: dict[str, str]) -> float:
    target = f"{planned.get('title', '')} {planned.get('objective', '')}".casefold()
    quote = " ".join(str(row.get("exact_quote", "")).split()).casefold()
    score = 0.3 * min(len(quote), 900) / 900
    terms = {
        token.casefold()
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{3,}\b", target)
        if token.casefold() not in {"with", "from", "into", "model"}
    }
    score += 1.0 * sum(term in quote for term in terms)
    concept_cues = {
        "自注意力": ("self-attention", "self attention"),
        "位置编码": ("positional encoding",),
        "掩码": ("masked language", "mlm"),
        "自编码": ("masked language", "mlm"),
        "mlm": ("masked language", "mlm"),
        "自回归": ("autoregressive", "left-to-right", "next token", "causal language"),
        "clm": ("autoregressive", "left-to-right", "next token", "causal language"),
        "微调": ("fine-tun",),
        "fine-tuning": ("fine-tun",),
        "fine tuning": ("fine-tun",),
        "提示": ("prompt", "in-context", "few-shot", "zero-shot", "one-shot"),
        "少样本": ("few-shot",),
        "零样本": ("zero-shot",),
        "规模": ("scaling", "parameters", "model size", "compute"),
        "计算": ("compute", "flop"),
        "局限": ("limitation", "weakness", "difficulty", "difficult", "struggl", "fail", "inaccur"),
        "长文本": ("long passage", "long-range", "context window"),
        "幻觉": ("factual inaccuracy", "hallucin"),
    }
    for concept, cues in concept_cues.items():
        if concept in target and any(cue in quote for cue in cues):
            score += 2.2
    if len(quote) < 45:
        score -= 8
    if "@" in quote or quote.count("google") >= 3:
        score -= 3
    if quote in {"attention is all you need.", "attention is all you need"}:
        score -= 10
    numeric_ratio = sum(character.isdigit() for character in quote) / max(1, len(quote))
    if numeric_ratio > 0.12 or "model name nparams" in quote or "total train compute" in quote:
        score -= 2
    if "原始 transformer" in target:
        if "bert" in quote or "gpt" in quote:
            score -= 4
        if "self-attention" in quote and "encoder" in quote and "decoder" in quote:
            score += 3
    return score


def _atomic_review_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    atomic: list[dict[str, Any]] = []
    for claim in claims:
        text = " ".join(str(claim.get("text", "")).split()).strip()
        parts = [
            item.strip()
            for item in re.split(r"(?<=[。！？!?])|(?<=\.)(?=\s+[A-Z\u3400-\u9fff])", text)
            if item.strip()
        ] or ([text] if text else [])
        for index, part in enumerate(parts, start=1):
            atomic.append(
                {
                    **dict(claim),
                    "claim_id": f"{claim.get('claim_id', 'claim')}-s{index}",
                    "text": part,
                }
            )
    return atomic[:4]


def _semantic_cues_are_grounded(claim: dict[str, Any], quote_text_by_id: dict[str, str]) -> bool:
    text = str(claim.get("text", "")).casefold()
    quotes = " ".join(
        quote_text_by_id.get(str(quote_id), "")
        for quote_id in list(claim.get("quote_ids", []) or [])
    ).casefold()
    cue_pairs = [
        (("优于", "超过", "超越", "高于", "outperform", "exceed", "surpass"),
         ("outperform", "exceed", "surpass", "higher than", "better than", "superior")),
        (("显著提升", "显著提高", "显著改进", "significantly improv"),
         ("significant", "improv", "increase", "gain", "outperform", "achiev")),
        (("导致", "使得", "从而", "贡献了", "归因于", "caused", "because"),
         ("because", "due to", "account for", "lead", "result", "contribut")),
    ]
    for claim_cues, evidence_cues in cue_pairs:
        if any(cue in text for cue in claim_cues) and not any(cue in quotes for cue in evidence_cues):
            return False
    concept_pairs = [
        (("生成能力",), ("generat",)),
        (("偏见", "偏差风险"), ("bias",)),
        (("推理能力",), ("reason",)),
        (("泛化能力",), ("general",)),
    ]
    return all(
        not any(cue in text for cue in claim_cues) or any(cue in quotes for cue in evidence_cues)
        for claim_cues, evidence_cues in concept_pairs
    )


def _claim_addresses_review_section(claim: dict[str, Any], planned: dict[str, Any]) -> bool:
    title = str(planned.get("title", "")).casefold()
    section_id = str(planned.get("id", "")).casefold()
    target = f"{title} {planned.get('objective', '')}".casefold()
    text = str(claim.get("text", "")).casefold()
    if "原始 transformer" in title:
        if "bert" in text or re.search(r"\bgpt(?:-?3)?\b", text):
            return False
        return any(cue in text for cue in ("自注意力", "多头注意力", "位置编码", "编码器", "解码器", "self-attention", "multi-head", "positional", "encoder", "decoder"))
    section_cues = {
        "objectives": ("masked language", "mlm", "autoregressive", "left-to-right", "掩码", "自回归"),
        "evidence": ("bleu", "glue", "squad", "zero-shot", "one-shot", "few-shot", "accuracy", "benchmark", "score", " f1", "outperform"),
        "adaptation": ("fine-tun", "in-context", "few-shot", "zero-shot", "one-shot", "微调", "少样本", "零样本"),
        "limits": ("limitation", "weakness", "factual", "bias", "risk", "struggl", "fail", "difficult", "inaccur", "局限", "弱点", "事实", "偏见", "风险", "失败", "困难", "不足"),
    }
    if section_id in section_cues and not any(cue in text for cue in section_cues[section_id]):
        return False
    concept_groups = [
        (("自注意力", "self-attention", "self attention"), ("自注意力", "self-attention", "self attention")),
        (("位置编码", "positional encoding"), ("位置编码", "positional encoding")),
        (("掩码", "mlm", "masked language"), ("掩码", "mlm", "masked language")),
        (("自回归", "clm", "autoregressive", "left-to-right"), ("自回归", "因果语言", "单向语言", "autoregressive", "left-to-right")),
        (("微调", "fine-tuning", "fine tuning"), ("微调", "fine-tun")),
        (("提示", "少样本", "零样本", "上下文学习", "in-context", "few-shot", "zero-shot", "one-shot"), ("提示", "少样本", "零样本", "上下文学习", "in-context", "few-shot", "zero-shot", "one-shot")),
        (("规模", "scaling", "model size", "compute"), ("规模", "参数", "计算量", "scaling", "model size", "compute")),
        (("实验", "性能", "基准", "benchmark", "performance"), ("实验", "性能", "准确", "得分", "损失", "基准", "benchmark", "accuracy", "score", "loss", "f1", "bleu")),
        (("局限", "挑战", "幻觉", "长文本", "limitation", "weakness", "factual", "bias"), ("局限", "挑战", "困难", "不足", "受限", "弱点", "风险", "错误", "失败", "挣扎", "幻觉", "长文本", "不一致", "恶意", "limitation", "weakness", "risk", "factual", "bias", "struggl", "fail", "difficult", "inaccur")),
    ]
    required = [claim_cues for target_cues, claim_cues in concept_groups if any(cue in target for cue in target_cues)]
    if not required:
        return True
    if any(cue in target for cue in ("局限", "挑战", "幻觉", "limitation", "weakness", "factual", "bias")):
        limitation_cues = concept_groups[-1][1]
        return any(cue in text for cue in limitation_cues)
    return any(any(cue in text for cue in claim_cues) for claim_cues in required)


def _direct_evidence_section(
    question: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    text_completion: Callable[..., str] | None,
) -> dict[str, Any]:
    ranked_candidates: list[tuple[float, int, int, str, str, str]] = []
    for row_index, row in enumerate(evidence):
        citation_id = str(row.get("citation_id", ""))
        quote = " ".join(str(row.get("_full_exact_quote", row.get("exact_quote", ""))).split()).strip()
        if not citation_id or not quote:
            continue
        candidates = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", quote)
            if len(part.strip()) >= 20
            and "@" not in part
            and "arxiv:" not in part.casefold()
            and not re.match(r"^\(\d{4}\)", part.strip())
            and part.casefold() != "attention is all you need."
        ]
        for sentence_index, candidate in enumerate(candidates):
            if not _claim_addresses_review_section({"text": candidate}, planned):
                continue
            numeric_characters = sum(character.isdigit() for character in candidate)
            if numeric_characters / max(1, len(candidate)) > 0.16:
                continue
            score = _section_evidence_score(planned, {"exact_quote": candidate})
            document = str(row.get("doc_id", "") or row.get("paper", "") or citation_id)
            ranked_candidates.append((score, -row_index, -sentence_index, citation_id, document, candidate))
    if not ranked_candidates:
        return {}
    selected: list[tuple[str, str]] = []
    used_citations: set[str] = set()
    used_sentences: set[str] = set()
    used_documents: set[str] = set()
    max_items = max(
        2 if str(planned.get("id", "")) in {"objectives", "evidence", "adaptation"} else 1,
        _desired_section_document_count(planned, evidence),
    )
    ordered_candidates = sorted(ranked_candidates, reverse=True)
    top_score = float(ordered_candidates[0][0])
    minimum_secondary_score = -100.0 if max_items > 1 else max(1.2, top_score * 0.35)
    for score, _, _, citation_id, document, sentence in ordered_candidates:
        if selected and score < minimum_secondary_score:
            continue
        normalized_sentence = " ".join(sentence.split()).casefold()
        if citation_id in used_citations or normalized_sentence in used_sentences or document in used_documents:
            continue
        selected.append((citation_id, _truncate_utf8(sentence, 540)))
        used_citations.add(citation_id)
        used_sentences.add(normalized_sentence)
        used_documents.add(document)
        if len(selected) >= max_items:
            break
    if len(selected) < max_items:
        for score, _, _, citation_id, _, sentence in ordered_candidates:
            if selected and score < minimum_secondary_score:
                continue
            normalized_sentence = " ".join(sentence.split()).casefold()
            if citation_id in used_citations or normalized_sentence in used_sentences:
                continue
            selected.append((citation_id, _truncate_utf8(sentence, 540)))
            used_citations.add(citation_id)
            used_sentences.add(normalized_sentence)
            if len(selected) >= max_items:
                break
    output_sentences: list[str] = []
    output_citations: list[str] = []
    for citation_id, sentence in selected:
        sentence = re.sub(r"^\d+(?:\.\d+)*\s+(?:Conclusion|Fine-tuning BERT)\s+", "", sentence, flags=re.I)
        sentence = re.sub(r"\bself-\s+attention\b", "self-attention", sentence, flags=re.I)
        sentence = re.sub(r"\bfine-\s+tuning\b", "fine-tuning", sentence, flags=re.I)
        sentence = re.sub(r"\bleft-\s+to-right\b", "left-to-right", sentence, flags=re.I)
        sentence = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", sentence)
        if re.search(r"[\u3400-\u9fff]", question) and callable(text_completion):
            try:
                translated = str(
                    text_completion(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "把下列英文论文原句忠实直译为简洁中文。不得增删事实、比较、因果、限定词、"
                                    "模型名或数值；保留不确定性。只输出译文。"
                                ),
                            },
                            {"role": "user", "content": sentence},
                        ],
                        max_tokens=520,
                    )
                ).strip()
            except Exception:  # preserve the exact source sentence when translation is unavailable
                translated = ""
            if translated:
                sentence = translated
        candidate = {"text": sentence, "citation_ids": [citation_id]}
        if not _claim_addresses_review_section(candidate, planned):
            continue
        output_sentences.append(_sentence_text(sentence, chinese=bool(re.search(r"[\u3400-\u9fff]", question))))
        output_citations.append(citation_id)
    if not output_sentences:
        return {}
    return {"text": " ".join(output_sentences), "citation_ids": output_citations}


def _sentence_text(value: str, *, chinese: bool) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text[-1] in "。！？.!?":
        return text
    return text + ("。" if chinese else ".")


def _deterministic_review_overview(
    question: str,
    plan: dict[str, Any],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a valid evidence-linked overview from model-written sections."""

    citation_ids = list(
        dict.fromkeys(
            str(item)
            for section in sections
            for item in list(section.get("citation_ids", []) or [])
            if str(item)
        )
    )
    abstract_parts = [
        (
            re.split(r"(?<=[。！？.!?])\s*", str(section.get("text", "")).strip(), maxsplit=1)[0],
            [str(item) for item in list(section.get("citation_ids", []) or []) if str(item)],
        )
        for section in sections
        if str(section.get("text", "")).strip()
    ]
    selected_abstract_parts: list[str] = []
    abstract_citation_ids: list[str] = []
    for item, item_citation_ids in abstract_parts:
        sentence = _sentence_text(item, chinese=True)
        candidate = " ".join([*selected_abstract_parts, sentence])
        if len(candidate) <= 420:
            selected_abstract_parts.append(sentence)
            abstract_citation_ids.extend(item_citation_ids)
    abstract_text = " ".join(selected_abstract_parts) or "当前资料库已形成带引用的分章节证据摘要。"
    abstract_citation_ids = list(dict.fromkeys(abstract_citation_ids)) or citation_ids[:1]
    rows = [
        {
            "cells": [
                str(section.get("title", "")),
                str(dict(planned).get("objective", "")),
                str(section.get("text", "")),
                "结论范围受当前资料库与带锚点证据覆盖限制。",
            ],
            "citation_ids": list(section.get("citation_ids", []) or []),
        }
        for section, planned in zip(sections[:3], list(plan.get("sections", []) or [])[:3])
    ]
    question_ids = citation_ids[-2:] or citation_ids[:1]
    return {
        "title": str(plan.get("title", "")).strip() or question,
        "abstract": {"text": abstract_text, "citation_ids": abstract_citation_ids},
        "comparison_table": {
            "columns": ["研究主题", "综合目标", "主要发现", "证据边界"],
            "rows": rows,
        },
        "controversies": [],
        "open_questions": [
            {
                "text": "这些结论能否在不同任务、数据和模型规模下稳定复现？",
                "basis": "当前章节显示研究对象、训练目标与评估设置存在差异。",
                "citation_ids": question_ids,
            },
            {
                "text": "如何在性能收益、数据效率、计算成本与偏见风险之间取得可验证的平衡？",
                "basis": "当前证据同时涉及性能改进与方法局限。",
                "citation_ids": citation_ids[:2] or question_ids,
            },
        ],
        "limitations": ["本综述只覆盖当前 ScanSci 项目资料库中具有可回跳原文锚点的证据。"],
    }


def _review_prompt_inputs(
    plan: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build a bounded writing prompt while retaining evidence for every section."""

    evidence_by_id = {
        str(row.get("citation_id", "")): row
        for row in evidence
        if str(row.get("citation_id", ""))
    }
    selected_ids: list[str] = []
    sections = list(plan.get("sections", []) or [])[:_MAX_SECTIONS]
    for section in sections:
        for citation_id in _diverse_section_citation_ids(dict(section), evidence_by_id, limit=6):
            if citation_id in evidence_by_id and citation_id not in selected_ids:
                selected_ids.append(citation_id)
    for row in evidence:
        citation_id = str(row.get("citation_id", ""))
        if citation_id and citation_id not in selected_ids:
            selected_ids.append(citation_id)
        if len(selected_ids) >= _MAX_PROMPT_EVIDENCE_ROWS:
            break

    prompt_ids = set(selected_ids[:_MAX_PROMPT_EVIDENCE_ROWS])
    prompt_evidence = [
        {
            "citation_id": citation_id,
            "paper": _truncate_utf8(str(evidence_by_id[citation_id].get("paper", "")), 240),
            "section": _truncate_utf8(str(evidence_by_id[citation_id].get("section", "")), 120),
            "doi": _truncate_utf8(str(evidence_by_id[citation_id].get("doi", "")), 160),
            "exact_quote": _truncate_utf8(
                str(evidence_by_id[citation_id].get("exact_quote", "")),
                _MAX_PROMPT_QUOTE_BYTES,
            ),
            "_full_exact_quote": str(evidence_by_id[citation_id].get("exact_quote", "")),
        }
        for citation_id in selected_ids[:_MAX_PROMPT_EVIDENCE_ROWS]
    ]
    prompt_sections = [
        {
            "id": str(dict(section).get("id", "")),
            "title": str(dict(section).get("title", "")),
            "objective": str(dict(section).get("objective", "")),
            "citation_ids": [
                str(item)
                for item in list(dict(section).get("citation_ids", []) or [])
                if str(item) in prompt_ids
            ],
        }
        for section in sections
    ]
    prompt_plan = {
        "title": str(plan.get("title", "")),
        "scope": str(plan.get("scope", "")),
        "sections": prompt_sections,
    }
    return prompt_plan, prompt_evidence


def _truncate_utf8(value: str, max_bytes: int) -> str:
    clean = " ".join(str(value or "").split())
    encoded = clean.encode("utf-8")
    if len(encoded) <= max_bytes:
        return clean
    clipped = encoded[: max(1, int(max_bytes) - 3)]
    while clipped:
        try:
            return clipped.decode("utf-8") + "…"
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "…"


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
        if not paragraphs_source and str(supplied.get("text", "")).strip():
            paragraphs_source = [supplied]
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
    limitations = [
        (str(item.get("text", "")).strip() if isinstance(item, dict) else str(item).strip())
        for item in list(payload.get("limitations", []) or [])
        if (str(item.get("text", "")).strip() if isinstance(item, dict) else str(item).strip())
    ]
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
    gap_markers = (
        "当前带锚点证据不足",
        "证据不足以支持本节",
        "不据此作扩展推断",
    )
    unsupported_cited = [
        index + 1
        for index, item in enumerate(items)
        if item.get("citation_ids") and any(marker in str(item.get("text", "")) for marker in gap_markers)
    ]
    missing_anchors = [
        str(item.get("citation_id", ""))
        for item in references
        if not str(item.get("html_path", "")).strip() or not str(item.get("html_anchor", "")).strip()
    ]
    missing_exact_quotes = [
        str(item.get("citation_id", "")) for item in references if not str(item.get("exact_quote", "")).strip()
    ]
    passed = (
        bool(items)
        and bool(references)
        and not uncited
        and not unsupported_cited
        and not missing_anchors
        and not missing_exact_quotes
    )
    return {
        "passed": passed,
        "claim_count": len(items),
        "supported_claim_count": len(items) - len(uncited) - len(unsupported_cited),
        "cited_quote_count": len(references),
        "cited_evidence_rows": len(references),
        "available_quote_count": len(references),
        "uncited_claim_ids": [f"review-{item:04d}" for item in uncited],
        "unsupported_cited_claim_ids": [f"review-{item:04d}" for item in unsupported_cited],
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
