from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SupportStatus = Literal[
    "supported",
    "partially_supported",
    "contradicted",
    "unsupported",
    "not_enough_information",
]


class ExtractedQuoteSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quote_id: str
    evidence_ids: list[str] = Field(min_length=1)
    exact_quote: str = Field(min_length=1)
    role: str = "supports"
    claim_hint: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AnswerClaimSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    text: str = Field(min_length=1)
    quote_ids: list[str] = Field(min_length=1)


class AnswerPayloadSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: list[AnswerClaimSchema] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClaimVerificationSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    support_status: SupportStatus
    verification_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ClaimVerificationPayloadSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[ClaimVerificationSchema] = Field(default_factory=list)
