from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import blake2b
import heapq
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any

from .bench_import import _beir_record_id, _beir_record_text, _beir_record_title, _clean_id, _read_json_records
from .bench_protocol import (
    benchmark_details_policy,
    filter_rows_for_benchmark_split,
    may_emit_question_details,
    normalize_benchmark_split,
)
from .embeddings import EmbeddingProvider, HashingEmbeddingProvider, cosine_similarity, embed_query
from .evidence_spans import EvidenceSpan, _sentence_offsets
from .evidence_store import _clear_index, _initialize_schema, _insert_document, _insert_spans
from .qa.query_planner import plan_query, query_routes
from .query_fusion import fuse_ranked_hits
from .rerankers import LexicalReranker, Reranker
from .retrieval import (
    _apply_per_document_limit,
    _fts_candidates,
    _fts_match_query,
    _load_evidence_spans,
    _query_terms,
    _route_counts,
)

try:  # Optional acceleration for large public benchmarks; not a package dependency.
    import numpy as _np
except ImportError:  # pragma: no cover - depends on local optional packages
    _np = None


@dataclass(frozen=True)
class _CachedSearchIndex:
    db_path: Path
    rows: dict[str, dict[str, Any]]
    evidence_ids: list[str]
    doc_ids: list[str]
    text_vectors: list[list[float]]
    vector_matrix: Any | None
    embedding_provider: EmbeddingProvider
    embedding_cache_rows: int
    embedding_cache_hits: int
    embedding_cache_misses: int


@dataclass
class _QueryEmbeddingCache:
    db_path: Path
    embedding_provider: EmbeddingProvider
    provider_name: str
    dimensions: int
    vectors_by_hash: dict[str, list[float]]
    hits: int = 0
    misses: int = 0

    def get(self, query: str) -> list[float]:
        query_hash = _text_hash(query)
        cached_vector = self.vectors_by_hash.get(query_hash)
        if cached_vector is not None:
            self.hits += 1
            return cached_vector
        cached_vector = _load_query_embedding_cache_row(
            self.db_path,
            provider_name=self.provider_name,
            dimensions=self.dimensions,
            query_hash=query_hash,
        )
        if cached_vector is not None:
            self.vectors_by_hash[query_hash] = cached_vector
            if self.dimensions <= 0:
                self.dimensions = len(cached_vector)
            self.hits += 1
            return cached_vector

        vector = [float(value) for value in embed_query(self.embedding_provider, query)]
        if self.dimensions <= 0:
            self.dimensions = len(vector)
        _write_query_embedding_cache_row(
            self.db_path,
            provider_name=self.provider_name,
            dimensions=self.dimensions,
            query_hash=query_hash,
            query=query,
            vector=vector,
        )
        self.vectors_by_hash[query_hash] = vector
        self.misses += 1
        return vector

    def row_count(self) -> int:
        return _query_embedding_cache_row_count(
            self.db_path,
            provider_name=self.provider_name,
            dimensions=self.dimensions,
        )


