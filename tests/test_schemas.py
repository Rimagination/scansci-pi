import pytest
from pydantic import ValidationError

from scansci_html.qa.schemas import (
    AnswerPayloadSchema,
    ClaimVerificationPayloadSchema,
    ExtractedQuoteSchema,
)


def test_extracted_quote_schema_requires_evidence_ids_and_bounded_confidence():
    with pytest.raises(ValidationError):
        ExtractedQuoteSchema.model_validate(
            {
                "quote_id": "q0001",
                "evidence_ids": [],
                "exact_quote": "Exact quote.",
                "confidence": 0.5,
            }
        )

    with pytest.raises(ValidationError):
        ExtractedQuoteSchema.model_validate(
            {
                "quote_id": "q0001",
                "evidence_ids": ["doc1.s0001"],
                "exact_quote": "Exact quote.",
                "confidence": 1.5,
            }
        )


def test_answer_payload_schema_requires_quote_ids_for_each_claim():
    with pytest.raises(ValidationError):
        AnswerPayloadSchema.model_validate(
            {
                "answer": [
                    {
                        "claim_id": "c0001",
                        "text": "Claim text.",
                        "quote_ids": [],
                    }
                ],
                "limitations": [],
            }
        )


def test_claim_verification_schema_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ClaimVerificationPayloadSchema.model_validate(
            {
                "claims": [
                    {
                        "claim_id": "c0001",
                        "support_status": "maybe",
                        "verification_score": 0.5,
                    }
                ]
            }
        )
