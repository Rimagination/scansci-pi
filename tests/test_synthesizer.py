from bs4 import BeautifulSoup

import pytest

from scansci_html.qa.synthesizer import synthesize_answer, synthesize_answer_with_llm
from scansci_html.render.report import render_answer_report


def test_synthesize_answer_uses_only_evidence_table_rows():
    evidence_table = [
        {
            "quote_id": "q0001",
            "claim_target": "Model predictions explained cortical activity.",
            "stance": "supports",
            "exact_quote": "Model predictions explained cortical activity in language regions.",
            "paper": "Model Paper",
            "section": "Results",
            "doi": "10.1234/model",
            "evidence_id": "doc1.s0001",
            "html_path": "paper.evidence.html",
            "html_anchor": "results-p1-s0001",
            "confidence": 0.92,
        }
    ]

    answer = synthesize_answer(
        "What evidence links language models to cortical activity?",
        evidence_table,
    )

    assert answer == {
        "question": "What evidence links language models to cortical activity?",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "Model predictions explained cortical activity.",
                "quote_ids": ["q0001"],
                "support_status": "supported_by_evidence_table",
            }
        ],
        "limitations": [],
        "insufficient_evidence": False,
    }


def test_synthesize_answer_refuses_when_evidence_table_is_empty():
    answer = synthesize_answer("What evidence supports X?", [])

    assert answer["answer"] == []
    assert answer["insufficient_evidence"] is True
    assert answer["limitations"] == ["No validated evidence quotes were available for this question."]


def test_local_fallback_selects_one_directly_relevant_sentence_for_a_direct_question():
    evidence_table = [
        {
            "quote_id": "q0001",
            "claim_target": "A large compute table contains BERT and GPT-3 rows.",
            "exact_quote": "Model Total train compute Params BERT-Base GPT-3 Small.",
            "confidence": 0.9,
        },
        {
            "quote_id": "q0002",
            "claim_target": "BERT uses bidirectional self-attention.",
            "exact_quote": (
                "Critically, however, the BERT Transformer uses bidirectional self-attention, "
                "while the GPT Transformer uses constrained self-attention where every token can only attend to previous tokens.4 "
                "1https://example.test/footnote"
            ),
            "confidence": 0.82,
        },
        {
            "quote_id": "q0003",
            "claim_target": "BERT fine-tuning is straightforward.",
            "exact_quote": "Fine-tuning BERT is straightforward for many downstream tasks.",
            "confidence": 0.8,
        },
    ]

    answer = synthesize_answer("BERT 的自注意力是双向还是只能看左侧上下文？", evidence_table)

    assert len(answer["answer"]) == 1
    assert answer["answer"][0]["quote_ids"] == ["q0002"]
    assert "bidirectional self-attention" in answer["answer"][0]["text"]
    assert "Total train compute" not in answer["answer"][0]["text"]
    assert "https://" not in answer["answer"][0]["text"]


def test_synthesize_answer_groups_conflict_evidence_into_contrast_claim():
    evidence_table = [
        {
            "quote_id": "q0001",
            "claim_target": "Treatment increased biomass by 18 percent in the greenhouse cohort.",
            "exact_quote": "Treatment increased biomass by 18 percent in the greenhouse cohort.",
        },
        {
            "quote_id": "q0002",
            "claim_target": "Treatment did not increase biomass in the validation cohort.",
            "exact_quote": "Treatment did not increase biomass in the validation cohort.",
        },
    ]

    answer = synthesize_answer(
        "What evidence conflicts on whether treatment increased biomass?",
        evidence_table,
    )

    assert answer["answer"] == [
        {
            "claim_id": "c0001",
            "text": (
                "One source reports that Treatment increased biomass by 18 percent in the greenhouse cohort; "
                "another source reports that Treatment did not increase biomass in the validation cohort."
            ),
            "quote_ids": ["q0001", "q0002"],
            "support_status": "supported_by_evidence_table",
        }
    ]
    assert answer["insufficient_evidence"] is False


