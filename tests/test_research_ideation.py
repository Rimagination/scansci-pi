from __future__ import annotations

from scansci_html.research_ideation import (
    assemble_research_idea_card,
    audit_candidate_coherence,
    audit_candidate_falsifiability,
    audit_candidate_implementability,
    diagnose_research_bottleneck,
    generate_research_candidate,
    plan_research_idea,
)


def _research() -> dict:
    return {
        "evidence": [
            {"citation_id": "1", "evidence_id": "a.s1", "doc_id": "a", "paper": "Paper A", "section": "Methods", "exact_quote": "Current systems retrieve passages before generation."},
            {"citation_id": "2", "evidence_id": "a.s2", "doc_id": "a", "paper": "Paper A", "section": "Results", "exact_quote": "Citation errors remain after retrieval."},
            {"citation_id": "3", "evidence_id": "b.s1", "doc_id": "b", "paper": "Paper B", "section": "Methods", "exact_quote": "Sentence-level verification reduces unsupported claims."},
            {"citation_id": "4", "evidence_id": "b.s2", "doc_id": "b", "paper": "Paper B", "section": "Limitations", "exact_quote": "Verification adds latency and can miss semantic contradictions."},
        ]
    }


class _Client:
    def complete_json(self, _messages, *, schema_name):
        if schema_name == "research_bottleneck_diagnosis":
            return {
                "bottleneck_statement": "Retrieval does not guarantee that each generated sentence is supported.",
                "why_load_bearing": "Unsupported synthesis remains possible after relevant passages are found.",
                "evidence_claims": [
                    {"text": "Retrieval precedes generation.", "citation_ids": ["1"]},
                    {"text": "Verification reduces unsupported claims.", "citation_ids": ["3", "fake"]},
                ],
                "competing_explanations": ["Poor retrieval recall"],
                "success_condition": "Reduce unsupported sentence rate without excessive latency.",
                "scope_limits": ["Scientific literature synthesis"],
            }
        if schema_name == "research_candidate":
            return {
                "title": "Claim-locked synthesis",
                "hook": "Make evidence binding a generation invariant.",
                "core_mechanism": "Generate one sentence only after selecting and validating its evidence span.",
                "mechanism_steps": [
                    {"id": "s1", "action": "Select evidence", "input": "retrieved passages", "output": "candidate spans"},
                    {"id": "s2", "action": "Generate and verify", "input": "candidate spans", "output": "supported sentence"},
                ],
                "expected_contribution": "A sentence-level evidence contract.",
                "assumptions": ["Evidence spans contain the required fact"],
                "naive_baseline": "Retrieve passages and generate a full paragraph.",
                "why_baseline_insufficient": "Paragraph generation can mix supported and unsupported claims.",
                "evidence_basis": [
                    {"text": "Retrieval alone leaves citation errors.", "citation_ids": ["1", "2"]},
                    {"text": "Sentence verification can reduce unsupported claims.", "citation_ids": ["3"]},
                ],
                "falsification": {
                    "experiment": "Compare against paragraph-level RAG on a held-out corpus.",
                    "outcome_metric": "unsupported sentence rate",
                    "expected_direction": "lower",
                    "load_bearing_variable": "sentence-level evidence lock",
                    "negative_control": "shuffle evidence locks across sentences",
                    "failure_condition": "No reduction in unsupported sentence rate.",
                },
                "compute_budget": {"hardware": "1 GPU", "time": "2 days", "api_cost": "$100"},
                "claim_strength": "Empirical method hypothesis, not a guarantee.",
                "open_risks": ["Latency"],
            }
        if schema_name == "research_candidate_coherence":
            return {
                "dataflow": [
                    {"step_id": "s1", "inputs": ["passages"], "outputs": ["spans"], "missing": []},
                    {"step_id": "s2", "inputs": ["spans"], "outputs": ["sentence"], "missing": []},
                ],
                "dry_run": {"example": "Two passages and one claim", "step_trace": ["select span", "write claim", "verify"], "result": "supported sentence"},
                "degenerate_cases": [{"case": "no span", "result": "abstain"}],
                "claim_step_map": [{"claim": "evidence lock", "step_ids": ["s1", "s2"], "status": "conditional"}],
                "naive_baseline_comparison": "The baseline writes before sentence verification.",
                "findings": [],
                "verdict": "pass",
            }
        if schema_name == "research_candidate_implementability":
            return {
                "enriched_steps": [
                    {"step_id": "s1", "implementation": "Rank spans and retain top-k.", "dependencies": ["reranker"], "acceptance_check": "Every retained span has a source ID."},
                    {"step_id": "s2", "implementation": "Generate one sentence and run entailment.", "dependencies": ["writer", "verifier"], "acceptance_check": "Unsupported sentences are rejected."},
                ],
                "underspecified_points": [],
                "resource_assessment": "Fits the stated budget.",
                "verdict": "ready",
            }
        raise AssertionError(schema_name)