@dataclass
class _RerankerScoreCache:
    db_path: Path
    cache_name: str
    hits: int = 0
    misses: int = 0

    def rerank(self, reranker: Reranker, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return []
        query_hash = _text_hash(query)
        candidate_infos = [
            (
                _candidate_cache_id(candidate),
                _text_hash(_candidate_cache_text(candidate)),
                dict(candidate),
            )
            for candidate in candidates
        ]
        cached_rows = _load_reranker_score_cache_rows(
            self.db_path,
            cache_name=self.cache_name,
            query_hash=query_hash,
        )
        reranked: list[dict[str, Any]] = []
        missing_candidates: list[dict[str, Any]] = []
        for evidence_id, candidate_text_hash, candidate in candidate_infos:
            cached = cached_rows.get((evidence_id, candidate_text_hash))
            if cached is None:
                missing_candidates.append(candidate)
                continue
            self.hits += 1
            reranked.append(_cached_reranker_hit(candidate, cached))

        if missing_candidates:
            self.misses += len(missing_candidates)
            scored_missing = reranker.rerank(query, missing_candidates)
            _write_reranker_score_cache_rows(
                self.db_path,
                cache_name=self.cache_name,
                query_hash=query_hash,
                scored_hits=scored_missing,
            )
            reranked.extend(scored_missing)

        reranked.sort(key=lambda hit: (-float(hit.get("score", 0.0)), str(hit.get("evidence_id", ""))))
        return reranked

    def row_count(self) -> int:
        return _reranker_score_cache_row_count(self.db_path, cache_name=self.cache_name)


def build_qasper_external_store(
    input_path: str | Path,
    gold_path: str | Path,
    db_path: str | Path,
    *,
    min_text_length: int = 10,
    gold_limit: int = 0,
    benchmark_split: str = "dev",
) -> dict[str, object]:
    gold_rows = _load_jsonl(Path(gold_path))
    gold_rows = filter_rows_for_benchmark_split(gold_rows, benchmark_split)
    if gold_limit > 0:
        gold_rows = gold_rows[: int(gold_limit)]
    gold_by_doc = _candidate_evidence_by_doc(gold_rows)
    limited_doc_ids = set(gold_by_doc) if gold_limit > 0 else set()
    spans_by_doc: dict[str, list[EvidenceSpan]] = defaultdict(list)
    gold_evidence_map: dict[str, list[str]] = defaultdict(list)
    for paper in _read_json_records(Path(input_path)):
        paper_id = _clean_id(_first_non_empty(paper.get("id"), paper.get("paper_id"), paper.get("title"), "paper"))
        if limited_doc_ids and paper_id not in limited_doc_ids:
            continue
        title = str(paper.get("title", "")).strip()
        raw_sentence_index = 0
        for section_name, sentence_text in _iter_qasper_full_text_sentences(paper):
            text = sentence_text.strip()
            if len(text) < int(min_text_length):
                continue
            raw_sentence_index += 1
            spans_by_doc[paper_id].append(
                _span(
                    evidence_id=f"qasper:{paper_id}.raw.s{raw_sentence_index:04d}",
                    doc_id=paper_id,
                    title=title,
                    text=text,
                    section=section_name or "full_text",
                    section_kind=_section_kind(section_name),
                    sentence_index=len(spans_by_doc[paper_id]) + 1,
                )
            )
        for candidate in gold_by_doc.get(paper_id, []):
            gold_evidence_id = str(candidate.get("evidence_id", "")).strip()
            if not gold_evidence_id:
                continue
            raw_evidence_ids = _match_gold_text_to_raw_spans(str(candidate.get("text", "")), spans_by_doc[paper_id])
            if raw_evidence_ids:
                gold_evidence_map[gold_evidence_id].extend(raw_evidence_ids)
    return _write_external_store(db_path, spans_by_doc, dataset="qasper", gold_evidence_map=gold_evidence_map)


def build_scifact_external_store(
    corpus_path: str | Path,
    db_path: str | Path,
    *,
    min_text_length: int = 1,
    doc_ids: set[str] | None = None,
) -> dict[str, object]:
    limited_doc_ids = doc_ids or set()
    spans_by_doc: dict[str, list[EvidenceSpan]] = defaultdict(list)
    for record in _read_json_records(Path(corpus_path)):
        doc_id = _clean_id(record.get("doc_id"))
        if limited_doc_ids and doc_id not in limited_doc_ids:
            continue
        title = str(record.get("title", "")).strip()
        for index, sentence in enumerate(_as_list(record.get("abstract")), start=1):
            text = str(sentence).strip()
            if len(text) < int(min_text_length):
                continue
            spans_by_doc[doc_id].append(
                _span(
                    evidence_id=f"scifact:{doc_id}.s{index:04d}",
                    doc_id=doc_id,
                    title=title,
                    text=text,
                    section="abstract",
                    section_kind="abstract",
                    sentence_index=index,
                )
            )
    return _write_external_store(db_path, spans_by_doc, dataset="scifact")


def build_beir_external_store(
    corpus_path: str | Path,
    db_path: str | Path,
    *,
    dataset: str = "beir",
    min_text_length: int = 1,
    doc_ids: set[str] | None = None,
) -> dict[str, object]:
    dataset_id = _clean_id(dataset or "beir")
    limited_doc_ids = doc_ids or set()
    spans_by_doc: dict[str, list[EvidenceSpan]] = defaultdict(list)
    for record in _read_json_records(Path(corpus_path)):
        doc_id = _clean_id(_beir_record_id(record))
        if limited_doc_ids and doc_id not in limited_doc_ids:
            continue
        text = _beir_record_text(record)
        if len(text) < int(min_text_length):
            continue
        spans_by_doc[doc_id].append(
            _span(
                evidence_id=f"{dataset_id}:{doc_id}.s0001",
                doc_id=doc_id,
                title=_beir_record_title(record),
                text=text,
                section="document",
                section_kind="document",
                sentence_index=1,
            )
        )
    return _write_external_store(db_path, spans_by_doc, dataset=dataset_id)


def run_external_retrieval_benchmark(
    db_path: str | Path,
    gold_path: str | Path,
    *,
    k: int = 20,
    limit: int = 0,
    include_details: bool = False,
    per_document_limit: int = 0,
    initial_limit: int = 200,
    dense_limit: int = 200,
    scope: str = "corpus",
    embedding_provider: EmbeddingProvider | None = None,
    embedding_provider_name: str = "local-hash-v1",
    reranker: Reranker | None = None,
    embedding_cache_batch_size: int = 512,
    reranker_cache_name: str = "",
    checkpoint_path: str | Path | None = None,
    query_variants: int = 1,
    benchmark_split: str = "dev",
) -> dict[str, object]:
    started_at = perf_counter()
    rows = _load_jsonl(Path(gold_path))
    resolved_benchmark_split = normalize_benchmark_split(benchmark_split)
    rows = filter_rows_for_benchmark_split(rows, resolved_benchmark_split)
    if limit > 0:
        rows = rows[: int(limit)]
    resolved_details_policy = benchmark_details_policy(
        resolved_benchmark_split,
        include_details=include_details,
    )
    emit_question_details = may_emit_question_details(
        resolved_benchmark_split,
        include_details=include_details,
    )
    search_index = _build_cached_search_index(
        Path(db_path),
        embedding_provider=embedding_provider,
        embedding_provider_name=embedding_provider_name,
        embedding_cache_batch_size=embedding_cache_batch_size,
        build_dense_cache=dense_limit > 0,
    )
    query_cache = _QueryEmbeddingCache(
        db_path=Path(db_path),
        embedding_provider=search_index.embedding_provider,
        provider_name=embedding_provider_name,
        dimensions=int(getattr(search_index.embedding_provider, "dimensions", 0) or 0),
        vectors_by_hash={},
    )
    gold_evidence_map = _load_external_gold_evidence_map(Path(db_path))
    answerable_rows = [row for row in rows if bool(row.get("answerable", True))]
    gold_labeled_rows = [
        row for row in answerable_rows if _gold_ids(row)
    ]
    resolved_reranker_cache_name = str(reranker_cache_name or "").strip()
    reranker_score_cache = (
        _RerankerScoreCache(Path(db_path), resolved_reranker_cache_name)
        if reranker is not None and resolved_reranker_cache_name
        else None
    )
    resolved_checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
    checkpoint_config_hash = _external_checkpoint_config_hash(
        db_path=Path(db_path),
        gold_path=Path(gold_path),
        k=k,
        limit=limit,
        per_document_limit=per_document_limit,
        initial_limit=initial_limit,
        dense_limit=dense_limit,
        scope=scope,
        embedding_provider_name=embedding_provider_name,
        reranker_name=_external_reranker_name(reranker, resolved_reranker_cache_name),
        query_variants=query_variants,
        benchmark_split=resolved_benchmark_split,
    )
    checkpoint_results = (
        _load_external_benchmark_checkpoint(resolved_checkpoint_path, config_hash=checkpoint_config_hash)
        if resolved_checkpoint_path
        else {}
    )
    checkpoint_resumed_questions = 0
    checkpoint_written_questions = 0
    retrieval_hits = 0
    all_gold_retrieval_hits = 0
    retrieved_gold_evidence_total = 0
    gold_evidence_total = 0
    mapped_gold_evidence_total = 0
    unmapped_gold_evidence_total = 0
    float_table_gold_labeled_questions = 0
    float_table_retrieval_hits = 0
    float_table_retrieved_gold_evidence_total = 0
    float_table_gold_evidence_total = 0
    non_float_table_gold_labeled_questions = 0
    non_float_table_retrieval_hits = 0
    non_float_table_retrieved_gold_evidence_total = 0
    non_float_table_gold_evidence_total = 0
    retrieval_trace_totals = _empty_retrieval_trace_totals()
    retrieval_route_counts: dict[str, int] = {}
    question_results: list[dict[str, Any]] = []

    for row_index, row in enumerate(rows):
        checkpoint_key = _external_checkpoint_key(row, row_index)
        checkpoint_result = checkpoint_results.get(checkpoint_key)
        if checkpoint_result is not None:
            question_result = dict(checkpoint_result)
            question_result.setdefault(
                "gold_evidence_kinds",
                _row_gold_evidence_kinds(row, set(_gold_ids(row))),
            )
            checkpoint_resumed_questions += 1
            (
                retrieval_hits,
                all_gold_retrieval_hits,
                retrieved_gold_evidence_total,
                gold_evidence_total,
                mapped_gold_evidence_total,
                unmapped_gold_evidence_total,
            ) = _accumulate_external_question_result(
                question_result,
                retrieval_hits=retrieval_hits,
                all_gold_retrieval_hits=all_gold_retrieval_hits,
                retrieved_gold_evidence_total=retrieved_gold_evidence_total,
                gold_evidence_total=gold_evidence_total,
                mapped_gold_evidence_total=mapped_gold_evidence_total,
                unmapped_gold_evidence_total=unmapped_gold_evidence_total,
            )
            (
                float_table_gold_labeled_questions,
                float_table_retrieval_hits,
                float_table_retrieved_gold_evidence_total,
                float_table_gold_evidence_total,
                non_float_table_gold_labeled_questions,
                non_float_table_retrieval_hits,
                non_float_table_retrieved_gold_evidence_total,
                non_float_table_gold_evidence_total,
            ) = _accumulate_external_kind_subset_result(
                question_result,
                float_table_gold_labeled_questions=float_table_gold_labeled_questions,
                float_table_retrieval_hits=float_table_retrieval_hits,
                float_table_retrieved_gold_evidence_total=float_table_retrieved_gold_evidence_total,
                float_table_gold_evidence_total=float_table_gold_evidence_total,
                non_float_table_gold_labeled_questions=non_float_table_gold_labeled_questions,
                non_float_table_retrieval_hits=non_float_table_retrieval_hits,
                non_float_table_retrieved_gold_evidence_total=non_float_table_retrieved_gold_evidence_total,
                non_float_table_gold_evidence_total=non_float_table_gold_evidence_total,
            )
            _accumulate_retrieval_trace_metrics(
                retrieval_trace_totals,
                retrieval_route_counts,
                question_result,
            )
            if emit_question_details:
                question_results.append(question_result)
            continue

        question = str(row.get("question", "")).strip()
        retrieval_queries = external_query_variants(question, max_queries=query_variants)
        gold_ids = set(_gold_ids(row))
        answerable = bool(row.get("answerable", True))
        allowed_doc_ids = _row_scope_doc_ids(row) if scope == "gold-docs" else set()
        retrieval_trace: list[dict[str, Any]] = []
        hits = _search_cached_evidence_store_multi_query(
            search_index,
            retrieval_queries,
            limit=k,
            initial_limit=initial_limit,
            dense_limit=dense_limit,
            per_document_limit=per_document_limit,
            allowed_doc_ids=allowed_doc_ids,
            reranker=reranker,
            reranker_score_cache=reranker_score_cache,
            query_cache=query_cache,
            trace=retrieval_trace,
        )
        hit_ids = {str(hit.get("evidence_id", "")) for hit in hits}
        retrieved_route_counts = _route_counts(hits)
        mapped_gold_ids = _mapped_gold_evidence_ids(gold_ids, gold_evidence_map, search_index.rows)
        retrieved_gold_ids = {
            gold_id for gold_id, evidence_ids in mapped_gold_ids.items() if set(evidence_ids).intersection(hit_ids)
        }
        unmapped_gold_ids = {gold_id for gold_id, evidence_ids in mapped_gold_ids.items() if not evidence_ids}
        retrieval_trace_summary = _retrieval_trace_summary(retrieval_trace, route_counts=retrieved_route_counts)
        question_result = {
            "question_id": str(row.get("question_id", "")),
            "question": question,
            "retrieval_queries": retrieval_queries,
            "answer_type": str(row.get("answer_type", "")),
            "answerable": answerable,
            "gold_evidence_ids": sorted(gold_ids),
            "gold_evidence_kinds": _row_gold_evidence_kinds(row, gold_ids),
            "retrieved_evidence_ids": [
                str(hit.get("evidence_id", "")) for hit in hits if str(hit.get("evidence_id", ""))
            ],
            "retrieved_route_counts": retrieved_route_counts,
            "retrieval_trace": retrieval_trace,
            "retrieval_trace_summary": retrieval_trace_summary,
            "mapped_gold_evidence_ids": mapped_gold_ids,
            "unmapped_gold_evidence_ids": sorted(unmapped_gold_ids),
            "retrieved_gold_evidence_ids": sorted(retrieved_gold_ids),
            "missing_gold_evidence_ids": sorted(gold_ids.difference(retrieved_gold_ids)),
            "retrieval_hit": bool(retrieved_gold_ids) if answerable and gold_ids else False,
            "all_gold_retrieved": gold_ids.issubset(retrieved_gold_ids) if answerable and gold_ids else False,
            "gold_evidence_recall_at_k": _ratio(len(retrieved_gold_ids), len(gold_ids)),
        }
        (
            retrieval_hits,
            all_gold_retrieval_hits,
            retrieved_gold_evidence_total,
            gold_evidence_total,
            mapped_gold_evidence_total,
            unmapped_gold_evidence_total,
        ) = _accumulate_external_question_result(
            question_result,
            retrieval_hits=retrieval_hits,
            all_gold_retrieval_hits=all_gold_retrieval_hits,
            retrieved_gold_evidence_total=retrieved_gold_evidence_total,
            gold_evidence_total=gold_evidence_total,
            mapped_gold_evidence_total=mapped_gold_evidence_total,
            unmapped_gold_evidence_total=unmapped_gold_evidence_total,
        )
        (
            float_table_gold_labeled_questions,
            float_table_retrieval_hits,
            float_table_retrieved_gold_evidence_total,
            float_table_gold_evidence_total,
            non_float_table_gold_labeled_questions,
            non_float_table_retrieval_hits,
            non_float_table_retrieved_gold_evidence_total,
            non_float_table_gold_evidence_total,
        ) = _accumulate_external_kind_subset_result(
            question_result,
            float_table_gold_labeled_questions=float_table_gold_labeled_questions,
            float_table_retrieval_hits=float_table_retrieval_hits,
            float_table_retrieved_gold_evidence_total=float_table_retrieved_gold_evidence_total,
            float_table_gold_evidence_total=float_table_gold_evidence_total,
            non_float_table_gold_labeled_questions=non_float_table_gold_labeled_questions,
            non_float_table_retrieval_hits=non_float_table_retrieval_hits,
            non_float_table_retrieved_gold_evidence_total=non_float_table_retrieved_gold_evidence_total,
                non_float_table_gold_evidence_total=non_float_table_gold_evidence_total,
            )
        _accumulate_retrieval_trace_metrics(
            retrieval_trace_totals,
            retrieval_route_counts,
            question_result,
        )
        if resolved_checkpoint_path:
            _append_external_benchmark_checkpoint(
                resolved_checkpoint_path,
                config_hash=checkpoint_config_hash,
                checkpoint_key=checkpoint_key,
                row_index=row_index,
                question_result=question_result,
            )
            checkpoint_written_questions += 1
        if emit_question_details:
            question_results.append(question_result)

    wall_time_seconds = round(perf_counter() - started_at, 6)
    metrics: dict[str, object] = {
        "benchmark_mode": "core" if max(1, int(query_variants)) == 1 else "multi_query",
        "benchmark_target": "external_evidence_retrieval",
        "query_rewrite_strategy": "deterministic_query_rewrite_plan_v1_rrf",
        "metric_groups": {
            "core_retrieval": [
                "retrieval_recall_at_k",
                "all_gold_retrieval_recall_at_k",
                "gold_evidence_recall_at_k",
            ],
            "workflow_answer": [],
        },
        "questions": len(rows),
        "benchmark_split": resolved_benchmark_split,
        "details_policy": resolved_details_policy,
        "answerable_questions": len(answerable_rows),
        "unanswerable_questions": len(rows) - len(answerable_rows),
        "gold_labeled_questions": len(gold_labeled_rows),
        "answerable_without_gold_evidence": len(answerable_rows) - len(gold_labeled_rows),
        "wall_time_seconds": wall_time_seconds,
        "avg_wall_time_seconds_per_question": _ratio(wall_time_seconds, len(rows)),
        "k": int(k),
        "initial_limit": int(initial_limit),
        "dense_limit": int(dense_limit),
        "per_document_limit": int(per_document_limit),
        "query_variants": max(1, int(query_variants)),
        "scope": scope,
        "embedding_provider": embedding_provider_name,
        "embedding_cache_batch_size": int(embedding_cache_batch_size),
        "embedding_cache_rows": search_index.embedding_cache_rows,
        "embedding_cache_hits": search_index.embedding_cache_hits,
        "embedding_cache_misses": search_index.embedding_cache_misses,
        "query_embedding_cache_rows": query_cache.row_count(),
        "query_embedding_cache_hits": query_cache.hits,
        "query_embedding_cache_misses": query_cache.misses,
        "reranker_score_cache_name": resolved_reranker_cache_name,
        "reranker_score_cache_rows": reranker_score_cache.row_count() if reranker_score_cache else 0,
        "reranker_score_cache_hits": reranker_score_cache.hits if reranker_score_cache else 0,
        "reranker_score_cache_misses": reranker_score_cache.misses if reranker_score_cache else 0,
        "checkpoint_path": str(resolved_checkpoint_path) if resolved_checkpoint_path else "",
        "checkpoint_resumed_questions": checkpoint_resumed_questions,
        "checkpoint_written_questions": checkpoint_written_questions,
        "mapped_gold_evidence": mapped_gold_evidence_total,
        "unmapped_gold_evidence": unmapped_gold_evidence_total,
        "float_table_gold_labeled_questions": float_table_gold_labeled_questions,
        "float_table_retrieval_recall_at_k": _ratio(
            float_table_retrieval_hits,
            float_table_gold_labeled_questions,
        ),
        "float_table_gold_evidence_recall_at_k": _ratio(
            float_table_retrieved_gold_evidence_total,
            float_table_gold_evidence_total,
        ),
        "non_float_table_gold_labeled_questions": non_float_table_gold_labeled_questions,
        "non_float_table_retrieval_recall_at_k": _ratio(
            non_float_table_retrieval_hits,
            non_float_table_gold_labeled_questions,
        ),
        "non_float_table_gold_evidence_recall_at_k": _ratio(
            non_float_table_retrieved_gold_evidence_total,
            non_float_table_gold_evidence_total,
        ),
        **_retrieval_trace_metric_payload(
            retrieval_trace_totals,
            retrieval_route_counts,
        ),
        "retrieval_recall_at_k": _ratio(retrieval_hits, len(gold_labeled_rows)),
        "all_gold_retrieval_recall_at_k": _ratio(all_gold_retrieval_hits, len(gold_labeled_rows)),
        "gold_evidence_recall_at_k": _ratio(retrieved_gold_evidence_total, gold_evidence_total),
    }
    if emit_question_details:
        metrics["question_results"] = question_results
    return metrics


def external_gold_document_ids(gold_path: str | Path, *, limit: int = 0, benchmark_split: str = "dev") -> set[str]:
    rows = _load_jsonl(Path(gold_path))
    rows = filter_rows_for_benchmark_split(rows, benchmark_split)
    if limit > 0:
        rows = rows[: int(limit)]
    return set(_candidate_evidence_by_doc(rows))


def external_query_variants(question: str, *, max_queries: int = 1) -> list[str]:
    base_query = str(question or "").strip()
    if not base_query:
        return []
    resolved_max = max(1, int(max_queries))
    plan = plan_query(base_query, max_routes=max(8, resolved_max))
    variants = [str(route.get("query", "")).strip() for route in query_routes(plan, max_routes=max(8, resolved_max))]
    if base_query not in variants:
        variants.insert(0, base_query)
    expanded_terms = _expanded_query_terms(base_query)
    if expanded_terms:
        variants.append(" ".join(expanded_terms))
    focused_terms = _focused_query_terms(base_query)
    if focused_terms:
        variants.append(" ".join(focused_terms))

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        normalized = " ".join(str(variant).split())
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= resolved_max:
            break
    return deduped


def _expanded_query_terms(question: str) -> list[str]:
    base_terms = _query_terms(question)
    expanded: list[str] = []
    seen: set[str] = set()
    for term in base_terms:
        for value in [term, *_QUERY_EXPANSIONS.get(term, [])]:
            if value in seen:
                continue
            seen.add(value)
            expanded.append(value)
    return expanded


def _focused_query_terms(question: str) -> list[str]:
    normalized = question.lower()
    terms: list[str] = []
    for trigger, values in _QUERY_FOCUS_EXPANSIONS:
        if trigger in normalized:
            terms.extend(values)
    if not terms:
        return []
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


_QUERY_EXPANSIONS = {
    "accuracies": ["accuracy", "performance", "score", "scores", "results"],
    "accuracy": ["accuracies", "performance", "score", "scores", "results"],
    "approach": ["method", "model", "system", "framework"],
    "approaches": ["methods", "models", "systems", "frameworks"],
    "baseline": ["baselines", "comparison", "compare"],
    "baselines": ["baseline", "comparison", "compare"],
    "data": ["dataset", "datasets", "corpus", "corpora"],
    "dataset": ["datasets", "data", "corpus", "corpora", "evaluation"],
    "datasets": ["dataset", "data", "corpus", "corpora", "evaluation"],
    "experiment": ["experiments", "experimental", "evaluation", "evaluate"],
    "experiments": ["experiment", "experimental", "evaluation", "evaluate"],
    "method": ["methods", "approach", "model", "system"],
    "methods": ["method", "approaches", "models", "systems"],
    "model": ["models", "system", "method", "approach"],
    "models": ["model", "systems", "methods", "approaches"],
    "result": ["results", "performance", "score", "scores", "accuracy"],
    "results": ["result", "performance", "score", "scores", "accuracy"],
}

_QUERY_FOCUS_EXPANSIONS = [
    ("dataset", ["dataset", "data", "corpus", "corpora", "evaluation", "experiment"]),
    ("experiment", ["experiment", "experiments", "evaluation", "evaluate", "corpus"]),
    ("accuracy", ["accuracy", "performance", "score", "scores", "results", "table"]),
    ("baseline", ["baseline", "baselines", "compare", "comparison", "method"]),
    ("compare", ["compare", "comparison", "baseline", "baselines", "approach", "method"]),
    ("language pair", ["language", "languages", "source", "target", "translation"]),
]


def _write_external_store(
    db_path: str | Path,
    spans_by_doc: dict[str, list[EvidenceSpan]],
    *,
    dataset: str,
    gold_evidence_map: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    documents = 0
    spans = 0
    gold_spans = 0
    with sqlite3.connect(db) as connection:
        _initialize_schema(connection)
        _initialize_external_gold_map_schema(connection)
        _clear_index(connection)
        connection.execute("delete from external_gold_evidence_map")
        for doc_spans in spans_by_doc.values():
            if not doc_spans:
                continue
            documents += 1
            spans += len(doc_spans)
            gold_spans += sum(1 for span in doc_spans if span.section_kind == "gold")
            _insert_document(connection, doc_spans[0], None)
            _insert_spans(connection, doc_spans)
        if gold_evidence_map:
            connection.executemany(
                """
                insert or ignore into external_gold_evidence_map (gold_evidence_id, evidence_id)
                values (?, ?)
                """,
                [
                    (gold_evidence_id, evidence_id)
                    for gold_evidence_id, evidence_ids in gold_evidence_map.items()
                    for evidence_id in evidence_ids
                ],
            )
        connection.commit()
    return {
        "dataset": dataset,
        "documents": documents,
        "spans": spans,
        "gold_spans": gold_spans,
        "gold_evidence_map_rows": sum(len(value) for value in (gold_evidence_map or {}).values()),
        "db_path": str(db),
    }


def _initialize_external_gold_map_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists external_gold_evidence_map (
            gold_evidence_id text not null,
            evidence_id text not null,
            primary key (gold_evidence_id, evidence_id)
        )
        """
    )


def _load_external_gold_evidence_map(db_path: Path) -> dict[str, list[str]]:
    with sqlite3.connect(db_path) as connection:
        if not _has_table(connection, "external_gold_evidence_map"):
            return {}
        rows = connection.execute(
            """
            select gold_evidence_id, evidence_id
            from external_gold_evidence_map
            order by gold_evidence_id, evidence_id
            """
        ).fetchall()
    result: dict[str, list[str]] = defaultdict(list)
    for gold_evidence_id, evidence_id in rows:
        result[str(gold_evidence_id)].append(str(evidence_id))
    return dict(result)


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _mapped_gold_evidence_ids(
    gold_ids: set[str],
    gold_evidence_map: dict[str, list[str]],
    evidence_rows: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = {}
    for gold_id in sorted(gold_ids):
        aliases = [evidence_id for evidence_id in gold_evidence_map.get(gold_id, []) if evidence_id in evidence_rows]
        if not aliases and gold_id in evidence_rows:
            aliases = [gold_id]
        mapped[gold_id] = aliases
    return mapped


def _build_cached_search_index(
    db_path: Path,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_provider_name: str = "local-hash-v1",
    embedding_cache_batch_size: int = 512,
    build_dense_cache: bool = True,
) -> _CachedSearchIndex:
    rows = _load_evidence_spans(db_path)
    evidence_ids = list(rows)
    doc_ids = [str(rows[evidence_id].get("doc_id", "")) for evidence_id in evidence_ids]
    provider = embedding_provider or HashingEmbeddingProvider()
    if build_dense_cache:
        text_vectors, cache_stats = _load_or_write_embedding_cache(
            db_path,
            rows,
            evidence_ids,
            provider,
            provider_name=embedding_provider_name,
            batch_size=embedding_cache_batch_size,
        )
    else:
        text_vectors = []
        cache_stats = {"rows": 0, "hits": 0, "misses": 0}
    vector_matrix = None
    if _np is not None and text_vectors:
        vector_matrix = _np.asarray(text_vectors, dtype=float)
    return _CachedSearchIndex(
        db_path=db_path,
        rows=rows,
        evidence_ids=evidence_ids,
        doc_ids=doc_ids,
        text_vectors=text_vectors,
        vector_matrix=vector_matrix,
        embedding_provider=provider,
        embedding_cache_rows=cache_stats["rows"],
        embedding_cache_hits=cache_stats["hits"],
        embedding_cache_misses=cache_stats["misses"],
    )


def _load_or_write_embedding_cache(
    db_path: Path,
    rows: dict[str, dict[str, Any]],
    evidence_ids: list[str],
    provider: EmbeddingProvider,
    *,
    provider_name: str,
    batch_size: int = 512,
) -> tuple[list[list[float]], dict[str, int]]:
    dimensions = int(getattr(provider, "dimensions", 0) or 0)
    text_hashes = {
        evidence_id: _text_hash(str(rows[evidence_id].get("text", "")))
        for evidence_id in evidence_ids
    }
    vectors_by_id: dict[str, list[float]] = {}
    hits = 0
    with sqlite3.connect(db_path) as connection:
        _initialize_embedding_cache_schema(connection)
        connection.execute(
            "delete from external_embedding_cache where evidence_id not in (select evidence_id from evidence_spans)"
        )
        if dimensions > 0:
            for evidence_id, vector_json, text_hash in connection.execute(
                """
                select evidence_id, vector_json, text_hash
                from external_embedding_cache
                where provider = ? and dimensions = ?
                """,
                (provider_name, dimensions),
            ):
                clean_evidence_id = str(evidence_id)
                if text_hashes.get(clean_evidence_id) != str(text_hash):
                    continue
                try:
                    vector = [float(value) for value in json.loads(str(vector_json))]
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if len(vector) != dimensions:
                    continue
                vectors_by_id[clean_evidence_id] = vector
                hits += 1

        missing_ids = [evidence_id for evidence_id in evidence_ids if evidence_id not in vectors_by_id]
        missing_count = len(missing_ids)
        if missing_ids:
            for batch_ids in _chunks(missing_ids, batch_size):
                missing_vectors = provider.embed_texts([str(rows[evidence_id].get("text", "")) for evidence_id in batch_ids])
                if len(missing_vectors) != len(batch_ids):
                    raise ValueError("embedding provider returned a different number of vectors than requested")
                if dimensions <= 0 and missing_vectors:
                    dimensions = len(missing_vectors[0])
                cache_rows = []
                for evidence_id, vector in zip(batch_ids, missing_vectors):
                    clean_vector = [float(value) for value in vector]
                    vectors_by_id[evidence_id] = clean_vector
                    cache_rows.append(
                        (
                            evidence_id,
                            provider_name,
                            dimensions,
                            text_hashes[evidence_id],
                            json.dumps(clean_vector, ensure_ascii=False),
                        )
                    )
                connection.executemany(
                    """
                    insert or replace into external_embedding_cache (
                        evidence_id, provider, dimensions, text_hash, vector_json
                    )
                    values (?, ?, ?, ?, ?)
                    """,
                    cache_rows,
                )
                connection.commit()
        connection.commit()
        cache_row_count = connection.execute("select count(*) from external_embedding_cache").fetchone()[0]
    return [vectors_by_id[evidence_id] for evidence_id in evidence_ids], {
        "rows": int(cache_row_count),
        "hits": hits,
        "misses": missing_count,
    }


def _initialize_embedding_cache_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists external_embedding_cache (
            evidence_id text primary key,
            provider text not null,
            dimensions integer not null,
            text_hash text not null,
            vector_json text not null
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_external_embedding_cache_provider
        on external_embedding_cache(provider, dimensions)
        """
    )


def _initialize_query_embedding_cache_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists external_query_embedding_cache (
            query_hash text not null,
            provider text not null,
            dimensions integer not null,
            query_text text not null,
            vector_json text not null,
            primary key (query_hash, provider, dimensions)
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_external_query_embedding_cache_provider
        on external_query_embedding_cache(provider, dimensions)
        """
    )


def _load_query_embedding_cache_row(
    db_path: Path,
    *,
    provider_name: str,
    dimensions: int,
    query_hash: str,
) -> list[float] | None:
    with sqlite3.connect(db_path) as connection:
        _initialize_query_embedding_cache_schema(connection)
        if dimensions > 0:
            row = connection.execute(
                """
                select vector_json
                from external_query_embedding_cache
                where query_hash = ? and provider = ? and dimensions = ?
                """,
                (query_hash, provider_name, dimensions),
            ).fetchone()
        else:
            row = connection.execute(
                """
                select vector_json, dimensions
                from external_query_embedding_cache
                where query_hash = ? and provider = ?
                order by dimensions desc
                limit 1
                """,
                (query_hash, provider_name),
            ).fetchone()
    if row is None:
        return None
    try:
        vector = [float(value) for value in json.loads(str(row[0]))]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if dimensions > 0 and len(vector) != dimensions:
        return None
    return vector


def _write_query_embedding_cache_row(
    db_path: Path,
    *,
    provider_name: str,
    dimensions: int,
    query_hash: str,
    query: str,
    vector: list[float],
) -> None:
    with sqlite3.connect(db_path) as connection:
        _initialize_query_embedding_cache_schema(connection)
        connection.execute(
            """
            insert or replace into external_query_embedding_cache (
                query_hash, provider, dimensions, query_text, vector_json
            )
            values (?, ?, ?, ?, ?)
            """,
            (
                query_hash,
                provider_name,
                int(dimensions),
                query,
                json.dumps([float(value) for value in vector], ensure_ascii=False),
            ),
        )
        connection.commit()


def _initialize_reranker_score_cache_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists external_reranker_score_cache (
            query_hash text not null,
            evidence_id text not null,
            reranker_name text not null,
            candidate_text_hash text not null,
            score real not null,
            cross_encoder_score real,
            routes_json text not null,
            primary key (query_hash, evidence_id, reranker_name, candidate_text_hash)
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_external_reranker_score_cache_name
        on external_reranker_score_cache(reranker_name, query_hash)
        """
    )


def _load_reranker_score_cache_rows(
    db_path: Path,
    *,
    cache_name: str,
    query_hash: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        _initialize_reranker_score_cache_schema(connection)
        rows = connection.execute(
            """
            select evidence_id, candidate_text_hash, score, cross_encoder_score, routes_json
            from external_reranker_score_cache
            where reranker_name = ? and query_hash = ?
            """,
            (cache_name, query_hash),
        ).fetchall()
    cached: dict[tuple[str, str], dict[str, Any]] = {}
    for evidence_id, candidate_text_hash, score, cross_encoder_score, routes_json in rows:
        try:
            routes = [str(route) for route in json.loads(str(routes_json))]
        except (TypeError, ValueError, json.JSONDecodeError):
            routes = []
        cached[(str(evidence_id), str(candidate_text_hash))] = {
            "score": float(score),
            "cross_encoder_score": None if cross_encoder_score is None else float(cross_encoder_score),
            "routes": routes,
        }
    return cached


def _write_reranker_score_cache_rows(
    db_path: Path,
    *,
    cache_name: str,
    query_hash: str,
    scored_hits: list[dict[str, Any]],
) -> None:
    if not scored_hits:
        return
    cache_rows = []
    for hit in scored_hits:
        evidence_id = _candidate_cache_id(hit)
        candidate_text_hash = _text_hash(_candidate_cache_text(hit))
        score = float(hit.get("score", 0.0))
        cross_encoder_value = hit.get("cross_encoder_score")
        cross_encoder_score = None if cross_encoder_value is None else float(cross_encoder_value)
        routes = [str(route) for route in hit.get("routes", []) or []]
        cache_rows.append(
            (
                query_hash,
                evidence_id,
                cache_name,
                candidate_text_hash,
                score,
                cross_encoder_score,
                json.dumps(routes, ensure_ascii=False),
            )
        )
    with sqlite3.connect(db_path) as connection:
        _initialize_reranker_score_cache_schema(connection)
        connection.executemany(
            """
            insert or replace into external_reranker_score_cache (
                query_hash, evidence_id, reranker_name, candidate_text_hash,
                score, cross_encoder_score, routes_json
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            cache_rows,
        )
        connection.commit()


def _reranker_score_cache_row_count(db_path: Path, *, cache_name: str) -> int:
    with sqlite3.connect(db_path) as connection:
        _initialize_reranker_score_cache_schema(connection)
        row = connection.execute(
            """
            select count(*)
            from external_reranker_score_cache
            where reranker_name = ?
            """,
            (cache_name,),
        ).fetchone()
    return int(row[0])


def _cached_reranker_hit(candidate: dict[str, Any], cached: dict[str, Any]) -> dict[str, Any]:
    hit = dict(candidate)
    score = float(cached.get("score", 0.0))
    hit["score"] = round(score, 6)
    cross_encoder_score = cached.get("cross_encoder_score")
    if cross_encoder_score is not None:
        hit["cross_encoder_score"] = round(float(cross_encoder_score), 6)
    routes = [str(route) for route in cached.get("routes", []) or []]
    if not routes:
        routes = [str(route) for route in hit.get("routes", []) or []]
    if "reranker-cache" not in routes:
        routes.append("reranker-cache")
    hit["routes"] = routes
    return hit


def _candidate_cache_id(candidate: dict[str, Any]) -> str:
    evidence_id = str(candidate.get("evidence_id", "")).strip()
    if evidence_id:
        return evidence_id
    return _text_hash(_candidate_cache_text(candidate))


def _candidate_cache_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            str(candidate.get("title", "")).strip(),
            str(candidate.get("section", "")).strip(),
            str(candidate.get("text", "")).strip(),
        ]
        if part
    )


def _query_embedding_cache_row_count(
    db_path: Path,
    *,
    provider_name: str,
    dimensions: int,
) -> int:
    with sqlite3.connect(db_path) as connection:
        _initialize_query_embedding_cache_schema(connection)
        if dimensions > 0:
            row = connection.execute(
                """
                select count(*)
                from external_query_embedding_cache
                where provider = ? and dimensions = ?
                """,
                (provider_name, dimensions),
            ).fetchone()
        else:
            row = connection.execute(
                """
                select count(*)
                from external_query_embedding_cache
                where provider = ?
                """,
                (provider_name,),
            ).fetchone()
    return int(row[0])


def _search_cached_evidence_store(
    index: _CachedSearchIndex,
    query: str,
    *,
    limit: int,
    initial_limit: int = 200,
    dense_limit: int = 200,
    per_document_limit: int = 0,
    allowed_doc_ids: set[str] | None = None,
    reranker: Reranker | None = None,
    reranker_score_cache: _RerankerScoreCache | None = None,
    query_vector: list[float] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    started_at = perf_counter()
    query_terms = _query_terms(query)
    if not query_terms or not index.rows:
        _append_external_retrieval_trace(
            trace,
            query=query,
            query_terms=query_terms,
            allowed_doc_ids=allowed_doc_ids,
            initial_limit=initial_limit,
            dense_limit=dense_limit,
            per_document_limit=per_document_limit,
            fts_candidates=0,
            dense_candidates=0,
            unique_candidates=0,
            reranked_candidates=0,
            returned_hits=0,
            route_counts={},
            started_at=started_at,
            status="empty_query" if not query_terms else "empty_corpus",
        )
        return []

    candidates: dict[str, dict[str, Any]] = {}
    fts_candidate_count = 0
    if initial_limit > 0:
        fts_candidates = (
            _scoped_fts_candidates(index.db_path, query_terms, allowed_doc_ids=allowed_doc_ids, limit=initial_limit)
            if allowed_doc_ids
            else _fts_candidates(index.db_path, query_terms, limit=initial_limit)
        )
        for evidence_id, fts_score in fts_candidates:
            row = index.rows.get(evidence_id)
            if row is None:
                continue
            fts_candidate_count += 1
            candidate = candidates.setdefault(evidence_id, dict(row))
            candidate["fts_score"] = max(float(candidate.get("fts_score", 0.0)), fts_score)
            candidate.setdefault("routes", set()).add("fts")

    dense_score_items: list[tuple[str, float]] = []
    dense_candidate_count = 0
    if dense_limit > 0:
        resolved_query_vector = query_vector if query_vector is not None else embed_query(index.embedding_provider, query)
        dense_score_items = _top_dense_scores(
            index,
            resolved_query_vector,
            dense_limit=dense_limit,
            allowed_doc_ids=allowed_doc_ids,
        )
    for evidence_id, dense_score in dense_score_items:
        if dense_score <= 0:
            continue
        dense_candidate_count += 1
        candidate = candidates.setdefault(evidence_id, dict(index.rows[evidence_id]))
        candidate["dense_score"] = max(float(candidate.get("dense_score", 0.0)), float(dense_score))
        candidate.setdefault("routes", set()).add("dense")

    normalized_candidates = []
    for candidate in candidates.values():
        routes = candidate.get("routes", set())
        candidate["routes"] = sorted(routes)
        candidate.setdefault("fts_score", 0.0)
        candidate.setdefault("dense_score", 0.0)
        normalized_candidates.append(candidate)

    resolved_reranker = reranker or LexicalReranker()
    ranked = (
        reranker_score_cache.rerank(resolved_reranker, query, normalized_candidates)
        if reranker_score_cache is not None
        else resolved_reranker.rerank(query, normalized_candidates)
    )
    capped = _apply_per_document_limit(ranked, per_document_limit=per_document_limit)
    hits = capped[: max(0, int(limit))]
    _append_external_retrieval_trace(
        trace,
        query=query,
        query_terms=query_terms,
        allowed_doc_ids=allowed_doc_ids,
        initial_limit=initial_limit,
        dense_limit=dense_limit,
        per_document_limit=per_document_limit,
        fts_candidates=fts_candidate_count,
        dense_candidates=dense_candidate_count,
        unique_candidates=len(normalized_candidates),
        reranked_candidates=len(ranked),
        returned_hits=len(hits),
        route_counts=_route_counts(hits),
        started_at=started_at,
        status="ok",
    )
    return hits


def _search_cached_evidence_store_multi_query(
    index: _CachedSearchIndex,
    queries: list[str],
    *,
    limit: int,
    initial_limit: int = 200,
    dense_limit: int = 200,
    per_document_limit: int = 0,
    allowed_doc_ids: set[str] | None = None,
    reranker: Reranker | None = None,
    reranker_score_cache: _RerankerScoreCache | None = None,
    query_cache: _QueryEmbeddingCache | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized_queries = [query for query in queries if str(query).strip()]
    if not normalized_queries:
        return []
    if len(normalized_queries) == 1:
        query = normalized_queries[0]
        return _search_cached_evidence_store(
            index,
            query,
            limit=limit,
            initial_limit=initial_limit,
            dense_limit=dense_limit,
            per_document_limit=per_document_limit,
            allowed_doc_ids=allowed_doc_ids,
            reranker=reranker,
            reranker_score_cache=reranker_score_cache,
            query_vector=query_cache.get(query) if dense_limit > 0 and query_cache is not None else None,
            trace=trace,
        )

    route_results: list[dict[str, Any]] = []
    merge_started_at = perf_counter()
    per_query_limit = max(max(0, int(limit)) * 4, min(50, max(0, int(limit)) + 20))
    for query_index, query in enumerate(normalized_queries, start=1):
        hits = _search_cached_evidence_store(
            index,
            query,
            limit=per_query_limit,
            initial_limit=initial_limit,
            dense_limit=dense_limit,
            per_document_limit=0,
            allowed_doc_ids=allowed_doc_ids,
            reranker=None,
            reranker_score_cache=None,
            query_vector=query_cache.get(query) if dense_limit > 0 and query_cache is not None else None,
            trace=trace,
        )
        route_results.append(
            {
                "label": f"query-{query_index}",
                "query": query,
                "weight": 1.0 if query_index == 1 else max(0.5, 1.0 - (query_index - 1) * 0.1),
                "hits": hits,
            }
        )

    fused = fuse_ranked_hits(
        route_results,
        limit=max(max(0, int(limit)) * 8, min(100, max(0, int(limit)) + 40)),
    )
    if reranker is not None and fused:
        ranked = (
            reranker_score_cache.rerank(reranker, normalized_queries[0], fused)
            if reranker_score_cache is not None
            else reranker.rerank(normalized_queries[0], fused)
        )
    else:
        ranked = fused
    capped = _apply_per_document_limit(ranked, per_document_limit=per_document_limit)
    hits = capped[: max(0, int(limit))]
    if trace is not None:
        trace.append(
            {
                "stage": "merge",
                "status": "ok",
                "fusion": "weighted_rrf",
                "queries": list(normalized_queries),
                "query_count": len(normalized_queries),
                "unique_candidates": len(fused),
                "final_reranker": reranker is not None,
                "reranked_candidates": len(ranked) if reranker is not None else 0,
                "returned_hits": len(hits),
                "route_counts": _route_counts(hits),
                "per_document_limit": int(per_document_limit),
                "elapsed_ms": round((perf_counter() - merge_started_at) * 1000.0, 3),
            }
        )
    return hits


def _scoped_fts_candidates(
    db_path: Path,
    query_terms: list[str],
    *,
    allowed_doc_ids: set[str] | None,
    limit: int,
) -> list[tuple[str, float]]:
    doc_ids = sorted(str(doc_id) for doc_id in (allowed_doc_ids or set()) if str(doc_id))
    query = _fts_match_query(query_terms)
    if not query or not doc_ids:
        return []
    placeholders = ",".join("?" for _ in doc_ids)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            f"""
            select evidence_id, bm25(evidence_spans_fts) as rank
            from evidence_spans_fts
            where evidence_spans_fts match ?
              and doc_id in ({placeholders})
            order by rank
            limit ?
            """,
            [query, *doc_ids, max(0, int(limit))],
        ).fetchall()
    return [(str(evidence_id), 1.0 / (1.0 + abs(float(rank)))) for evidence_id, rank in rows]


def _top_dense_scores(
    index: _CachedSearchIndex,
    query_vector: list[float],
    *,
    dense_limit: int,
    allowed_doc_ids: set[str] | None = None,
) -> list[tuple[str, float]]:
    if dense_limit <= 0 or not index.evidence_ids:
        return []
    candidate_positions = None
    if allowed_doc_ids:
        candidate_positions = [
            position for position, doc_id in enumerate(index.doc_ids) if doc_id in allowed_doc_ids
        ]
        if not candidate_positions:
            return []
    if index.vector_matrix is not None:
        if candidate_positions is None:
            dense_scores = index.vector_matrix @ _np.asarray(query_vector, dtype=float)
            evidence_positions = list(range(len(index.evidence_ids)))
        else:
            dense_scores = index.vector_matrix[candidate_positions] @ _np.asarray(query_vector, dtype=float)
            evidence_positions = candidate_positions
        top_count = min(int(dense_limit), len(evidence_positions))
        if top_count <= 0:
            return []
        if top_count == len(evidence_positions):
            top_indices = _np.arange(len(evidence_positions))
        else:
            top_indices = _np.argpartition(dense_scores, -top_count)[-top_count:]
        return [
            (index.evidence_ids[evidence_positions[int(position)]], float(dense_scores[int(position)]))
            for position in top_indices
            if float(dense_scores[int(position)]) > 0
        ]
    return heapq.nlargest(
        int(dense_limit),
        (
            (evidence_id, cosine_similarity(query_vector, vector))
            for evidence_id, doc_id, vector in zip(index.evidence_ids, index.doc_ids, index.text_vectors)
            if not allowed_doc_ids or doc_id in allowed_doc_ids
        ),
        key=lambda item: item[1],
    )


def _candidate_evidence_by_doc(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        for candidate in _as_list(row.get("candidate_evidence")):
            if not isinstance(candidate, dict):
                continue
            evidence_id = str(candidate.get("evidence_id", "")).strip()
            doc_id_value = candidate.get("doc_id")
            if doc_id_value in (None, ""):
                doc_id_value = _doc_id_from_external_source(row)
            doc_id = _clean_id(doc_id_value)
            text = str(candidate.get("text", "")).strip()
            if not evidence_id or not doc_id or not text:
                continue
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            by_doc[doc_id].append(dict(candidate))
    return by_doc


def _doc_id_from_external_source(row: dict[str, Any]) -> str:
    source = row.get("external_source", {})
    if not isinstance(source, dict):
        return ""
    return str(source.get("paper_id") or source.get("doc_id") or "")


def _iter_qasper_full_text_sentences(paper: dict[str, Any]) -> list[tuple[str, str]]:
    sentences: list[tuple[str, str]] = []
    for section in _as_list(paper.get("full_text")):
        if not isinstance(section, dict):
            continue
        section_name = str(section.get("section_name", "")).strip()
        for paragraph in _as_list(section.get("paragraphs")):
            for sentence, _start, _end in _sentence_offsets(str(paragraph)):
                sentences.append((section_name, sentence))
    return sentences


def _match_gold_text_to_raw_spans(gold_text: str, raw_spans: list[EvidenceSpan]) -> list[str]:
    normalized_gold = _normalize_text(gold_text)
    if not normalized_gold:
        return []
    exact_matches = [
        span.evidence_id for span in raw_spans if _normalize_text(span.text) == normalized_gold
    ]
    if exact_matches:
        return exact_matches
    contained_matches = []
    for span in raw_spans:
        normalized_raw = _normalize_text(span.text)
        if normalized_gold in normalized_raw or normalized_raw in normalized_gold:
            contained_matches.append(span.evidence_id)
    if contained_matches:
        return contained_matches
    if _looks_like_external_float_selection(normalized_gold):
        return []
    return _token_overlap_gold_matches(gold_text, raw_spans)


def _token_overlap_gold_matches(gold_text: str, raw_spans: list[EvidenceSpan]) -> list[str]:
    gold_tokens = _significant_tokens(gold_text)
    if len(gold_tokens) < 3:
        return []
    required_coverage = 1.0 if len(gold_tokens) <= 5 else 0.85
    matches: list[str] = []
    for span in raw_spans:
        raw_tokens = set(_significant_tokens(span.text))
        if not raw_tokens:
            continue
        covered = sum(1 for token in gold_tokens if token in raw_tokens)
        coverage = covered / len(gold_tokens)
        if coverage >= required_coverage:
            matches.append(span.evidence_id)
    return matches


def _looks_like_external_float_selection(normalized_text: str) -> bool:
    return normalized_text.startswith("float selected")


def _looks_like_external_float_or_table_selection(text: str) -> bool:
    normalized = _normalize_text(text)
    return (
        _looks_like_external_float_selection(normalized)
        or normalized.startswith("table ")
        or " table " in f" {normalized} "
    )


def _span(
    *,
    evidence_id: str,
    doc_id: str,
    title: str,
    text: str,
    section: str,
    section_kind: str,
    sentence_index: int,
) -> EvidenceSpan:
    clean_evidence_id = evidence_id.strip()
    clean_doc_id = doc_id.strip()
    return EvidenceSpan(
        doc_id=clean_doc_id,
        evidence_id=clean_evidence_id,
        title=title.strip(),
        doi=None,
        source_url=f"external://{clean_doc_id}",
        publication_year=None,
        html_path=f"external://{clean_doc_id}",
        html_anchor=clean_evidence_id,
        section=section.strip(),
        section_kind=section_kind.strip() or "other",
        block_id=f"{clean_doc_id}:{section.strip() or 'section'}",
        block_type="paragraph",
        sentence_index=int(sentence_index),
        char_start=0,
        char_end=len(text),
        text=text,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _gold_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("gold_evidence_ids", [])
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _row_scope_doc_ids(row: dict[str, Any]) -> set[str]:
    doc_ids: set[str] = set()
    for candidate in _as_list(row.get("candidate_evidence")):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("doc_id")
        if value not in (None, ""):
            doc_ids.add(_clean_id(value))
    fallback_doc_id = _doc_id_from_external_source(row)
    if fallback_doc_id:
        doc_ids.add(_clean_id(fallback_doc_id))
    return {doc_id for doc_id in doc_ids if doc_id}


def _section_kind(section_name: str) -> str:
    normalized = section_name.strip().lower()
    for kind in ("abstract", "introduction", "methods", "results", "discussion", "conclusion"):
        if kind in normalized:
            return kind
    return "other"


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _chunks(values: list[str], size: int) -> list[list[str]]:
    resolved_size = int(size)
    if resolved_size <= 0:
        resolved_size = len(values) or 1
    return [values[index : index + resolved_size] for index in range(0, len(values), resolved_size)]


def _accumulate_external_question_result(
    result: dict[str, Any],
    *,
    retrieval_hits: int,
    all_gold_retrieval_hits: int,
    retrieved_gold_evidence_total: int,
    gold_evidence_total: int,
    mapped_gold_evidence_total: int,
    unmapped_gold_evidence_total: int,
) -> tuple[int, int, int, int, int, int]:
    answerable = bool(result.get("answerable", True))
    gold_ids = [str(value) for value in result.get("gold_evidence_ids", []) or [] if str(value)]
    if not answerable or not gold_ids:
        return (
            retrieval_hits,
            all_gold_retrieval_hits,
            retrieved_gold_evidence_total,
            gold_evidence_total,
            mapped_gold_evidence_total,
            unmapped_gold_evidence_total,
        )
    retrieved_gold_ids = [
        str(value) for value in result.get("retrieved_gold_evidence_ids", []) or [] if str(value)
    ]
    unmapped_gold_ids = [
        str(value) for value in result.get("unmapped_gold_evidence_ids", []) or [] if str(value)
    ]
    gold_evidence_total += len(gold_ids)
    retrieved_gold_evidence_total += len(retrieved_gold_ids)
    mapped_gold_evidence_total += len(gold_ids) - len(unmapped_gold_ids)
    unmapped_gold_evidence_total += len(unmapped_gold_ids)
    if retrieved_gold_ids:
        retrieval_hits += 1
    if bool(result.get("all_gold_retrieved", False)):
        all_gold_retrieval_hits += 1
    return (
        retrieval_hits,
        all_gold_retrieval_hits,
        retrieved_gold_evidence_total,
        gold_evidence_total,
        mapped_gold_evidence_total,
        unmapped_gold_evidence_total,
    )


def _accumulate_external_kind_subset_result(
    result: dict[str, Any],
    *,
    float_table_gold_labeled_questions: int,
    float_table_retrieval_hits: int,
    float_table_retrieved_gold_evidence_total: int,
    float_table_gold_evidence_total: int,
    non_float_table_gold_labeled_questions: int,
    non_float_table_retrieval_hits: int,
    non_float_table_retrieved_gold_evidence_total: int,
    non_float_table_gold_evidence_total: int,
) -> tuple[int, int, int, int, int, int, int, int]:
    answerable = bool(result.get("answerable", True))
    if not answerable:
        return (
            float_table_gold_labeled_questions,
            float_table_retrieval_hits,
            float_table_retrieved_gold_evidence_total,
            float_table_gold_evidence_total,
            non_float_table_gold_labeled_questions,
            non_float_table_retrieval_hits,
            non_float_table_retrieved_gold_evidence_total,
            non_float_table_gold_evidence_total,
        )
    gold_ids = [str(value) for value in result.get("gold_evidence_ids", []) or [] if str(value)]
    if not gold_ids:
        return (
            float_table_gold_labeled_questions,
            float_table_retrieval_hits,
            float_table_retrieved_gold_evidence_total,
            float_table_gold_evidence_total,
            non_float_table_gold_labeled_questions,
            non_float_table_retrieval_hits,
            non_float_table_retrieved_gold_evidence_total,
            non_float_table_gold_evidence_total,
        )
    kinds = dict(result.get("gold_evidence_kinds", {}) or {})
    retrieved_gold_ids = {
        str(value) for value in result.get("retrieved_gold_evidence_ids", []) or [] if str(value)
    }
    float_table_gold_ids = [gold_id for gold_id in gold_ids if kinds.get(gold_id) == "float_or_table"]
    non_float_table_gold_ids = [gold_id for gold_id in gold_ids if kinds.get(gold_id) != "float_or_table"]
    if float_table_gold_ids:
        float_table_gold_labeled_questions += 1
        float_table_gold_evidence_total += len(float_table_gold_ids)
        retrieved_subset = [gold_id for gold_id in float_table_gold_ids if gold_id in retrieved_gold_ids]
        float_table_retrieved_gold_evidence_total += len(retrieved_subset)
        if retrieved_subset:
            float_table_retrieval_hits += 1
    if non_float_table_gold_ids:
        non_float_table_gold_labeled_questions += 1
        non_float_table_gold_evidence_total += len(non_float_table_gold_ids)
        retrieved_subset = [gold_id for gold_id in non_float_table_gold_ids if gold_id in retrieved_gold_ids]
        non_float_table_retrieved_gold_evidence_total += len(retrieved_subset)
        if retrieved_subset:
            non_float_table_retrieval_hits += 1
    return (
        float_table_gold_labeled_questions,
        float_table_retrieval_hits,
        float_table_retrieved_gold_evidence_total,
        float_table_gold_evidence_total,
        non_float_table_gold_labeled_questions,
        non_float_table_retrieval_hits,
        non_float_table_retrieved_gold_evidence_total,
        non_float_table_gold_evidence_total,
    )


def _empty_retrieval_trace_totals() -> dict[str, float]:
    return {
        "questions": 0.0,
        "search_calls": 0.0,
        "queries": 0.0,
        "fts_candidates": 0.0,
        "dense_candidates": 0.0,
        "unique_candidates": 0.0,
        "reranked_candidates": 0.0,
        "returned_hits": 0.0,
        "elapsed_ms": 0.0,
    }


def _retrieval_trace_summary(
    trace: list[dict[str, Any]],
    *,
    route_counts: dict[str, int],
) -> dict[str, object]:
    search_events = [event for event in trace if str(event.get("stage", "")) == "search"]
    return {
        "search_calls": len(search_events),
        "queries": len(search_events),
        "fts_candidates": sum(int(event.get("fts_candidates", 0) or 0) for event in search_events),
        "dense_candidates": sum(int(event.get("dense_candidates", 0) or 0) for event in search_events),
        "unique_candidates": sum(int(event.get("unique_candidates", 0) or 0) for event in search_events),
        "reranked_candidates": sum(int(event.get("reranked_candidates", 0) or 0) for event in search_events),
        "returned_hits": sum(int(event.get("returned_hits", 0) or 0) for event in search_events),
        "elapsed_ms": round(sum(float(event.get("elapsed_ms", 0.0) or 0.0) for event in trace), 3),
        "route_counts": dict(sorted(route_counts.items())),
    }


def _accumulate_retrieval_trace_metrics(
    totals: dict[str, float],
    route_counts: dict[str, int],
    question_result: dict[str, Any],
) -> None:
    summary = question_result.get("retrieval_trace_summary")
    if not isinstance(summary, dict):
        return
    totals["questions"] += 1
    for key in (
        "search_calls",
        "queries",
        "fts_candidates",
        "dense_candidates",
        "unique_candidates",
        "reranked_candidates",
        "returned_hits",
        "elapsed_ms",
    ):
        totals[key] += float(summary.get(key, 0) or 0)
    for route, count in (summary.get("route_counts") or {}).items():
        route_name = str(route).strip()
        if not route_name:
            continue
        route_counts[route_name] = route_counts.get(route_name, 0) + int(count)


def _retrieval_trace_metric_payload(
    totals: dict[str, float],
    route_counts: dict[str, int],
) -> dict[str, object]:
    questions = int(totals.get("questions", 0) or 0)
    return {
        "retrieval_trace_questions": questions,
        "retrieval_search_calls": int(totals.get("search_calls", 0) or 0),
        "retrieval_queries": int(totals.get("queries", 0) or 0),
        "retrieval_fts_candidates": int(totals.get("fts_candidates", 0) or 0),
        "retrieval_dense_candidates": int(totals.get("dense_candidates", 0) or 0),
        "retrieval_unique_candidates": int(totals.get("unique_candidates", 0) or 0),
        "retrieval_reranked_candidates": int(totals.get("reranked_candidates", 0) or 0),
        "retrieval_returned_hits": int(totals.get("returned_hits", 0) or 0),
        "retrieval_elapsed_ms": round(float(totals.get("elapsed_ms", 0.0) or 0.0), 3),
        "retrieval_route_counts": dict(sorted(route_counts.items())),
        "avg_search_calls_per_question": _ratio(int(totals.get("search_calls", 0) or 0), questions),
        "avg_retrieval_queries_per_question": _ratio(int(totals.get("queries", 0) or 0), questions),
        "avg_fts_candidates_per_question": _ratio(int(totals.get("fts_candidates", 0) or 0), questions),
        "avg_dense_candidates_per_question": _ratio(int(totals.get("dense_candidates", 0) or 0), questions),
        "avg_unique_candidates_per_question": _ratio(int(totals.get("unique_candidates", 0) or 0), questions),
        "avg_reranked_candidates_per_question": _ratio(int(totals.get("reranked_candidates", 0) or 0), questions),
        "avg_returned_hits_per_question": _ratio(int(totals.get("returned_hits", 0) or 0), questions),
    }


def _append_external_retrieval_trace(
    trace: list[dict[str, Any]] | None,
    *,
    query: str,
    query_terms: list[str],
    allowed_doc_ids: set[str] | None,
    initial_limit: int,
    dense_limit: int,
    per_document_limit: int,
    fts_candidates: int,
    dense_candidates: int,
    unique_candidates: int,
    reranked_candidates: int,
    returned_hits: int,
    route_counts: dict[str, int],
    started_at: float,
    status: str,
) -> None:
    if trace is None:
        return
    trace.append(
        {
            "stage": "search",
            "status": status,
            "query": query,
            "query_terms": list(query_terms),
            "scope_doc_count": len(allowed_doc_ids or set()),
            "initial_limit": int(initial_limit),
            "dense_limit": int(dense_limit),
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


def _row_gold_evidence_kinds(row: dict[str, Any], gold_ids: set[str]) -> dict[str, str]:
    kinds = {str(gold_id): "text" for gold_id in gold_ids if str(gold_id)}
    for candidate in _as_list(row.get("candidate_evidence")):
        if not isinstance(candidate, dict):
            continue
        evidence_id = str(candidate.get("evidence_id", "")).strip()
        if evidence_id not in kinds:
            continue
        text = str(candidate.get("text", ""))
        kinds[evidence_id] = "float_or_table" if _looks_like_external_float_or_table_selection(text) else "text"
    return kinds


def _external_checkpoint_key(row: dict[str, Any], row_index: int) -> str:
    question_id = str(row.get("question_id", "")).strip()
    if question_id:
        return f"id:{question_id}"
    question = str(row.get("question", "")).strip()
    gold_ids = ",".join(_gold_ids(row))
    return f"row:{int(row_index)}:{_text_hash(question + '|' + gold_ids)}"


def _external_checkpoint_config_hash(
    *,
    db_path: Path,
    gold_path: Path,
    k: int,
    limit: int,
    per_document_limit: int,
    initial_limit: int,
    dense_limit: int,
    scope: str,
    embedding_provider_name: str,
    reranker_name: str,
    query_variants: int,
    benchmark_split: str,
) -> str:
    payload = {
        "db_path": str(db_path),
        "gold_path": str(gold_path),
        "k": int(k),
        "limit": int(limit),
        "per_document_limit": int(per_document_limit),
        "initial_limit": int(initial_limit),
        "dense_limit": int(dense_limit),
        "scope": scope,
        "embedding_provider_name": embedding_provider_name,
        "reranker_name": reranker_name,
        "query_variants": max(1, int(query_variants)),
        "query_rewrite_strategy": "deterministic_query_rewrite_plan_v1_rrf",
        "benchmark_split": normalize_benchmark_split(benchmark_split),
    }
    return _text_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _external_reranker_name(reranker: Reranker | None, reranker_cache_name: str) -> str:
    if reranker_cache_name:
        return reranker_cache_name
    if reranker is None:
        return ""
    return str(getattr(reranker, "model_name", "") or "")


def _load_external_benchmark_checkpoint(
    checkpoint_path: Path,
    *,
    config_hash: str,
) -> dict[str, dict[str, Any]]:
    if not checkpoint_path.exists():
        return {}
    results: dict[str, dict[str, Any]] = {}
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("config_hash", "")) != config_hash:
            continue
        checkpoint_key = str(row.get("checkpoint_key", "")).strip()
        if not checkpoint_key:
            continue
        result = dict(row)
        result.pop("config_hash", None)
        result.pop("checkpoint_key", None)
        result.pop("row_index", None)
        results[checkpoint_key] = result
    return results


def _append_external_benchmark_checkpoint(
    checkpoint_path: Path,
    *,
    config_hash: str,
    checkpoint_key: str,
    row_index: int,
    question_result: dict[str, Any],
) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(question_result)
    record["config_hash"] = config_hash
    record["checkpoint_key"] = checkpoint_key
    record["row_index"] = int(row_index)
    with checkpoint_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _significant_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in _ALIGNMENT_STOPWORDS and len(token) > 1
    ]


def _text_hash(value: str) -> str:
    return blake2b(value.encode("utf-8"), digest_size=16).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


_ALIGNMENT_STOPWORDS = {
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
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "with",
}
