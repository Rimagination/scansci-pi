from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Protocol

from .schemas import ExtractedQuoteSchema


class ChatJsonClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        ...


@dataclass(frozen=True)
class ExtractedQuote:
    quote_id: str
    question: str
    evidence_ids: list[str]
    exact_quote: str
    role: str
    claim_hint: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_quotes(
    question: str,
    evidence_hits: Iterable[dict[str, Any]],
    *,
    max_quotes: int = 8,
) -> list[ExtractedQuote]:
    selected: list[dict[str, Any]] = []
    for hit in evidence_hits:
        evidence_id = str(hit.get("evidence_id", "")).strip()
        text = str(hit.get("text", "")).strip()
        matched_terms = list(hit.get("matched_terms", []) or [])
        if not evidence_id or not text or not matched_terms:
            continue
        selected.append(hit)
        if len(selected) >= max(0, int(max_quotes)):
            break

    max_score = max((float(hit.get("score", 0.0) or 0.0) for hit in selected), default=0.0)
    quotes: list[ExtractedQuote] = []
    for index, hit in enumerate(selected, start=1):
        text = _exact_quote_text(hit)
        confidence = _confidence(float(hit.get("score", 0.0) or 0.0), max_score)
        quotes.append(
            ExtractedQuote(
                quote_id=f"q{index:04d}",
                question=question,
                evidence_ids=[str(hit["evidence_id"])],
                exact_quote=text,
                role="supports",
                claim_hint=_claim_hint(text),
                confidence=confidence,
            )
        )
    evidence_by_id = {str(hit.get("evidence_id", "")): hit for hit in selected}
    validate_quotes(quotes, evidence_by_id)
    return quotes


def extract_quotes_with_llm(
    question: str,
    evidence_hits: Iterable[dict[str, Any]],
    *,
    chat_client: ChatJsonClient,
) -> list[ExtractedQuote]:
    hits = list(evidence_hits)
    evidence_by_id = {str(hit.get("evidence_id", "")): hit for hit in hits if str(hit.get("evidence_id", ""))}
    messages = [
        {
            "role": "system",
            "content": (
                "Extract exact evidence quotes for the question. Use only provided evidence_ids. "
                "Every exact_quote must be copied verbatim from the corresponding evidence text."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "evidence": [
                        {
                            "evidence_id": hit.get("evidence_id", ""),
                            "text": hit.get("text", ""),
                            "title": hit.get("title", ""),
                            "section": hit.get("section", ""),
                        }
                        for hit in hits
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    payload = chat_client.complete_json(messages, schema_name="extracted_quotes")
    quote_items = payload.get("quotes", []) if isinstance(payload, dict) else payload
    quotes: list[ExtractedQuote] = []
    for index, item in enumerate(quote_items or [], start=1):
        item_payload = dict(item)
        item_payload.setdefault("quote_id", f"q{index:04d}")
        schema = ExtractedQuoteSchema.model_validate(item_payload)
        quotes.append(
            ExtractedQuote(
                quote_id=schema.quote_id,
                question=question,
                evidence_ids=schema.evidence_ids,
                exact_quote=schema.exact_quote,
                role=schema.role,
                claim_hint=schema.claim_hint,
                confidence=schema.confidence,
            )
        )
    validate_quotes(quotes, evidence_by_id)
    return quotes


def validate_quotes(
    quotes: Iterable[ExtractedQuote],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    for quote in quotes:
        if not quote.evidence_ids:
            raise ValueError(f"{quote.quote_id} has no evidence_ids")
        for evidence_id in quote.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise ValueError(f"{quote.quote_id} references unknown evidence_id: {evidence_id}")
            source_text = str(evidence.get("text", ""))
            if quote.exact_quote not in source_text:
                raise ValueError(
                    f"{quote.quote_id} exact_quote is not an exact substring of evidence_id {evidence_id}"
                )


def _confidence(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.0
    return round(max(0.0, min(1.0, score / max_score)), 2)


def _claim_hint(text: str) -> str:
    value = text.strip()
    if len(value) <= 180:
        return value
    return value[:177].rstrip() + "..."


def _exact_quote_text(hit: dict[str, Any]) -> str:
    context_quote_text = str(hit.get("context_quote_text", "")).strip()
    if context_quote_text:
        return context_quote_text
    span_text = str(hit.get("span_text", "")).strip()
    if span_text:
        return span_text
    return str(hit.get("text", "")).strip()
