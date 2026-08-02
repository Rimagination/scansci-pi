from scansci_html.qa.agent import verify_citations


def test_claim_evidence_audit_requires_exact_source_anchor_for_each_supported_claim():
    answer = {
        "answer": [
            {
                "claim_id": "claim-1",
                "text": "Plant richness increased after grazing.",
                "quote_ids": ["quote-1"],
                "support_status": "supported",
            },
            {
                "claim_id": "claim-2",
                "text": "An uncited mechanism is established.",
                "quote_ids": [],
                "support_status": "unsupported",
            },
        ]
    }
    evidence = [
        {
            "quote_id": "quote-1",
            "evidence_id": "doc.s0001",
            "exact_quote": "Plant richness increased after grazing.",
            "html_path": "C:/library/source.html",
            "html_anchor": "#results",
        }
    ]

    audit = verify_citations(answer, evidence)

    assert audit["passed"] is False
    assert audit["audited_claim_count"] == 2
    assert audit["supported_anchor_claim_count"] == 1
    assert audit["claim_evidence_audit"][0]["audit_status"] == "supported"
    assert audit["claim_evidence_audit"][1]["audit_status"] == "needs_review"
