from __future__ import annotations

from scansci_html.deep_research import discovery_only_result, plan_deep_research, run_discovery_loop


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

