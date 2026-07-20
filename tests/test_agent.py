from pathlib import Path
import sqlite3

from scansci_html.evidence_store import index_evidence_library
from scansci_html.qa import agent
from scansci_html.qa.agent import (
    answer_question,
    assess_evidence_adequacy,
    build_reader_answer,
    evidence_adequacy_thresholds,
    resolve_agentic_controls,
    verify_citations,
)
from scansci_html.qa.query_planner import plan_query


def test_plan_query_identifies_comparison_and_core_terms():
    plan = plan_query("Compare method A and method B for cortical activity after 2020")

    assert plan["query"] == "Compare method A and method B for cortical activity after 2020"
    assert plan["question_type"] == "comparison"
    assert plan["core_terms"] == ["compare", "method", "cortical", "activity", "after", "2020"]
    assert plan["filters"] == {"year_min": 2020}
    assert plan["query_variants"] == [
        "method cortical activity",
        "findings results method cortical activity",
        "evidence method cortical activity",
        "methods protocol method cortical activity",
    ]
    assert plan["followup_queries"] == [
        "method cortical activity",
        "compare method cortical activity after 2020",
    ]


def test_plan_query_adds_methods_filter_for_explicit_method_questions():
    plan = plan_query("What method was used to randomize samples since 2020?")

    assert plan["question_type"] == "evidence"
    assert plan["filters"] == {"year_min": 2020, "section_kinds": ["methods"]}
    assert plan["core_terms"] == ["method", "used", "randomize", "samples", "since", "2020"]


def test_plan_query_builds_chinese_rewrite_routes():
    plan = plan_query("这篇论文提出的两个使能特征是什么？", max_routes=5)

    assert plan["language"] == "zh"
    assert plan["answer_type"] == "named_list"
    assert plan["expected_answer_count"] == 2
    assert "enabling" in plan["core_terms"]
    assert "characteristics" in plan["core_terms"]
    assert [route["label"] for route in plan["routes"][:2]] == ["original", "keywords"]
    assert any(route["query"] == "enabling characteristics features paper study" for route in plan["routes"])


def test_plan_query_identifies_conflict_and_synthesis_questions():
    conflict_plan = plan_query("What evidence conflicts on whether treatment increased biomass?")
    synthesis_plan = plan_query("Synthesize findings across studies on treatment biomass")

    assert conflict_plan["question_type"] == "conflict"
    assert synthesis_plan["question_type"] == "synthesis"


def test_evidence_adequacy_thresholds_auto_promotes_multi_source_questions():
    assert evidence_adequacy_thresholds("comparison", profile="auto", min_quotes=1, min_documents=1) == {
        "profile": "auto",
        "min_quotes": 2,
        "min_documents": 2,
    }
    assert evidence_adequacy_thresholds("evidence", profile="auto", min_quotes=1, min_documents=1) == {
        "profile": "auto",
        "min_quotes": 1,
        "min_documents": 1,
    }
    assert evidence_adequacy_thresholds("conflict", profile="manual", min_quotes=1, min_documents=1) == {
        "profile": "manual",
        "min_quotes": 1,
        "min_documents": 1,
    }


def test_resolve_agentic_controls_presets_are_bounded_and_auditable():
    plan = {"question_type": "synthesis", "answer_type": "synthesis"}

    assert resolve_agentic_controls(
        plan,
        profile="fast",
        query_variants=4,
        max_followup_queries=4,
        paper_recall_limit=100,
    ) == {
        "profile": "fast",
        "question_type": "synthesis",
        "answer_type": "synthesis",
        "query_variants": 1,
        "max_followup_queries": 0,
        "paper_recall_limit": 0,
    }

    assert resolve_agentic_controls(
        plan,
        profile="deep",
        query_variants=1,
        max_followup_queries=1,
        paper_recall_limit=0,
    )["query_variants"] == 4


