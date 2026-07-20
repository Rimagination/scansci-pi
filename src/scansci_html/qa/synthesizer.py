from __future__ import annotations

import json
import re
from typing import Any

from .quote_extractor import ChatJsonClient
from .schemas import AnswerPayloadSchema
from ..text_tokenization import lexical_tokens


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
    ranked_rows = _rank_local_evidence(question, evidence_table)
    if len(evidence_table) > 1:
        ranked_rows = ranked_rows[: 1 if _is_direct_question(question) else 3]
    for row in ranked_rows:
        claim_text = (
            _best_local_excerpt(question, str(row.get("exact_quote", "")))
            if len(evidence_table) > 1
            else str(row.get("claim_target", "")).strip()
        )
        claim_text = claim_text or str(row.get("claim_target", "")).strip()
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


def _rank_local_evidence(question: str, evidence_table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _question_evidence_terms(question)
    indexed = list(enumerate(evidence_table))

    def score(item: tuple[int, dict[str, Any]]) -> tuple[float, int]:
        index, row = item
        quote = " ".join(str(row.get("exact_quote", "")).split()).casefold()
        matched = sum(1.0 for term in terms if term in quote)
        confidence = float(row.get("confidence", 0.0) or 0.0)
        length_penalty = max(0.0, (len(quote) - 420) / 700)
        return (matched + confidence - length_penalty, -index)

    return [row for _, row in sorted(indexed, key=score, reverse=True)]


def _question_evidence_terms(question: str) -> set[str]:
    terms = {
        token.casefold()
        for token in lexical_tokens(question)
        if re.fullmatch(r"[a-z0-9][a-z0-9.-]*", token) and len(token) >= 3
    }
    mappings = {
        "双向": {"bidirectional", "left and right", "both directions"},
        "左侧": {"left-to-right", "previous tokens", "left context"},
        "自注意力": {"self-attention", "self attention"},
        "掩码": {"masked language", "mlm"},
        "微调": {"fine-tuning", "fine tuning"},
        "少样本": {"few-shot", "few shot"},
        "零样本": {"zero-shot", "zero shot"},
        "自回归": {"autoregressive", "left-to-right", "next token"},
    }
    folded = question.casefold()
    for cue, values in mappings.items():
        if cue in folded:
            terms.update(values)
    return terms


def _best_local_excerpt(question: str, exact_quote: str) -> str:
    clean = " ".join(str(exact_quote or "").split()).strip()
    if not clean:
        return ""
    terms = _question_evidence_terms(question)
    segments = [
        segment.strip(" •")
        for segment in re.split(r"(?<=[.!?。！？])\s+|\s*[•]\s*", clean)
        if segment.strip(" •")
    ]
    if not segments:
        segments = [clean]
    best = max(
        enumerate(segments),
        key=lambda item: (
            sum(term in item[1].casefold() for term in terms),
            -abs(len(item[1]) - 180),
            -item[0],
        ),
    )[1]
    best = re.split(r"\s+\d+(?:https?://|www\.)", best, maxsplit=1, flags=re.I)[0]
    best = re.sub(r"(?<=[.!?。！？])\d+$", "", best).strip()
    best = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", best)
    if len(best) <= 360:
        return best
    clipped = best[:360]
    boundary = clipped.rfind(" ")
    return clipped[:boundary].rstrip(" ,;:") if boundary >= 120 else ""


def _is_direct_question(question: str) -> bool:
    value = question.strip().casefold()
    return any(marker in value for marker in ("？", "?", "是否", "还是", "吗", "does ", "is ", "are ", "can "))


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
                "Answer in the same language as the question. Use only relevant rows from the evidence table. "
                "Return 1 to at most 4 concise, non-overlapping claims ordered by importance; never repeat a claim. "
                "Every claim must be directly entailed by its exact supporting quote_ids. Do not infer the objective, "
                "architecture or result of an entity that the cited quote does not name. Do not cite any other source."
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
    seen_claim_texts: set[str] = set()
    for claim in answer_claims:
        normalized_text = " ".join(claim.text.split()).casefold()
        if not normalized_text or normalized_text in seen_claim_texts:
            continue
        seen_claim_texts.add(normalized_text)
        quote_ids = [str(quote_id) for quote_id in claim.quote_ids]
        for quote_id in quote_ids:
            if quote_id not in known_quote_ids:
                raise ValueError(f"answer claim references unknown quote_id: {quote_id}")
        claims.append(
            {
                "claim_id": claim.claim_id or f"c{len(claims) + 1:04d}",
                "text": claim.text,
                "quote_ids": quote_ids,
                "support_status": "pending_verification",
            }
        )
        if len(claims) >= 4:
            break
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