def test_synthesize_answer_with_llm_validates_quote_ids():
    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            return {
                "answer": [
                    {
                        "claim_id": "c9000",
                        "text": "The treatment increased biomass.",
                        "quote_ids": ["q0001"],
                    }
                ],
                "limitations": ["Only one paper is available."],
            }

    evidence_table = [
        {
            "quote_id": "q0001",
            "exact_quote": "The treatment increased biomass by 18%.",
        }
    ]

    answer = synthesize_answer_with_llm(
        "What happened?",
        evidence_table,
        chat_client=FakeChatClient(),
    )

    assert answer == {
        "question": "What happened?",
        "answer": [
            {
                "claim_id": "c9000",
                "text": "The treatment increased biomass.",
                "quote_ids": ["q0001"],
                "support_status": "pending_verification",
            }
        ],
        "limitations": ["Only one paper is available."],
        "insufficient_evidence": False,
    }


def test_synthesize_answer_with_llm_rejects_quote_ids_outside_evidence_table():
    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            return {
                "answer": [
                    {
                        "claim_id": "c9000",
                        "text": "The treatment increased biomass.",
                        "quote_ids": ["missing"],
                    }
                ],
                "limitations": [],
            }

    with pytest.raises(ValueError, match="unknown quote_id"):
        synthesize_answer_with_llm(
            "What happened?",
            [{"quote_id": "q0001", "exact_quote": "quote"}],
            chat_client=FakeChatClient(),
        )


def test_synthesize_answer_with_llm_deduplicates_and_caps_claims():
    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            claims = [
                {"claim_id": "c0001", "text": "BERT 使用双向自注意力。", "quote_ids": ["q0001"]},
                {"claim_id": "c0002", "text": "BERT 使用双向自注意力。", "quote_ids": ["q0001"]},
            ]
            claims.extend(
                {"claim_id": f"c{index:04d}", "text": f"补充结论 {index}", "quote_ids": ["q0001"]}
                for index in range(3, 9)
            )
            return {"answer": claims, "limitations": []}

    answer = synthesize_answer_with_llm(
        "BERT 的注意力方向是什么？",
        [{"quote_id": "q0001", "exact_quote": "BERT uses bidirectional self-attention."}],
        chat_client=FakeChatClient(),
    )

    assert len(answer["answer"]) == 4
    assert [item["text"] for item in answer["answer"]].count("BERT 使用双向自注意力。") == 1


def test_synthesize_answer_with_llm_compacts_large_tool_rows_before_provider_call():
    captured = {}

    class FakeChatClient:
        def complete_json(self, messages, *, schema_name):
            captured["messages"] = messages
            return {
                "answer": [{"claim_id": "c0001", "text": "结论。", "quote_ids": ["q0001"]}],
                "limitations": [],
            }

    rows = [
        {
            "quote_id": f"q{index:04d}",
            "claim_target": "光伏板下土壤水分变化。" * 100,
            "exact_quote": "这是来自原始文献的精确证据。" * 100,
            "paper": "一篇很长的中文文献题名" * 20,
            "section": "结果" * 20,
            "context_text": "不应传给模型的巨大父级证据块" * 1000,
            "html_path": "D:/private/path/source.html",
        }
        for index in range(1, 13)
    ]

    synthesize_answer_with_llm("有哪些一致结论？", rows, chat_client=FakeChatClient())

    body = captured["messages"][1]["content"]
    assert len(body.encode("utf-8")) < 13_000
    assert "context_text" not in body
    assert "private/path" not in body


