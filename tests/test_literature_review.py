from __future__ import annotations

from pathlib import Path

import pytest

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.literature_review import plan_literature_review, synthesize_literature_review
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
        if schema_name == "evidence_grounded_literature_review":
            citation = "99" if self.bad_citation else "2"
            return {
                "title": "免疫治疗的机制、疗效与转化边界",
                "abstract": {"text": "现有证据显示不同干预通过互补机制影响免疫反应。", "citation_ids": [citation, "4"]},
                "sections": [
                    {
                        "id": "ignored-by-normalizer",
                        "title": "ignored",
                        "paragraphs": [{"text": "两项研究分别观察到调节性 T 细胞下降和树突细胞活化。", "citation_ids": ["2", "4"]}],
                    },
                    {
                        "paragraphs": [{"text": "动物模型中的生存获益尚不能直接外推到临床。", "citation_ids": ["4"]}],
                    },
                    {
                        "paragraphs": [{"text": "研究设计和对象差异限制了效应量的直接比较。", "citation_ids": ["1", "2"]}],
                    },
                ],
                "comparison_table": {
                    "columns": ["代表工作", "研究对象", "方法", "主要发现", "局限"],
                    "rows": [
                        {"cells": ["研究 A", "患者", "药物干预", "T 细胞下降", "样本较小"], "citation_ids": ["2"]},
                        {"cells": ["研究 B", "动物模型", "细胞干预", "生存改善", "外推有限"], "citation_ids": ["4"]},
                    ],
                },
                "controversies": [{"text": "不同模型中的获益是否可直接比较仍有争议。", "citation_ids": ["2", "4"]}],
                "open_questions": [{"text": "哪些人群最可能获益？", "basis": "现有研究对象差异较大。", "citation_ids": ["1", "2"]}],
                "limitations": ["仅纳入当前资料库中带原文锚点的证据。"],
            }
        raise AssertionError(schema_name)


def _research_payload() -> dict[str, object]:
    plan = plan_literature_review("免疫治疗有哪些证据？", chat_client=FakeReviewClient())
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
    assert len(document["comparison_table"]["rows"]) == 2
    assert document["open_questions"][0]["basis"]
    assert [item["citation_id"] for item in document["references"]] == ["1", "2", "3"]
    assert document["references"][0]["reader_url"].startswith("/reader/")
    assert result["citation_verification"]["passed"] is True
    assert result["adequacy"]["document_count"] == 2


def test_synthesis_rejects_hallucinated_citation_ids():
    with pytest.raises(ValueError, match="不存在的证据编号"):
        synthesize_literature_review(_research_payload(), chat_client=FakeReviewClient(bad_citation=True))


def test_default_local_evidence_role_cannot_pretend_to_be_review_writer(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["model_roles"]["writing"] = "provider:local-evidence:evidence-retrieval"
    settings["active_model"] = {"provider_id": "local-evidence", "model_id": "evidence-retrieval"}
    save_settings(workspace, settings)
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    with pytest.raises(ValueError, match="真正的文献综述需要生成模型"):
        runtime._writing_chat_client()
