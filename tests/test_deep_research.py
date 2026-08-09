from __future__ import annotations

from scansci_html.deep_research import (
    _normalize_scholarly_query,
    _rerank_for_question,
    discovery_only_result,
    plan_deep_research,
    run_discovery_loop,
)


class _FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, **_kwargs):
        self.queries.append(query)
        normalized = query.casefold()
        if "limitations" in normalized or "conflicting" in normalized:
            items = [
                {
                    "title": "Known limitations of retrieval systems",
                    "abstract": "Limitations and conflicting evidence in retrieval systems.",
                    "doi": "10.1000/limits",
                    "year": 2024,
                    "sources": ["crossref"],
                    "score": 1.0,
                },
                {
                    "title": "Failure modes in retrieval augmented generation",
                    "abstract": "Limitations, failures and conflicting results.",
                    "doi": "10.1000/failures",
                    "year": 2025,
                    "sources": ["openalex"],
                    "score": 0.9,
                },
            ]
        else:
            items = [
                {
                    "title": "Core retrieval evidence",
                    "abstract": "Core findings and methods for retrieval augmented generation.",
                    "doi": "10.1000/core",
                    "year": 2023,
                    "sources": ["openalex"],
                    "score": 1.2,
                }
            ]
        return {
            "items": items,
            "count": len(items),
            "providers_succeeded": ["openalex"],
            "provider_errors": {},
            "latency_ms": 1,
        }


class _StringKeywordPlanClient:
    def complete_json(self, _messages, *, schema_name):
        assert schema_name == "academic_deep_research_plan"
        return {
            "title": "RAG literature review",
            "objective": "Assess RAG-supported literature reviews",
            "perspectives": [
                {
                    "title": "Retrieval quality",
                    "question": "How is retrieval quality evaluated?",
                    "keywords": "retrieval quality; citation grounding",
                },
                {
                    "title": "Limitations",
                    "question": "What limitations remain?",
                    "keywords": "hallucination, coverage gap",
                },
            ],
            "search_queries": "RAG literature review 2024; retrieval augmented scientific review",
            "inclusion_criteria": "Published since 2024; traceable scholarly metadata",
            "exclusion_criteria": "Unverifiable citations",
        }


def test_planner_does_not_split_string_fields_into_characters() -> None:
    plan = plan_deep_research(
        "RAG for scientific literature reviews",
        chat_client=_StringKeywordPlanClient(),
    )

    assert plan["planner"] == "llm"
    assert plan["perspectives"][0]["keywords"] == ["retrieval quality", "citation grounding"]
    assert plan["search_queries"] == [
        "RAG literature review 2024",
        "retrieval augmented scientific review",
    ]
    assert plan["inclusion_criteria"] == ["Published since 2024", "traceable scholarly metadata"]


def test_deep_research_plan_and_gap_loop_are_bounded() -> None:
    plan = {
        "title": "RAG evidence",
        "objective": "Assess RAG",
        "search_queries": ["retrieval augmented generation"],
        "perspectives": [
            {"title": "Core", "question": "Core findings", "keywords": ["core", "retrieval"]},
            {"title": "Limitations", "question": "Limitations", "keywords": ["limitations", "conflicting"]},
        ],
    }
    searcher = _FakeSearch()
    result = run_discovery_loop(
        "retrieval augmented generation",
        plan,
        searcher=searcher,  # type: ignore[arg-type]
        result_limit=10,
        per_source=5,
        max_rounds=2,
    )

    assert len(result["rounds"]) == 2
    assert any("Limitations" in query for query in searcher.queries)
    assert result["deduplicated_count"] == 3
    assert result["evidence_status"] == "discovery_leads"


def test_discovery_normalizes_boolean_queries_and_records_outbound_form() -> None:
    plan = {
        "title": "Citation faithfulness in RAG",
        "objective": "Evaluate citation faithfulness in retrieval augmented generation.",
        "search_queries": ['"citation faithfulness" AND "retrieval-augmented generation" AND 2023'],
        "perspectives": [
            {
                "title": "Metrics",
                "question": "How is citation faithfulness measured?",
                "keywords": ["citation faithfulness", "citation precision"],
            }
        ],
    }
    searcher = _FakeSearch()

    result = run_discovery_loop(
        "What evidence since 2023 evaluates citation faithfulness in RAG systems?",
        plan,
        searcher=searcher,  # type: ignore[arg-type]
        result_limit=10,
        year_from=2023,
        max_rounds=1,
    )

    assert searcher.queries == ["citation faithfulness retrieval augmented generation"]
    assert result["rounds"][0]["queries"][0] == {
        "query": '"citation faithfulness" AND "retrieval-augmented generation" AND 2023',
        "outbound_query": "citation faithfulness retrieval augmented generation",
        "count": 1,
        "providers_succeeded": ["openalex"],
        "latency_ms": 1,
    }


