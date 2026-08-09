from __future__ import annotations

import json
from pathlib import Path

import pytest

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.llm import managed_gateway_session
from scansci_html.literature_review import (
    _atomic_review_claims,
    _balanced_review_queries,
    _claim_addresses_review_section,
    _concise_review_title,
    _direct_evidence_section,
    _deterministic_review_overview,
    _deterministic_grounded_review_section,
    _diverse_section_citation_ids,
    _exclusive_section_citation_ids,
    _has_unrequested_model_detour,
    _required_review_subjects,
    _review_subject_coverage_complete,
    _review_query_variant_budget,
    _review_text_is_readable,
    _strip_unrequested_model_detours,
    _semantic_cues_are_grounded,
    _subject_balanced_section_citation_ids,
    _strip_inline_citation_markers,
    _synthesize_review_in_parts,
    _verify_review_document,
    plan_literature_review,
    retrieve_review_evidence,
    synthesize_literature_review,
)
from scansci_html.research_agent import ResearchAgentRuntime


class FakeReviewClient:
    def __init__(self, *, bad_citation: bool = False) -> None:
        self.bad_citation = bad_citation

    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str):
        if schema_name == "literature_review_plan":
            return {
                "title": "免疫治疗证据综述",
                "scope": "比较机制、疗效和转化边界。",
                "sections": [
                    {"id": "mechanism", "title": "作用机制", "objective": "比较免疫调节机制", "queries": ["免疫治疗 作用机制"]},
                    {"id": "outcomes", "title": "疗效证据", "objective": "比较主要疗效", "queries": ["免疫治疗 疗效"]},
                    {"id": "translation", "title": "转化边界", "objective": "识别局限和转化条件", "queries": ["免疫治疗 转化 局限"]},
                ],
            }
        if schema_name == "literature_review_section":
            payload = json.loads(messages[1]["content"])
            citation = "99" if self.bad_citation else payload["evidence"][0]["citation_id"]
            return {
                "text": "当前证据显示，不同研究从作用机制、疗效指标、局限与转化条件三个层面描述干预结果；这些结论需要结合具体研究对象、方法设计和证据边界进行比较。",
                "citation_ids": [citation],
            }
        if schema_name == "answer_claims":
            payload = json.loads(messages[1]["content"])
            quote_id = "99" if self.bad_citation else payload["evidence_table"][0]["quote_id"]
            return {
                "answer": [
                    {"claim_id": "c0001", "text": payload["question"], "quote_ids": [quote_id]}
                ],
                "limitations": [],
            }
        if schema_name == "claim_verification":
            payload = json.loads(messages[1]["content"])
            return {
                "claims": [
                    {"claim_id": item["claim_id"], "support_status": "supported", "verification_score": 0.95}
                    for item in payload["answer"]["claims"]
                ]
            }
        raise AssertionError(schema_name)

    def complete_text(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        if "综述主编" in messages[0]["content"]:
            return "现有证据从机制、疗效与转化边界三个方面刻画了免疫治疗，但研究对象和设计差异限制了直接外推。"
        payload = json.loads(messages[1]["content"])
        return (
            f"围绕{payload['section']['title']}，当前证据显示不同研究的对象、方法和结论需要结合证据边界综合解释；"
            "资料覆盖局限意味着不得将研究条件不同的发现直接合并成统一结论，也不能把资料库之外的推断写成已有证据。"
        )


def test_review_query_expansion_is_conditional():
    assert _review_query_variant_budget(
        "What is the reported sample size?",
        {"title": "Sample", "objective": "Report the sample size"},
        "study sample size",
    ) == 1
    assert _review_query_variant_budget(
        "比较两种 RAG 方法",
        {"title": "机制差异", "objective": "比较检索和重排机制"},
        "RAG retrieval reranking comparison",
    ) == 2


def test_review_retrieval_scopes_every_query_and_preserves_writing_brief(monkeypatch, tmp_path: Path):
    calls: list[dict[str, object]] = []

    def fake_answer(_db_path, query, **kwargs):
        calls.append({"query": query, **kwargs})
        index = len(calls)
        return {
            "evidence_table": [
                {
                    "evidence_id": f"paper-a.s{index}",
                    "exact_quote": f"Grounded evidence {index}.",
                    "doc_id": "paper-a" if index % 2 else "paper-b",
                    "paper": "Paper A" if index % 2 else "Paper B",
                    "section": "Results",
                }
            ],
            "adequacy": {"document_count": 1},
            "retrieval_queries": [query],
        }

    monkeypatch.setattr("scansci_html.literature_review.answer_question", fake_answer)
    result = retrieve_review_evidence(
        tmp_path / "evidence.sqlite",
        "免疫治疗有哪些证据？",
        chat_client=FakeReviewClient(),
        source_doc_ids=["paper-a", "paper-b", "paper-a"],
        writing_brief={"audience": "general", "tone": "teaching", "length": "long", "focus": "机制差异"},
    )

    assert calls
    assert all(call["filters"] == {"doc_ids": ["paper-a", "paper-b"]} for call in calls)
    assert result["source_scope"] == {
        "mode": "selected",
        "doc_ids": ["paper-a", "paper-b"],
        "document_count": 2,
    }
    assert result["writing_brief"] == {
        "audience": "general",
        "tone": "teaching",
        "length": "long",
        "focus": "机制差异",
    }


def test_review_title_is_content_focused_instead_of_replaying_the_instruction():
    question = (
        "请基于当前三篇论文撰写中文综述：比较原始 Transformer、BERT 与 GPT-3。"
        "必须分别讨论架构、训练、实验评价与能力边界，每个段落都要引用证据。"
    )

    assert _concise_review_title(question, f"{question}：证据综述") == (
        "Transformer、BERT 与 GPT-3：架构、训练与能力边界"
    )
    assert _concise_review_title("免疫治疗有哪些证据？", "免疫治疗证据综述") == "免疫治疗证据综述"
    assert ResearchAgentRuntime._run_title("literature_review", {"question": question}) == (
        "Transformer、BERT 与 GPT-3：架构、训练与能力边界"
    )


def _research_payload() -> dict[str, object]:
    plan = plan_literature_review("免疫治疗有哪些证据？", chat_client=FakeReviewClient())
    for section, citation_ids in zip(plan["sections"], (["2", "4"], ["4"], ["1", "2"])):
        section["citation_ids"] = citation_ids
    evidence = [
        {
            "citation_id": str(index),
            "quote_id": f"q{index}",
            "paper": "研究 A" if index <= 2 else "研究 B",
            "doc_id": "paper-a" if index <= 2 else "paper-b",
            "section": "Results",
            "doi": f"10.1000/{index}",
            "evidence_id": f"paper-{index}.s1",
            "exact_quote": f"Exact evidence sentence {index}.",
            "html_path": f"paper-{index}.html",
            "html_anchor": f"evidence-{index}",
        }
        for index in range(1, 5)
    ]
    return {
        "phase": "retrieval",
        "question": "免疫治疗有哪些证据？",
        "review_plan": plan,
        "evidence": evidence,
        "section_results": [],
        "retrieval_summary": {"section_count": 3, "document_count": 2, "evidence_count": 4},
    }


def test_synthesis_builds_real_review_structure_and_compacts_citations():
    result = synthesize_literature_review(
        _research_payload(),
        chat_client=FakeReviewClient(),
        reader_url_builder=lambda doc_id, anchor: f"/reader/{doc_id}#{anchor}",
    )

    document = result["review_document"]
    assert [section["title"] for section in document["sections"]] == ["作用机制", "疗效证据", "转化边界"]
    assert len(document["comparison_table"]["rows"]) == 3
    assert document["open_questions"][0]["basis"]
    assert [item["citation_id"] for item in document["references"]] == ["1", "2", "3"]
    assert document["references"][0]["reader_url"].startswith("/reader/")
    assert result["citation_verification"]["passed"] is True
    assert result["adequacy"]["document_count"] == 2
    assert result["adequacy"]["is_sufficient"] is (
        result["adequacy"]["quote_count"] >= 3 and result["adequacy"]["document_count"] >= 2
    )


def test_long_evidence_review_preserves_the_sentence_level_citation_contract():
    research = _research_payload()
    research["writing_brief"] = {"audience": "researcher", "tone": "academic", "length": "long"}

    result = synthesize_literature_review(research, chat_client=FakeReviewClient())

    assert result["writing_brief"]["length"] == "long"
    assert result["citation_verification"]["passed"] is True
    assert all(
        sentence["citation_ids"]
        for section in result["review_document"]["sections"]
        for paragraph in section["paragraphs"]
        for sentence in paragraph["sentences"]
    )


def test_evidence_review_is_scoped_to_the_local_knowledge_corpus():
    """A NotebookLM-like evidence review must never silently add web evidence."""
    assert ResearchAgentRuntime._workflow_task_mode("literature_review", {}) == "knowledge"


def test_synthesis_preserves_external_source_links_without_a_local_reader():
    research = _research_payload()
    research["phase"] = "external_abstracts"
    for index, row in enumerate(research["evidence"], start=1):
        row["doc_id"] = f"external:run-1:{index}"
        row["original_url"] = f"https://doi.org/10.1000/{index}"

    result = synthesize_literature_review(
        research,
        chat_client=FakeReviewClient(),
        reader_url_builder=None,
    )

    reference = result["review_document"]["references"][0]
    assert reference["reader_url"] == ""
    assert reference["original_url"].startswith("https://doi.org/10.1000/")


def test_synthesis_preserves_sentence_level_citation_placement():
    class SentenceCitationClient(FakeReviewClient):
        def complete_json(self, messages, *, schema_name):
            if schema_name == "literature_review_section":
                payload = json.loads(messages[1]["content"])
                citations = [item["citation_id"] for item in payload["evidence"]]
                return {
                    "sentences": [
                        {
                            "text": "当前证据描述了这一主题的研究对象、干预方法与具体评价设计，并保留了研究条件差异。",
                            "citation_ids": [citations[0]],
                        },
                        {
                            "text": "另一项证据界定了相应结论的适用范围、转化条件与外推边界，不能直接合并为统一结论。",
                            "citation_ids": [citations[-1]],
                        },
                    ]
                }
            return super().complete_json(messages, schema_name=schema_name)

    result = synthesize_literature_review(_research_payload(), chat_client=SentenceCitationClient())

    paragraph = result["review_document"]["sections"][0]["paragraphs"][0]
    assert len(paragraph["sentences"]) == 2
    assert all(len(sentence["citation_ids"]) == 1 for sentence in paragraph["sentences"])
    assert paragraph["sentences"][0]["citation_ids"] != paragraph["sentences"][1]["citation_ids"]
    assert [sentence["text"] for sentence in result["reader_answer"]["sentences"][:2]] == [
        sentence["text"] for sentence in result["review_document"]["abstract"]["sentences"][:2]
    ]


def test_synthesis_discards_hallucinated_citation_ids_before_safe_fallback():
    result = synthesize_literature_review(_research_payload(), chat_client=FakeReviewClient(bad_citation=True))

    used = {
        citation_id
        for section in result["review_document"]["sections"]
        for paragraph in section["paragraphs"]
        for citation_id in paragraph["citation_ids"]
    }
    assert "99" not in used
    assert used <= {"1", "2", "3", "4"}


def test_synthesis_falls_back_to_bounded_section_calls_when_nested_json_is_invalid():
    calls = []

    class SplitReviewClient:
        def complete_json(self, messages, *, schema_name):
            calls.append(schema_name)
            if schema_name == "evidence_grounded_literature_review":
                raise ValueError("invalid nested JSON")
            if schema_name == "answer_claims":
                payload = json.loads(messages[1]["content"])
                quote_id = payload["evidence_table"][0]["quote_id"]
                return {
                    "answer": [{"claim_id": "c0001", "text": payload["question"], "quote_ids": [quote_id]}],
                    "limitations": [],
                }
            if schema_name == "literature_review_section":
                payload = json.loads(messages[1]["content"])
                citation_ids = [item["citation_id"] for item in payload["evidence"]]
                return {
                    "text": f"围绕{payload['section']['title']}，当前资料提供了作用机制、疗效指标、局限与转化条件方面的可回跳原文证据；综合时需要保留研究对象、方法设计和适用边界，避免把不同研究条件下的结论直接等同。",
                    "citation_ids": citation_ids[:1],
                }
            if schema_name == "literature_review_overview":
                return {
                    "title": "分段生成的证据综述",
                    "abstract": {"text": "三个章节共同刻画了当前证据边界。", "citation_ids": ["1"]},
                    "comparison_table": {
                        "columns": ["对象", "方法", "发现", "局限"],
                        "rows": [{"cells": ["研究", "综合", "有差异", "资料有限"], "citation_ids": ["1"]}],
                    },
                    "controversies": [],
                    "open_questions": [{"text": "如何外推？", "basis": "对象不同", "citation_ids": ["1"]}],
                    "limitations": ["仅覆盖当前资料库。"],
                }
            if schema_name == "claim_verification":
                payload = json.loads(messages[1]["content"])
                return {
                    "claims": [
                        {"claim_id": item["claim_id"], "support_status": "supported", "verification_score": 0.95}
                        for item in payload["answer"]["claims"]
                    ]
                }
            raise AssertionError(schema_name)

    result = synthesize_literature_review(_research_payload(), chat_client=SplitReviewClient())

    assert len(result["review_document"]["sections"]) == 3
    assert calls.count("literature_review_section") >= 3
    assert set(calls) == {"literature_review_section"}
    assert result["citation_verification"]["passed"] is True


def test_synthesis_compacts_large_evidence_before_calling_the_writer():
    captured = {}

    class CapturingClient(FakeReviewClient):
        def complete_json(self, messages, *, schema_name):
            if schema_name == "literature_review_section" and "body" not in captured:
                captured["body"] = messages[1]["content"]
            return super().complete_json(messages, schema_name=schema_name)

    research = _research_payload()
    research["writing_brief"] = {
        "audience": "general",
        "tone": "teaching",
        "length": "long",
        "focus": "解释机制差异",
    }
    for row in research["evidence"]:
        row["exact_quote"] = "Very long exact evidence. " * 2000
        row["context_text"] = "Private parent context. " * 5000
        row["html_path"] = "D:/private/library/paper.html"

    synthesize_literature_review(research, chat_client=CapturingClient())

    body = captured["body"]
    parsed = json.loads(body)
    assert len(body.encode("utf-8")) < 32_000
    assert "Private parent context" not in body
    assert "private/library" not in body
    assert parsed["writing_brief"] == research["writing_brief"]
    assert all(len(item["exact_quote"].encode("utf-8")) <= 903 for item in parsed["evidence"])


def test_default_local_evidence_role_cannot_pretend_to_be_review_writer(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["model_roles"]["writing"] = "provider:local-evidence:evidence-retrieval"
    settings["active_model"] = {"provider_id": "local-evidence", "model_id": "evidence-retrieval"}
    save_settings(workspace, settings)
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    with pytest.raises(ValueError, match="真正的文献综述需要生成模型"):
        runtime._writing_chat_client()


def test_managed_writing_client_disables_hidden_reasoning_for_bounded_workflows(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    client = runtime._writing_chat_client()

    assert client.thinking_mode == "disabled"
    assert client.session is managed_gateway_session()
    assert runtime._writing_chat_client() is client


def test_review_planning_keeps_an_evidence_plan_when_gateway_is_rate_limited():
    class RateLimitedClient:
        def complete_json(self, messages, *, schema_name):
            raise RuntimeError("HTTP 429")

    plan = plan_literature_review(
        "比较 Transformer、BERT 与 GPT-3 的训练和适配",
        chat_client=RateLimitedClient(),
    )

    assert len(plan["sections"]) == 5
    assert plan["planning"]["mode"] == "deterministic-evidence-plan"
    assert all(section["queries"] for section in plan["sections"])
    assert plan["sections"][0]["title"] == "原始 Transformer 架构"
    assert "self-attention" in plan["sections"][0]["queries"][0]
    assert "GPT-3" in plan["sections"][2]["queries"][1]
    assert _required_review_subjects(
        "比较原始 Transformer、BERT 与 GPT-3。",
        plan["sections"][2],
    ) == ["原始 Transformer", "BERT", "GPT-3"]
    assert _required_review_subjects(
        "比较原始 Transformer、BERT 与 GPT-3。",
        plan["sections"][3],
    ) == ["原始 Transformer", "BERT", "GPT-3"]


def test_explicit_three_paper_contract_does_not_accept_a_model_rewritten_outline():
    class RewritingClient:
        def complete_json(self, messages, *, schema_name):
            raise AssertionError("the explicit five-part comparison should not be replanned")

    plan = plan_literature_review(
        "请写综述并比较原始 Transformer、BERT 与 GPT-3。",
        chat_client=RewritingClient(),
    )

    assert [section["id"] for section in plan["sections"]] == [
        "transformer",
        "objectives",
        "evidence",
        "adaptation",
        "limits",
    ]


def test_review_section_evidence_is_diverse_before_filling_remaining_slots():
    evidence = {
        "1": {"doc_id": "paper-a"},
        "2": {"doc_id": "paper-a"},
        "3": {"doc_id": "paper-b"},
        "4": {"doc_id": "paper-c"},
    }

    selected = _diverse_section_citation_ids({"citation_ids": ["1", "2", "3", "4"]}, evidence, limit=4)

    assert selected == ["1", "3", "4", "2"]


def test_three_way_evaluation_uses_subject_balanced_queries_and_evidence():
    question = "比较原始 Transformer、BERT 与 GPT-3。"
    planned = {
        "title": "三者的实验评价与适配方式",
        "objective": "比较三种模型的实验基准与下游适配。",
        "queries": ["too broad"],
    }
    evidence = {
        "1": {"paper": "1706.03762", "exact_quote": "The Transformer achieved 28.4 BLEU on WMT."},
        "2": {"paper": "1810.04805", "exact_quote": "BERT is fine-tuned on GLUE tasks."},
        "3": {"paper": "2005.14165", "exact_quote": "GPT-3 is evaluated in zero-shot and few-shot settings."},
        "4": {"paper": "2005.14165", "exact_quote": "GPT-3 unrelated appendix material."},
    }

    queries = _balanced_review_queries(question, planned)
    selected = _subject_balanced_section_citation_ids(
        question,
        planned,
        ["4"],
        evidence,
        limit=4,
    )

    assert "WMT BLEU" in queries[0]
    assert "BERT GLUE" in queries[1]
    assert selected[:3] == ["1", "2", "3"]


def test_pretraining_objective_retrieval_separates_bert_from_gpt3():
    queries = _balanced_review_queries(
        "比较原始 Transformer、BERT 与 GPT-3。",
        {
            "title": "预训练目标的演变",
            "objective": "对比 BERT 的掩码语言模型与 GPT-3 的自回归训练目标。",
            "queries": ["too broad"],
        },
    )

    assert len(queries) == 2
    assert "BERT masked language model" in queries[0]
    assert queries[1] == "autoregressive language model 175 billion"


def test_review_overview_keeps_decimals_and_deduplicates_repeated_openers():
    overview = _deterministic_review_overview(
        "比较模型。",
        {"sections": [{"objective": "a"}, {"objective": "b"}, {"objective": "c"}]},
        [
            {"title": "A", "text": "模型报告 28.4 BLEU；这是实验结果。", "citation_ids": ["1"]},
            {"title": "B", "text": "模型报告 28.4 BLEU；这是实验结果。", "citation_ids": ["1"]},
            {"title": "C", "text": "GPT-3 使用上下文示例。", "citation_ids": ["2"]},
        ],
    )

    abstract = overview["abstract"]["text"]
    assert "28.4 BLEU" in abstract
    assert abstract.count("模型报告 28.4 BLEU") == 1
    assert "GPT-3 使用上下文示例" in abstract


def test_three_way_deterministic_fallback_stays_grounded_and_readable():
    question = "比较原始 Transformer、BERT 与 GPT-3。"
    planned = {
        "title": "三者的实验评价与适配方式",
        "objective": "比较三种模型的实验评价、微调与下游适配。",
    }
    evidence = [
        {
            "citation_id": "1",
            "evidence_id": "doc-1.s1",
            "paper": "1706.03762",
            "exact_quote": "On the WMT 2014 task, the Transformer achieves 28.4 BLEU.",
        },
        {
            "citation_id": "2",
            "evidence_id": "doc-2.s1",
            "paper": "1810.04805",
            "exact_quote": "BERT chooses a task-specific fine-tuning learning rate on the development set.",
        },
        {
            "citation_id": "3",
            "evidence_id": "doc-3.s1",
            "paper": "2005.14165",
            "exact_quote": "GPT-3 Zero-shot, One-shot, and Few-shot results are reported for all tasks.",
        },
    ]

    result = _deterministic_grounded_review_section(question, planned, evidence)

    # The deterministic fallback now uses actual evidence quotes instead of
    # pre-written Chinese templates.  Each evidence row should produce one
    # grounded sentence with its own citation.
    assert result["citation_ids"] == ["1", "2", "3"]
    assert [sentence["citation_ids"] for sentence in result["sentences"]] == [["1"], ["2"], ["3"]]
    assert "28.4" in result["text"]
    assert "Transformer" in result["text"]
    assert "BERT" in result["text"]
    assert "GPT-3" in result["text"]
    assert _review_text_is_readable(result["text"])


def test_single_model_section_filters_out_other_papers_before_writing():
    evidence = {
        "1": {"exact_quote": "BERT uses masked language modeling."},
        "2": {"exact_quote": "OpenAI GPT is a left-to-right Transformer language model."},
        "3": {"exact_quote": "GPT-3 is evaluated in the few-shot setting."},
    }

    selected = _exclusive_section_citation_ids(
        {"title": "GPT-3 的自回归训练与上下文学习"},
        ["1", "2", "3"],
        evidence,
    )

    assert selected == ["3"]


def test_review_claims_are_split_before_semantic_verification():
    claims = _atomic_review_claims(
        [{"claim_id": "c1", "text": "第一项有依据。第二项需要单独核验。", "quote_ids": ["1"]}]
    )

    assert [item["claim_id"] for item in claims] == ["c1-s1", "c1-s2"]


def test_review_semantic_cue_gate_rejects_unsupported_superiority():
    claim = {"text": "该模型的生成文本长度超越人类。", "quote_ids": ["1"]}

    assert _semantic_cues_are_grounded(claim, {"1": "Human and model articles both averaged 216 words."}) is False


def test_review_semantic_gate_rejects_conflating_openai_gpt_with_gpt3_fine_tuning():
    claim = {"text": "GPT-3 同样采用微调方法。", "quote_ids": ["1", "2"]}
    quotes = {
        "1": "BERT and OpenAI GPT are fine-tuning approaches.",
        "2": "GPT-3 is an autoregressive language model evaluated without gradient updates.",
    }

    assert _semantic_cues_are_grounded(claim, quotes) is False


def test_review_semantic_gate_requires_the_subject_of_human_detection_accuracy():
    quotes = {
        "1": "Human accuracy in identifying whether news articles are model generated decreased to 52%.",
    }

    assert _semantic_cues_are_grounded(
        {"text": "生成文本的准确率随模型规模增大而下降。", "quote_ids": ["1"]},
        quotes,
    ) is False
    assert _semantic_cues_are_grounded(
        {"text": "人类识别机器生成文本的准确率随模型规模增大而下降。", "quote_ids": ["1"]},
        quotes,
    ) is True


def test_review_semantic_gate_rejects_reversing_human_detection_result():
    quotes = {
        "1": "Human accuracy in identifying whether GPT-3 news articles are model generated was 52%, near chance.",
    }

    assert _semantic_cues_are_grounded(
        {"text": "GPT-3 的生成文本仍容易被察觉。", "quote_ids": ["1"]},
        quotes,
    ) is False
    assert _semantic_cues_are_grounded(
        {"text": "GPT-3 的生成文本让人类难以区分。", "quote_ids": ["1"]},
        quotes,
    ) is True


def test_review_semantic_gate_requires_direct_support_for_bert_generation_limit():
    assert _semantic_cues_are_grounded(
        {"text": "BERT 的生成能力受限。", "quote_ids": ["1"]},
        {"1": "BERT uses bidirectional self-attention for language understanding."},
    ) is False


def test_review_claim_must_answer_the_planned_section_not_merely_have_a_citation():
    planned = {
        "title": "预训练目标的演变",
        "objective": "对比 BERT 的掩码语言模型与 GPT 的自回归训练目标。",
    }

    assert _claim_addresses_review_section({"text": "两者每参数每 token 的 FLOPs 都是 6。"}, planned) is False
    assert _claim_addresses_review_section({"text": "BERT 使用掩码语言模型，GPT 使用自回归目标。"}, planned) is True


def test_original_transformer_section_rejects_a_bert_subject_claim():
    planned = {
        "title": "原始 Transformer 架构",
        "objective": "解释原始 Transformer 的自注意力和位置编码。",
    }

    assert _claim_addresses_review_section({"text": "BERT 的模型架构基于 Transformer。"}, planned) is False


def test_model_specific_section_rejects_a_different_paper_subject():
    planned = {
        "title": "GPT-3 的单向解码与大规模预训练范式",
        "objective": "解释 GPT-3 的自回归训练与规模化设置。",
    }

    assert _claim_addresses_review_section(
        {"text": "Transformer 是完全依赖自注意力的序列转换模型。"},
        planned,
    ) is False
    assert _claim_addresses_review_section(
        {"text": "GPT-3 是一个自回归语言模型。"},
        planned,
    ) is True


def test_direct_review_fallback_scores_relevant_sentences_across_sources():
    planned = {
        "title": "原始 Transformer 架构",
        "objective": "解释原始 Transformer 的 self-attention、多头注意力和编码器—解码器结构。",
    }
    evidence = [
        {
            "citation_id": "1",
            "exact_quote": "BERT uses a masked language model and bidirectional attention. " * 8,
        },
        {
            "citation_id": "2",
            "exact_quote": (
                "The Transformer follows an encoder-decoder architecture. "
                "The encoder and decoder use stacked self-attention and position-wise feed-forward layers."
            ),
        },
    ]

    section = _direct_evidence_section(
        "原始 Transformer 使用什么架构？",
        planned,
        evidence,
        text_completion=None,
    )

    assert section["citation_ids"] == ["2"]
    assert "encoder and decoder" in section["text"]
    assert "BERT" not in section["text"]


def test_three_model_architecture_section_keeps_three_source_documents():
    planned = {
        "id": "architecture",
        "title": "基础架构与并行路线的构建差异",
        "objective": "比较 Transformer 的核心组件如何被 BERT 和 GPT-3 继承与改造。",
    }
    evidence = [
        {
            "citation_id": "1",
            "doc_id": "transformer",
            "exact_quote": "The Transformer follows an encoder-decoder architecture using stacked self-attention layers.",
        },
        {
            "citation_id": "2",
            "doc_id": "bert",
            "exact_quote": "BERT uses a multi-layer bidirectional Transformer encoder with bidirectional self-attention.",
        },
        {
            "citation_id": "3",
            "doc_id": "gpt3",
            "exact_quote": "GPT-3 is an autoregressive language model trained with a left-to-right objective.",
        },
    ]

    section = _direct_evidence_section(
        "比较 Transformer、BERT 与 GPT-3 的架构路线。",
        planned,
        evidence,
        text_completion=None,
    )

    assert set(section["citation_ids"]) == {"1", "2", "3"}


def test_three_model_comparison_requires_every_named_subject():
    question = "比较原始 Transformer、BERT 与 GPT-3。"
    planned = {
        "title": "三者的实验评价与适配方式",
        "objective": "对比原始 Transformer、BERT 和 GPT-3 的实验评价与适配方式。",
    }

    assert _required_review_subjects(question, planned) == ["原始 Transformer", "BERT", "GPT-3"]
    assert _review_subject_coverage_complete(
        question,
        planned,
        "原始 Transformer 以任务训练评估，BERT 采用微调，GPT-3 采用上下文学习。",
    ) is True
    assert _review_subject_coverage_complete(
        question,
        planned,
        "原始 Transformer 以任务训练评估，BERT 采用微调。",
    ) is False


def test_review_readability_gate_rejects_corruption_and_runaway_repetition():
    assert _review_text_is_readable("BERT 使用掩码语言模型进行双向预训练，并通过微调适配下游任务。") is True
    assert _review_text_is_readable("GPT-3 G G G G G G G G G G") is False
    assert _review_text_is_readable("模型表现也也也也也也更强。") is False
    assert _review_text_is_readable("开发集集数据上上 上出现异常。") is False
    assert _review_text_is_readable(r"权重 \\ \\ \\times H 在微调中引入。") is False
    assert _review_text_is_readable("参数量从 1B �长到 10B。") is False


def test_three_model_comparison_rejects_side_model_substitution():
    question = "比较原始 Transformer、BERT 与 GPT-3。"
    planned = {
        "title": "三者的实验评价与适配方式",
        "objective": "对比原始 Transformer、BERT 和 GPT-3。",
    }

    assert _has_unrequested_model_detour(
        question,
        planned,
        "原始 Transformer、BERT、GPT-3 与 T5-Small 的训练计算不同。",
    ) is True
    assert _has_unrequested_model_detour(
        question,
        planned,
        "原始 Transformer、BERT 与 GPT-3 采用不同适配方式。",
    ) is False
    assert _strip_unrequested_model_detours(
        question,
        planned,
        "原始 Transformer 采用任务训练。BERT 与 GPT-3 采用不同适配方式。T5-Small 的计算量不同。",
    ) == "原始 Transformer 采用任务训练。 BERT 与 GPT-3 采用不同适配方式。"


def test_generic_three_model_limit_heading_requires_supported_modern_boundaries_only():
    assert _required_review_subjects(
        "比较原始 Transformer、BERT 与 GPT-3。",
        {
            "title": "能力边界与局限",
            "objective": "总结并比较三种模型的能力边界与局限。",
        },
    ) == ["BERT", "GPT-3"]


def test_review_limitation_section_accepts_direct_failure_evidence():
    planned = {
        "id": "limits",
        "title": "能力边界与局限性",
        "objective": "总结 GPT-3 的 few-shot weaknesses and limitations。",
    }

    assert _claim_addresses_review_section(
        {"text": "Few-shot performance struggles on ANLI and reading comprehension tasks."},
        planned,
    ) is True


def test_cited_evidence_gap_placeholder_fails_review_verification():
    cited = {"text": "当前带锚点证据不足以支持本节目标，因此不据此作扩展推断。", "citation_ids": ["1"]}
    document = {
        "abstract": cited,
        "sections": [],
        "comparison_table": {"rows": []},
        "controversies": [],
        "open_questions": [],
    }
    references = [{"citation_id": "1", "html_path": "paper.md", "html_anchor": "s1", "exact_quote": "Evidence."}]

    result = _verify_review_document(document, references)

    assert result["passed"] is False
    assert result["unsupported_cited_claim_ids"] == ["review-0001"]


def test_model_authored_inline_citation_labels_are_removed_before_remapping():
    text = "BERT (14) 使用掩码语言模型【20】，并在下游任务微调 [15]（citation_id: 7）。"

    assert _strip_inline_citation_markers(text) == "BERT 使用掩码语言模型，并在下游任务微调。"


def test_chinese_review_never_succeeds_with_english_excerpt_fallback():
    class UnavailableWritingClient:
        def complete_json(self, messages, *, schema_name):
            raise RuntimeError("gateway unavailable")

        def complete_text(self, messages, *, max_tokens=700):
            raise RuntimeError("gateway unavailable")

    evidence = [
        {
            "citation_id": str(index),
            "quote_id": f"q{index}",
            "paper": "Attention Is All You Need",
            "doc_id": f"transformer-{index}",
            "section": "Conclusion",
            "evidence_id": f"transformer-{index}.s1",
            "exact_quote": (
                "The Transformer is a sequence transduction model based entirely on attention, "
                "replacing recurrent layers with multi-headed self-attention."
            ),
            "html_path": f"transformer-{index}.md",
            "html_anchor": "s1",
        }
        for index in range(1, 4)
    ]
    research = {
        "phase": "retrieval",
        "question": "原始 Transformer 使用什么架构？",
        "review_plan": {
            "title": "Transformer 架构综述",
            "scope": "原始论文",
            "sections": [
                {
                    "id": "transformer",
                    "title": "原始 Transformer 架构",
                    "objective": "解释原始 Transformer 的 self-attention 与编码器—解码器结构。",
                    "queries": ["Transformer architecture"],
                    "citation_ids": ["1", "2", "3"],
                }
            ],
        },
        "evidence": evidence,
        "section_results": [],
        "retrieval_summary": {"section_count": 1, "document_count": 3, "evidence_count": 3},
    }

    with pytest.raises(ValueError, match="不会把英文摘录伪装成中文综述"):
        synthesize_literature_review(research, chat_client=UnavailableWritingClient())


def test_three_retrieved_documents_require_three_cited_documents():
    research = _research_payload()
    research["retrieval_summary"]["document_count"] = 3
    research["evidence"][3]["doc_id"] = "paper-c"
    research["evidence"][3]["paper"] = "研究 C"

    result = synthesize_literature_review(research, chat_client=FakeReviewClient())

    assert result["adequacy"]["min_documents"] == 3
    assert result["adequacy"]["document_count"] == 3
    assert result["adequacy"]["is_sufficient"] is True


def test_review_skips_one_unsupported_section_instead_of_discarding_supported_report() -> None:
    class OfflineClient:
        def complete_json(self, _messages, *, schema_name):
            raise RuntimeError(f"offline: {schema_name}")

        def complete_text(self, _messages, *, max_tokens=700):
            raise RuntimeError(f"offline: {max_tokens}")

    plan = {
        "title": "Evidence-bounded RAG review",
        "scope": "Only indexed evidence.",
        "sections": [
            {
                "id": "benchmarks",
                "title": "Performance benchmarks",
                "objective": "Compare benchmark performance",
                "citation_ids": ["1"],
            },
            {
                "id": "limitations",
                "title": "Citation reliability limitations",
                "objective": "Identify citation limitations and factual risks",
                "citation_ids": ["2"],
            },
            {
                "id": "retrieval",
                "title": "Retrieval architecture",
                "objective": "Describe the retrieval architecture",
                "citation_ids": ["3"],
            },
        ],
    }
    evidence = [
        {
            "citation_id": "1",
            "doc_id": "doc-1",
            "paper": "Architecture paper",
            "evidence_id": "doc-1.s1",
            "html_anchor": "s1",
            "html_path": "doc-1.md",
            "exact_quote": "The system combines a retriever with a language model for document-grounded generation.",
        },
        {
            "citation_id": "2",
            "doc_id": "doc-2",
            "paper": "Reliability paper",
            "evidence_id": "doc-2.s1",
            "html_anchor": "s1",
            "html_path": "doc-2.md",
            "exact_quote": "A central limitation is citation hallucination and the risk of factual inaccuracy in generated reviews.",
        },
        {
            "citation_id": "3",
            "doc_id": "doc-3",
            "paper": "Retrieval paper",
            "evidence_id": "doc-3.s1",
            "html_anchor": "s1",
            "html_path": "doc-3.md",
            "exact_quote": "The retrieval architecture indexes scientific documents and supplies selected passages to the generator.",
        },
    ]

    result = _synthesize_review_in_parts(
        "How reliable is RAG for scientific reviews?",
        plan,
        evidence,
        chat_client=OfflineClient(),
    )

    assert [section["id"] for section in result["sections"]] == ["limitations", "retrieval"]
    assert result["writing_runtime"]["skipped_sections"] == ["Performance benchmarks"]
    assert "未通过严格证据校验" in result["limitations"][-1]

    full = synthesize_literature_review(
        {
            "question": "How reliable is RAG for scientific reviews?",
            "review_plan": plan,
            "evidence": evidence,
            "section_results": plan["sections"],
            "retrieval_summary": {"section_count": 3, "document_count": 3, "evidence_count": 3},
        },
        chat_client=OfflineClient(),
    )
    assert [section["id"] for section in full["review_document"]["sections"]] == ["limitations", "retrieval"]