def test_render_answer_report_links_claims_quotes_and_source_anchors():
    answer = {
        "question": "What evidence supports X?",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "The treatment increased biomass.",
                "quote_ids": ["q0001"],
                "support_status": "supported",
                "verification_score": 0.92,
            }
        ],
        "reader_answer": {
            "style": "notebooklm_like_inline_citations",
            "text": "The treatment increased biomass. [1]",
            "sentences": [
                {
                    "claim_id": "c0001",
                    "text": "The treatment increased biomass.",
                    "quote_ids": ["q0001"],
                    "citation_ids": ["1"],
                    "support_status": "supported",
                    "verification_score": 0.92,
                }
            ],
            "citations": [
                {
                    "citation_id": "1",
                    "quote_id": "q0001",
                    "evidence_id": "doc1.s0001",
                    "source_href": "paper.evidence.html#results-p1-s0001",
                }
            ],
        },
        "limitations": [],
        "insufficient_evidence": False,
    }
    evidence_table = [
        {
            "quote_id": "q0001",
            "claim_target": "The treatment increased biomass.",
            "stance": "supports",
            "exact_quote": "The treatment increased biomass by 18%.",
            "paper": "Biomass Paper",
            "section": "Results",
            "section_kind": "results",
            "doi": "10.1234/biomass",
            "evidence_id": "doc1.s0001",
            "html_path": "paper.evidence.html",
            "html_anchor": "results-p1-s0001",
            "context_text": "The cohort included 120 participants. The treatment increased biomass by 18%.",
            "parent_block_id": "doc1:results-p1",
            "parent_evidence_ids": ["doc1.s0001", "doc1.s0002"],
            "confidence": 0.82,
        }
    ]

    html = render_answer_report(
        answer,
        evidence_table,
        retrieval_metadata={
            "query_plan": {
                "question_type": "evidence",
                "filters": {"year_min": 2020, "section_kinds": ["results"]},
            },
            "retrieval_queries": [
                "What evidence supports X?",
                "evidence supports x",
            ],
            "adequacy": {
                "is_sufficient": True,
                "profile": "manual",
                "quote_count": 1,
                "min_quotes": 1,
                "document_count": 1,
                "min_documents": 1,
                "followup_reason": "",
            },
        },
    )
    soup = BeautifulSoup(html, "lxml")

    assert soup.select_one("h1").get_text(strip=True) == "What evidence supports X?"
    reader = soup.select_one("[data-reader-answer]")
    assert reader is not None
    assert reader.select_one("[data-reader-claim-id='c0001']").get_text(" ", strip=True) == (
        "The treatment increased biomass. [1]"
    )
    reader_citation = reader.select_one("[data-citation-id='1'][data-quote-id='q0001']")
    assert reader_citation["href"] == "#quote-q0001"
    audit = soup.select_one("section.retrieval-audit")
    assert audit is not None
    assert "Retrieval Audit" in audit.get_text(" ", strip=True)
    assert '"section_kinds": ["results"]' in audit.get_text(" ", strip=True)
    assert "What evidence supports X? | evidence supports x" in audit.get_text(" ", strip=True)
    assert "True" in audit.get_text(" ", strip=True)
    assert "Adequacy profile manual" in audit.get_text(" ", strip=True)
    assert "Minimum quotes 1" in audit.get_text(" ", strip=True)
    assert "Minimum documents 1" in audit.get_text(" ", strip=True)
    claim = soup.select_one("[data-claim-id='c0001']")
    assert claim is not None
    assert claim.name == "details"
    assert claim["data-support-status"] == "supported"
    assert claim.select_one("[data-support-status]").get_text(strip=True) == "supported"
    assert claim.select_one("[data-verification-score]").get_text(strip=True) == "0.92"
    citation = claim.select_one("[data-quote-id='q0001']")
    assert citation.get_text(strip=True) == "q0001"
    assert citation["title"] == "The treatment increased biomass by 18%."
    assert citation["data-quote-preview"] == "The treatment increased biomass by 18%."
    source = soup.select_one("a[data-evidence-id='doc1.s0001']")
    assert source["href"] == "paper.evidence.html#results-p1-s0001"
    assert source.get_text(strip=True) == "doc1.s0001"
    context = soup.select_one("[data-context-for='q0001']")
    assert context is not None
    assert "The cohort included 120 participants." in context.get_text(" ", strip=True)
    assert context["data-parent-block-id"] == "doc1:results-p1"
    source_pane = soup.select_one("section.source-pane")
    assert source_pane is not None
    iframe = source_pane.select_one("iframe[data-evidence-id='doc1.s0001']")
    assert iframe["src"] == "paper.evidence.html#results-p1-s0001"
    assert iframe["title"] == "Source doc1.s0001"
    assert soup.select_one("input#show-unsupported[data-toggle-unsupported]") is not None
