from __future__ import annotations

import json
from typing import Any

from .quote_extractor import ChatJsonClient
from .schemas import AnswerPayloadSchema


def synthesize_answer(question: str, evidence_table: list[dict[str, Any]]) -> dict[str, object]:
    if not evidence_table:
        return {
            "question": question,
            "answer": [],
            "limitations": ["No validated evidence quotes were available for this question."],
            "insufficient_evidence": True,
        }

    if _is_conflict_question(question):
        conflict_claim = _conflict_claim(evidence_table)
        if conflict_claim:
            return {
                "question": question,
                "answer": [conflict_claim],
                "limitations": [],
                "insufficient_evidence": False,
            }

    claims: list[dict[str, object]] = []
    seen_claims: dict[str, list[str]] = {}
    for row in evidence_table:
        claim_text = str(row.get("claim_target", "")).strip()
        quote_id = str(row.get("quote_id", "")).strip()
        if not claim_text or not quote_id:
            continue
        seen_claims.setdefault(claim_text, [])
        if quote_id not in seen_claims[claim_text]:
            seen_claims[claim_text].append(quote_id)

    for index, (claim_text, quote_ids) in enumerate(seen_claims.items(), start=1):
        claims.append(
            {
                "claim_id": f"c{index:04d}",
                "text": claim_text,
                "quote_ids": quote_ids,
                "support_status": "supported_by_evidence_table",
            }
        )

    return {
        "question": question,
        "answer": claims,
        "limitations": [],
        "insufficient_evidence": False if claims else True,
    }


def _is_conflict_question(question: str) -> bool:
    value = question.lower()
    return any(term in value for term in ("conflict", "conflicting", "contradict", "contradiction", "inconsistent"))


def _conflict_claim(evidence_table: list[dict[str, Any]]) -> dict[str, object] | None:
    parts: list[str] = []
    quote_ids: list[str] = []
    for row in evidence_table:
        quote_id = str(row.get("quote_id", "")).strip()
        claim_text = str(row.get("claim_target", "") or row.get("exact_quote", "")).strip()
        if not quote_id or not claim_text:
            continue
        prefix = "One source reports that" if not parts else "another source reports that"
        parts.append(f"{prefix} {_without_terminal_period(claim_text)}")
        if quote_id not in quote_ids:
            quote_ids.append(quote_id)
    if len(parts) < 2:
        return None
    return {
        "claim_id": "c0001",
        "text": "; ".join(parts) + ".",
        "quote_ids": quote_ids,
        "support_status": "supported_by_evidence_table",
    }


def _without_terminal_period(text: str) -> str:
    return text.rstrip().rstrip(".")


def synthesize_answer_with_llm(
    question: str,
    evidence_table: list[dict[str, Any]],
    *,
    chat_client: ChatJsonClient,
) -> dict[str, object]:
    if not evidence_table:
        return synthesize_answer(question, evidence_table)
    compact_evidence = _compact_evidence_for_llm(evidence_table)
    messages = [
        {
            "role": "system",
            "content": (
                "Write concise answer claims using only the provided evidence table. "
                "Every claim must include quote_ids from the table. Do not cite any other source."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "evidence_table": compact_evidence,
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = AnswerPayloadSchema.model_validate(chat_client.complete_json(messages, schema_name="answer_claims") or {})
    answer_claims = payload.answer
    known_quote_ids = {str(row.get("quote_id", "")) for row in evidence_table}
    claims: list[dict[str, object]] = []
    for index, claim in enumerate(answer_claims, start=1):
        quote_ids = [str(quote_id) for quote_id in claim.quote_ids]
        for quote_id in quote_ids:
            if quote_id not in known_quote_ids:
                raise ValueError(f"answer claim references unknown quote_id: {quote_id}")
        claims.append(
            {
                "claim_id": claim.claim_id or f"c{index:04d}",
                "text": claim.text,
                "quote_ids": quote_ids,
                "support_status": "pending_verification",
            }
        )
    return {
        "question": question,
        "answer": claims,
        "limitations": [str(item) for item in payload.limitations],
        "insufficient_evidence": False if claims else True,
    }


def _compact_evidence_for_llm(evidence_table: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep evidence prompts below conservative compatible-gateway limits.

    The complete evidence rows remain in ScanSci for citation verification and
    source navigation.  The model only needs the quote identifier, exact quote,
    claim hint and compact provenance to write supported claims.  This mirrors
    mature agent runtimes that prune bulky tool metadata before the next model
    step instead of sending paths, anchors and duplicate parent blocks back to
    every provider.
    """

    rows: list[dict[str, str]] = []
    for raw in evidence_table[:12]:
        row = {
            "quote_id": str(raw.get("quote_id", "")),
            "claim_target": _truncate_utf8(str(raw.get("claim_target", "")), 480),
            "exact_quote": _truncate_utf8(str(raw.get("exact_quote", "")), 720),
            "paper": _truncate_utf8(str(raw.get("paper", "")), 240),
            "section": _truncate_utf8(str(raw.get("section", "")), 120),
            "stance": _truncate_utf8(str(raw.get("stance", "")), 80),
        }
        rows.append(row)

    # Managed and self-hosted compatible gateways often enforce a request-body
    # limit lower than the advertised model context.  Stay within 12 KiB while
    # retaining source diversity whenever possible.
    while len(json.dumps(rows, ensure_ascii=False).encode("utf-8")) > 12_000 and len(rows) > 3:
        rows.pop()
    return rows


def _truncate_utf8(value: str, max_bytes: int) -> str:
    clean = " ".join(str(value or "").split())
    encoded = clean.encode("utf-8")
    if len(encoded) <= max_bytes:
        return clean
    clipped = encoded[: max(1, int(max_bytes) - 3)]
    while clipped:
        try:
            return clipped.decode("utf-8") + "…"
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "…"
