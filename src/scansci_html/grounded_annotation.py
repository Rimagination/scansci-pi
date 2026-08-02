from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .retrieval import search_evidence_store


def split_draft_segments(
    text: str,
    *,
    min_segment_length: int = 8,
    max_segments: int = 0,
) -> list[dict[str, object]]:
    """Split user draft text into citation-sized claim candidates."""

    segments: list[dict[str, object]] = []
    for paragraph_index, paragraph in enumerate(_iter_paragraphs(text), start=1):
        for sentence in _split_paragraph_sentences(paragraph):
            normalized = _normalize_segment_text(sentence)
            if len(normalized) < int(min_segment_length):
                continue
            segments.append(
                {
                    "segment_id": f"c{len(segments) + 1:04d}",
                    "index": len(segments) + 1,
                    "paragraph_index": paragraph_index,
                    "text": normalized,
                }
            )
            if max_segments > 0 and len(segments) >= int(max_segments):
                return segments
    return segments


def ground_draft_text(
    db_path: str | Path,
    draft_text: str,
    *,
    limit: int = 3,
    initial_limit: int = 200,
    paper_recall_limit: int = 0,
    per_document_limit: int = 3,
    context_mode: str = "sentence",
    min_segment_length: int = 8,
    max_segments: int = 0,
    min_matched_terms: int = 1,
    query_variants: int = 4,
    candidate_pool_multiplier: int = 5,
    max_alternatives: int = 3,
    embedding_provider: object | None = None,
    reranker: object | None = None,
) -> dict[str, object]:
    segments = split_draft_segments(
        draft_text,
        min_segment_length=min_segment_length,
        max_segments=max_segments,
    )
    evidence_cards: list[dict[str, object]] = []
    citation_id_by_evidence_id: dict[str, str] = {}
    annotated_segments: list[dict[str, object]] = []

    for segment in segments:
        claim_text = str(segment["text"])
        queries = build_grounding_queries(claim_text, max_queries=query_variants)
        candidates = _retrieve_grounding_candidates(
            db_path,
            claim_text,
            queries,
            limit=limit,
            initial_limit=initial_limit,
            paper_recall_limit=paper_recall_limit,
            per_document_limit=per_document_limit,
            context_mode=context_mode,
            min_matched_terms=min_matched_terms,
            candidate_pool_multiplier=candidate_pool_multiplier,
            embedding_provider=embedding_provider,
            reranker=reranker,
        )
        ranked = _rank_and_verify_candidates(claim_text, candidates)
        selected = ranked[: max(0, int(limit))]
        alternatives = ranked[max(0, int(limit)) : max(0, int(limit)) + max(0, int(max_alternatives))]

        segment_evidence: list[dict[str, object]] = []
        citation_ids: list[str] = []
        for hit in selected:
            evidence_id = str(hit.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            citation_id = citation_id_by_evidence_id.get(evidence_id)
            if citation_id is None:
                citation_id = str(len(citation_id_by_evidence_id) + 1)
                citation_id_by_evidence_id[evidence_id] = citation_id
                evidence_cards.append(_evidence_card(citation_id, hit, cited_by=[str(segment["segment_id"])]))
            else:
                _append_cited_by(evidence_cards, citation_id, str(segment["segment_id"]))
            citation_ids.append(citation_id)
            segment_evidence.append(_segment_evidence(citation_id, hit))

        best = segment_evidence[0] if segment_evidence else {}
        support_status = str(best.get("support_status") or "no_evidence_found")
        best_support_score = _rounded_float(best.get("support_score"))
        annotated_segments.append(
            {
                **segment,
                "query": claim_text,
                "queries": queries,
                "status": support_status,
                "support_status": support_status,
                "best_support_score": best_support_score,
                "needs_review": support_status != "supported",
                "citation_ids": citation_ids,
                "evidence": segment_evidence,
                "alternatives": [_segment_evidence("", hit) for hit in alternatives],
                "missing_terms": list(best.get("missing_terms", []) or []),
                "verification_notes": list(best.get("verification_notes", []) or []),
            }
        )

    summary = _annotation_summary(annotated_segments, evidence_cards)
    return {
        "schema_version": "grounded_annotation.v2",
        "source_text": draft_text,
        "db_path": str(Path(db_path)),
        "segments": annotated_segments,
        "evidence_cards": evidence_cards,
        "retrieval": {
            "limit": int(limit),
            "initial_limit": int(initial_limit),
            "paper_recall_limit": int(paper_recall_limit),
            "per_document_limit": int(per_document_limit),
            "context_mode": context_mode,
            "min_matched_terms": int(min_matched_terms),
            "query_variants": int(query_variants),
            "candidate_pool_multiplier": int(candidate_pool_multiplier),
            "max_alternatives": int(max_alternatives),
            "verification": "local-claim-evidence-overlap-v2",
        },
        "summary": summary,
    }


def build_grounding_queries(claim_text: str, *, max_queries: int = 4) -> list[dict[str, object]]:
    claim = _normalize_segment_text(claim_text)
    variants: list[dict[str, object]] = []
    _add_query_variant(variants, "claim", claim, reason="original_claim")

    expanded = _expand_science_abbreviations(claim)
    if expanded != claim:
        _add_query_variant(variants, "expanded", expanded, reason="abbreviation_expansion")

    key_terms = _key_terms_query(claim)
    if key_terms and key_terms != claim.lower():
        _add_query_variant(variants, "key_terms", key_terms, reason="high_signal_terms")

    phrase_query = _phrase_query(expanded)
    if phrase_query and phrase_query not in {claim.lower(), key_terms}:
        _add_query_variant(variants, "phrases", phrase_query, reason="claim_phrases")

    return variants[: max(1, int(max_queries))]


def _retrieve_grounding_candidates(
    db_path: str | Path,
    claim_text: str,
    queries: list[dict[str, object]],
    *,
    limit: int,
    initial_limit: int,
    paper_recall_limit: int,
    per_document_limit: int,
    context_mode: str,
    min_matched_terms: int,
    candidate_pool_multiplier: int,
    embedding_provider: object | None,
    reranker: object | None,
) -> list[dict[str, Any]]:
    pool_limit = _retrieval_candidate_limit(
        limit,
        initial_limit,
        candidate_pool_multiplier=candidate_pool_multiplier,
    )
    candidates: dict[str, dict[str, Any]] = {}
    for query_index, query_item in enumerate(queries, start=1):
        query_text = str(query_item.get("query", "") or "").strip()
        if not query_text:
            continue
        hits = search_evidence_store(
            db_path,
            query_text,
            limit=pool_limit,
            initial_limit=initial_limit,
            paper_recall_limit=paper_recall_limit,
            per_document_limit=per_document_limit,
            context_mode=context_mode,
            embedding_provider=embedding_provider,
            reranker=reranker,
        )
        for hit in _filter_hits(hits, min_matched_terms=min_matched_terms):
            evidence_id = str(hit.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            candidate = candidates.setdefault(evidence_id, dict(hit))
            candidate["best_retrieval_score"] = max(
                _rounded_float(candidate.get("best_retrieval_score")),
                _rounded_float(hit.get("score")),
            )
            candidate["score"] = max(_rounded_float(candidate.get("score")), _rounded_float(hit.get("score")))
            _merge_list_field(candidate, "routes", hit.get("routes", []))
            _merge_list_field(candidate, "matched_terms", hit.get("matched_terms", []))
            retrieval_queries = list(candidate.get("retrieval_queries", []) or [])
            retrieval_queries.append(
                {
                    "index": query_index,
                    "label": str(query_item.get("label", "")),
                    "query": query_text,
                    "score": _rounded_float(hit.get("score")),
                    "matched_terms": list(hit.get("matched_terms", []) or []),
                }
            )
            candidate["retrieval_queries"] = retrieval_queries
    if not candidates and min_matched_terms > 0:
        return _retrieve_grounding_candidates(
            db_path,
            claim_text,
            queries,
            limit=limit,
            initial_limit=initial_limit,
            paper_recall_limit=paper_recall_limit,
            per_document_limit=per_document_limit,
            context_mode=context_mode,
            min_matched_terms=0,
            candidate_pool_multiplier=candidate_pool_multiplier,
            embedding_provider=embedding_provider,
            reranker=reranker,
        )
    return list(candidates.values())


def _rank_and_verify_candidates(claim_text: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        verification = _verify_claim_against_evidence(claim_text, candidate)
        hit = dict(candidate)
        hit.update(verification)
        hit["grounding_score"] = round(
            float(verification["support_score"]) + (_rounded_float(candidate.get("best_retrieval_score")) * 0.05),
            6,
        )
        ranked.append(hit)
    ranked.sort(
        key=lambda hit: (
            _support_rank(str(hit.get("support_status", ""))),
            -float(hit.get("grounding_score", 0.0) or 0.0),
            -float(hit.get("best_retrieval_score", 0.0) or 0.0),
            str(hit.get("evidence_id", "")),
        )
    )
    return ranked


def _verify_claim_against_evidence(claim_text: str, hit: dict[str, Any]) -> dict[str, object]:
    claim_tokens = _grounding_tokens(_expand_science_abbreviations(claim_text))
    evidence_text = " ".join(
        part
        for part in [
            _exact_quote(hit),
            _context_text(hit),
            str(hit.get("section", "")),
        ]
        if part
    )
    evidence_tokens = _grounding_tokens(_expand_science_abbreviations(evidence_text))
    if not claim_tokens or not evidence_tokens:
        return _verification_payload(
            support_status="weak_candidate",
            support_score=0.0,
            term_coverage=0.0,
            phrase_overlap=0.0,
            numeric_status="not_applicable",
            missing_terms=[],
            notes=["empty_claim_or_evidence_tokens"],
        )

    claim_terms = set(claim_tokens)
    evidence_terms = set(evidence_tokens)
    meaningful_terms = {term for term in claim_terms if _is_meaningful_grounding_term(term)}
    if not meaningful_terms:
        meaningful_terms = claim_terms
    covered_terms = meaningful_terms & evidence_terms
    missing_terms = sorted(meaningful_terms - evidence_terms)
    term_coverage = len(covered_terms) / max(1, len(meaningful_terms))
    phrase_overlap = _phrase_overlap_score(claim_tokens, evidence_tokens)
    numeric_status, numeric_score = _numeric_alignment(claim_text, evidence_text)
    negation_penalty = 0.15 if _negation_mismatch(claim_text, evidence_text) else 0.0
    evidence_directness = 1.0 if _exact_quote(hit) else 0.75
    support_ratio = (
        term_coverage * 0.55
        + phrase_overlap * 0.25
        + numeric_score * 0.15
        + evidence_directness * 0.05
        - negation_penalty
    )
    support_score = max(0.0, min(100.0, support_ratio * 100.0))
    support_status = _support_status(support_score, term_coverage, phrase_overlap, numeric_status)
    notes: list[str] = []
    if missing_terms:
        notes.append("missing_terms")
    if numeric_status == "mismatch":
        notes.append("number_mismatch")
    if negation_penalty:
        notes.append("possible_negation_mismatch")
    if support_status in {"partial_support", "weak_candidate"}:
        notes.append("human_review_recommended")
    return _verification_payload(
        support_status=support_status,
        support_score=support_score,
        term_coverage=term_coverage,
        phrase_overlap=phrase_overlap,
        numeric_status=numeric_status,
        missing_terms=missing_terms[:8],
        notes=notes,
    )


def _verification_payload(
    *,
    support_status: str,
    support_score: float,
    term_coverage: float,
    phrase_overlap: float,
    numeric_status: str,
    missing_terms: list[str],
    notes: list[str],
) -> dict[str, object]:
    return {
        "support_status": support_status,
        "support_score": round(float(support_score), 3),
        "term_coverage": round(float(term_coverage), 3),
        "phrase_overlap": round(float(phrase_overlap), 3),
        "numeric_status": numeric_status,
        "missing_terms": missing_terms,
        "verification_notes": notes,
    }


def _support_status(
    support_score: float,
    term_coverage: float,
    phrase_overlap: float,
    numeric_status: str,
) -> str:
    if numeric_status == "mismatch":
        return "weak_candidate"
    if support_score >= 68.0 and term_coverage >= 0.58:
        return "supported"
    if support_score >= 42.0 and (term_coverage >= 0.34 or phrase_overlap >= 0.2):
        return "partial_support"
    return "weak_candidate"


def _support_rank(status: str) -> int:
    ranks = {
        "supported": 0,
        "partial_support": 1,
        "weak_candidate": 2,
        "no_evidence_found": 3,
    }
    return ranks.get(status, 4)


def _annotation_summary(
    segments: list[dict[str, object]],
    evidence_cards: list[dict[str, object]],
) -> dict[str, object]:
    counts = {
        "supported": 0,
        "partial_support": 0,
        "weak_candidate": 0,
        "no_evidence_found": 0,
    }
    for segment in segments:
        status = str(segment.get("support_status") or "no_evidence_found")
        counts[status] = counts.get(status, 0) + 1
    cited_segments = sum(1 for segment in segments if segment.get("citation_ids"))
    return {
        "segments": len(segments),
        "cited_segments": cited_segments,
        "uncited_segments": len(segments) - cited_segments,
        "evidence_cards": len(evidence_cards),
        "supported_segments": counts.get("supported", 0),
        "partial_support_segments": counts.get("partial_support", 0),
        "weak_candidate_segments": counts.get("weak_candidate", 0),
        "no_evidence_segments": counts.get("no_evidence_found", 0),
        "needs_review_segments": sum(1 for segment in segments if segment.get("needs_review")),
    }


def _iter_paragraphs(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    current: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if _is_list_item(stripped):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(stripped)
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _split_paragraph_sentences(paragraph: str) -> list[str]:
    text = paragraph.strip()
    if not text:
        return []

    parts: list[str] = []
    start = 0
    index = 0
    sentence_endings = "\u3002\uff01\uff1f!?"
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        previous_char = text[index - 1] if index > 0 else ""
        boundary = False
        if char in sentence_endings:
            boundary = True
        elif char == ".":
            boundary = _is_sentence_period(text, index, previous_char, next_char)
        if boundary:
            end = index + 1
            parts.append(text[start:end])
            index = end
            while index < len(text) and text[index].isspace():
                index += 1
            start = index
            continue
        index += 1
    if start < len(text):
        parts.append(text[start:])
    return parts


def _is_sentence_period(text: str, index: int, previous_char: str, next_char: str) -> bool:
    if previous_char.isdigit() and next_char.isdigit():
        return False
    prefix = _last_alpha_token(text[:index]).lower()
    if prefix in {"al", "fig", "eq", "e.g", "i.e", "vs", "dr", "mr", "mrs", "ms"}:
        return False
    return not next_char or next_char.isspace()


def _last_alpha_token(text: str) -> str:
    match = re.search(r"([A-Za-z](?:[A-Za-z]|\.)*)$", text.strip())
    return match.group(1) if match else ""


def _is_list_item(text: str) -> bool:
    return bool(re.match(r"^([-*+]|\d+[.)]|[A-Za-z][.)])\s+", text))


def _normalize_segment_text(text: str) -> str:
    stripped = re.sub(r"^([-*+]|\d+[.)]|[A-Za-z][.)])\s+", "", text.strip())
    return re.sub(r"\s+", " ", stripped).strip()


def _add_query_variant(
    variants: list[dict[str, object]],
    label: str,
    query: str,
    *,
    reason: str,
) -> None:
    normalized = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized:
        return
    dedupe_key = normalized.lower()
    if any(str(item.get("query", "")).lower() == dedupe_key for item in variants):
        return
    variants.append({"label": label, "query": normalized, "reason": reason})


def _expand_science_abbreviations(text: str) -> str:
    expanded = str(text or "")
    replacements = [
        (r"\brIL[- ]?15\b", "rIL15 interleukin 15 IL 15"),
        (r"\bIL[- ]?15\b", "IL 15 interleukin 15"),
        (r"\bTregs?\b", "regulatory T cells Tregs"),
        (r"\bDCs?\b", "dendritic cells DC"),
        (r"\bTME\b", "tumor microenvironment TME"),
        (r"\bLY2157299\b", "LY2157299 galunisertib"),
    ]
    for pattern, replacement in replacements:
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", expanded).strip()


def _key_terms_query(text: str) -> str:
    tokens = _grounding_tokens(_expand_science_abbreviations(text))
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not _is_meaningful_grounding_term(token) or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= 10:
            break
    return " ".join(terms)


def _phrase_query(text: str) -> str:
    tokens = _grounding_tokens(text)
    phrases: list[str] = []
    for size in (3, 2):
        for phrase in zip(*(tokens[offset:] for offset in range(size))):
            if not any(_is_meaningful_grounding_term(term) for term in phrase):
                continue
            value = " ".join(phrase)
            if value not in phrases:
                phrases.append(value)
            if len(phrases) >= 5:
                return " ".join(phrases)
    return " ".join(phrases)


def _filter_hits(hits: list[dict[str, Any]], *, min_matched_terms: int) -> list[dict[str, Any]]:
    if min_matched_terms <= 0:
        return hits
    filtered: list[dict[str, Any]] = []
    for hit in hits:
        matched_terms = list(hit.get("matched_terms", []) or [])
        if len(matched_terms) >= int(min_matched_terms):
            filtered.append(hit)
    return filtered


def _retrieval_candidate_limit(
    limit: int,
    initial_limit: int,
    *,
    candidate_pool_multiplier: int,
) -> int:
    requested = max(0, int(limit))
    if requested <= 0:
        return 0
    multiplier = max(1, int(candidate_pool_multiplier))
    return min(max(requested * multiplier, requested), max(requested, int(initial_limit)))


def _grounding_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if token not in _GROUNDING_STOPWORDS
    ]


def _is_meaningful_grounding_term(term: str) -> bool:
    return len(term) >= 4 or any(char.isdigit() for char in term) or term in _SHORT_SCIENCE_TERMS


def _phrase_overlap_score(claim_tokens: list[str], evidence_tokens: list[str]) -> float:
    claim_bigrams = set(zip(claim_tokens, claim_tokens[1:]))
    evidence_bigrams = set(zip(evidence_tokens, evidence_tokens[1:]))
    claim_trigrams = set(zip(claim_tokens, claim_tokens[1:], claim_tokens[2:]))
    evidence_trigrams = set(zip(evidence_tokens, evidence_tokens[1:], evidence_tokens[2:]))
    if not claim_bigrams and not claim_trigrams:
        return 0.0
    matched = len(claim_bigrams & evidence_bigrams) + (2 * len(claim_trigrams & evidence_trigrams))
    possible = len(claim_bigrams) + (2 * len(claim_trigrams))
    return min(1.0, matched / max(1, possible))


def _numeric_alignment(claim_text: str, evidence_text: str) -> tuple[str, float]:
    claim_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", claim_text))
    if not claim_numbers:
        return "not_applicable", 1.0
    evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", evidence_text))
    if claim_numbers <= evidence_numbers:
        return "matched", 1.0
    if claim_numbers & evidence_numbers:
        return "partial", 0.5
    return "mismatch", 0.0


def _negation_mismatch(claim_text: str, evidence_text: str) -> bool:
    claim_negated = bool(re.search(r"\b(no|not|without|failed|lack|lacks|absence|absent)\b", claim_text.lower()))
    evidence_negated = bool(re.search(r"\b(no|not|without|failed|lack|lacks|absence|absent)\b", evidence_text.lower()))
    return claim_negated != evidence_negated


def _merge_list_field(candidate: dict[str, Any], field: str, values: object) -> None:
    merged = [str(value) for value in candidate.get(field, []) or []]
    for value in values or []:
        string_value = str(value)
        if string_value and string_value not in merged:
            merged.append(string_value)
    candidate[field] = merged


def _append_cited_by(cards: list[dict[str, object]], citation_id: str, segment_id: str) -> None:
    for card in cards:
        if str(card.get("citation_id", "")) != citation_id:
            continue
        cited_by = [str(value) for value in card.get("cited_by", []) or []]
        if segment_id not in cited_by:
            cited_by.append(segment_id)
        card["cited_by"] = cited_by
        return


def _segment_evidence(citation_id: str, hit: dict[str, Any]) -> dict[str, object]:
    return {
        "citation_id": citation_id,
        "evidence_id": str(hit.get("evidence_id", "")),
        "title": str(hit.get("title", "")),
        "doi": str(hit.get("doi", "")),
        "section": str(hit.get("section", "")),
        "section_kind": str(hit.get("section_kind", "")),
        "exact_quote": _exact_quote(hit),
        "context_text": _context_text(hit),
        "score": _rounded_float(hit.get("score")),
        "best_retrieval_score": _rounded_float(hit.get("best_retrieval_score")),
        "grounding_score": _rounded_float(hit.get("grounding_score")),
        "support_score": _rounded_float(hit.get("support_score")),
        "support_status": str(hit.get("support_status", "weak_candidate")),
        "term_coverage": _rounded_float(hit.get("term_coverage")),
        "phrase_overlap": _rounded_float(hit.get("phrase_overlap")),
        "numeric_status": str(hit.get("numeric_status", "")),
        "missing_terms": list(hit.get("missing_terms", []) or []),
        "verification_notes": list(hit.get("verification_notes", []) or []),
        "matched_terms": list(hit.get("matched_terms", []) or []),
        "routes": list(hit.get("routes", []) or []),
        "retrieval_queries": list(hit.get("retrieval_queries", []) or []),
        "html_path": str(hit.get("html_path", "")),
        "html_anchor": str(hit.get("html_anchor", "")),
        "source_href": _source_href(hit),
    }


def _evidence_card(
    citation_id: str,
    hit: dict[str, Any],
    *,
    cited_by: list[str],
) -> dict[str, object]:
    card = _segment_evidence(citation_id, hit)
    card.update(
        {
            "doc_id": str(hit.get("doc_id", "")),
            "source_url": str(hit.get("source_url", "")),
            "publication_year": hit.get("publication_year"),
            "sentence_index": hit.get("sentence_index"),
            "block_id": str(hit.get("block_id", "")),
            "block_type": str(hit.get("block_type", "")),
            "cited_by": cited_by,
        }
    )
    return card


def _exact_quote(hit: dict[str, Any]) -> str:
    return str(hit.get("span_text") or hit.get("text") or "").strip()


def _context_text(hit: dict[str, Any]) -> str:
    quote = _exact_quote(hit)
    text = str(hit.get("text", "") or "").strip()
    if text and text != quote:
        return text
    parent_text = str(hit.get("parent_text", "") or "").strip()
    if parent_text and parent_text != quote:
        return parent_text
    return ""


def _source_href(hit: dict[str, Any]) -> str:
    html_path = str(hit.get("html_path", "") or "").strip()
    html_anchor = str(hit.get("html_anchor", "") or "").strip()
    if not html_path:
        return ""
    if not html_anchor:
        return html_path
    return f"{html_path}#{html_anchor}"


def _rounded_float(value: object) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


_GROUNDING_STOPWORDS = {
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
    "these",
    "this",
    "to",
    "was",
    "were",
    "with",
}

_SHORT_SCIENCE_TERMS = {
    "dc",
    "il",
    "cd4",
    "cd8",
    "treg",
    "tregs",
}
