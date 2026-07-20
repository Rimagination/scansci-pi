from __future__ import annotations

from collections import Counter, defaultdict
import json
import re
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Any

from .embeddings import EmbeddingProvider, HashingEmbeddingProvider, cosine_similarity, embed_query
from .rerankers import LexicalReranker, Reranker
from .text_tokenization import lexical_tokens
from .vector_index import cached_hashing_candidates


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


def search_evidence_index(
    index_path: str | Path,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_terms = _query_terms(query)
    if not query_terms:
        return []

    hits: list[dict[str, Any]] = []
    for row in _load_jsonl(Path(index_path)):
        score, matched_terms = _score_row(row, query_terms)
        if score <= 0:
            continue
        hit = dict(row)
        hit["score"] = round(score, 6)
        hit["matched_terms"] = matched_terms
        hits.append(hit)

    hits.sort(key=lambda hit: (-float(hit["score"]), str(hit.get("block_id", ""))))
    return hits[: max(0, int(limit))]


def search_evidence_store(
    db_path: str | Path,
    query: str,
    *,
    limit: int = 5,
    initial_limit: int = 200,
    paper_recall_limit: int = 0,
    per_document_limit: int = 5,
    filters: dict[str, Any] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    context_mode: str = "sentence",
    trace: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    started_at = perf_counter()
    query_terms = _query_terms(query)
    if not query_terms:
        _append_retrieval_trace(
            trace,
            query=query,
            query_terms=query_terms,
            total_rows=0,
            filtered_rows=0,
            initial_limit=initial_limit,
            dense_limit=-1,
            paper_recall_limit=paper_recall_limit,
            paper_recalled_documents=0,
            per_document_limit=per_document_limit,
            fts_candidates=0,
            dense_candidates=0,
            unique_candidates=0,
            reranked_candidates=0,
            returned_hits=0,
            route_counts={},
            started_at=started_at,
            status="empty_query",
            dense_backend="none",
        )
        return []

    db = Path(db_path)
    rows = _load_evidence_spans(db)
    total_rows = len(rows)
    rows = _filter_evidence_spans(rows, filters or {})
    provider = embedding_provider or HashingEmbeddingProvider()
    recalled_documents: list[dict[str, Any]] = []
    if paper_recall_limit > 0 and rows:
        recalled_documents = recall_relevant_documents(
            db,
            query,
            limit=paper_recall_limit,
            filters=filters,
            embedding_provider=provider,
            trace=trace,
            rows=rows,
        )
        recalled_doc_ids = {str(document.get("doc_id", "")) for document in recalled_documents}
        recalled_doc_ids.discard("")
        rows = {
            evidence_id: row
            for evidence_id, row in rows.items()
            if str(row.get("doc_id", "")) in recalled_doc_ids
        }
    if not rows:
        _append_retrieval_trace(
            trace,
            query=query,
            query_terms=query_terms,
            total_rows=total_rows,
            filtered_rows=0,
            initial_limit=initial_limit,
            dense_limit=-1,
            paper_recall_limit=paper_recall_limit,
            paper_recalled_documents=len(recalled_documents),
            per_document_limit=per_document_limit,
            fts_candidates=0,
            dense_candidates=0,
            unique_candidates=0,
            reranked_candidates=0,
            returned_hits=0,
            route_counts={},
            started_at=started_at,
            status="empty_corpus",
            dense_backend="none",
        )
        return []

    candidates: dict[str, dict[str, Any]] = {}
    fts_candidate_count = 0
    for evidence_id, fts_score in _fts_candidates(db, query_terms, limit=initial_limit):
        row = rows.get(evidence_id)
        if row is None:
            continue
        fts_candidate_count += 1
        candidate = candidates.setdefault(evidence_id, dict(row))
        candidate["fts_score"] = max(float(candidate.get("fts_score", 0.0)), fts_score)
        candidate.setdefault("routes", set()).add("fts")

    query_vector = embed_query(provider, query)
    evidence_ids = list(rows)
    cached_dense = None
    if isinstance(provider, HashingEmbeddingProvider) and len(rows) == total_rows and paper_recall_limit <= 0:
        cached_dense = cached_hashing_candidates(
            db,
            rows,
            provider=provider,
            query_vector=query_vector,
            limit=max(initial_limit, max(1, int(limit)) * 20, 200),
        )
    dense_backend = str(cached_dense[1]["backend"]) if cached_dense else "python"
    dense_values: list[tuple[str, float]]
    if cached_dense:
        dense_values = cached_dense[0]
        evidence_ids = [evidence_id for evidence_id, _score in dense_values]
    else:
        text_vectors = provider.embed_texts([str(rows[evidence_id].get("text", "")) for evidence_id in evidence_ids])
        dense_values = [
            (evidence_id, cosine_similarity(query_vector, vector))
            for evidence_id, vector in zip(evidence_ids, text_vectors)
        ]
    dense_candidate_count = 0
    document_recall_by_id = {str(document.get("doc_id", "")): document for document in recalled_documents}
    for evidence_id, dense_score in dense_values:
        # sqlite-vec returns float32 distances; orthogonal normalized vectors
        # can round back to a tiny positive cosine instead of exact zero.
        if dense_score <= 1e-6:
            continue
        dense_candidate_count += 1
        candidate = candidates.setdefault(evidence_id, dict(rows[evidence_id]))
        candidate["dense_score"] = max(float(candidate.get("dense_score", 0.0)), dense_score)
        candidate.setdefault("routes", set()).add("dense")

    normalized_candidates = []
    for candidate in candidates.values():
        routes = candidate.get("routes", set())
        candidate["routes"] = sorted(routes)
        candidate.setdefault("fts_score", 0.0)
        candidate.setdefault("dense_score", 0.0)
        document_recall = document_recall_by_id.get(str(candidate.get("doc_id", "")))
        if document_recall:
            candidate["paper_recall_rank"] = document_recall.get("rank")
            candidate["paper_recall_score"] = document_recall.get("score")
        normalized_candidates.append(candidate)

    ranked = (reranker or LexicalReranker()).rerank(query, normalized_candidates)
    capped = _apply_per_document_limit(ranked, per_document_limit=per_document_limit)
    hits = capped[: max(0, int(limit))]
    if _normalized_context_mode(context_mode) == "block":
        hits = _expand_hits_to_parent_blocks(hits, rows)
    _append_retrieval_trace(
        trace,
        query=query,
        query_terms=query_terms,
        total_rows=total_rows,
        filtered_rows=len(rows),
        initial_limit=initial_limit,
        dense_limit=len(evidence_ids),
        paper_recall_limit=paper_recall_limit,
        paper_recalled_documents=len(recalled_documents),
        per_document_limit=per_document_limit,
        fts_candidates=fts_candidate_count,
        dense_candidates=dense_candidate_count,
        unique_candidates=len(normalized_candidates),
        reranked_candidates=len(ranked),
        returned_hits=len(hits),
        route_counts=_route_counts(hits),
        started_at=started_at,
        status="ok",
        dense_backend=dense_backend,
    )
    return hits


def recall_relevant_documents(
    db_path: str | Path,
    query: str,
    *,
    limit: int = 50,
    filters: dict[str, Any] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    trace: list[dict[str, Any]] | None = None,
    rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    started_at = perf_counter()
    query_terms = _query_terms(query)
    if not query_terms:
        _append_paper_recall_trace(
            trace,
            query=query,
            query_terms=query_terms,
            total_documents=0,
            selected_documents=[],
            started_at=started_at,
            status="empty_query",
        )
        return []

    db = Path(db_path)
    evidence_rows = rows if rows is not None else _filter_evidence_spans(_load_evidence_spans(db), filters or {})
    documents = _document_profiles(evidence_rows)
    if not documents:
        _append_paper_recall_trace(
            trace,
            query=query,
            query_terms=query_terms,
            total_documents=0,
            selected_documents=[],
            started_at=started_at,
            status="empty_corpus",
        )
        return []

    provider = embedding_provider or HashingEmbeddingProvider()
    query_vector = embed_query(provider, query)
    profile_vectors = provider.embed_texts([str(document["profile_text"]) for document in documents])
    ranked: list[dict[str, Any]] = []
    for document, vector in zip(documents, profile_vectors):
        lexical_score = _document_lexical_score(document, query_terms)
        dense_score = cosine_similarity(query_vector, vector)
        score = lexical_score + dense_score
        if score <= 0:
            continue
        ranked.append(
            {
                "doc_id": str(document["doc_id"]),
                "title": str(document.get("title", "")),
                "doi": str(document.get("doi", "")),
                "publication_year": document.get("publication_year"),
                "score": round(score, 6),
                "lexical_score": round(lexical_score, 6),
                "dense_score": round(dense_score, 6),
                "matched_terms": _matched_terms_in_text(str(document["profile_text"]), query_terms),
                "profile_span_count": int(document.get("profile_span_count", 0) or 0),
                "span_count": int(document.get("span_count", 0) or 0),
            }
        )
    ranked.sort(key=lambda document: (-float(document["score"]), str(document.get("doc_id", ""))))
    selected = ranked[: max(0, int(limit))]
    for rank, document in enumerate(selected, start=1):
        document["rank"] = rank
    _append_paper_recall_trace(
        trace,
        query=query,
        query_terms=query_terms,
        total_documents=len(documents),
        selected_documents=selected,
        started_at=started_at,
        status="ok",
    )
    return selected


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_evidence_spans(db_path: Path) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        publication_year_expr = (
            "publication_year" if _has_column(connection, "evidence_spans", "publication_year") else "null as publication_year"
        )
        rows = connection.execute(
            f"""
            select
              evidence_id,
              doc_id,
              title,
              doi,
              source_url,
              {publication_year_expr},
              html_path,
              html_anchor,
              section,
              section_kind,
              block_id,
              block_type,
              sentence_index,
              char_start,
              char_end,
              text
            from evidence_spans
            order by evidence_id
            """
        ).fetchall()
    return {str(row["evidence_id"]): dict(row) for row in rows}


def _filter_evidence_spans(
    rows: dict[str, dict[str, Any]],
    filters: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    year_min = _int_or_none(filters.get("year_min"))
    section_kinds = _string_set(filters.get("section_kinds"))
    doc_ids = _string_set(filters.get("doc_ids"))
    filtered = rows
    if doc_ids:
        filtered = {
            evidence_id: row
            for evidence_id, row in filtered.items()
            if str(row.get("doc_id", "")).strip().lower() in doc_ids
        }
    if year_min is None:
        pass
    else:
        filtered = {
            evidence_id: row
            for evidence_id, row in filtered.items()
            if (publication_year := _int_or_none(row.get("publication_year"))) is not None
            and publication_year >= year_min
        }
    if section_kinds:
        filtered = {
            evidence_id: row
            for evidence_id, row in filtered.items()
            if str(row.get("section_kind", "")).strip().lower() in section_kinds
        }
    return filtered


def _has_column(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return column_name in {str(row[1]) for row in connection.execute(f"pragma table_info({table_name})")}


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        try:
            raw_values = list(value)
        except TypeError:
            raw_values = [value]
    return {str(item).strip().lower() for item in raw_values if str(item).strip()}


def _document_profiles(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows.values():
        doc_id = str(row.get("doc_id", "")).strip()
        if doc_id:
            grouped[doc_id].append(row)

    documents: list[dict[str, Any]] = []
    for doc_id, doc_rows in grouped.items():
        doc_rows.sort(
            key=lambda row: (
                _section_priority(str(row.get("section_kind", ""))),
                _int_or_none(row.get("sentence_index")) or 0,
                str(row.get("evidence_id", "")),
            )
        )
        first = doc_rows[0]
        title = str(first.get("title", ""))
        doi = str(first.get("doi", ""))
        publication_year = first.get("publication_year")
        abstract_rows = [row for row in doc_rows if str(row.get("section_kind", "")).lower() == "abstract"]
        priority_rows = (abstract_rows or doc_rows)[:5]
        section_names = []
        seen_sections: set[str] = set()
        for row in doc_rows:
            section = str(row.get("section", "")).strip()
            normalized = section.lower()
            if section and normalized not in seen_sections:
                seen_sections.add(normalized)
                section_names.append(section)
            if len(section_names) >= 8:
                break
        text_parts = [
            title,
            " ".join(section_names),
            " ".join(str(row.get("text", "")).strip() for row in priority_rows if str(row.get("text", "")).strip()),
        ]
        profile_text = " ".join(part for part in text_parts if part).strip()
        documents.append(
            {
                "doc_id": doc_id,
                "title": title,
                "doi": doi,
                "publication_year": publication_year,
                "profile_text": profile_text,
                "profile_span_count": len(priority_rows),
                "span_count": len(doc_rows),
            }
        )
    documents.sort(key=lambda document: str(document.get("doc_id", "")))
    return documents


def _section_priority(section_kind: str) -> int:
    priorities = {
        "abstract": 0,
        "introduction": 1,
        "results": 2,
        "discussion": 3,
        "methods": 4,
        "conclusion": 5,
    }
    return priorities.get(section_kind.strip().lower(), 9)


def _document_lexical_score(document: dict[str, Any], query_terms: list[str]) -> float:
    profile_counts = Counter(_tokens(str(document.get("profile_text", ""))))
    title_counts = Counter(_tokens(str(document.get("title", ""))))
    score = 0.0
    for term in query_terms:
        score += profile_counts.get(term, 0)
        score += title_counts.get(term, 0) * 0.8
    return score


def _matched_terms_in_text(text: str, query_terms: list[str]) -> list[str]:
    tokens = set(_tokens(text))
    return [term for term in query_terms if term in tokens]


def _fts_candidates(db_path: Path, query_terms: list[str], *, limit: int) -> list[tuple[str, float]]:
    query = _fts_match_query(query_terms)
    if not query:
        return []
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            select evidence_id, bm25(evidence_spans_fts) as rank
            from evidence_spans_fts
            where evidence_spans_fts match ?
            order by rank
            limit ?
            """,
            (query, max(0, int(limit))),
        ).fetchall()
    return [(str(evidence_id), 1.0 / (1.0 + abs(float(rank)))) for evidence_id, rank in rows]


def _fts_match_query(query_terms: list[str]) -> str:
    return " OR ".join(_fts_match_term(term) for term in query_terms if term)


def _fts_match_term(term: str) -> str:
    if len(term) >= 4 and term.isalnum():
        return f"{term}*"
    return term


def _apply_per_document_limit(
    hits: list[dict[str, Any]],
    *,
    per_document_limit: int,
) -> list[dict[str, Any]]:
    if per_document_limit <= 0:
        return hits
    counts: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for hit in hits:
        doc_id = str(hit.get("doc_id", ""))
        count = counts.get(doc_id, 0)
        if count >= per_document_limit:
            continue
        counts[doc_id] = count + 1
        capped.append(hit)
    return capped


def _expand_hits_to_parent_blocks(
    hits: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    spans_by_block = _spans_by_block(rows)
    expanded_hits: list[dict[str, Any]] = []
    for hit in hits:
        block_id = str(hit.get("block_id", "")).strip()
        block_spans = spans_by_block.get(block_id, [])
        if not block_spans:
            expanded_hits.append(hit)
            continue
        parent_text = _parent_block_text(block_spans)
        expanded = dict(hit)
        expanded["span_text"] = str(hit.get("text", ""))
        expanded["parent_text"] = parent_text
        expanded["parent_block_id"] = block_id
        expanded["parent_evidence_ids"] = [str(span.get("evidence_id", "")) for span in block_spans]
        expanded["text"] = parent_text
        expanded_hits.append(expanded)
    return expanded_hits


def _spans_by_block(rows: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        block_id = str(row.get("block_id", "")).strip()
        if not block_id:
            continue
        grouped.setdefault(block_id, []).append(row)
    for block_rows in grouped.values():
        block_rows.sort(
            key=lambda row: (
                _int_or_none(row.get("char_start")) if _int_or_none(row.get("char_start")) is not None else 0,
                _int_or_none(row.get("sentence_index")) if _int_or_none(row.get("sentence_index")) is not None else 0,
                str(row.get("evidence_id", "")),
            )
        )
    return grouped


def _parent_block_text(block_spans: list[dict[str, Any]]) -> str:
    return " ".join(str(span.get("text", "")).strip() for span in block_spans if str(span.get("text", "")).strip())


def _route_counts(hits: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        for route in hit.get("routes", []) or []:
            route_name = str(route).strip()
            if not route_name:
                continue
            counts[route_name] = counts.get(route_name, 0) + 1
    return dict(sorted(counts.items()))


def _append_retrieval_trace(
    trace: list[dict[str, Any]] | None,
    *,
    query: str,
    query_terms: list[str],
    total_rows: int,
    filtered_rows: int,
    initial_limit: int,
    dense_limit: int,
    paper_recall_limit: int = 0,
    paper_recalled_documents: int = 0,
    per_document_limit: int,
    fts_candidates: int,
    dense_candidates: int,
    unique_candidates: int,
    reranked_candidates: int,
    returned_hits: int,
    route_counts: dict[str, int],
    started_at: float,
    status: str,
    dense_backend: str = "python",
) -> None:
    if trace is None:
        return
    trace.append(
        {
            "stage": "search",
            "status": status,
            "dense_backend": dense_backend,
            "query": query,
            "query_terms": list(query_terms),
            "total_rows": int(total_rows),
            "filtered_rows": int(filtered_rows),
            "initial_limit": int(initial_limit),
            "dense_limit": int(dense_limit),
            "paper_recall_limit": int(paper_recall_limit),
            "paper_recalled_documents": int(paper_recalled_documents),
            "per_document_limit": int(per_document_limit),
            "fts_candidates": int(fts_candidates),
            "dense_candidates": int(dense_candidates),
            "unique_candidates": int(unique_candidates),
            "reranked_candidates": int(reranked_candidates),
            "returned_hits": int(returned_hits),
            "route_counts": dict(sorted(route_counts.items())),
            "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
        }
    )


def _append_paper_recall_trace(
    trace: list[dict[str, Any]] | None,
    *,
    query: str,
    query_terms: list[str],
    total_documents: int,
    selected_documents: list[dict[str, Any]],
    started_at: float,
    status: str,
) -> None:
    if trace is None:
        return
    trace.append(
        {
            "stage": "paper_recall",
            "status": status,
            "query": query,
            "query_terms": list(query_terms),
            "total_documents": int(total_documents),
            "selected_documents": len(selected_documents),
            "selected_doc_ids": [str(document.get("doc_id", "")) for document in selected_documents],
            "top_documents": [
                {
                    "rank": int(document.get("rank", index)),
                    "doc_id": str(document.get("doc_id", "")),
                    "title": str(document.get("title", "")),
                    "score": float(document.get("score", 0.0) or 0.0),
                    "matched_terms": list(document.get("matched_terms", []) or []),
                }
                for index, document in enumerate(selected_documents[:10], start=1)
            ],
            "elapsed_ms": round((perf_counter() - started_at) * 1000.0, 3),
        }
    )


def _normalized_context_mode(context_mode: str) -> str:
    mode = str(context_mode or "sentence").strip().lower()
    if mode in {"sentence", "span"}:
        return "sentence"
    if mode in {"block", "parent"}:
        return "block"
    raise ValueError(f"Unsupported context_mode: {context_mode}")


def _score_row(row: dict[str, Any], query_terms: list[str]) -> tuple[float, list[str]]:
    text_counts = Counter(_tokens(str(row.get("text", ""))))
    title_counts = Counter(_tokens(str(row.get("title", ""))))
    section_counts = Counter(_tokens(str(row.get("section", ""))))
    matched_terms: list[str] = []
    score = 0.0
    for term in query_terms:
        term_score = (
            text_counts.get(term, 0)
            + title_counts.get(term, 0) * 0.4
            + section_counts.get(term, 0) * 0.25
        )
        if term_score > 0:
            matched_terms.append(term)
            score += term_score
    return score, matched_terms


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