def test_evidence_grounded_idea_flow_produces_one_candidate_and_explicit_novelty_gate() -> None:
    plan = plan_research_idea("Reduce unsupported claims in scientific RAG")
    bottleneck = diagnose_research_bottleneck(plan, _research(), chat_client=_Client())
    candidate = generate_research_candidate(plan, bottleneck, _research(), chat_client=_Client())
    coherence = audit_candidate_coherence(candidate, chat_client=_Client())
    falsifiability = audit_candidate_falsifiability(candidate)
    implementability = audit_candidate_implementability(candidate, chat_client=_Client())
    card = assemble_research_idea_card(plan, _research(), bottleneck, candidate, coherence, falsifiability, implementability)

    assert bottleneck["status"] == "grounded"
    assert "fake" not in bottleneck["citation_ids"]
    assert candidate["status"] == "candidate"
    assert len(candidate["mechanism_steps"]) == 2
    assert coherence["verdict"] == "pass"
    assert coherence["dry_run"]["execution_status"] == "model_simulated"
    assert falsifiability["passed"] is True
    assert implementability["verdict"] == "ready"
    assert card["status"] == "ready_for_novelty_check"
    assert card["quality_gates"]["novelty"] is False
    assert card["required_next_gate"]["workflow_type"] == "novelty_check"
    assert card["citation_verification"]["passed"] is True


def test_ideation_does_not_invent_a_bottleneck_without_model_or_fulltext() -> None:
    plan = plan_research_idea("A new scientific agent")
    no_evidence = diagnose_research_bottleneck(plan, {"evidence": []}, chat_client=_Client())
    no_model = diagnose_research_bottleneck(plan, _research(), chat_client=None)

    assert no_evidence["status"] == "insufficient_evidence"
    assert no_model["status"] == "model_required"
    assert "bottleneck_statement" not in no_model


def test_falsifiability_gate_rejects_missing_or_tautological_negative_control() -> None:
    candidate = {
        "falsification": {
            "experiment": "A/B test",
            "outcome_metric": "accuracy",
            "expected_direction": "higher",
            "load_bearing_variable": "evidence lock",
            "negative_control": "evidence lock",
            "failure_condition": "No gain",
        }
    }
    result = audit_candidate_falsifiability(candidate)

    assert result["passed"] is False
    assert result["issues"]


def test_candidate_generation_rejects_hallucinated_citations() -> None:
    class _BadClient(_Client):
        def complete_json(self, messages, *, schema_name):
            raw = super().complete_json(messages, schema_name=schema_name)
            if schema_name == "research_candidate":
                raw["evidence_basis"] = [{"text": "Unsupported", "citation_ids": ["999"]}]
            return raw

    plan = plan_research_idea("Reduce unsupported claims")
    bottleneck = diagnose_research_bottleneck(plan, _research(), chat_client=_Client())
    candidate = generate_research_candidate(plan, bottleneck, _research(), chat_client=_BadClient())

    assert candidate["status"] == "invalid_model_output"
