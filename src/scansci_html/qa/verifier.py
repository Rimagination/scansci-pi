from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from ..text_tokenization import lexical_tokens
from .quote_extractor import ChatJsonClient
from .schemas import ClaimVerificationPayloadSchema


SUPPORT_STATUSES = {
    "supported",
    "partially_supported",
    "contradicted",
    "unsupported",
    "not_enough_information",
}


def verify_answer_claims(answer: dict[str, Any], evidence_table: list[dict[str, Any]]) -> dict[str, Any]:
    verified = deepcopy(answer)
    quote_texts = {
        str(row.get("quote_id", "")): str(row.get("exact_quote", ""))
        for row in evidence_table
        if str(row.get("quote_id", ""))
    }
    summary = {
        "supported_claims": [],
        "partially_supported_claims": [],
        "contradicted_claims": [],
        "unsupported_claims": [],
        "not_enough_information_claims": [],
    }

    claims = list(verified.get("answer", []) or [])
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        claim_text = str(claim.get("text", ""))
        quote_ids = [str(quote_id) for quote_id in claim.get("quote_ids", []) or []]
        bound_quotes = [quote_texts[quote_id] for quote_id in quote_ids if quote_id in quote_texts]
        if not bound_quotes:
            status = "not_enough_information"
            score = 0.0
        elif _is_contradicted(claim_text, bound_quotes):
            status = "contradicted"
            score = 0.0
        else:
            score = _support_score(claim_text, bound_quotes)
            if score >= 0.75:
                status = "supported"
            elif score >= 0.5:
                status = "partially_supported"
            else:
                status = "unsupported"
        claim["support_status"] = status
        claim["verification_score"] = round(score, 2)
        summary[f"{status}_claims"].append(claim_id)

    verified["answer"] = claims
    verified["verification"] = summary
    return verified


def verification_counts(verified_answer: dict[str, Any]) -> dict[str, int]:
    claims = list(verified_answer.get("answer", []) or [])
    counts = {
        "claims": len(claims),
        "supported": 0,
        "partially_supported": 0,
        "contradicted": 0,
        "unsupported": 0,
        "not_enough_information": 0,
    }
    for claim in claims:
        status = str(claim.get("support_status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def apply_verification_policy(verified_answer: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(verified_answer)
    claims = list(result.get("answer", []) or [])
    if not claims:
        result["insufficient_evidence"] = True
        result["verification_policy"] = {"action": "abstain", "reason": "no answer claims"}
        return result

    supported_statuses = {"supported", "partially_supported"}
    has_supported = any(str(claim.get("support_status", "")) in supported_statuses for claim in claims)
    if has_supported:
        result["verification_policy"] = {"action": "keep", "reason": "at least one claim is supported"}
        return result

    result["insufficient_evidence"] = True
    limitations = [str(item) for item in result.get("limitations", []) or []]
    message = "No supported or partially supported claims remained after verification."
    if message not in limitations:
        limitations.append(message)
    result["limitations"] = limitations
    result["verification_policy"] = {
        "action": "abstain",
        "reason": "no supported or partially supported claims",
    }
    return result


def verify_answer_claims_with_llm(
    answer: dict[str, Any],
    evidence_table: list[dict[str, Any]],
    *,
    chat_client: ChatJsonClient,
) -> dict[str, Any]:
    verified = deepcopy(answer)
    messages = [
        {
            "role": "system",
            "content": (
                "Judge whether each claim is supported by its cited quotes. "
                "Use only these statuses: supported, partially_supported, contradicted, "
                "unsupported, not_enough_information."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "answer": answer,
                    "evidence_table": evidence_table,
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = ClaimVerificationPayloadSchema.model_validate(
        chat_client.complete_json(messages, schema_name="claim_verification") or {}
    )
    status_by_claim = {
        item.claim_id: (
            item.support_status,
            item.verification_score,
        )
        for item in payload.claims
    }
    summary = _empty_summary()
    claims = list(verified.get("answer", []) or [])
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        status, score = status_by_claim.get(claim_id, ("not_enough_information", 0.0))
        if status not in SUPPORT_STATUSES:
            raise ValueError(f"unsupported verification status for {claim_id}: {status}")
        claim["support_status"] = status
        claim["verification_score"] = round(score, 2)
        summary[f"{status}_claims"].append(claim_id)
    verified["answer"] = claims
    verified["verification"] = summary
    return verified


def _support_score(claim_text: str, quotes: list[str]) -> float:
    claim_terms = _content_terms(claim_text)
    if not claim_terms:
        return 0.0
    quote_terms = set(_content_terms(" ".join(quotes)))
    matched = [term for term in claim_terms if term in quote_terms]
    return len(matched) / len(claim_terms)


def _empty_summary() -> dict[str, list[str]]:
    return {
        "supported_claims": [],
        "partially_supported_claims": [],
        "contradicted_claims": [],
        "unsupported_claims": [],
        "not_enough_information_claims": [],
    }


def _is_contradicted(claim_text: str, quotes: list[str]) -> bool:
    claim = claim_text.lower()
    quote = " ".join(quotes).lower()
    positive_increase = any(term in claim for term in ("increase", "increased", "higher", "improved"))
    if positive_increase and _has_negated_increase(claim):
        return False
    negated_increase = any(
        phrase in quote
        for phrase in (
            "did not increase",
            "does not increase",
            "no increase",
            "not increased",
            "did not improve",
            "does not improve",
            "no improvement",
        )
    )
    opposite_decrease = any(term in quote for term in ("decreased", "lower", "reduced"))
    return positive_increase and (negated_increase or opposite_decrease)


def _has_negated_increase(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "did not increase",
            "does not increase",
            "no increase",
            "not increased",
            "did not improve",
            "does not improve",
            "no improvement",
        )
    )


def _content_terms(text: str) -> list[str]:
    return [term for term in lexical_tokens(text) if term not in STOPWORDS]


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "what",
    "which",
    "with",
}
