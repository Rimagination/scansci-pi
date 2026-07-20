from __future__ import annotations

from collections import Counter
import re
from typing import Any, Protocol

from .text_tokenization import lexical_tokens


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_JINA_RERANKER_MODEL = "jinaai/jina-reranker-v3"


class LexicalReranker:
    """Deterministic reranker used until a cross-encoder provider is configured."""

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_terms = _query_terms(query)
        reranked: list[dict[str, Any]] = []
        for candidate in candidates:
            hit = dict(candidate)
            matched_terms = _matched_terms(hit, query_terms)
            lexical_score = _lexical_score(hit, query_terms)
            phrase_bonus = _phrase_bonus(str(hit.get("text", "")), query_terms)
            dense_score = float(hit.get("dense_score", 0.0))
            fts_score = float(hit.get("fts_score", 0.0))
            hit["matched_terms"] = matched_terms
            hit["score"] = round(lexical_score + phrase_bonus + dense_score + fts_score, 6)
            reranked.append(hit)
        reranked.sort(key=lambda hit: (-float(hit["score"]), str(hit.get("evidence_id", ""))))
        return reranked


class CrossEncoderReranker:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_CROSS_ENCODER_MODEL,
        model: Any | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.model = model if model is not None else _load_cross_encoder_model(model_name)
        self.batch_size = int(batch_size)

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pairs = [(query, _candidate_text(candidate)) for candidate in candidates]
        raw_scores = self.model.predict(pairs, batch_size=self.batch_size)
        scores = [float(score) for score in raw_scores]
        query_terms = _query_terms(query)
        reranked: list[dict[str, Any]] = []
        for candidate, score in zip(candidates, scores):
            hit = dict(candidate)
            hit["matched_terms"] = _matched_terms(hit, query_terms)
            hit["cross_encoder_score"] = round(score, 6)
            hit["score"] = round(score, 6)
            routes = [str(route) for route in hit.get("routes", []) or []]
            if "cross-encoder" not in routes:
                routes.append("cross-encoder")
            hit["routes"] = routes
            reranked.append(hit)
        reranked.sort(key=lambda hit: (-float(hit["score"]), str(hit.get("evidence_id", ""))))
        return reranked


class JinaReranker:
    """Reranker for Jina models that expose the official model.rerank API."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_JINA_RERANKER_MODEL,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.model = model if model is not None else _load_jina_reranker_model(model_name)

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        documents = [_candidate_text(candidate) for candidate in candidates]
        raw_results = self.model.rerank(query, documents, top_n=len(documents))
        scores_by_index: dict[int, float] = {
            int(result["index"]): float(result["relevance_score"]) for result in raw_results
        }
        query_terms = _query_terms(query)
        reranked: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            score = scores_by_index.get(index, float("-inf"))
            hit = dict(candidate)
            hit["matched_terms"] = _matched_terms(hit, query_terms)
            hit["jina_score"] = round(score, 6)
            hit["score"] = round(score, 6)
            routes = [str(route) for route in hit.get("routes", []) or []]
            if "jina-reranker" not in routes:
                routes.append("jina-reranker")
            hit["routes"] = routes
            reranked.append(hit)
        reranked.sort(key=lambda hit: (-float(hit["score"]), str(hit.get("evidence_id", ""))))
        return reranked


class CascadeReranker:
    """Run rerankers in stages, optionally trimming between expensive stages."""

    def __init__(self, stages: list[tuple[Reranker, int | None]]) -> None:
        if not stages:
            raise ValueError("CascadeReranker requires at least one stage")
        self.stages = stages

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current = list(candidates)
        for stage_index, (reranker, keep_top) in enumerate(self.stages, start=1):
            current = reranker.rerank(query, current)
            for hit in current:
                routes = [str(route) for route in hit.get("routes", []) or []]
                route_name = f"cascade-stage-{stage_index}"
                if route_name not in routes:
                    routes.append(route_name)
                hit["routes"] = routes
            if keep_top is not None and keep_top > 0:
                current = current[:keep_top]
        return current


def build_reranker(
    provider: str,
    *,
    model_name: str = "",
    model: Any | None = None,
    batch_size: int = 32,
) -> Reranker:
    name = (provider or "local").strip().lower()
    if name in {"local", "lexical"}:
        return LexicalReranker()
    if name in {"cross-encoder", "cross_encoder", "sentence-transformers"}:
        return CrossEncoderReranker(
            model_name=model_name or DEFAULT_CROSS_ENCODER_MODEL,
            model=model,
            batch_size=batch_size,
        )
    if name == "jina":
        return JinaReranker(
            model_name=model_name or DEFAULT_JINA_RERANKER_MODEL,
            model=model,
        )
    raise ValueError(f"Unsupported reranker provider: {provider}")


def _load_cross_encoder_model(model_name: str) -> Any:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "sentence-transformers is required for --reranker cross-encoder; "
            "install sentence-transformers or use --reranker local"
        ) from error
    return CrossEncoder(model_name)


def _load_jina_reranker_model(model_name: str) -> Any:
    try:
        from transformers import AutoModel
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "transformers is required for --reranker jina; install transformers or use --reranker local"
        ) from error
    return AutoModel.from_pretrained(model_name, trust_remote_code=True, torch_dtype="auto")


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            str(candidate.get("title", "")).strip(),
            str(candidate.get("section", "")).strip(),
            str(candidate.get("text", "")).strip(),
        ]
        if part
    )


def _lexical_score(row: dict[str, Any], query_terms: list[str]) -> float:
    text_counts = Counter(_tokens(str(row.get("text", ""))))
    title_counts = Counter(_tokens(str(row.get("title", ""))))
    section_counts = Counter(_tokens(str(row.get("section", ""))))
    score = 0.0
    for term in query_terms:
        score += text_counts.get(term, 0)
        score += title_counts.get(term, 0) * 0.4
        score += section_counts.get(term, 0) * 0.25
    return score


def _matched_terms(row: dict[str, Any], query_terms: list[str]) -> list[str]:
    haystack = set(
        _tokens(
            " ".join(
                [
                    str(row.get("text", "")),
                    str(row.get("title", "")),
                    str(row.get("section", "")),
                ]
            )
        )
    )
    return [term for term in query_terms if term in haystack]


def _phrase_bonus(text: str, query_terms: list[str]) -> float:
    tokens = _tokens(text)
    if len(query_terms) < 2 or len(tokens) < 2:
        return 0.0
    adjacent_pairs = set(zip(tokens, tokens[1:]))
    bonus = 0.0
    for pair in zip(query_terms, query_terms[1:]):
        if pair in adjacent_pairs:
            bonus += 0.5
    return bonus


def _query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in _tokens(query):
        if term in STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _tokens(value: str) -> list[str]:
    return lexical_tokens(value)


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
