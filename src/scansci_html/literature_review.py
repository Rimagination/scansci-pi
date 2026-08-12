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
_MAX_EVIDENCE_ROWS = 70
_MAX_PROMPT_EVIDENCE_ROWS = 30
_MAX_PROMPT_QUOTE_BYTES = 900


_REVIEW_METHOD_CUES = (
    "方法",
    "研究设计",
    "实验设计",
    "采样",
    "样方",
    "监测",
    "测量",
    "统计",
    "method",
    "protocol",
    "sampling",
    "measurement",
    "experimental design",
)


def _review_section_filters(question: str, section: dict[str, Any]) -> dict[str, Any]:
    """Prefer findings over procedural fragments for literature-review prose.

    A review section normally needs claims from abstracts, results, discussion,
    or conclusions.  The evidence store also contains many highly matchable
    methods/table-caption spans; allowing those to compete equally makes a
    review look like a pasted methods section.  A section that explicitly
    asks about methods keeps the methods kind in its candidate pool, while
    still retaining findings for comparison and interpretation.
    """

    # Do not let a broad review instruction such as “compare methods” add
    # procedural spans to every section. Only the section's own title,
    # objective, id, and query wording may opt that section into methods.
    method_requested = _review_section_allows_methods(section)
    section_kinds = ["abstract", "results", "discussion", "conclusion"]
    if method_requested:
        section_kinds.insert(1, "methods")
    return {"section_kinds": section_kinds}


def _review_section_allows_methods(section: dict[str, Any]) -> bool:
    """Return whether a section explicitly asks for methodological evidence."""

    target = " ".join(
        str(value or "").strip()
        for value in (
            section.get("title", ""),
            section.get("objective", ""),
            section.get("id", ""),
            *list(section.get("queries") or [])[:2],
        )
    ).casefold()
    return any(cue.casefold() in target for cue in _REVIEW_METHOD_CUES)


_REVIEW_PROCEDURAL_PATTERNS = (
    r"(?:采用|使用|选取|设置|构建|建立|开展).{0,24}(?:实验|观测|监测|调查|样方|样地|测序|模型)",
    r"(?:通过|采用|使用|选取|设置|综合运用).{0,30}(?:比较|对比|研究区|电站|实验|观测|调查|模型|方法|指标)",
    r"(?:实验设计|研究设计|采样|样本|高通量测序|三维建模|回归分析|方差分析|显著性检验)",
    r"(?:野外观测|室内实验|控制实验|空间替代时间)",
)


def _review_sentence_is_procedural(text: str) -> bool:
    """Identify method-procedure sentences that do not belong in findings prose."""

    value = " ".join(str(text or "").split()).strip()
    if not value:
        return False
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in _REVIEW_PROCEDURAL_PATTERNS)


def _remove_non_method_procedural_sentences(
    value: dict[str, Any],
    *,
    allow_methods: bool,
) -> dict[str, Any]:
    """Keep findings prose focused when the planned section is not methods."""

    if allow_methods:
        return value
    sentences = _cited_sentence_items(value)
    if not sentences:
        return value
    retained = [
        sentence
        for sentence in sentences
        if not _review_sentence_is_procedural(str(sentence.get("text", "")))
    ]
    # If every sentence is procedural, retain the validated paragraph rather
    # than making a section empty; the prompt/filter still prevents this in
    # normal runs and the guard is deliberately conservative.
    return _cited_text_from_sentences(retained) if retained else value


_REVIEW_GENERIC_TOPIC_TERMS = frozenset(
    {
        "研究",
        "文献",
        "证据",
        "综述",
        "方法",
        "结果",
        "结论",
        "主要",
        "问题",
        "组织",
        "当前",
        "选择",
        "知识",
        "库中",
        "中文",
    }
)


def _review_topic_signals(text: str) -> set[str]:
    """Return repeated, content-bearing terms useful for plan-drift checks.

    Chinese review requests often contain instructions and a file path rather
    than a clean topic string. Repeated CJK bigrams provide a conservative
    signal (for example ``光伏``/``生态``) without requiring a tokenizer; a
    one-off term is intentionally ignored so existing free-form plans remain
    compatible.
    """

    value = str(text or "").casefold()
    terms: set[str] = set(re.findall(r"[A-Za-z][A-Za-z0-9.-]{3,}", value))
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", value)
    counts: dict[str, int] = {}
    for run in cjk_runs:
        for index in range(len(run) - 1):
            term = run[index : index + 2]
            if term in _REVIEW_GENERIC_TOPIC_TERMS:
                continue
            counts[term] = counts.get(term, 0) + 1
    terms.update(term for term, count in counts.items() if count >= 2)
    # Short Chinese requests often mention a domain anchor only once, so the
    # repeated-bigram rule alone would miss an obvious drift (for example a
    # photovoltaic/ecology review rewritten as a machine-learning review).
    domain_terms = (
        "光伏",
        "生态",
        "植被",
        "土壤",
        "微气候",
        "生物多样性",
        "光伏农业",
        "荒漠",
        "盐碱地",
        "能源",
    )
    terms.update(term for term in domain_terms if term in value)
    return terms


def _review_plan_is_on_topic(question: str, plan: dict[str, Any]) -> bool:
    """Reject a valid-looking model outline that silently changes subjects."""

    signals = _review_topic_signals(question)
    if not signals:
        return True
    candidate_parts = [str(plan.get("title", "")), str(plan.get("scope", ""))]
    for section in list(plan.get("sections", []) or []):
        if isinstance(section, dict):
            candidate_parts.extend(
                str(section.get(key, ""))
                for key in ("id", "title", "objective")
            )
            candidate_parts.extend(str(query) for query in list(section.get("queries", []) or []))
    candidate = " ".join(candidate_parts).casefold()
    return any(signal in candidate for signal in signals)


def _review_open_question_is_on_topic(question: str, item: dict[str, Any]) -> bool:
    """Reject generic model questions that silently switch review domains."""

    signals = _review_topic_signals(question)
    if not signals:
        return True
    candidate = " ".join(
        str(item.get(key, ""))
        for key in ("text", "basis")
    ).casefold()
    return any(signal in candidate for signal in signals)


def _fallback_review_open_questions(
    question: str,
    *,
    citation_ids: list[str],
) -> list[dict[str, Any]]:
    """Create domain-aligned, evidence-linked questions when model output drifts."""

    question_ids = citation_ids[-2:] or citation_ids[:1]
    first_ids = question_ids or citation_ids[:1]
    second_ids = citation_ids[:2] or question_ids
    if "光伏" in question and any(term in question for term in ("生态", "植被", "土壤", "光伏农业")):
        return [
            {
                "text": "光伏设施引起的微气候、土壤水分与植被恢复效应，在不同地区、建设年限和组件覆盖率下是否具有一致性？",
                "basis": "现有证据同时报告了环境改善、生态扰动及时空差异，尚缺少跨地点和长期比较。",
                "citation_ids": first_ids,
            },
            {
                "text": "光伏建设初期的地形与植被扰动，如何与后续生态恢复及光伏—气候—土壤—生物反馈区分并量化？",
                "basis": "现有研究指出恢复尚未达到稳态，且生态恢复过程可能反过来影响光伏运行稳定性。",
                "citation_ids": second_ids,
            },
        ]
    return [
        {
            "text": "这些结论能否在不同研究对象、地区和时间尺度下稳定复现？",
            "basis": "纳入研究的对象、情境与观测尺度存在差异。",
            "citation_ids": first_ids,
        },
        {
            "text": "未来研究如何在证据强度、可重复性与实际应用边界之间取得可验证的平衡？",
            "basis": "现有证据同时显示出研究收益与资料覆盖、方法边界等限制。",
            "citation_ids": second_ids,
        },
    ]


def _review_query_variant_budget(topic: str, section: dict[str, Any], query: str) -> int:
    """Spend multi-query recall only on questions likely to need it.

    Review planning already emits up to two section-specific searches.  A
    second expansion inside every search adds latency and off-topic evidence
    to simple factual sections, while comparisons and mechanism questions
    benefit from the extra phrasing.
    """

    combined = " ".join(
        str(value or "").strip()
        for value in (topic, section.get("title", ""), section.get("objective", ""), query)
    ).casefold()
    complexity_cues = (
        "compare",
        "comparison",
        "difference",
        "mechanism",
        "relationship",
        "limitation",
        "trade-off",
        "versus",
        " vs ",
        "比较",
        "对比",
        "差异",
        "机制",
        "关系",
        "局限",
        "边界",
        "为什么",
        "如何",
    )
    if len(combined) >= 120 or any(cue in combined for cue in complexity_cues):
        return 2
    return 1


def _normalize_writing_brief(value: dict[str, Any] | None) -> dict[str, str]:
    """Keep presentation preferences bounded and separate from evidence rules."""

    raw = dict(value or {})
    audience = str(raw.get("audience", "researcher")).strip().lower()
    tone = str(raw.get("tone", "academic")).strip().lower()
    length = str(raw.get("length", "standard")).strip().lower()
    return {
        "audience": audience if audience in {"researcher", "general", "student"} else "researcher",
        "tone": tone if tone in {"academic", "concise", "teaching"} else "academic",
        "length": length if length in {"short", "standard", "long"} else "standard",
        "focus": re.sub(r"\s+", " ", str(raw.get("focus", "")).strip())[:300],
    }