def test_assess_evidence_adequacy_requires_minimum_quotes_and_diversity():
    assert assess_evidence_adequacy([], min_quotes=1, min_documents=1) == {
        "is_sufficient": False,
        "quote_count": 0,
        "document_count": 0,
        "profile": "manual",
        "min_quotes": 1,
        "min_documents": 1,
        "followup_reason": "no validated quotes",
    }

    quotes = [
        {
            "quote_id": "q0001",
            "evidence_ids": ["doc1.s0001"],
        },
        {
            "quote_id": "q0002",
            "evidence_ids": ["doc1.s0002"],
        },
    ]

    assert assess_evidence_adequacy(quotes, min_quotes=2, min_documents=2) == {
        "is_sufficient": False,
        "quote_count": 2,
        "document_count": 1,
        "profile": "manual",
        "min_quotes": 2,
        "min_documents": 2,
        "followup_reason": "not enough source-document diversity",
    }


def test_answer_question_runs_local_evidence_first_pipeline(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/agent">
          <h1>Agent Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    result = answer_question(
        db_path,
        "What evidence links models to cortical activity?",
        limit=5,
        min_quotes=1,
        min_documents=1,
    )

    assert result["query_plan"]["question_type"] == "evidence"
    assert result["adequacy"]["is_sufficient"] is True
    assert result["adequacy"]["profile"] == "manual"
    assert result["adequacy"]["min_quotes"] == 1
    assert result["adequacy"]["min_documents"] == 1
    assert result["quotes"][0]["evidence_ids"] == ["10.1234_agent.s0001"]
    assert result["answer"]["answer"][0]["support_status"] == "supported"
    assert result["verification"]["supported_claims"] == ["c0001"]
    assert result["citation_verification"]["passed"] is True
    assert result["answer"]["citation_verification"]["cited_quote_count"] == 1
    assert result["reader_answer"]["text"].endswith("[1]")
    assert result["reader_answer"]["citations"][0]["quote_id"] == "q0001"
    assert result["reader_answer"]["citations"][0]["source_href"].endswith("#results-p1-s0001")


def test_answer_question_abstains_when_adequacy_gate_fails(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/one-source">
          <h1>One Source Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Treatment increased biomass in the greenhouse cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    result = answer_question(
        db_path,
        "What evidence conflicts on whether treatment increased biomass?",
        limit=5,
        adequacy_profile="auto",
    )

    assert result["query_plan"]["question_type"] == "conflict"
    assert result["adequacy"] == {
        "is_sufficient": False,
        "quote_count": 1,
        "document_count": 1,
        "profile": "auto",
        "min_quotes": 2,
        "min_documents": 2,
        "followup_reason": "not enough validated quotes",
    }
    assert len(result["evidence_table"]) == 1
    assert result["answer"]["answer"] == []
    assert result["answer"]["insufficient_evidence"] is True
    assert "evidence adequacy gate failed" in result["answer"]["limitations"][0]
    assert result["answer"]["verification_policy"]["action"] == "abstain"


def test_answer_question_runs_followup_search_when_initial_evidence_is_insufficient(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_search_evidence_store(
        db_path,
        query,
        *,
        limit,
        per_document_limit,
        filters,
        embedding_provider,
        reranker,
        context_mode,
    ):
        calls.append((query, context_mode))
        if len(calls) == 1:
            return []
        return [
            {
                "evidence_id": "doc1.s0001",
                "doc_id": "doc1",
                "title": "Followup Paper",
                "doi": "10.1234/followup",
                "section": "Results",
                "section_kind": "results",
                "text": "Model predictions explained cortical activity in language regions.",
                "score": 3.0,
                "matched_terms": ["model", "cortical", "activity"],
            }
        ]

    monkeypatch.setattr(agent, "search_evidence_store", fake_search_evidence_store)

    result = answer_question(
        "unused.sqlite",
        "What evidence supports model cortical activity?",
        limit=5,
        context_mode="block",
    )

    assert len(calls) >= 2
    assert all(context_mode == "block" for _query, context_mode in calls)
    assert result["adequacy"]["is_sufficient"] is True
    assert result["quotes"][0]["evidence_ids"] == ["doc1.s0001"]
    assert result["retrieval_queries"][0] == "What evidence supports model cortical activity?"
    assert result["agentic_trace"]["slow_path_triggered"] is True
    assert result["agentic_trace"]["stop_reason"] == "evidence_sufficient_after_followup"
    assert [step["step"] for step in result["agentic_trace"]["steps"]] == [
        "initial_retrieval",
        "followup_retrieval",
        "citation_verification",
    ]


def test_verify_citations_fails_uncited_or_unsupported_claims():
    evidence_table = [
        {
            "quote_id": "q0001",
            "evidence_id": "doc1.s0001",
            "exact_quote": "The treatment increased biomass.",
            "html_path": "paper.evidence.html",
            "html_anchor": "doc1-s0001",
        }
    ]
    answer = {
        "answer": [
            {"claim_id": "c0001", "text": "Treatment increased biomass.", "quote_ids": ["q0001"], "support_status": "supported"},
            {"claim_id": "c0002", "text": "Treatment also changed roots.", "quote_ids": [], "support_status": "supported"},
            {"claim_id": "c0003", "text": "Treatment reduced biomass.", "quote_ids": ["q0001"], "support_status": "unsupported"},
        ]
    }

    result = verify_citations(answer, evidence_table)

    assert result["passed"] is False
    assert result["uncited_claim_ids"] == ["c0002"]
    assert result["unsupported_cited_claim_ids"] == ["c0003"]


def test_reader_answer_prioritizes_question_relevant_supported_claims():
    answer = {
        "question": "What are the two emerging hallmarks of cancer proposed in this paper?",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "The invasion-metastasis cascade proceeds through several steps.",
                "quote_ids": ["q0001"],
                "support_status": "supported",
            },
            {
                "claim_id": "c0002",
                "text": "Two such attributes are reprogramming of cellular energy metabolism and evading immune destruction.",
                "quote_ids": ["q0002"],
                "support_status": "supported",
            },
        ],
    }
    evidence_table = [
        {"quote_id": "q0001", "evidence_id": "doc1.s0001", "exact_quote": "invasion", "html_path": "paper.html", "html_anchor": "s1"},
        {"quote_id": "q0002", "evidence_id": "doc1.s0002", "exact_quote": "two hallmarks", "html_path": "paper.html", "html_anchor": "s2"},
    ]

    reader_answer = build_reader_answer(answer, evidence_table)

    assert reader_answer["text"] == (
        "Two such attributes are reprogramming of cellular energy metabolism and evading immune destruction. [1]"
    )
    assert reader_answer["citations"][0]["quote_id"] == "q0002"


def test_reader_answer_limits_named_list_when_top_claim_fully_answers():
    answer = {
        "question": "What are the two emerging hallmarks of cancer proposed in this paper?",
        "answer": [
            {
                "claim_id": "c0001",
                "text": "Two such attributes are reprogramming of cellular energy metabolism and evading immune destruction.",
                "quote_ids": ["q0001"],
                "support_status": "supported",
            },
            {
                "claim_id": "c0002",
                "text": "The hallmarks also include sustaining proliferative signaling.",
                "quote_ids": ["q0002"],
                "support_status": "supported",
            },
        ],
    }
    evidence_table = [
        {
            "quote_id": "q0001",
            "evidence_id": "doc1.s0001",
            "exact_quote": "The two emerging hallmarks of cancer are reprogramming of energy metabolism and evading immune destruction.",
            "html_path": "paper.html",
            "html_anchor": "s1",
        },
        {
            "quote_id": "q0002",
            "evidence_id": "doc1.s0002",
            "exact_quote": "The hallmarks also include sustaining proliferative signaling.",
            "html_path": "paper.html",
            "html_anchor": "s2",
        },
    ]

    reader_answer = build_reader_answer(
        answer,
        evidence_table,
        query_plan={"answer_type": "named_list", "expected_answer_count": 2},
    )

    assert [sentence["claim_id"] for sentence in reader_answer["sentences"]] == ["c0001"]


def test_query_plan_does_not_treat_yizhi_as_one_requested_item():
    plan = plan_query("这些研究的结论和证据是否一致？有哪些分歧？")

    assert plan["question_type"] == "conflict"
    assert plan["answer_type"] == "conflict"
    assert plan["expected_answer_count"] is None


def test_query_plan_parses_explicit_chinese_item_count():
    plan = plan_query("请列出两个最重要的影响因素")

    assert plan["answer_type"] == "named_list"
    assert plan["expected_answer_count"] == 2


def test_answer_question_runs_planned_query_variants_before_followups(monkeypatch):
    calls: list[str] = []

    def fake_search_evidence_store(
        db_path,
        query,
        *,
        limit,
        per_document_limit,
        filters,
        embedding_provider,
        reranker,
        context_mode,
    ):
        calls.append(query)
        if len(calls) == 1:
            return []
        return [
            {
                "evidence_id": "doc1.s0001",
                "doc_id": "doc1",
                "title": "Variant Paper",
                "doi": "10.1234/variant",
                "html_path": "paper.evidence.html",
                "html_anchor": "results-p1-s0001",
                "section": "Results",
                "section_kind": "results",
                "text": "Model predictions explained cortical activity in language regions.",
                "score": 3.0,
                "matched_terms": ["model", "cortical", "activity"],
            }
        ]

    monkeypatch.setattr(agent, "search_evidence_store", fake_search_evidence_store)

    result = answer_question(
        "unused.sqlite",
        "What evidence supports model cortical activity?",
        limit=5,
        query_variants=2,
    )

    assert calls[:2] == [
        "What evidence supports model cortical activity?",
        "evidence supports model cortical activity",
    ]
    assert result["retrieval_queries"] == calls[:2]
    assert result["adequacy"]["is_sufficient"] is True


def test_answer_question_reranks_fused_multi_query_candidates_once(monkeypatch):
    search_rerankers: list[object | None] = []

    def fake_search_evidence_store(
        db_path,
        query,
        *,
        limit,
        per_document_limit,
        filters,
        embedding_provider,
        reranker,
        context_mode,
    ):
        search_rerankers.append(reranker)
        if query == "What evidence supports model cortical activity?":
            return [
                {
                    "evidence_id": "doc1.s0001",
                    "doc_id": "doc1",
                    "title": "Original Route Paper",
                    "doi": "10.1234/original",
                    "html_path": "paper.evidence.html",
                    "html_anchor": "results-p1-s0001",
                    "section": "Results",
                    "section_kind": "results",
                    "text": "Model evidence supports cortical activity in language regions.",
                    "score": 2.0,
                    "matched_terms": ["model", "cortical", "activity"],
                }
            ]
        return [
            {
                "evidence_id": "doc2.s0001",
                "doc_id": "doc2",
                "title": "Keyword Route Paper",
                "doi": "10.1234/keyword",
                "html_path": "paper.evidence.html",
                "html_anchor": "results-p2-s0001",
                "section": "Results",
                "section_kind": "results",
                "text": "Keyword route evidence links models and cortical activity.",
                "score": 3.0,
                "matched_terms": ["model", "cortical", "activity"],
            }
        ]

    class RecordingReranker:
        def __init__(self):
            self.calls: list[tuple[str, list[str]]] = []

        def rerank(self, query, candidates):
            self.calls.append((query, [str(candidate.get("evidence_id", "")) for candidate in candidates]))
            reranked = [dict(candidate) for candidate in candidates]
            for index, hit in enumerate(reranked, start=1):
                hit["score"] = float(len(reranked) - index + 1)
                routes = [str(route) for route in hit.get("routes", []) or []]
                routes.append("recording-reranker")
                hit["routes"] = routes
            return reranked

    monkeypatch.setattr(agent, "search_evidence_store", fake_search_evidence_store)
    reranker = RecordingReranker()

    result = answer_question(
        "unused.sqlite",
        "What evidence supports model cortical activity?",
        limit=5,
        query_variants=2,
        reranker=reranker,
    )

    assert search_rerankers == [None, None]
    assert len(reranker.calls) == 1
    assert set(reranker.calls[0][1]) == {"doc1.s0001", "doc2.s0001"}
    assert result["retrieval_queries"] == [
        "What evidence supports model cortical activity?",
        "evidence supports model cortical activity",
    ]
    assert result["retrieval_query_routes"][1]["label"] == "keywords"
    assert result["adequacy"]["is_sufficient"] is True


def test_answer_question_expands_named_list_hits_to_parent_block(tmp_path: Path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/block-neighbor">
          <h1>Block Neighbor Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">
            Their acquisition is made possible by two enabling characteristics.
            Most prominent is genomic instability, which generates mutations.
            A second enabling characteristic involves tumor-promoting inflammation.
          </p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        first_hit = dict(
            connection.execute(
                """
                select *
                from evidence_spans
                where text like 'Their acquisition%'
                """
            ).fetchone()
        )

    def fake_search_evidence_store(
        db_path_arg,
        query,
        *,
        limit,
        per_document_limit,
        filters,
        embedding_provider,
        reranker,
        context_mode,
    ):
        hit = dict(first_hit)
        hit["score"] = 3.0
        hit["matched_terms"] = ["two", "enabling", "characteristics"]
        return [hit]

    monkeypatch.setattr(agent, "search_evidence_store", fake_search_evidence_store)

    result = answer_question(
        db_path,
        "What two enabling characteristics do the authors identify?",
        limit=5,
        query_variants=1,
    )

    quote = result["quotes"][0]
    evidence_row = result["evidence_table"][0]
    assert "genomic instability" in quote["exact_quote"]
    assert "tumor-promoting inflammation" in quote["exact_quote"]
    assert evidence_row["parent_block_id"] == first_hit["block_id"]
    assert len(evidence_row["parent_evidence_ids"]) == 3
    assert result["answer"]["answer"][0]["support_status"] == "supported"


def test_answer_question_applies_planned_year_filter(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "old.html").write_text(
        """
        <article class="paper" data-doi="10.1234/old-agent" data-publication-year="2018">
          <h1>Old Agent Paper</h1>
          <h2>Results</h2>
          <p id="old-results">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "new.html").write_text(
        """
        <article class="paper" data-doi="10.1234/new-agent" data-publication-year="2023">
          <h1>New Agent Paper</h1>
          <h2>Results</h2>
          <p id="new-results">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    result = answer_question(
        db_path,
        "What evidence links models to cortical activity since 2020?",
        limit=5,
        min_quotes=1,
        min_documents=1,
    )

    assert result["query_plan"]["filters"] == {"year_min": 2020}
    assert result["quotes"][0]["evidence_ids"] == ["10.1234_new-agent.s0001"]
    assert all(hit["publication_year"] >= 2020 for hit in result["hits"])


def test_answer_question_applies_planned_methods_filter(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/method-agent">
          <h1>Method Agent Paper</h1>
          <h2>Methods</h2>
          <p id="methods-p1">Samples were randomized before biomass measurement.</p>
          <h2>Results</h2>
          <p id="results-p1">Randomized samples produced higher biomass in the treatment cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    result = answer_question(
        db_path,
        "What method was used to randomize samples?",
        limit=5,
        min_quotes=1,
        min_documents=1,
    )

    assert result["query_plan"]["filters"] == {"section_kinds": ["methods"]}
    assert [hit["section_kind"] for hit in result["hits"]] == ["methods"]
    assert result["quotes"][0]["evidence_ids"] == ["10.1234_method-agent.s0001"]
