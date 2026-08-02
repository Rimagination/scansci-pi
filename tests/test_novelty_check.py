from __future__ import annotations

import json

from scansci_html.novelty_check import assess_novelty_evidence, plan_novelty_check


def _research() -> dict:
    return {
        "phase": "retrieval",
        "retrieval_summary": {"document_count": 2, "evidence_count": 3},
        "evidence": [
            {
                "citation_id": "1",
                "evidence_id": "paper-a.s1",
                "doc_id": "paper-a",
                "paper": "Prior A",
                "section": "Methods",
                "exact_quote": "The method retrieves evidence before generation.",
                "html_anchor": "s1",
            },
            {
                "citation_id": "2",
                "evidence_id": "paper-a.s2",
                "doc_id": "paper-a",
                "paper": "Prior A",
                "section": "Evaluation",
                "exact_quote": "Claims are checked against source passages.",
                "html_anchor": "s2",
            },
            {
                "citation_id": "3",
                "evidence_id": "paper-b.s1",
                "doc_id": "paper-b",
                "paper": "Prior B",
                "section": "Methods",
                "exact_quote": "A local reranker orders candidate passages.",
                "html_anchor": "s1",
            },
        ],
    }


def _discovery() -> dict:
    return {
        "items": [{"title": "Prior A", "sources": ["openalex", "openreview"]}],
        "candidate_count": 5,
        "deduplicated_count": 4,
        "rounds": [{"queries": [{"query": "evidence agents"}]}],
        "provider_errors": {},
        "unresolved_gaps": [],
    }


class _Client:
    def complete_json(self, messages, *, schema_name):
        assert schema_name == "novelty_evidence_assessment"
        payload = json.loads(messages[1]["content"])
        assert {item["citation_id"] for item in payload["fulltext_evidence"]} == {"1", "2", "3"}
        return {
            "prior_works": [
                {
                    "paper": "Prior A",
                    "doc_id": "paper-a",
                    "axes": {
                        "problem_framing": "match",
                        "core_mechanism": "match",
                        "key_insight": "partial",
                        "application_domain": "differ",
                    },
                    "citation_ids": ["1", "2", "hallucinated"],
                    "summary": "Three axes overlap, while the domain differs.",
                }
            ],
            "delta_statement": "The proposed work changes the application domain.",
            "limitations": [],
        }


def test_novelty_assessment_is_fulltext_cited_and_drops_unknown_citation_ids() -> None:
    plan = plan_novelty_check("Evidence-grounded research agents", "Verify claims before writing")
    result = assess_novelty_evidence(plan, _discovery(), _research(), chat_client=_Client())

    assert result["status"] == "assessed"
    assert result["verdict"]["level"] == 2
    assert result["verdict"]["not_proof_of_novelty"] is True
    assert result["closest_prior_work"]["citation_ids"] == ["1", "2"]
    assert result["citation_verification"]["passed"] is True
    assert result["reader_answer"]["citation_count"] == 2
    assert result["provenance_policy"]["model_recall_allowed_as_evidence"] is False


def test_novelty_assessment_refuses_to_turn_discovery_leads_into_evidence() -> None:
    plan = plan_novelty_check("Evidence-grounded research agents", "Verify claims before writing")
    result = assess_novelty_evidence(
        plan,
        _discovery(),
        {"phase": "retrieval_unavailable", "evidence": [], "retrieval_summary": {}},
    )

    assert result["status"] == "insufficient_evidence"
    assert result["verdict"]["code"] == "unresolved"
    assert result["reader_answer"]["citation_count"] == 0
    assert result["citation_verification"]["claim_count"] == 0
    assert result["discovery_candidates"][0]["title"] == "Prior A"


def test_novelty_plan_has_exactly_four_axes_and_bounded_queries() -> None:
    plan = plan_novelty_check("Scientific claim verification", "Use sentence-level evidence links", max_queries=4)

    assert list(plan["axes"]) == [
        "problem_framing",
        "core_mechanism",
        "key_insight",
        "application_domain",
    ]
    assert 3 <= len(plan["search_queries"]) <= 4
    assert plan["planner"] == "deterministic"


def test_lexical_fallback_never_assigns_a_novelty_level() -> None:
    plan = plan_novelty_check("Evidence-grounded research agents", "Verify claims before writing")
    result = assess_novelty_evidence(plan, _discovery(), _research(), chat_client=None)

    assert result["status"] == "provisional"
    assert result["verdict"]["code"] == "unresolved"
    assert result["verdict"]["level"] is None
    assert result["reader_answer"]["citation_count"] >= 1