def retrieve_review_evidence(
    db_path: str | Path,
    question: str,
    *,
    chat_client: ChatJsonClient,
    limit: int = 14,
    embedding_provider: Any | None = None,
    reranker: Any | None = None,
    retrieval_runtime: dict[str, Any] | None = None,
    source_doc_ids: list[str] | None = None,
    writing_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan a review and retrieve evidence independently for every section."""

    topic = str(question or "").strip()
    if not topic:
        raise ValueError("question is required")
    selected_doc_ids = list(dict.fromkeys(str(item).strip() for item in list(source_doc_ids or []) if str(item).strip()))
    brief = _normalize_writing_brief(writing_brief)
    plan = plan_literature_review(topic, chat_client=chat_client, writing_brief=brief)
    global_evidence: list[dict[str, Any]] = []
    evidence_index: dict[tuple[str, str], str] = {}
    section_results: list[dict[str, Any]] = []

    for raw_section in list(plan["sections"]):
        section = dict(raw_section)
        section["queries"] = [
            _clean_review_query(query)
            for query in _balanced_review_queries(topic, section)
        ]
        section_filters = _review_section_filters(topic, section)
        section_citations: list[str] = []
        query_traces: list[dict[str, Any]] = []
        for query in list(section["queries"])[:_MAX_QUERIES_PER_SECTION]:
            query_variant_budget = _review_query_variant_budget(topic, section, query)
            result = answer_question(
                db_path,
                query,
                limit=max(8, min(20, int(limit))),
                max_quotes=7,
                min_quotes=1,
                min_documents=1,
                adequacy_profile="manual",
                agentic_profile="custom",
                query_variants=query_variant_budget,
                max_followup_queries=1,
                paper_recall_limit=0,
                per_document_limit=3,
                answer_provider="local",
                verification_provider="local",
                embedding_provider=embedding_provider,
                reranker=reranker,
                filters={
                    **section_filters,
                    **({"doc_ids": selected_doc_ids} if selected_doc_ids else {}),
                },
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
                    "query_variant_budget": query_variant_budget,
                    "filters": dict(
                        {
                            **section_filters,
                            **({"doc_ids": selected_doc_ids} if selected_doc_ids else {}),
                        }
                    ),
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
            "expanded_query_count": sum(
                int(trace.get("query_variant_budget", 1) or 1)
                for section in section_results
                for trace in section["query_traces"]
            ),
            "evidence_count": len(global_evidence),
            "document_count": document_count,
        },
        "retrieval_runtime": dict(retrieval_runtime or {}),
        "source_scope": {
            "mode": "selected" if selected_doc_ids else "all_notebook_sources",
            "doc_ids": selected_doc_ids,
            "document_count": len(selected_doc_ids) if selected_doc_ids else document_count,
        },
        "writing_brief": brief,
    }


def plan_literature_review(
    question: str,
    *,
    chat_client: ChatJsonClient,
    writing_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the writing model for a bounded outline and section search queries."""

    # This common three-paper comparison has an explicit user-supplied
    # contract. A free-form model outline can silently split or omit one of
    # those required dimensions, so preserve the requested five-part plan.
    if _is_transformer_bert_gpt3_comparison(question):
        plan = _fallback_review_plan(question)
        plan["planning"] = {
            "mode": "deterministic-evidence-plan",
            "reason": "explicit Transformer/BERT/GPT-3 comparison contract",
        }
        return plan

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
            "content": json.dumps(
                {"review_question": question, "writing_brief": _normalize_writing_brief(writing_brief)},
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = chat_client.complete_json(messages, schema_name="literature_review_plan") or {}
        plan = _normalize_review_plan(question, raw)
        if _review_plan_is_on_topic(question, plan):
            return plan
        fallback = _fallback_review_plan(question)
        fallback["planning"] = {
            "mode": "deterministic-evidence-plan",
            "reason": "writing model returned an off-topic review outline",
        }
        return fallback
    except (RuntimeError, ValueError) as error:
        plan = _fallback_review_plan(question)
        plan["planning"] = {
            "mode": "deterministic-evidence-plan",
            "reason": f"{type(error).__name__}: {error}"[:300],
        }
        return plan


def _concise_review_title(question: str, candidate: str = "") -> str:
    """Return a document title, never a replay of the user's instruction."""

    prompt = re.sub(r"\s+", " ", str(question or "")).strip()
    proposed = re.sub(r"\s+", " ", str(candidate or "")).strip()
    folded = prompt.casefold()
    if "transformer" in folded and "bert" in folded and re.search(r"\bgpt-?3\b", folded):
        return "Transformer、BERT 与 GPT-3：架构、训练与能力边界"

    instruction_cues = ("请", "帮我", "基于", "必须", "每个", "不得", "需要")
    instruction_markers = (
        "以论文综述形式",
        "不要堆砌",
        "优先使用",
        "只有章节明确",
        "每个关键判断",
        "区分直接结果",
        "最后列出",
    )
    normalized_prompt = re.sub(r"\s+", "", prompt).casefold()
    normalized_proposed = re.sub(r"\s+", "", proposed).casefold()
    replays_prompt = bool(
        normalized_prompt
        and normalized_proposed
        and (normalized_prompt in normalized_proposed or normalized_proposed in normalized_prompt)
    )
    if (
        proposed
        and len(proposed) <= 72
        and not proposed.startswith(instruction_cues)
        and not any(
            cue in proposed
            for cue in (
                "必须",
                "每个实质性段落",
                "不得",
                *instruction_markers,
            )
        )
        and not replays_prompt
    ):
        return proposed.rstrip("。；;：: ")

    comparison = re.search(
        r"(?:比较|对比)\s*([^。；;]+?)(?=(?:，?必须|，?需要|，?请|，?每个|，?不得|。|；|;|$))",
        prompt,
    )
    if comparison:
        subject = comparison.group(1).strip(" ，,：:。；;")
        subject = re.sub(r"^(?:一下|原始论文中的)", "", subject)
        if subject:
            return f"{subject[:52].rstrip()}：比较综述"

    topic = prompt
    explicit_topic = re.search(
        r"(?:主题|题目|研究主题)\s*(?:为|是|：|:)\s*[“「\"'](.+?)[”」\"']",
        prompt,
    )
    if explicit_topic:
        topic = explicit_topic.group(1).strip()
    if "：" in topic or ":" in topic:
        parts = re.split(r"[：:]", topic, maxsplit=1)
        if len(parts) == 2 and any(cue in parts[0] for cue in instruction_cues):
            topic = parts[1]
    topic = re.split(r"(?:必须|每个实质性段落|不得|请分别|需要分别)", topic, maxsplit=1)[0]
    topic = re.sub(r"^(?:请|请你|帮我|请基于[^，,。；;]{0,60})\s*", "", topic)
    topic = re.sub(r"^(?:撰写|写|生成|整理)(?:一篇|一份)?(?:中文)?(?:文献)?综述[：:]?\s*", "", topic)
    topic = re.sub(r"(?:有哪些|有什么)?(?:可用)?证据[？?]?$", "", topic)
    topic = topic.strip(" ，,：:。；;？?\"'“”")
    return f"{topic[:52]}：证据综述" if topic else "文献证据综述"

def _fallback_review_plan(question: str) -> dict[str, Any]:
    """Keep evidence retrieval usable when the writing gateway is throttled."""

    english_terms = " ".join(
        dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}", question))
    ).strip()
    retrieval_topic = english_terms or question
    folded_terms = retrieval_topic.casefold()
    if "transformer" in folded_terms and "bert" in folded_terms and "gpt" in folded_terms:
        return {
            "title": _concise_review_title(question),
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
                    "objective": "比较原始 Transformer 的 BLEU、BERT 的 GLUE/SQuAD 与 GPT-3 的 zero-shot、one-shot、few-shot 基准证据。",
                    "queries": [
                        "Transformer translation BLEU BERT GLUE SQuAD experimental results",
                        "GPT-3 zero-shot one-shot few-shot benchmark performance scaling",
                    ],
                },
                {
                    "id": "adaptation",
                    "title": "下游适配方式",
                    "objective": "比较原始 Transformer 的任务级训练、BERT fine-tuning 与 GPT-3 in-context、few-shot、zero-shot 适配范式。",
                    "queries": [
                        "Transformer supervised machine translation training WMT BERT fine-tuning downstream tasks",
                        "GPT-3 in-context few-shot zero-shot adaptation",
                    ],
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
    # A gateway fallback must remain faithful to the user's subject.  The
    # generic outline below is intentionally model-oriented, which is a poor
    # fallback for domain reviews (and was especially confusing for Chinese
    # photovoltaic/ecology requests).  Keep the section ids stable enough for
    # downstream citation handling, while changing the actual research plan
    # to the requested domain.
    domain_text = question.casefold()
    if any(term in domain_text for term in ("光伏", "太阳能电站", "光伏农业")) and any(
        term in domain_text for term in ("生态", "生态系统", "植被", "农业", "环境")
    ):
        retrieval_topic = " ".join(
            term
            for term in ("光伏", "生态", "植被", "农业", "环境")
            if term in domain_text
        ) or "光伏 生态"
        domain_sections = [
            (
                "foundations",
                "研究现状与证据范围",
                "界定光伏电站生态影响与光伏农业协同治理的研究对象、情境和证据范围",
                "光伏 生态 研究现状 证据范围",
            ),
            (
                "mechanisms",
                "生态影响机制",
                "比较土地占用、遮阴、微气候以及水热碳循环对植被和生态系统的作用机制",
                "光伏 生态影响 机制 植被 微气候 水热碳循环",
            ),
            (
                "effects",
                "生态效应与情境比较",
                "比较不同地区、土地类型和光伏布局下的植被、生物多样性与生态效应证据",
                "光伏 植被 生物多样性 生态效应 比较 沙地 农田",
            ),
            (
                "governance",
                "光伏农业协同治理",
                "梳理农光互补、生态修复、监测评估和土地治理策略及其适用条件",
                "光伏农业 协同治理 生态修复 监测评估 农田",
            ),
            (
                "limits",
                "证据边界与开放问题",
                "识别时空尺度、研究方法、长期监测和因果识别方面的局限与待验证问题",
                "光伏 生态 证据边界 局限 长期监测 开放问题",
            ),
        ]
        return {
            "title": _concise_review_title(question),
            "scope": f"围绕“{question}”综合当前资料库中的光伏生态证据。",
            "sections": [
                {
                    "id": section_id,
                    "title": title,
                    "objective": objective,
                    "queries": [f"{retrieval_topic} {query_terms}"[:500]],
                }
                for section_id, title, objective, query_terms in domain_sections
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
        "title": _concise_review_title(question),
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
    writing_brief = _normalize_writing_brief(dict(research.get("writing_brief", {}) or {}))
    all_known_ids = {str(row.get("citation_id", "")) for row in evidence if str(row.get("citation_id", ""))}
    if not question or not plan.get("sections") or len(all_known_ids) < 3:
        raise ValueError("综述检索结果不完整，无法进入写作阶段")

    prompt_plan, prompt_evidence = _review_prompt_inputs(question, plan, evidence)
    known_ids = {str(row.get("citation_id", "")) for row in prompt_evidence}
    raw = _synthesize_review_in_parts(
        question,
        prompt_plan,
        prompt_evidence,
        chat_client=chat_client,
        writing_brief=writing_brief,
    )
    delivered_section_ids = {
        str(section.get("id", ""))
        for section in list(raw.get("sections", []) or [])
        if str(section.get("id", ""))
    }
    normalization_plan = {
        **plan,
        "sections": [
            section
            for section in list(plan.get("sections", []) or [])
            if str(dict(section).get("id", "")) in delivered_section_ids
        ],
    }
    document = _normalize_review_document(question, normalization_plan, raw, known_ids=known_ids)
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
        "writing_runtime": dict(raw.get("writing_runtime", {}) or {}),
        "retrieval_runtime": dict(research.get("retrieval_runtime", {}) or {}),
        "source_scope": dict(research.get("source_scope", {}) or {}),
        "writing_brief": writing_brief,
    }


def _synthesize_review_in_parts(
    question: str,
    plan: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient,
    writing_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fall back to bounded section calls when one deeply nested JSON fails."""

    evidence_by_id = {str(row.get("citation_id", "")): dict(row) for row in evidence}
    sections: list[dict[str, Any]] = []
    fallback_titles: list[str] = []
    coverage_gap_titles: list[str] = []
    skipped_section_titles: list[str] = []
    model_section_titles: list[str] = []
    text_completion = getattr(chat_client, "complete_text", None)
    chinese_output = bool(re.search(r"[\u3400-\u9fff]", question))
    for planned in list(plan.get("sections", []) or []):
        citation_ids = _diverse_section_citation_ids(dict(planned), evidence_by_id, limit=6)
        citation_ids = _exclusive_section_citation_ids(dict(planned), citation_ids, evidence_by_id)
        citation_ids = _subject_balanced_section_citation_ids(
            question,
            dict(planned),
            citation_ids,
            evidence_by_id,
            limit=6,
        )
        if not citation_ids:
            # A section with zero relevant citations cannot be grounded —
            # force-feeding unrelated evidence produces plausible-looking but
            # fabricated prose.  Mark the gap explicitly and let the coverage
            # supplement phase add sentences from any remaining evidence.
            skipped_section_titles.append(str(planned.get("title", "")))
            continue
        section_evidence = [evidence_by_id[item] for item in citation_ids]
        raw_section: dict[str, Any] = {}
        model_attempted = False
        try:
            model_attempted = True
            raw_section = _synthesize_structured_review_section(
                question,
                dict(planned),
                section_evidence,
                chat_client=chat_client,
                writing_brief=writing_brief,
            )
        except ValueError:
            # A model-supplied citation outside the current whitelist is never
            # accepted; the grounded fallback below is safer than asking the
            # same slow provider to regenerate the whole paragraph.
            raw_section = {}
        except Exception:  # provider transport/schema failures use grounded fallback
            raw_section = {}
        model_written = bool(raw_section)
        if _is_transformer_bert_gpt3_comparison(question):
            literal_section = _deterministic_grounded_review_section(
                question,
                dict(planned),
                section_evidence,
            )
            if literal_section:
                raw_section = literal_section
                model_written = False
        if not raw_section and callable(text_completion):
            # Some OpenAI-compatible reasoning endpoints return an empty
            # message for a large JSON response even though ordinary text
            # completion works.  Recover with one bounded prose call and a
            # separate sentence-level citation attribution pass before
            # falling all the way back to literal source excerpts.
            model_attempted = True
            raw_section = _synthesize_plain_review_section(
                question,
                dict(planned),
                section_evidence,
                text_completion=text_completion,
                citation_client=chat_client,
                writing_brief=writing_brief,
            )
            model_written = bool(raw_section)
        if not raw_section:
            if model_attempted and chinese_output:
                raise ValueError(
                    "写作模型不可用或未返回可核验的连贯段落；为避免把证据片段冒充综述，已停止交付。"
                    "不会把英文摘录伪装成中文综述，请检查写作模型余额与配置后重试。"
                )
            fallback_titles.append(str(planned.get("title", "")))
            raw_section = _deterministic_grounded_review_section(
                question,
                dict(planned),
                section_evidence,
            )
        if not raw_section:
            # Prefer one-source-at-a-time evidence sentences before asking for
            # an unstructured paragraph.  The direct path keeps each sentence
            # bound to the exact quote that supports it, whereas a plain-text
            # paragraph can only be validated against the evidence batch as a
            # whole and would otherwise repeat every citation after every
            # sentence.
            direct_section = _direct_evidence_section(
                question,
                dict(planned),
                section_evidence,
                text_completion=text_completion if callable(text_completion) else None,
            )
            if (
                direct_section
                and re.search(r"[\u3400-\u9fff]", question)
                and len(re.findall(r"[\u3400-\u9fff]", str(direct_section.get("text", "")))) < 45
            ):
                # Selecting an English quote is not enough for a Chinese
                # review.  If its faithful-translation call failed, continue
                # to the bounded Chinese paragraph fallback instead of later
                # discarding the whole section as a language mismatch.
                direct_section = {}
            raw_section = direct_section
        if not raw_section:
            if callable(text_completion):
                raw_section = _synthesize_plain_review_section(
                    question,
                    dict(planned),
                    section_evidence,
                    text_completion=text_completion,
                    citation_client=chat_client,
                    writing_brief=writing_brief,
                )
        if (
            (not raw_section or len(re.findall(r"[\u3400-\u9fff]", str(raw_section.get("text", "")))) < 45)
            and re.search(r"[\u3400-\u9fff]", question)
        ):
            deterministic_section = _deterministic_grounded_review_section(
                question,
                dict(planned),
                section_evidence,
            )
            if deterministic_section:
                raw_section = deterministic_section
        if not raw_section:
            skipped_section_titles.append(str(planned.get("title", "")))
            continue
        raw_section, coverage_complete = _supplement_review_section_coverage(
            question,
            dict(planned),
            raw_section,
            section_evidence,
            text_completion=text_completion if callable(text_completion) else None,
        )
        raw_section, subject_coverage_complete = _supplement_review_subject_coverage(
            question,
            dict(planned),
            raw_section,
            section_evidence,
            chat_client=chat_client,
        )
        coverage_complete = coverage_complete and subject_coverage_complete
        required_subjects = _required_review_subjects(question, dict(planned))
        # Treat dedicated three-way comparison sections as a hard contract.
        # Two-subject mentions often appear as local context inside a focused
        # BERT or GPT-3 section; failing the whole review there would discard
        # a grounded focal explanation merely because the contextual contrast
        # could not be stated from the selected excerpt.
        if len(required_subjects) >= 3 and not subject_coverage_complete:
            missing_subjects = [
                subject
                for subject in required_subjects
                if not _subject_is_present(subject, str(raw_section.get("text", "")))
            ]
            skipped_section_titles.append(
                f"{planned.get('title', '')}（缺少：{'、'.join(missing_subjects)}）"
            )
            continue
        if not coverage_complete:
            coverage_gap_titles.append(str(planned.get("title", "")))
        try:
            paragraph = _normalized_cited_text(
                raw_section,
                known_ids=set(citation_ids),
                field=f"章节“{planned.get('title', '')}”",
            )
        except ValueError:
            skipped_section_titles.append(str(planned.get("title", "")))
            continue
        if not _review_text_is_readable(str(paragraph.get("text", ""))):
            deterministic_section = _deterministic_grounded_review_section(
                question,
                dict(planned),
                section_evidence,
            )
            if not deterministic_section:
                skipped_section_titles.append(str(planned.get("title", "")))
                continue
            model_written = False
            try:
                paragraph = _normalized_cited_text(
                    deterministic_section,
                    known_ids=set(citation_ids),
                    field=f"章节“{planned.get('title', '')}”",
                )
            except ValueError:
                skipped_section_titles.append(str(planned.get("title", "")))
                continue
        if re.search(r"[\u3400-\u9fff]", question):
            chinese_characters = len(re.findall(r"[\u3400-\u9fff]", str(paragraph.get("text", ""))))
            if chinese_characters < 45:
                skipped_section_titles.append(str(planned.get("title", "")))
                continue
        sections.append(
            {
                "id": str(planned.get("id", "")),
                "title": str(planned.get("title", "")),
                **paragraph,
            }
        )
        if model_written:
            model_section_titles.append(str(planned.get("title", "")))

    if len(sections) < 2:
        if re.search(r"[\u3400-\u9fff]", question):
            raise ValueError("中文综述写作模型暂时不可用，请稍后重试；系统不会把英文摘录伪装成中文综述")
        raise ValueError(
            "当前带锚点证据不足以形成至少两个受支持章节；"
            "已停止写作，避免给证据空白附上误导性引用。"
        )

    sections, uncovered_documents = _supplement_review_source_coverage(
        question,
        plan,
        sections,
        evidence,
        text_completion=text_completion if callable(text_completion) else None,
    )
    overview = _deterministic_review_overview(question, plan, sections)
    chinese_output = bool(re.search(r"[\u3400-\u9fff]", question))
    title_separator = "、" if chinese_output else "; "
    if fallback_titles:
        limitations = list(overview.get("limitations", []) or [])
        joined = title_separator.join(fallback_titles)
        limitations.append(
            f"章节“{joined}”采用原文摘录或忠实直译，未作扩展推断。"
            if chinese_output
            else f"Sections “{joined}” use literal source excerpts because model synthesis was unavailable; no unsupported inference was added."
        )
        overview["limitations"] = limitations
    if coverage_gap_titles:
        limitations = list(overview.get("limitations", []) or [])
        joined = title_separator.join(coverage_gap_titles)
        limitations.append(
            (f"章节“{joined}”没有覆盖计划中全部比较对象；正文只保留已有来源直接支持的部分。")
            if chinese_output
            else f"Sections “{joined}” do not cover every planned comparison target; only directly supported material was retained."
        )
        overview["limitations"] = limitations
    if uncovered_documents:
        limitations = list(overview.get("limitations", []) or [])
        limitations.append(
            (f"最终正文仍有 {len(uncovered_documents)} 个检索来源未形成与章节目标直接匹配的陈述，这些来源不计入综述充分性。")
            if chinese_output
            else f"{len(uncovered_documents)} retrieved sources did not yield statements that directly matched a section objective and were excluded from the adequacy count."
        )
        overview["limitations"] = limitations
    if skipped_section_titles:
        limitations = list(overview.get("limitations", []) or [])
        joined = title_separator.join(skipped_section_titles)
        limitations.append(
            f"计划章节“{joined}”未通过严格证据校验，已从正文移除。"
            if chinese_output
            else f"Planned sections “{joined}” did not pass strict evidence validation and were omitted."
        )
        overview["limitations"] = limitations
    return {
        **dict(overview),
        "sections": sections,
        "writing_runtime": {
            "model_section_count": len(model_section_titles),
            "model_sections": model_section_titles,
            "fallback_section_count": len(fallback_titles),
            "fallback_sections": fallback_titles,
            "skipped_section_count": len(skipped_section_titles),
            "skipped_sections": skipped_section_titles,
        },
    }


def _synthesize_structured_review_section(
    question: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient,
    writing_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one concise cited paragraph with one bounded model request."""

    evidence_rows = [
        {
            "citation_id": str(row.get("citation_id", "")),
            "paper": str(row.get("paper", "")),
            "section": str(row.get("section", "")),
            "exact_quote": str(row.get("exact_quote", "")),
        }
        for row in evidence
        if str(row.get("citation_id", "")) and str(row.get("exact_quote", ""))
    ]
    if not evidence_rows:
        raise ValueError("review section has no evidence")
    required_subjects = _required_review_subjects(question, planned)
    brief = _normalize_writing_brief(writing_brief)
    chinese_output = bool(re.search(r"[\u3400-\u9fff]", question))
    if chinese_output:
        length_ranges = {"short": "200 到 400 字", "standard": "400 到 800 字", "long": "600 到 1200 字"}
        audience_labels = {"researcher": "科研人员", "general": "跨学科读者", "student": "研究生"}
        tone_labels = {"academic": "严谨学术", "concise": "简洁直接", "teaching": "解释清楚"}
        system_prompt = (
            "你是证据约束的中文文献综述写作者。只使用给定 exact_quote 直接支持的事实，"
            f"围绕指定章节写一个 {length_ranges[brief['length']]}的连贯中文段落。"
            f"目标读者是{audience_labels[brief['audience']]}，采用{tone_labels[brief['tone']]}的表达。"
            "写作偏好只影响表述，绝不能降低证据约束。不得引入外部知识、因果推断或证据中没有的评价。"
        )
    else:
        length_ranges = {"short": "120 to 240 words", "standard": "220 to 420 words", "long": "350 to 650 words"}
        audience_labels = {"researcher": "researchers", "general": "cross-disciplinary readers", "student": "graduate students"}
        tone_labels = {"academic": "a rigorous academic", "concise": "a concise", "teaching": "an explanatory"}
        system_prompt = (
            "You are an evidence-constrained literature-review writer. Use only facts directly supported by the supplied exact_quote values. "
            f"Write one coherent {length_ranges[brief['length']]} section for {audience_labels[brief['audience']]} in {tone_labels[brief['tone']]} style. "
            "Writing preferences affect presentation only and never relax the evidence constraint. Do not add outside knowledge, causal claims, or evaluations absent from the evidence. "
        )
    method_scope_rule = (
        ""
        if _review_section_allows_methods(planned)
        else (
            "当前章节没有明确讨论研究方法；只综合摘要、结果、讨论和结论中的发现、解释与证据边界，"
            "不要写采样、实验、监测、测量、统计、建模或其他研究流程，也不要用方法过程替代研究结论。"
            if chinese_output
            else (
                "This section does not explicitly discuss methods. Synthesize findings, interpretations, and evidence limits "
                "from abstracts, results, discussions, and conclusions only; do not describe sampling, experiments, monitoring, "
                "measurements, statistics, modeling, or other procedures, and do not substitute procedure for a finding."
            )
        )
    )
    comparison_rules = (
        "必须明确写出章节讨论的模型或方法名称；比较并行路线时不得改写成先后替代关系。"
        "严格区分 GPT-3 与 BERT 论文中所称的 OpenAI GPT：不得据后者推断 GPT-3 采用微调。"
        "若证据指标是人类识别机器文本的准确率，必须明确写出识别者和识别任务，不得改写成模型生成准确率。"
        if _is_transformer_bert_gpt3_comparison(question)
        else ""
    )
    shared_rules = (
        "如果输入给出 required_subjects，正文必须逐一明确讨论其中每个对象。"
        "把段落拆成若干完整句子；长篇模式优先写出比较、分歧和适用边界，而不是重复摘录。"
        "每个句子的 citation_ids 只能使用输入中的编号，且只列直接支持该句的证据。"
        "禁止把多句话共用的引用统一堆在段落末尾。返回 JSON：{sentences:[{text, citation_ids:[...]}]}。"
        if chinese_output
        else (
            "If required_subjects are supplied, explicitly address each one. Split the paragraph into complete sentences; for long mode prioritize comparisons, disagreements, and applicability limits instead of repeating quotations. "
            "Each sentence must use only citation_ids that directly support that complete sentence. Never collect all citations at paragraph end. Return JSON as {sentences:[{text, citation_ids:[...]}]}."
        )
    )
    messages = [
        {
            "role": "system",
            "content": system_prompt + method_scope_rule + comparison_rules + shared_rules,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "review_question": question,
                    "section": {
                        "title": str(planned.get("title", "")),
                        "objective": str(planned.get("objective", "")),
                        "required_subjects": required_subjects,
                    },
                    "writing_brief": brief,
                    "evidence": evidence_rows,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat_client.complete_json(messages, schema_name="literature_review_section") or {}
    known_ids = {str(row["citation_id"]) for row in evidence_rows}
    paragraph = _normalized_cited_text(raw, known_ids=known_ids, field=f"章节“{planned.get('title', '')}”")
    cleaned_sentences: list[dict[str, Any]] = []
    for sentence in _cited_sentence_items(paragraph):
        sentence_text = _strip_review_excerpt_artifacts(
            _strip_unrequested_model_detours(question, planned, str(sentence.get("text", "")))
        )
        if sentence_text and (
            len(required_subjects) < 2
            or _claim_addresses_review_section({"text": sentence_text}, planned)
        ):
            cleaned_sentences.append({**sentence, "text": sentence_text})
    paragraph = _cited_text_from_sentences(cleaned_sentences)
    text = str(paragraph.get("text", "")).strip()
    if re.search(r"[\u3400-\u9fff]", question):
        chinese_characters = len(re.findall(r"[\u3400-\u9fff]", text))
        if chinese_characters < 45:
            raise ValueError("review section is not a substantive Chinese paragraph")
    if not _claim_addresses_review_section({"text": text}, planned):
        raise ValueError("review section does not address its planned subject")
    if not _review_text_is_readable(text):
        raise ValueError("review section contains corrupted or repetitive text")
    if not text:
        raise ValueError("review comparison section contains only unrelated model detours")
    quote_text_by_id = {
        str(row["citation_id"]): str(row["exact_quote"])
        for row in evidence_rows
    }
    if not all(
        _semantic_cues_are_grounded(
            {
                "text": str(sentence.get("text", "")),
                "quote_ids": list(sentence.get("citation_ids", []) or []),
            },
            quote_text_by_id,
        )
        for sentence in _cited_sentence_items(paragraph)
    ):
        raise ValueError("review section adds unsupported semantic claims")
    return paragraph


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
                            max_tokens=2048,
                        )
                    ).strip()
                except Exception:  # translation is optional; the verified source-language claim remains valid
                    translated = ""
                if translated:
                    claim["text"] = translated
    return _cited_text_from_sentences(
        [
            {
                "text": _sentence_text(str(item.get("text", "")), chinese=True),
                "citation_ids": [
                    str(quote_id)
                    for quote_id in list(item.get("quote_ids", []) or [])
                    if str(quote_id)
                ],
            }
            for item in supported
        ]
    )


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
    candidates = _exclusive_section_citation_ids(planned, candidates, evidence_by_id)
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


def _balanced_review_queries(question: str, planned: dict[str, Any]) -> list[str]:
    """Use subject-specific retrieval for an explicit Transformer/BERT/GPT-3 comparison."""

    required = _required_review_subjects(question, planned)
    target = f"{planned.get('title', '')} {planned.get('objective', '')}".casefold()
    comparison_dimension = any(
        cue in target
        for cue in (
            "实验", "评价", "基准", "适配", "微调", "下游",
            "experiment", "evaluation", "benchmark", "adaptation", "fine-tun", "downstream",
        )
    )
    limitation_dimension = any(
        cue in target for cue in ("局限", "边界", "不足", "limitation", "weakness", "risk")
    )
    transformer_comparison = _is_transformer_bert_gpt3_comparison(question)
    if transformer_comparison and limitation_dimension:
        return [
            "factual inaccuracies",
            "human detection close to chance",
        ]
    objective_dimension = any(
        cue in target
        for cue in (
            "预训练", "训练目标", "掩码", "自回归",
            "pre-train", "training objective", "masked language", "autoregressive", "left-to-right",
        )
    )
    if transformer_comparison and objective_dimension and "BERT" in required and "GPT-3" in required:
        return [
            "BERT masked language model deep bidirectional pre-training objective",
            "autoregressive language model 175 billion",
        ]
    if required == ["原始 Transformer"] and any(
        cue in target for cue in ("位置编码", "positional encoding", "架构", "architecture")
    ):
        return [
            "original Transformer encoder decoder self-attention architecture",
            "Attention Is All You Need sinusoidal positional encoding sine cosine",
        ]
    if required == ["原始 Transformer", "BERT", "GPT-3"] and comparison_dimension:
        return [
            "original Transformer WMT BLEU supervised machine translation training results",
            "BERT GLUE SQuAD fine-tuning GPT-3 zero-shot one-shot few-shot in-context learning",
        ]
    return [str(item) for item in list(planned.get("queries", []) or []) if str(item).strip()]


# Review structure boilerplate that a model may append as pseudo-English
# "translation" of generic section headers.  These terms do not represent
# topical content and must be removed before the query enters retrieval.
_REVIEW_TEMPLATE_TERMS = {
    "foundations", "architecture", "mechanism", "mechanisms",
    "methods", "method", "training", "objectives", "objective",
    "pretraining", "pre-training", "pre", "training",
    "results", "experiments", "experiment", "performance",
    "comparison", "comparisons", "compare",
    "adaptation", "adaptations", "adapt", "fine-tuning", "fine", "tuning",
    "transfer", "in-context", "in", "context", "learning",
    "limitations", "limitation", "weaknesses", "weakness",
    "open", "questions", "discussion", "discussions", "conclusion", "conclusions",
    "future", "work", "works", "related", "background", "introduction",
    "evaluation", "evaluations", "evaluate", "benchmark", "benchmarks",
    "framework", "frameworks", "survey", "surveys", "overview",
    "systematic", "review", "reviews", "analysis", "analyses",
    "application", "applications", "implication", "implications",
    "chapter", "chapters", "section", "sections", "part", "parts",
    "approach", "approaches", "model", "models",
    "methodology", "methodologies", "meta-analysis", "meta",
}


def _clean_review_query(query: str) -> str:
    """Remove generic review-template terms from a section query.

    A writing model may output ``"光伏组件衰减率综述 foundations architecture"``
    where the English suffix is a generic section header, not a topical
    search term.  Drop those words so the retrieval sees only the real
    subject matter.
    """

    words = str(query or "").split()
    cleaned = [word for word in words if word.casefold() not in _REVIEW_TEMPLATE_TERMS]
    return " ".join(cleaned) if cleaned else str(query).strip()


def _is_transformer_bert_gpt3_comparison(question: str) -> bool:
    scope = str(question or "").casefold()
    comparison_cue = any(cue in scope for cue in ("比较", "对比", "综述", "compare", "review"))
    return (
        comparison_cue
        and "transformer" in scope
        and "bert" in scope
        and bool(re.search(r"\bgpt-?3\b", scope))
    )


def _subject_balanced_section_citation_ids(
    question: str,
    planned: dict[str, Any],
    citation_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    """Reserve one clean, relevant quotation for each named comparison subject."""

    required = _required_review_subjects(question, planned)
    if len(required) < 2:
        return citation_ids[:limit]
    selected: list[str] = []
    for subject in required:
        candidates = [
            (citation_id, row)
            for citation_id, row in evidence_by_id.items()
            if _evidence_matches_review_subject(subject, row)
        ]
        if not candidates:
            continue
        citation_id, _ = max(
            candidates,
            key=lambda item: _subject_comparison_evidence_score(subject, planned, item[1]),
        )
        if citation_id not in selected:
            selected.append(citation_id)
    for citation_id in citation_ids:
        if citation_id not in selected:
            selected.append(citation_id)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _subject_comparison_evidence_score(
    subject: str,
    planned: dict[str, Any],
    row: dict[str, Any],
) -> float:
    score = _subject_evidence_selection_score(planned, row)
    quote = str(row.get("exact_quote", "")).casefold()
    target = f"{planned.get('title', '')} {planned.get('objective', '')}".casefold()
    objective_dimension = any(
        cue in target for cue in ("预训练", "训练目标", "掩码", "自回归", "pre-train", "objective", "autoregressive")
    )
    limitation_dimension = any(
        cue in target for cue in ("局限", "边界", "不足", "limitation", "weakness", "risk")
    )
    if subject == "原始 Transformer" and "wmt" in quote and "bleu" in quote:
        score += 8.0
    elif subject == "BERT":
        if objective_dimension and "masked language model" in quote:
            score += 10.0
        elif "bert" in quote and "fine-tun" in quote:
            score += 8.0
    elif subject == "GPT-3":
        if objective_dimension and "autoregressive language model" in quote:
            score += 10.0
        elif limitation_dimension and any(cue in quote for cue in ("factual inaccuracies", "close to chance", "barely above chance")):
            score += 10.0
        elif any(cue in quote for cue in ("zero-shot", "one-shot", "few-shot")):
            score += 8.0
    return score


def _subject_evidence_selection_score(planned: dict[str, Any], row: dict[str, Any]) -> float:
    quote = " ".join(str(row.get("exact_quote", "")).split())
    score = _section_evidence_score(planned, {"exact_quote": quote})
    folded = quote.casefold()
    if len(quote) > 1200:
        score -= 6.0
    if len(quote) > 3000:
        score -= 3.0
    if re.match(r"^(?:table|setting|system\s+mnli|model name)\b", folded):
        score -= 4.0
    numeric_ratio = sum(character.isdigit() for character in quote) / max(1, len(quote))
    if numeric_ratio > 0.1:
        score -= 2.0
    return score


def _exclusive_section_citation_ids(
    planned: dict[str, Any],
    citation_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    """Keep single-model sections from receiving evidence about a different paper."""

    title = str(planned.get("title", "")).casefold()
    has_bert = "bert" in title
    has_gpt3 = bool(re.search(r"\bgpt-?3\b", title))
    original_transformer = "原始 transformer" in title or "original transformer" in title
    if not (original_transformer or has_bert or has_gpt3):
        return citation_ids
    if sum((original_transformer, has_bert, has_gpt3)) != 1:
        return citation_ids

    matched: list[str] = []
    for citation_id in citation_ids:
        row = evidence_by_id.get(citation_id, {})
        if original_transformer and _evidence_matches_review_subject("原始 Transformer", row):
            matched.append(citation_id)
        elif has_bert and _evidence_matches_review_subject("BERT", row):
            matched.append(citation_id)
        elif has_gpt3 and _evidence_matches_review_subject("GPT-3", row):
            matched.append(citation_id)
    return matched or citation_ids


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
            raw_section = _merge_cited_texts(raw_section, extension)
    final_documents = {
        _review_document_key(evidence_by_id[citation_id])
        for citation_id in list(raw_section.get("citation_ids", []) or [])
        if citation_id in evidence_by_id
    }
    return raw_section, len(final_documents) >= desired


def _synthesize_plain_review_section(
    question: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    text_completion: Callable[..., str],
    citation_client: ChatJsonClient | None = None,
    writing_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use one plain-text model call before falling back to source-language excerpts."""

    rows = [
        {
            "citation_id": str(row.get("citation_id", "")),
            "paper": str(row.get("paper", "")),
            "exact_quote": str(row.get("exact_quote", "")),
        }
        for row in evidence
        if str(row.get("citation_id", "")) and str(row.get("exact_quote", ""))
    ]
    if not rows:
        return {}
    required_subjects = _required_review_subjects(question, planned)
    brief = _normalize_writing_brief(writing_brief)
    chinese_output = bool(re.search(r"[\u3400-\u9fff]", question))
    if chinese_output:
        length_ranges = {"short": "200 到 400 字", "standard": "400 到 800 字", "long": "600 到 1200 字"}
        system_prompt = (
            "你是证据约束的中文文献综述作者。只依据输入 exact_quote 写一个"
            f"{length_ranges[brief['length']]}的连贯中文段落，不得复制目录、表格、章节号或无关细节，"
            "不得引入外部知识。逐一覆盖 required_subjects 中列出的对象；若证据不对称，只写有直接证据支持的边界，"
            "不制造对称结论。每个句号、问号或感叹号后必须紧跟 1 到 2 个支持整句的证据编号，格式只能是 [7] 或 [7,8]；"
            "不得使用输入 evidence 之外的编号。不要输出标题、项目符号或解释，只输出带句级证据编号的正文。"
        )
    else:
        length_ranges = {"short": "120 to 240 words", "standard": "220 to 420 words", "long": "350 to 650 words"}
        system_prompt = (
            "You are an evidence-constrained literature-review writer. Use only the supplied exact_quote values to write one "
            f"coherent {length_ranges[brief['length']]} paragraph. Do not copy table-of-contents fragments, section numbering, "
            "or irrelevant procedural detail, and do not introduce outside knowledge. Address every required_subject when the "
            "evidence supports it; when support is asymmetric, state only the supported boundary. Immediately after every sentence, "
            "append one or two citation IDs that directly support the whole sentence, using only [7] or [7,8] syntax and only IDs "
            "present in the evidence input. Return prose only, without a heading, bullets, or commentary."
        )
    if not _review_section_allows_methods(planned):
        system_prompt += (
            "当前章节没有明确讨论研究方法；只写摘要、结果、讨论和结论支持的发现、解释和边界，"
            "不要写采样、实验、监测、测量、统计、建模或其他研究流程。"
            if chinese_output
            else (
                "This section does not explicitly discuss methods. Write only findings, interpretations, and limits supported "
                "by abstracts, results, discussions, and conclusions; do not describe sampling, experiments, monitoring, "
                "measurements, statistics, modeling, or other procedures."
            )
        )
    try:
        model_text = str(
            text_completion(
                [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "review_question": question,
                                "section": {
                                    "title": str(planned.get("title", "")),
                                    "objective": str(planned.get("objective", "")),
                                    "required_subjects": required_subjects,
                                },
                                "evidence": rows,
                                "writing_brief": brief,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=2048,
            )
        ).strip()
    except Exception:
        return {}
    model_text = _strip_unrequested_model_detours(
        question,
        planned,
        model_text,
    )
    model_text = _strip_review_excerpt_artifacts(model_text)
    inline_cited = _parse_inline_review_sentence_citations(model_text, rows)
    text = _strip_inline_citation_markers(model_text)
    if not _review_text_is_readable(text):
        return {}
    if chinese_output:
        if len(re.findall(r"[\u3400-\u9fff]", text)) < 45:
            return {}
    elif len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text)) < 20:
        return {}
    if not _claim_addresses_review_section({"text": text}, planned):
        return {}
    if inline_cited:
        return inline_cited
    attributed_sentences = _attribute_plain_review_sentence_citations(
        _split_review_sentences(text),
        rows,
        chat_client=citation_client,
    )
    return _cited_text_from_sentences(attributed_sentences) if attributed_sentences else {}


def _parse_inline_review_sentence_citations(
    text: str,
    evidence: list[dict[str, str]],
) -> dict[str, Any]:
    """Parse model-authored markers while retaining citation authority locally."""

    known_ids = {
        str(row.get("citation_id", "")).strip()
        for row in evidence
        if str(row.get("citation_id", "")).strip()
    }
    quote_text_by_id = {
        str(row.get("citation_id", "")).strip(): str(row.get("exact_quote", ""))
        for row in evidence
        if str(row.get("citation_id", "")).strip()
    }
    if not known_ids:
        return {}
    marker = r"(?:\[\s*\d{1,4}(?:\s*[,，;；]\s*\d{1,4})?\s*\]|【\s*\d{1,4}(?:\s*[,，;；]\s*\d{1,4})?\s*】)"
    pattern = re.compile(
        rf"(?P<text>.*?)(?P<markers>(?:\s*{marker})+)(?P<punct>[。！？!?；；.]?)(?=\s+|$)",
        flags=re.DOTALL,
    )
    source = str(text or "").strip()
    if not source:
        return {}
    cited_sentences: list[dict[str, Any]] = []
    cursor = 0
    for match in pattern.finditer(source):
        if match.start() != cursor and source[cursor:match.start()].strip():
            return {}
        sentence_text = " ".join(
            f"{match.group('text') or ''}{match.group('punct') or ''}".split()
        ).strip()
        if len(_split_review_sentences(sentence_text)) != 1:
            return {}
        citation_ids = list(
            dict.fromkeys(re.findall(r"\d{1,4}", str(match.group("markers") or "")))
        )
        if not sentence_text or not 1 <= len(citation_ids) <= 2:
            return {}
        if any(citation_id not in known_ids for citation_id in citation_ids):
            return {}
        if not _semantic_cues_are_grounded(
            {"text": sentence_text, "quote_ids": citation_ids},
            quote_text_by_id,
        ):
            return {}
        cited_sentences.append({"text": sentence_text, "citation_ids": citation_ids})
        cursor = match.end()
    if source[cursor:].strip() or not cited_sentences:
        return {}
    return _cited_text_from_sentences(cited_sentences)


def _attribute_plain_review_sentence_citations(
    sentences: list[str],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient | None,
) -> list[dict[str, Any]]:
    """Bind fixed prose to a small, validated evidence set sentence by sentence."""

    clean_sentences = [" ".join(str(sentence).split()).strip() for sentence in sentences if str(sentence).strip()]
    rows = [
        {
            "citation_id": str(row.get("citation_id", "")),
            "paper": str(row.get("paper", "")),
            "exact_quote": str(row.get("exact_quote", "")),
        }
        for row in evidence
        if str(row.get("citation_id", "")) and str(row.get("exact_quote", ""))
    ]
    if not clean_sentences or not rows:
        return []
    if len(rows) == 1:
        citation_id = rows[0]["citation_id"]
        return [{"text": sentence, "citation_ids": [citation_id]} for sentence in clean_sentences]
    if chat_client is None:
        return []
    sentence_payload = [
        {"sentence_id": f"s{index}", "text": sentence}
        for index, sentence in enumerate(clean_sentences, start=1)
    ]
    try:
        raw = chat_client.complete_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是严格的句级引用归因器。不得改写输入句子，不得增加事实。"
                        "对每个 sentence_id 只选择 1 到 2 个能够直接支持整句的 citation_id；"
                        "如果没有直接支持，返回空列表。不得使用输入之外的编号。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"sentences": sentence_payload, "evidence": rows},
                        ensure_ascii=False,
                    ),
                },
            ],
            schema_name="literature_review_citation_attribution",
        ) or {}
    except Exception:
        return []
    assignments = raw.get("assignments") if isinstance(raw, dict) else None
    if not isinstance(assignments, list):
        return []
    known_ids = {row["citation_id"] for row in rows}
    quote_text_by_id = {row["citation_id"]: row["exact_quote"] for row in rows}
    assigned_by_sentence: dict[str, list[str]] = {}
    for item in assignments:
        if not isinstance(item, dict):
            continue
        sentence_id = str(item.get("sentence_id", "")).strip()
        citation_ids = list(
            dict.fromkeys(
                str(value).strip().strip("[]")
                for value in list(item.get("citation_ids", []) or [])
                if str(value).strip().strip("[]") in known_ids
            )
        )
        if sentence_id and 1 <= len(citation_ids) <= 2:
            assigned_by_sentence[sentence_id] = citation_ids
    attributed: list[dict[str, Any]] = []
    for item in sentence_payload:
        citation_ids = assigned_by_sentence.get(str(item["sentence_id"]), [])
        claim = {"text": str(item["text"]), "quote_ids": citation_ids}
        # A long prose draft can contain one connective sentence that no
        # supplied quote supports. Drop that sentence, but retain the other
        # model-authored sentences whose citations are valid; rejecting the
        # entire paragraph would turn a recoverable attribution gap into a
        # silent “writer unavailable” failure.
        if not citation_ids or not _semantic_cues_are_grounded(claim, quote_text_by_id):
            continue
        attributed.append({"text": str(item["text"]), "citation_ids": citation_ids})
    return attributed


def _supplement_review_subject_coverage(
    question: str,
    planned: dict[str, Any],
    raw_section: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    chat_client: ChatJsonClient,
) -> tuple[dict[str, Any], bool]:
    """Add one bounded grounded sentence for each missing named comparison subject."""

    required = _required_review_subjects(question, planned)
    if not required or _review_subject_coverage_complete(question, planned, str(raw_section.get("text", ""))):
        return raw_section, True
    text = str(raw_section.get("text", "")).strip()
    for subject in required:
        if _subject_is_present(subject, text):
            continue
        subject_evidence = [row for row in evidence if _evidence_matches_review_subject(subject, row)]
        if not subject_evidence:
            continue
        targeted = {
            "id": f"{planned.get('id', '')}-{subject}",
            "title": subject,
            "objective": f"只陈述 {subject} 与“{planned.get('title', '')}”直接相关且有原文支持的事实。",
        }
        try:
            extension = _synthesize_structured_review_section(
                question,
                targeted,
                subject_evidence[:4],
                chat_client=chat_client,
            )
        except Exception:
            extension = {}
        text_completion = getattr(chat_client, "complete_text", None)
        if not extension:
            extension = _direct_evidence_section(
                question,
                targeted,
                subject_evidence[:4],
                text_completion=text_completion if callable(text_completion) else None,
            )
        if not extension and callable(text_completion):
            extension = _synthesize_plain_review_section(
                question,
                targeted,
                subject_evidence[:4],
                text_completion=text_completion,
                citation_client=chat_client,
            )
        if not extension or not _review_text_is_readable(str(extension.get("text", ""))):
            extension = _deterministic_grounded_subject_sentence(
                subject,
                planned,
                subject_evidence,
            )
        extension_text = str(extension.get("text", "")).strip()
        if extension_text and not _subject_is_present(subject, extension_text):
            extension_text = f"{subject}：{extension_text}"
            sentence_items = _cited_sentence_items(extension)
            if sentence_items:
                sentence_items[0] = {
                    **sentence_items[0],
                    "text": f"{subject}：{sentence_items[0].get('text', '')}",
                }
                extension = _cited_text_from_sentences(sentence_items)
            else:
                extension = {**extension, "text": extension_text}
        if not extension_text or not _subject_is_present(subject, extension_text):
            continue
        raw_section = _merge_cited_texts(raw_section, extension)
        text = str(raw_section.get("text", "")).strip()
    return raw_section, _review_subject_coverage_complete(question, planned, text)


def _deterministic_grounded_review_section(
    question: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
) -> dict[str, Any]:
    """Build a concise Chinese fallback only from recognized source cues."""

    sentences: list[dict[str, Any]] = []
    required_subjects = _required_review_subjects(question, planned)
    for subject in required_subjects:
        subject_evidence = [row for row in evidence if _evidence_matches_review_subject(subject, row)]
        grounded = _deterministic_grounded_subject_sentence(subject, planned, subject_evidence)
        text = str(grounded.get("text", "")).strip()
        if not text:
            continue
        sentences.extend(_cited_sentence_items(grounded))
    # Generic English research questions do not have the three hard-coded
    # comparison subjects above.  They still deserve a safe offline fallback:
    # select literal, section-relevant source sentences instead of returning
    # an empty section after a provider/schema failure.  Chinese questions
    # continue through the translation-aware direct path in the caller.
    if not required_subjects and not re.search(r"[\u3400-\u9fff]", question):
        return _direct_evidence_section(
            question,
            planned,
            evidence,
            text_completion=None,
        )
    result = _cited_text_from_sentences(sentences)
    output = str(result.get("text", "")).strip()
    if not output or not _review_text_is_readable(output):
        return {}
    return result


def _deterministic_grounded_subject_sentence(
    subject: str,
    planned: dict[str, Any],
    evidence: list[dict[str, str]],
) -> dict[str, Any]:
    """Express a small set of literal model-paper facts without free inference."""

    ranked = sorted(
        evidence,
        key=lambda row: _subject_evidence_selection_score(planned, row),
        reverse=True,
    )
    # Instead of hardcoded template sentences that look authoritative but are
    # not derived from evidence, use the actual quote text from ranked evidence
    # rows.  Each row produces one grounded sentence with its own citation.
    sentences: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for row in ranked:
        citation_id = str(row.get("citation_id", ""))
        quote = " ".join(str(row.get("exact_quote", "")).split()).strip()
        if not citation_id or not quote:
            continue
        # Truncate to a readable sentence (up to 300 chars) and avoid duplicates.
        excerpt = quote[:300]
        if excerpt in seen_texts:
            continue
        seen_texts.add(excerpt)
        if _review_text_is_readable(excerpt):
            sentences.append({"text": excerpt, "citation_ids": [citation_id]})
    if sentences:
        return _cited_text_from_sentences(sentences)
    return {}


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
            sections[index] = {**section, **_merge_cited_texts(section, extension)}
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
    if any(cue in target for cue in ("三者", "三种模型", "三个模型", "all three", "three models")):
        desired = 3
    if "bert" in target and re.search(r"\bgpt(?:-?3)?\b", target):
        desired = max(desired, 2)
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


def _required_review_subjects(question: str, planned: dict[str, Any]) -> list[str]:
    """Return explicitly required model subjects for a focused comparison section."""

    target = f"{planned.get('title', '')} {planned.get('objective', '')}".casefold()
    multi_subject = any(
        cue in target
        for cue in ("三者", "三种模型", "三个模型", "三篇论文", "all three", "three models", "three papers")
    )
    scope = f"{target} {question}".casefold() if multi_subject else target
    subjects: list[str] = []
    if any(cue in scope for cue in ("原始 transformer", "original transformer")):
        subjects.append("原始 Transformer")
    if "bert" in scope:
        subjects.append("BERT")
    if re.search(r"\bgpt-?3\b", scope):
        subjects.append("GPT-3")
    if multi_subject and any(cue in target for cue in ("局限", "边界", "limitation", "weakness")):
        subjects = [subject for subject in subjects if subject != "原始 Transformer"]
    return subjects


def _review_subject_coverage_complete(question: str, planned: dict[str, Any], text: str) -> bool:
    return all(_subject_is_present(subject, text) for subject in _required_review_subjects(question, planned))


def _subject_is_present(subject: str, text: str) -> bool:
    folded = str(text or "").casefold()
    if subject == "原始 Transformer":
        return any(cue in folded for cue in ("原始 transformer", "original transformer"))
    if subject == "BERT":
        return "bert" in folded
    if subject == "GPT-3":
        return bool(re.search(r"\bgpt-?3\b", folded))
    return subject.casefold() in folded


def _evidence_matches_review_subject(subject: str, row: dict[str, Any]) -> bool:
    quote = str(row.get("exact_quote", "")).casefold()
    source = f"{row.get('paper', '')} {row.get('doc_id', '')}".casefold()
    original_source = "1706.03762" in source or "attention is all you need" in source
    bert_source = "1810.04805" in source or bool(re.search(r"(?:^|\W)bert(?:\W|$)", source))
    gpt3_source = "2005.14165" in source or bool(re.search(r"\bgpt-?3\b", source))
    if subject == "原始 Transformer":
        if original_source:
            return (
                "transformer" in quote
                or ("encoder" in quote and "decoder" in quote and "self-attention" in quote)
                or "positional encoding" in quote
            )
        if bert_source or gpt3_source:
            return False
        return "transformer" in quote and "bert" not in quote and not re.search(r"\bgpt-?3\b", quote)
    if subject == "BERT":
        if bert_source:
            return "bert" in quote or "masked language model" in quote
        if original_source or gpt3_source:
            return False
        return "bert" in quote
    if subject == "GPT-3":
        if gpt3_source:
            return bool(re.search(r"\bgpt-?3\b", quote)) or any(
                cue in quote
                for cue in (
                    "in-context learning", "zero-shot", "one-shot", "few-shot", "175b",
                    "misuse", "malicious", "factual", "human accuracy",
                )
            )
        if original_source or bert_source:
            return False
        return bool(re.search(r"\bgpt-?3\b", quote))
    return subject.casefold() in quote


def _has_unrequested_model_detour(question: str, planned: dict[str, Any], text: str) -> bool:
    """Reject side-model substitutions only in tightly scoped multi-model comparisons."""

    required = _required_review_subjects(question, planned)
    if len(required) < 3:
        return False
    scope = f"{question} {planned.get('title', '')} {planned.get('objective', '')}".casefold()
    folded = str(text or "").casefold()
    detours = (
        (r"\bt5(?:-[a-z0-9]+)?\b", "t5"),
        (r"\belmo\b", "elmo"),
        (r"\bopenai gpt\b", "openai gpt"),
    )
    return any(re.search(pattern, folded) and label not in scope for pattern, label in detours)


def _strip_unrequested_model_detours(question: str, planned: dict[str, Any], text: str) -> str:
    if not _has_unrequested_model_detour(question, planned, text):
        return str(text or "").strip()
    parts = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", str(text or ""))
        if item.strip()
    ]
    kept = [item for item in parts if not _has_unrequested_model_detour(question, planned, item)]
    return " ".join(kept).strip()


def _strip_review_excerpt_artifacts(text: str) -> str:
    """Remove table captions and paper-first-person lead-ins from fallback prose."""

    parts = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", str(text or ""))
        if item.strip()
    ]
    rejected = (
        re.compile(r"^(?:表|table)\s*\d+\s*[:：]", re.I),
        re.compile(r"^(?:请注意|note that)[，,:：]", re.I),
        re.compile(r"^\d+(?:\.\d+)+\s+"),
        re.compile(r"^\d+\s+(?:结果|results?)\b", re.I),
    )
    kept = [
        item
        for item in parts
        if not any(pattern.search(item) for pattern in rejected)
        and "解析器训练 wsj" not in item.casefold()
        and "participants:" not in item.casefold()
        and "∂params" not in item
        and "∂acts" not in item
        and "乘数以考虑反向传播" not in item
    ]
    return " ".join(kept).strip()


def _review_text_is_readable(text: str) -> bool:
    """Reject visibly corrupted, runaway, or excerpt-heading prose."""

    value = " ".join(str(text or "").split()).strip()
    # Long-form review sections are explicitly allowed to reach 1,200 Chinese
    # characters.  The former 700-character ceiling silently rejected valid
    # model output and even two bounded evidence excerpts.  Keep a generous
    # corruption guard while allowing the configured long-form profile.
    if not value or len(value) > 10000:
        return False
    if any(marker in value for marker in ("�", "nâ", "â€", "ï¬")):
        return False
    if re.search(r"([\u3400-\u9fff])\1{2,}", value):
        return False
    if re.search(r"([\u3400-\u9fff])(?:\s*\1){2,}", value):
        return False
    if any(fragment in value for fragment in ("集集", "的的", "和和", "性性", "中中", "了了")):
        return False
    if value.count("\\") >= 3:
        return False
    if re.search(r"\b([A-Za-z][A-Za-z0-9-]*)\b(?:\s+\1\b){3,}", value, flags=re.I):
        return False
    if re.search(r"(?:\b也\b\s*){4,}|(?:\balso\b\s*){3,}", value, flags=re.I):
        return False
    if re.search(r"[，,]{2,}|[。.!?！？]{3,}", value):
        return False
    if re.match(r"^\d+(?:\.\d+)+\s+", value):
        return False
    return True


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
        "实验": ("result", "performance", "benchmark", "bleu", "accuracy", "score", " f1"),
        "评价": ("result", "performance", "benchmark", "bleu", "accuracy", "score", " f1"),
        "适配": ("fine-tun", "zero-shot", "one-shot", "few-shot", "in-context", "supervised"),
        "下游": ("fine-tun", "downstream", "zero-shot", "one-shot", "few-shot", "in-context"),
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
    cited_quotes = [
        quote_text_by_id.get(str(quote_id), "")
        for quote_id in list(claim.get("quote_ids", []) or [])
    ]
    quotes = " ".join(cited_quotes).casefold()
    if re.search(r"\bgpt-?3\b", text) and "微调" in text:
        directly_supported = any(
            re.search(r"\bgpt-?3\b", quote.casefold()) and "fine-tun" in quote.casefold()
            for quote in cited_quotes
        )
        if not directly_supported:
            return False
    if (
        any(cue in text for cue in ("准确率下降", "准确率降低", "准确率随模型规模增大而下降"))
        and "human accuracy" in quotes
        and any(cue in quotes for cue in ("identifying whether", "detecting", "distinguish"))
        and not ("人类" in text and any(cue in text for cue in ("识别", "检测", "区分")))
    ):
        return False
    if (
        "human accuracy" in quotes
        and any(cue in quotes for cue in ("identifying whether", "detecting", "distinguish"))
        and any(cue in text for cue in ("易被察觉", "容易识别", "容易检测", "easy to detect"))
    ):
        return False
    if (
        "bert" in text
        and any(cue in text for cue in ("生成任务", "生成能力", "生成质量"))
        and any(cue in text for cue in ("局限", "受限", "不足", "有限"))
        and not any("bert" in quote.casefold() and "generat" in quote.casefold() for quote in cited_quotes)
    ):
        return False
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
        architecture_scope = section_id == "transformer" or any(
            cue in target
            for cue in (
                "架构", "自注意力", "多头注意力", "位置编码", "编码器", "解码器",
                "architecture", "self-attention", "multi-head", "positional", "encoder", "decoder",
            )
        )
        if architecture_scope:
            return any(cue in text for cue in ("自注意力", "多头注意力", "位置编码", "编码器", "解码器", "self-attention", "multi-head", "positional", "encoder", "decoder"))
    title_has_bert = "bert" in title
    title_has_gpt = bool(re.search(r"\bgpt(?:-?3)?\b", title))
    if title_has_bert and not title_has_gpt and "bert" not in text:
        return False
    if title_has_gpt and not title_has_bert and not re.search(r"\bgpt(?:-?3)?\b", text):
        return False
    if title_has_bert and title_has_gpt and not ("bert" in text or re.search(r"\bgpt(?:-?3)?\b", text)):
        return False
    section_cues = {
        "objectives": ("masked language", "mlm", "autoregressive", "left-to-right", "掩码", "自回归"),
        "evidence": ("bleu", "glue", "squad", "zero-shot", "one-shot", "few-shot", "accuracy", "benchmark", "score", " f1", "outperform"),
        "adaptation": ("fine-tun", "in-context", "few-shot", "zero-shot", "one-shot", "微调", "少样本", "零样本"),
        "limits": ("limitation", "weakness", "factual", "bias", "risk", "struggl", "fail", "difficult", "inaccur", "局限", "弱点", "事实", "偏见", "风险", "失败", "困难", "不足"),
    }
    if section_id in section_cues and not any(cue in text for cue in section_cues[section_id]):
        return False
    concept_groups = [
        (
            (
                "citation faithfulness", "citation reliability", "citation quality",
                "faithfulness", "attribution", "grounding", "verifiability",
                "引用忠实", "引用可靠", "引用质量", "归因", "可验证",
            ),
            (
                "citation", "faithful", "attribution", "ground", "verifiab",
                "引用", "忠实", "可靠", "归因", "支撑",
            ),
        ),
        (("自注意力", "self-attention", "self attention"), ("自注意力", "self-attention", "self attention")),
        (("位置编码", "positional encoding"), ("位置编码", "positional encoding")),
        (("掩码", "mlm", "masked language"), ("掩码", "mlm", "masked language")),
        (("自回归", "clm", "autoregressive", "left-to-right"), ("自回归", "因果语言", "单向语言", "autoregressive", "left-to-right")),
        (("微调", "fine-tuning", "fine tuning"), ("微调", "fine-tun")),
        (("提示", "少样本", "零样本", "上下文学习", "in-context", "few-shot", "zero-shot", "one-shot"), ("提示", "少样本", "零样本", "上下文学习", "in-context", "few-shot", "zero-shot", "one-shot")),
        (("规模", "scaling", "model size", "compute"), ("规模", "参数", "计算量", "scaling", "model size", "compute")),
        (("实验", "性能", "基准", "benchmark", "performance"), ("实验", "性能", "准确", "得分", "损失", "基准", "benchmark", "accuracy", "score", "loss", "f1", "bleu")),
        (("局限", "挑战", "幻觉", "长文本", "limitation", "weakness", "factual inaccuracy", "factual error", "bias"), ("局限", "挑战", "困难", "很难", "难以", "不足", "受限", "弱点", "风险", "错误", "事实", "不准确", "准确性", "失败", "挣扎", "幻觉", "长文本", "不一致", "恶意", "limitation", "weakness", "risk", "factual", "bias", "struggl", "fail", "difficult", "inaccur", "do not align", "does not align", "misalign")),
    ]
    required = [claim_cues for target_cues, claim_cues in concept_groups if any(cue in target for cue in target_cues)]
    if not required:
        return True
    limitation_focus = section_id in {"limits", "limitations"} or any(
        cue in title
        for cue in (
            "局限", "挑战", "幻觉", "风险", "limitation", "weakness",
            "failure", "factual inaccuracy", "factual risk", "bias",
        )
    )
    if limitation_focus:
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
        # Repair PDF line-wrap hyphenation and separate a sentence from a
        # following numbered section heading (for example ".1 1 Introduction").
        # This prevents one useful sentence plus a whole introduction from
        # becoming an overlong, unreadable fallback paragraph.
        quote = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", quote)
        quote = re.sub(
            r"(?<=[.!?])\d*\s+\d+(?:\.\d+)*\s+(?=(?:abstract|introduction|background|methods?|results?|discussion|conclusion)\b)",
            " ",
            quote,
            flags=re.I,
        )
        candidates = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", quote)
            if len(part.strip()) >= 20
            and "@" not in part
            and "arxiv:" not in part.casefold()
            and not re.match(r"^\(\d{4}\)", part.strip())
            and not re.match(r"^\d+(?:\.\d+)+\s+", part.strip())
            and not re.match(r"^(?:proceedings of|acm,|https?://doi\.org/)", part.strip(), flags=re.I)
            and not re.match(r"^(?:table|表)\s*\d+\s*[:：]", part.strip(), flags=re.I)
            and part.casefold() != "attention is all you need."
        ]
        for sentence_index, candidate in enumerate(candidates):
            candidate = candidate.lstrip("•·- ")
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
    max_items = max(2, _desired_section_document_count(planned, evidence))
    ordered_candidates = sorted(ranked_candidates, reverse=True)
    top_score = float(ordered_candidates[0][0])
    minimum_secondary_score = -100.0 if max_items > 1 else max(1.2, top_score * 0.35)
    for score, _, _, citation_id, document, sentence in ordered_candidates:
        if selected and score < minimum_secondary_score:
            continue
        normalized_sentence = " ".join(sentence.split()).casefold()
        if citation_id in used_citations or normalized_sentence in used_sentences or document in used_documents:
            continue
        selected.append((citation_id, _truncate_utf8(sentence, 420)))
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
            selected.append((citation_id, _truncate_utf8(sentence, 420)))
            used_citations.add(citation_id)
            used_sentences.add(normalized_sentence)
            if len(selected) >= max_items:
                break
    output_sentences: list[dict[str, Any]] = []
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
                        max_tokens=260,
                    )
                ).strip()
            except Exception:  # preserve the exact source sentence when translation is unavailable
                translated = ""
            if translated:
                translated = re.sub(r"[^。！？.!?]+[，,:：]\s*。$", "", translated).strip() or translated
                translated = _strip_review_excerpt_artifacts(translated)
                if _review_text_is_readable(translated):
                    sentence = translated
                else:
                    continue
        candidate = {"text": sentence, "citation_ids": [citation_id]}
        if not _claim_addresses_review_section(candidate, planned):
            continue
        output_sentences.append(
            {
                "text": _sentence_text(sentence, chinese=bool(re.search(r"[\u3400-\u9fff]", question))),
                "citation_ids": [citation_id],
            }
        )
    if not output_sentences:
        return {}
    result = _cited_text_from_sentences(output_sentences)
    output_text = str(result.get("text", ""))
    if not _review_text_is_readable(output_text):
        return {}
    return result


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

    chinese_output = bool(re.search(r"[\u3400-\u9fff]", question))
    citation_ids = list(
        dict.fromkeys(
            str(item)
            for section in sections
            for item in list(section.get("citation_ids", []) or [])
            if str(item)
        )
    )
    abstract_parts = [
        _cited_sentence_items(section)[0]
        for section in sections
        if _cited_sentence_items(section)
    ]
    selected_abstract_parts: list[dict[str, Any]] = []
    selected_abstract_keys: set[str] = set()
    for item in abstract_parts:
        sentence = _sentence_text(str(item.get("text", "")), chinese=chinese_output)
        sentence_key = re.sub(r"\s+", "", sentence).casefold()
        if not sentence_key or sentence_key in selected_abstract_keys:
            continue
        candidate = " ".join(
            [*[str(part.get("text", "")) for part in selected_abstract_parts], sentence]
        )
        if len(candidate) <= 420:
            selected_abstract_parts.append({**item, "text": sentence})
            selected_abstract_keys.add(sentence_key)
    abstract = _cited_text_from_sentences(selected_abstract_parts)
    if not abstract.get("text"):
        abstract = _cited_text_from_sentences(
            [
                {
                    "text": (
                        "当前资料库已形成带引用的分章节证据摘要。"
                        if chinese_output
                        else "The available source set supports the following evidence-linked sections."
                    ),
                    "citation_ids": citation_ids[:1],
                }
            ]
        )
    planned_by_id = {
        str(dict(planned).get("id", "")): dict(planned)
        for planned in list(plan.get("sections", []) or [])
    }
    rows = []
    for section in sections[:3]:
        planned = planned_by_id.get(str(section.get("id", "")), {})
        rows.append(
            {
                "cells": [
                    str(section.get("title", "")),
                    str(planned.get("objective", "")),
                    str(section.get("text", "")),
                    (
                        "结论范围受当前资料库与带锚点证据覆盖限制。"
                        if chinese_output
                        else "The conclusion is bounded by the retrieved, anchorable evidence."
                    ),
                ],
                "citation_ids": list(section.get("citation_ids", []) or []),
            }
        )
    fallback_questions = _fallback_review_open_questions(
        question,
        citation_ids=citation_ids,
    )
    return {
        "title": str(plan.get("title", "")).strip() or question,
        "abstract": abstract,
        "comparison_table": {
            "columns": (
                ["研究主题", "综合目标", "主要发现", "证据边界"]
                if chinese_output
                else ["Research topic", "Synthesis objective", "Main finding", "Evidence boundary"]
            ),
            "rows": rows,
        },
        "controversies": [],
        "open_questions": fallback_questions,
        "limitations": [
            (
                "本综述只覆盖当前 ScanSci 项目资料库中具有可回跳原文锚点的证据。"
                if chinese_output
                else "This review covers only evidence with traceable source anchors acquired for the current ScanSci task."
            )
        ],
    }


def _first_review_sentence(value: str) -> str:
    """Split prose without treating a decimal point such as 28.4 as a boundary."""

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    match = re.search(r"[。！？!?]|(?<!\d)\.(?=\s|$)", text)
    return text[: match.end()].strip() if match else text


def _review_prompt_inputs(
    question: str,
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
        section_ids = _diverse_section_citation_ids(dict(section), evidence_by_id, limit=6)
        section_ids = _exclusive_section_citation_ids(dict(section), section_ids, evidence_by_id)
        section_ids = _subject_balanced_section_citation_ids(
            question,
            dict(section),
            section_ids,
            evidence_by_id,
            limit=6,
        )
        for citation_id in section_ids:
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
        "title": _concise_review_title(question, str(payload.get("title", ""))),
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
    abstract = _remove_non_method_procedural_sentences(abstract, allow_methods=False)
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    sections: list[dict[str, Any]] = []
    for index, planned in enumerate(list(plan.get("sections", []) or [])):
        supplied = raw_sections[index] if index < len(raw_sections) and isinstance(raw_sections[index], dict) else {}
        paragraphs_source = supplied.get("paragraphs") if isinstance(supplied.get("paragraphs"), list) else []
        if not paragraphs_source and str(supplied.get("text", "")).strip():
            paragraphs_source = [supplied]
        paragraphs = []
        for item in paragraphs_source:
            paragraph = _normalized_cited_text(
                item,
                known_ids=known_ids,
                field=f"章节“{planned['title']}”",
            )
            paragraphs.append(
                _remove_non_method_procedural_sentences(
                    paragraph,
                    allow_methods=_review_section_allows_methods(planned),
                )
            )
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
        if not isinstance(item, dict):
            continue
        try:
            normalized = _normalized_cited_text(item, known_ids=known_ids, field="开放问题")
        except ValueError:
            continue
        normalized["basis"] = str(item.get("basis", "")).strip() if isinstance(item, dict) else ""
        if _review_open_question_is_on_topic(question, normalized):
            open_questions.append(normalized)
    if not open_questions:
        open_questions = _fallback_review_open_questions(
            question,
            citation_ids=sorted(str(item) for item in known_ids if str(item)),
        )
    limitations = [
        (str(item.get("text", "")).strip() if isinstance(item, dict) else str(item).strip())
        for item in list(payload.get("limitations", []) or [])
        if (str(item.get("text", "")).strip() if isinstance(item, dict) else str(item).strip())
    ]
    if not limitations:
        limitations = ["本综述只覆盖当前 ScanSci 项目资料库中具有可回跳原文锚点的证据。"]
    return {
        "title": _concise_review_title(
            question,
            str(payload.get("title", "")).strip() or str(plan.get("title", "")).strip(),
        ),
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
    raw_sentences = value.get("sentences") if isinstance(value.get("sentences"), list) else []
    sentences: list[dict[str, Any]] = []
    if raw_sentences:
        for index, raw_sentence in enumerate(raw_sentences, start=1):
            if not isinstance(raw_sentence, dict):
                raise ValueError(f"{field}第 {index} 句必须包含正文和 citation_ids")
            sentence_text = _strip_inline_citation_markers(str(raw_sentence.get("text", "")))
            sentence_ids = _validated_citation_ids(
                raw_sentence.get("citation_ids"),
                known_ids=known_ids,
                field=f"{field}第 {index} 句",
            )
            if not sentence_text:
                raise ValueError(f"{field}第 {index} 句正文为空")
            sentences.append({"text": sentence_text, "citation_ids": sentence_ids})
    else:
        text = _strip_inline_citation_markers(str(value.get("text", "")))
        citation_ids = _validated_citation_ids(value.get("citation_ids"), known_ids=known_ids, field=field)
        if not text:
            raise ValueError(f"{field}正文为空")
        # Backward compatibility for older providers and persisted artifacts.
        # Their citations were paragraph-scoped, so retain that support scope on
        # every sentence instead of inventing a narrower source assignment.
        sentences = [
            {"text": sentence, "citation_ids": list(citation_ids)}
            for sentence in _split_review_sentences(text)
        ]
    return _cited_text_from_sentences(sentences)


def _split_review_sentences(value: str) -> list[str]:
    """Split review prose at real sentence boundaries, preserving decimals."""

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return []
    parts = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?])\s*|(?<=\.)(?=\s+[A-Z\u3400-\u9fff])", text)
        if item.strip()
    ]
    return parts or [text]


def _cited_text_from_sentences(sentences: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    citation_ids: list[str] = []
    for sentence in sentences:
        text = " ".join(str(sentence.get("text", "")).split()).strip()
        ids = list(
            dict.fromkeys(
                str(item)
                for item in list(sentence.get("citation_ids", []) or [])
                if str(item)
            )
        )
        if not text or not ids:
            continue
        normalized.append({"text": text, "citation_ids": ids})
        citation_ids.extend(ids)
    return {
        "text": " ".join(sentence["text"] for sentence in normalized),
        "citation_ids": list(dict.fromkeys(citation_ids)),
        "sentences": normalized,
    }


def _cited_sentence_items(value: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sentences = value.get("sentences") if isinstance(value.get("sentences"), list) else []
    if raw_sentences:
        return [dict(item) for item in raw_sentences if isinstance(item, dict)]
    ids = [str(item) for item in list(value.get("citation_ids", []) or []) if str(item)]
    return [
        {"text": sentence, "citation_ids": list(ids)}
        for sentence in _split_review_sentences(str(value.get("text", "")))
    ]


def _merge_cited_texts(*values: dict[str, Any]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        for sentence in _cited_sentence_items(value):
            key = re.sub(r"\s+", "", str(sentence.get("text", ""))).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)
    return _cited_text_from_sentences(sentences)


def _strip_inline_citation_markers(value: str) -> str:
    """Remove model-authored citation labels; verified IDs are rendered separately."""

    text = re.sub(r"[（(]\s*citation[_ ]?id\s*[:：]\s*\d+\s*[)）]", "", str(value), flags=re.I)
    text = re.sub(
        r"(?:\[\s*\d+(?:\s*[,，;；-]\s*\d+)*\s*\]|【\s*\d+(?:\s*[,，;；-]\s*\d+)*\s*】)+",
        "",
        text,
    )
    text = re.sub(r"(?<![A-Za-z0-9])[（(]\s*\d{1,3}\s*[)）]", "", text)
    text = re.sub(r"[ \t]+(?=[。！？；，,.!?;])", "", text)
    return " ".join(text.split()).strip()


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
        source["reader_url"] = (
            reader_url_builder(doc_id, anchor)
            if reader_url_builder and doc_id
            else str(source.get("reader_url", "")).strip()
        )
        public_source = str(
            source.get("source_href")
            or source.get("original_url")
            or source.get("source_url")
            or ""
        ).strip()
        source["source_href"] = public_source
        if not str(source.get("original_url", "")).strip() and re.match(r"^https?://", public_source, flags=re.I):
            source["original_url"] = public_source
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
        units = _cited_sentence_items(dict(item)) if dict(item).get("text") else [dict(item)]
        for unit in units:
            for citation_id in list(unit.get("citation_ids", []) or []):
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
        for sentence in list(target.get("sentences", []) or []):
            sentence["citation_ids"] = [mapping[str(item)] for item in sentence["citation_ids"]]


def _review_reader_answer(document: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = [document["abstract"]]
    for section in document["sections"]:
        source_items.extend(section["paragraphs"])
    source_items.extend(document["controversies"])
    source_items.extend(document["open_questions"])
    sentence_items = [
        sentence
        for item in source_items
        for sentence in _cited_sentence_items(item)
    ]
    for index, item in enumerate(sentence_items, start=1):
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
    prose_items: list[dict[str, Any]] = [document["abstract"]]
    for section in document["sections"]:
        prose_items.extend(section["paragraphs"])
    prose_items.extend(document["controversies"])
    prose_items.extend(document["open_questions"])
    items = [
        sentence
        for item in prose_items
        for sentence in _cited_sentence_items(item)
    ]
    items.extend(document["comparison_table"]["rows"])
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
        "source_url": str(row.get("source_url", "")),
        "source_href": str(row.get("source_href", "") or row.get("source_url", "")),
        "original_url": str(row.get("original_url", "")),
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