def test_question_reranking_beats_popular_but_off_topic_results() -> None:
    question = "What evidence evaluates citation faithfulness in retrieval-augmented generation systems?"
    plan = {
        "title": "Citation faithfulness in RAG",
        "objective": question,
        "perspectives": [
            {
                "title": "Metrics",
                "question": "How is faithfulness measured?",
                "keywords": ["citation faithfulness", "citation precision", "RAG benchmark"],
            }
        ],
    }
    ranked = _rerank_for_question(
        question,
        plan,
        [
            {
                "title": "Large Language Models in Clinical Neurology: A Systematic Review",
                "abstract": "A highly cited review that briefly mentions retrieval augmented generation in clinical systems.",
                "score": 9.0,
                "sources": ["crossref", "pubmed"],
            },
            {
                "title": "CiteCheck: Citation Faithfulness Detection for Retrieval-Augmented Generation",
                "abstract": "We benchmark citation precision, source attribution and faithfulness errors in RAG answers.",
                "score": 0.4,
                "sources": ["arxiv"],
            },
        ],
    )

    assert ranked[0]["title"].startswith("CiteCheck")
    assert ranked[0]["question_relevance"]["title_phrase_matches"]
    assert ranked[0]["provider_score"] == 0.4


def test_discovery_merges_same_title_even_when_providers_disagree_on_doi() -> None:
    class DuplicateTitleSearch:
        def search(self, _query: str, **_kwargs):
            return {
                "items": [
                    {
                        "title": "Model Internals-based Answer Attribution for Trustworthy RAG",
                        "doi": "10.1/preprint",
                        "abstract": "Citation attribution in retrieval augmented generation.",
                        "sources": ["crossref"],
                        "score": 1.0,
                    },
                    {
                        "title": "Model Internals-based Answer Attribution for Trustworthy RAG",
                        "doi": "10.2/camera-ready",
                        "abstract": "A longer abstract about citation attribution in retrieval augmented generation systems.",
                        "sources": ["openalex"],
                        "score": 0.8,
                    },
                ],
                "count": 2,
                "providers_succeeded": ["crossref", "openalex"],
                "provider_errors": {},
                "latency_ms": 1,
            }

    result = run_discovery_loop(
        "citation attribution in retrieval augmented generation",
        {
            "title": "Citation attribution",
            "objective": "Citation attribution in retrieval augmented generation",
            "search_queries": ["citation attribution RAG"],
            "perspectives": [],
        },
        searcher=DuplicateTitleSearch(),  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert result["deduplicated_count"] == 1
    assert result["items"][0]["sources"] == ["crossref", "openalex"]
    assert result["items"][0]["query_hit_count"] == 2


def test_boolean_query_normalizer_expands_rag_and_keeps_audit_plan_unchanged() -> None:
    raw = '"RAG" AND "verifiability" AND "citation" AND 2024'

    assert _normalize_scholarly_query(raw, year_from=2023) == (
        "retrieval augmented generation verifiability citation"
    )


def test_planner_falls_back_without_a_model_and_discovery_only_is_honest() -> None:
    plan = plan_deep_research("How reliable is retrieval augmented generation?", chat_client=None)
    assert plan["planner"] == "deterministic"
    assert len(plan["search_queries"]) >= 2

    result = discovery_only_result(
        "How reliable is retrieval augmented generation?",
        plan=plan,
        discovery={"items": [{"title": "Lead"}], "candidate_count": 1, "deduplicated_count": 1, "rounds": [], "unresolved_gaps": []},
        acquisition={"acquired_count": 0, "failed_count": 1},
        reason="No lawful full text was available.",
    )
    assert result["answer"]["insufficient_evidence"] is True
    assert result["reader_answer"]["citation_count"] == 0
    assert result["citation_verification"]["passed"] is True
    assert result["citation_verification"]["claim_count"] == 0
