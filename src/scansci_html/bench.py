from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any

from .embeddings import build_embedding_provider
from .qa.agent import answer_question, evidence_adequacy_thresholds
from .rerankers import build_reranker
from .retrieval import search_evidence_store

DEFAULT_TEMPLATE_ANSWER_TYPES = [
    "single_paper_fact",
    "single_paper_method",
    "multi_paper_synthesis",
    "conflict_evidence",
    "unanswerable",
    "numeric_extraction",
]

MAX_PAIR_CANDIDATE_ROWS = 3000
MAX_PAIR_CANDIDATE_ROWS_PER_DOC = 40
MAX_PAIR_TERM_POSTINGS = 80

BENCHMARK_PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    "baseline": {
        "embedding_provider": "local",
        "embedding_model": "",
        "reranker": "local",
        "reranker_model": "",
        "reranker_batch_size": 32,
    },
    "minilm": {
        "embedding_provider": "sentence-transformers",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "reranker": "cross-encoder",
        "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2",
        "reranker_batch_size": 32,
    },
    "qwen3-vl": {
        "embedding_provider": "sentence-transformers",
        "embedding_model": "Qwen/Qwen3-VL-Embedding-2B",
        "reranker": "cross-encoder",
        "reranker_model": "Qwen/Qwen3-Reranker-0.6B",
        "reranker_batch_size": 16,
    },
    "bge-small": {
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "reranker": "cross-encoder",
        "reranker_model": "BAAI/bge-reranker-base",
        "reranker_batch_size": 32,
    },
}

CORE_RETRIEVAL_METRICS = [
    "retrieval_recall_at_k",
    "all_gold_retrieval_recall_at_k",
    "gold_evidence_recall_at_k",
]

WORKFLOW_ANSWER_METRICS = [
    "answer_accuracy",
    "answerable_evidence_adequacy_rate",
    "citation_precision",
    "citation_recall",
    "citation_f1",
    "citation_verification_pass_rate",
    "unsupported_claim_rate",
    "abstention_accuracy",
]

MATURE_QUALITY_METRICS = [
    "answer_completeness_rate",
    "facet_coverage",
    "context_precision",
    "reference_contamination_rate",
    "abstention_precision",
    "abstention_recall",
]


def run_benchmark(
    db_path: str | Path,
    gold_path: str | Path,
    *,
    k: int = 20,
    include_details: bool = False,
    min_quotes: int = 1,
    min_documents: int = 1,
    adequacy_profile: str = "manual",
    embedding_provider: Any | None = None,
    reranker: Any | None = None,
    benchmark_mode: str = "core",
    query_variants: int | None = None,
    max_followup_queries: int | None = None,
    paper_recall_limit: int | None = None,
) -> dict[str, object]:
    started_at = perf_counter()
    min_quotes = max(0, int(min_quotes))
    min_documents = max(0, int(min_documents))
    workflow_config = _resolve_benchmark_workflow_config(
        benchmark_mode,
        query_variants=query_variants,
        max_followup_queries=max_followup_queries,
        paper_recall_limit=paper_recall_limit,
    )
    gold_rows = _load_gold_rows(Path(gold_path))
    answerable_rows = [row for row in gold_rows if bool(row.get("answerable", True))]
    retrieval_hits = 0
    all_gold_retrieval_hits = 0
    retrieved_gold_evidence_total = 0
    gold_evidence_total = 0
    cited_gold = 0
    cited_total = 0
    gold_total = 0
    unsupported_claims = 0
    total_claims = 0
    answerable_adequacy_sufficient = 0
    answerable_adequacy_total = 0
    abstention_correct = 0
    unanswerable_count = 0
    answer_accuracy_hits = 0
    answer_accuracy_total = 0
    citation_verification_passes = 0
    citation_verification_total = 0
    mature_answer_complete_hits = 0
    mature_answer_complete_total = 0
    mature_facet_coverage_sum = 0.0
    mature_facet_coverage_total = 0
    mature_context_precision_sum = 0.0
    mature_context_precision_total = 0
    mature_reference_hits = 0
    mature_retrieved_hits = 0
    mature_predicted_abstentions = 0
    mature_abstention_true_positives = 0
    question_results: list[dict[str, Any]] = []

    for row in gold_rows:
        question = str(row.get("question", ""))
        gold_ids = {str(evidence_id) for evidence_id in row.get("gold_evidence_ids", []) or []}
        answerable = bool(row.get("answerable", True))
        adequacy_thresholds = _adequacy_thresholds_for_gold_answer_type(
            str(row.get("answer_type", "")),
            profile=adequacy_profile,
            min_quotes=min_quotes,
            min_documents=min_documents,
        )
        result = answer_question(
            db_path,
            question,
            limit=k,
            min_quotes=int(adequacy_thresholds["min_quotes"]),
            min_documents=int(adequacy_thresholds["min_documents"]),
            adequacy_profile=str(adequacy_thresholds["profile"]),
            query_variants=int(workflow_config["query_variants"]),
            max_followup_queries=int(workflow_config["max_followup_queries"]),
            paper_recall_limit=int(workflow_config["paper_recall_limit"]),
            embedding_provider=embedding_provider,
            reranker=reranker,
        )
        if str(workflow_config["benchmark_mode"]) == "enhanced":
            hits = list(result.get("hits", []) or [])[: max(0, int(k))]
        else:
            search_kwargs: dict[str, Any] = {
                "limit": k,
                "embedding_provider": embedding_provider,
                "reranker": reranker,
            }
            if int(workflow_config["paper_recall_limit"]) > 0:
                search_kwargs["paper_recall_limit"] = int(workflow_config["paper_recall_limit"])
            hits = search_evidence_store(db_path, question, **search_kwargs)
        hit_ids = {str(hit.get("evidence_id", "")) for hit in hits}
        if str(workflow_config["benchmark_mode"]) == "enhanced":
            mature_reference_hits += sum(1 for hit in hits if _is_reference_hit(hit))
            mature_retrieved_hits += len(hits)
        predicted_abstention = bool(result.get("answer", {}).get("insufficient_evidence", False))
        if str(workflow_config["benchmark_mode"]) == "enhanced":
            mature_predicted_abstentions += int(predicted_abstention)
            if not answerable and predicted_abstention:
                mature_abstention_true_positives += 1
        retrieved_gold_ids: set[str] = set()
        if answerable and gold_ids:
            retrieved_gold_ids = gold_ids.intersection(hit_ids)
            gold_evidence_total += len(gold_ids)
            retrieved_gold_evidence_total += len(retrieved_gold_ids)
            if retrieved_gold_ids:
                retrieval_hits += 1
            if gold_ids.issubset(hit_ids):
                all_gold_retrieval_hits += 1

        quote_evidence_ids = {
            str(evidence_id)
            for quote in result.get("quotes", [])
            for evidence_id in quote.get("evidence_ids", [])
        }
        adequacy = dict(result.get("adequacy", {}) or {})
        cited_gold_ids = quote_evidence_ids.intersection(gold_ids)
        answer_matches_points = None
        if answerable:
            answerable_adequacy_total += 1
            if bool(adequacy.get("is_sufficient", False)):
                answerable_adequacy_sufficient += 1
            cited_total += len(quote_evidence_ids)
            gold_total += len(gold_ids)
            cited_gold += len(cited_gold_ids)
            required_points = [str(point) for point in row.get("required_points", []) or []]
            forbidden_points = [str(point) for point in row.get("forbidden_points", []) or []]
            if required_points or forbidden_points:
                answer_accuracy_total += 1
                answer_text = _answer_text(result)
                answer_matches_points = _answer_matches_points(
                    answer_text,
                    required_points=required_points,
                    forbidden_points=forbidden_points,
                )
                if answer_matches_points:
                    answer_accuracy_hits += 1
            if str(workflow_config["benchmark_mode"]) == "enhanced":
                gold_facets = _gold_facets(row)
                result_completeness = dict(result.get("answer", {}).get("answer_completeness", {}) or {})
                result_facet_coverage = dict(
                    result.get("adequacy", {}).get("facet_coverage", {}) or {}
                )
                if gold_facets:
                    mature_facet_coverage_total += 1
                    coverage_ratio = _coverage_ratio_for_facets(
                        result_completeness or result_facet_coverage,
                        result.get("answer", {}),
                        gold_facets,
                    )
                    mature_facet_coverage_sum += coverage_ratio
                    complete = coverage_ratio >= 1.0
                else:
                    mature_facet_coverage_total += 1
                    mature_facet_coverage_sum += 1.0
                    complete = bool(answer_matches_points) if required_points else not bool(
                        result.get("answer", {}).get("insufficient_evidence", False)
                    )
                mature_answer_complete_total += 1
                if complete:
                    mature_answer_complete_hits += 1
        else:
            unanswerable_count += 1
            if predicted_abstention:
                abstention_correct += 1

        if str(workflow_config["benchmark_mode"]) == "enhanced":
            if answerable and hit_ids:
                mature_context_precision_total += 1
                mature_context_precision_sum += len(retrieved_gold_ids) / len(hit_ids)

        claims = list(result.get("answer", {}).get("answer", []) or [])
        if claims:
            citation_verification_total += 1
            if bool(result.get("citation_verification", {}).get("passed", False)):
                citation_verification_passes += 1
        total_claims += len(claims)
        unsupported_claims += sum(
            1
            for claim in claims
            if str(claim.get("support_status", "")) in {"unsupported", "contradicted", "not_enough_information"}
        )
        if include_details:
            question_results.append(
                _question_result(
                    row,
                    hits=hits,
                    gold_ids=gold_ids,
                    retrieved_gold_ids=retrieved_gold_ids,
                    quote_evidence_ids=quote_evidence_ids,
                    cited_gold_ids=cited_gold_ids,
                    answer=result,
                    claims=claims,
                    answer_matches_points=answer_matches_points,
                )
            )

    citation_precision = _ratio(cited_gold, cited_total)
    citation_recall = _ratio(cited_gold, gold_total)
    citation_f1 = (
        0.0
        if citation_precision + citation_recall <= 0
        else round(2 * citation_precision * citation_recall / (citation_precision + citation_recall), 6)
    )
    wall_time_seconds = round(perf_counter() - started_at, 6)
    metrics: dict[str, object] = {
        "benchmark_mode": str(workflow_config["benchmark_mode"]),
        "benchmark_target": "local_gold_evidence_answer",
        "metric_groups": {
            "core_retrieval": CORE_RETRIEVAL_METRICS,
            "workflow_answer": WORKFLOW_ANSWER_METRICS,
        },
        "questions": len(gold_rows),
        "answerable_questions": len(answerable_rows),
        "wall_time_seconds": wall_time_seconds,
        "avg_wall_time_seconds_per_question": _ratio(wall_time_seconds, len(gold_rows)),
        "k": int(k),
        "query_variants": int(workflow_config["query_variants"]),
        "max_followup_queries": int(workflow_config["max_followup_queries"]),
        "paper_recall_limit": int(workflow_config["paper_recall_limit"]),
        "retrieval_recall_at_k": _ratio(retrieval_hits, len(answerable_rows)),
        "all_gold_retrieval_recall_at_k": _ratio(all_gold_retrieval_hits, len(answerable_rows)),
        "gold_evidence_recall_at_k": _ratio(retrieved_gold_evidence_total, gold_evidence_total),
        "answer_accuracy": _ratio(answer_accuracy_hits, answer_accuracy_total),
        "adequacy_profile": str(adequacy_profile),
        "min_quotes": min_quotes,
        "min_documents": min_documents,
        "answerable_evidence_adequacy_rate": _ratio(
            answerable_adequacy_sufficient,
            answerable_adequacy_total,
        ),
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "citation_f1": citation_f1,
        "citation_verification_pass_rate": _ratio(citation_verification_passes, citation_verification_total),
        "unsupported_claim_rate": _ratio(unsupported_claims, total_claims),
        "abstention_accuracy": _ratio(abstention_correct, unanswerable_count),
    }
    if str(workflow_config["benchmark_mode"]) == "enhanced":
        metrics["metric_groups"] = {
            **dict(metrics["metric_groups"]),
            "mature_quality": MATURE_QUALITY_METRICS,
        }
        metrics.update(
            {
                "answer_completeness_rate": _ratio(
                    mature_answer_complete_hits,
                    mature_answer_complete_total,
                ),
                "facet_coverage": _ratio(
                    mature_facet_coverage_sum,
                    mature_facet_coverage_total,
                ),
                "context_precision": _ratio(
                    mature_context_precision_sum,
                    mature_context_precision_total,
                ),
                "reference_contamination_rate": _ratio(
                    mature_reference_hits,
                    mature_retrieved_hits,
                ),
                "abstention_precision": _ratio(
                    mature_abstention_true_positives,
                    mature_predicted_abstentions,
                ),
                "abstention_recall": _ratio(
                    mature_abstention_true_positives,
                    unanswerable_count,
                ),
            }
        )
    if include_details:
        metrics["question_results"] = question_results
    return metrics


def run_benchmark_comparison(
    db_path: str | Path,
    gold_path: str | Path,
    *,
    presets: list[str] | None = None,
    k: int = 20,
    min_quotes: int = 1,
    min_documents: int = 1,
    adequacy_profile: str = "auto",
    benchmark_mode: str = "core",
    query_variants: int | None = None,
    max_followup_queries: int | None = None,
    paper_recall_limit: int | None = None,
) -> dict[str, object]:
    requested_presets = _normalized_presets(presets)
    rows: list[dict[str, object]] = []
    for preset_name in requested_presets:
        config = _benchmark_provider_preset(preset_name)
        embedding_provider = build_embedding_provider(
            str(config["embedding_provider"]),
            model=str(config["embedding_model"]),
        )
        reranker = build_reranker(
            str(config["reranker"]),
            model_name=str(config["reranker_model"]),
            batch_size=int(config["reranker_batch_size"]),
        )
        metrics = run_benchmark(
            db_path,
            gold_path,
            k=k,
            include_details=False,
            min_quotes=min_quotes,
            min_documents=min_documents,
            adequacy_profile=adequacy_profile,
            embedding_provider=embedding_provider,
            reranker=reranker,
            benchmark_mode=benchmark_mode,
            query_variants=query_variants,
            max_followup_queries=max_followup_queries,
            paper_recall_limit=paper_recall_limit,
        )
        rows.append(
            {
                "preset": preset_name,
                "embedding_provider": str(config["embedding_provider"]),
                "embedding_model": str(config["embedding_model"]),
                "reranker": str(config["reranker"]),
                "reranker_model": str(config["reranker_model"]),
                "reranker_batch_size": int(config["reranker_batch_size"]),
                **metrics,
            }
        )
    return {
        "presets": requested_presets,
        "k": int(k),
        "min_quotes": max(0, int(min_quotes)),
        "min_documents": max(0, int(min_documents)),
        "adequacy_profile": str(adequacy_profile),
        "benchmark_mode": str(rows[0].get("benchmark_mode", benchmark_mode)) if rows else benchmark_mode,
        "rows": rows,
    }


def _normalized_presets(presets: list[str] | None) -> list[str]:
    values = [preset.strip().lower() for preset in presets or ["baseline", "minilm"] if preset.strip()]
    return values or ["baseline", "minilm"]


def _benchmark_provider_preset(name: str) -> dict[str, object]:
    try:
        return dict(BENCHMARK_PROVIDER_PRESETS[name])
    except KeyError as error:
        known = ", ".join(sorted(BENCHMARK_PROVIDER_PRESETS))
        raise ValueError(f"Unsupported benchmark preset: {name}. Known presets: {known}") from error


def _resolve_benchmark_workflow_config(
    benchmark_mode: str,
    *,
    query_variants: int | None,
    max_followup_queries: int | None,
    paper_recall_limit: int | None,
) -> dict[str, object]:
    mode = str(benchmark_mode or "core").strip().lower()
    if mode not in {"core", "enhanced"}:
        raise ValueError(f"Unsupported benchmark_mode: {benchmark_mode}")
    if mode == "core":
        default_query_variants = 1
        default_followups = 0
        default_paper_recall = 0
    else:
        default_query_variants = 2
        default_followups = 2
        default_paper_recall = 50
    return {
        "benchmark_mode": mode,
        "query_variants": max(1, int(query_variants if query_variants is not None else default_query_variants)),
        "max_followup_queries": max(
            0,
            int(max_followup_queries if max_followup_queries is not None else default_followups),
        ),
        "paper_recall_limit": max(0, int(paper_recall_limit if paper_recall_limit is not None else default_paper_recall)),
    }


def generate_gold_question_templates(
    db_path: str | Path,
    *,
    questions_per_type: int = 2,
    answer_types: list[str] | None = None,
) -> dict[str, object]:
    rows = _load_evidence_rows(Path(db_path))
    requested_answer_types = answer_types or list(DEFAULT_TEMPLATE_ANSWER_TYPES)
    templates: list[dict[str, Any]] = []
    missing_answer_types: list[str] = []

    for answer_type in requested_answer_types:
        candidates = _template_candidates_for_answer_type(
            rows,
            answer_type,
            limit=max(0, int(questions_per_type)),
        )
        if not candidates:
            missing_answer_types.append(answer_type)
            continue
        for index, candidate_group in enumerate(candidates, start=1):
            templates.append(_gold_template_row(answer_type, index, candidate_group))

    counts: dict[str, int] = {}
    for template in templates:
        answer_type = str(template.get("answer_type", ""))
        counts[answer_type] = counts.get(answer_type, 0) + 1

    return {
        "rows": len(templates),
        "answer_type_counts": dict(sorted(counts.items())),
        "template_coverage": summarize_template_coverage(templates),
        "requested_answer_types": requested_answer_types,
        "missing_answer_types": missing_answer_types,
        "templates": templates,
    }


def summarize_template_coverage(rows: list[dict[str, Any]]) -> dict[str, object]:
    candidate_evidence_references = 0
    unique_evidence_ids: set[str] = set()
    source_document_counts: dict[str, int] = {}
    section_kind_counts: dict[str, int] = {}
    block_type_counts: dict[str, int] = {}

    for row in rows:
        candidate_evidence = row.get("candidate_evidence", [])
        if not isinstance(candidate_evidence, list):
            continue
        for item in candidate_evidence:
            if not isinstance(item, dict):
                continue
            candidate_evidence_references += 1
            evidence_id = str(item.get("evidence_id", "")).strip()
            if evidence_id:
                unique_evidence_ids.add(evidence_id)
            _increment_count(source_document_counts, _source_document_key(item))
            _increment_count(section_kind_counts, str(item.get("section_kind", "")).strip() or "unset")
            _increment_count(block_type_counts, str(item.get("block_type", "")).strip() or "unset")

    return {
        "candidate_evidence_references": candidate_evidence_references,
        "unique_evidence_spans": len(unique_evidence_ids),
        "source_documents": len(source_document_counts),
        "source_document_counts": dict(sorted(source_document_counts.items())),
        "section_kind_counts": dict(sorted(section_kind_counts.items())),
        "block_type_counts": dict(sorted(block_type_counts.items())),
    }


def _source_document_key(candidate_evidence: dict[str, Any]) -> str:
    for field in ("doc_id", "doi", "title", "evidence_id"):
        value = str(candidate_evidence.get(field, "")).strip()
        if value:
            return value
    return "unset"


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _evidence_record_coverage(
    records: list[dict[str, str]],
    *,
    reference_count_label: str,
) -> dict[str, object]:
    unique_evidence_ids: set[str] = set()
    source_document_counts: dict[str, int] = {}
    section_kind_counts: dict[str, int] = {}
    block_type_counts: dict[str, int] = {}

    for record in records:
        evidence_id = str(record.get("evidence_id", "")).strip()
        if evidence_id:
            unique_evidence_ids.add(evidence_id)
        _increment_count(source_document_counts, _source_document_key(record))
        _increment_count(section_kind_counts, str(record.get("section_kind", "")).strip() or "unset")
        _increment_count(block_type_counts, str(record.get("block_type", "")).strip() or "unset")

    return {
        reference_count_label: len(records),
        "unique_evidence_spans": len(unique_evidence_ids),
        "source_documents": len(source_document_counts),
        "source_document_counts": dict(sorted(source_document_counts.items())),
        "section_kind_counts": dict(sorted(section_kind_counts.items())),
        "block_type_counts": dict(sorted(block_type_counts.items())),
    }


def validate_gold_questions(
    gold_path: str | Path,
    *,
    min_questions: int = 0,
    required_answer_types: list[str] | None = None,
    min_per_answer_type: int = 0,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    rows = _load_gold_rows(Path(gold_path))
    issues: list[dict[str, object]] = []
    answer_type_counts: dict[str, int] = {}
    seen_question_ids: set[str] = set()
    answerable_questions = 0
    unanswerable_questions = 0
    annotation_status_counts: dict[str, int] = {}
    completed_annotation_rows = 0
    empty_question_rows = 0
    known_evidence_metadata = _load_evidence_metadata(Path(db_path)) if db_path else None
    known_evidence_ids = set(known_evidence_metadata) if known_evidence_metadata is not None else None
    missing_gold_evidence_ids: list[str] = []
    gold_evidence_adequacy_issues: list[dict[str, object]] = []
    gold_evidence_quality_warnings: list[dict[str, object]] = []
    valid_gold_evidence_metadata: list[dict[str, str]] = []
    question_summaries: list[dict[str, object]] = []

    if len(rows) < int(min_questions):
        issues.append(
            {
                "line": 0,
                "question_id": "",
                "message": f"minimum question count {int(min_questions)} not met",
            }
        )

    for line_number, row in enumerate(rows, start=1):
        question_id = str(row.get("question_id", "")).strip()
        question = str(row.get("question", "")).strip()
        answer_type = str(row.get("answer_type", "")).strip()
        answerable = bool(row.get("answerable", True))
        raw_gold_ids = row.get("gold_evidence_ids", [])
        gold_ids = list(raw_gold_ids or []) if isinstance(raw_gold_ids, list) else []
        gold_id_values = [str(evidence_id) for evidence_id in gold_ids]
        annotation_status = str(row.get("annotation_status", "")).strip().lower()
        annotation_status_key = annotation_status or "unset"
        annotation_status_counts[annotation_status_key] = annotation_status_counts.get(annotation_status_key, 0) + 1
        if not question:
            empty_question_rows += 1
        if question and annotation_status in {"done", "verified", "approved"}:
            completed_annotation_rows += 1
        question_summary: dict[str, object] = {
            "line": line_number,
            "question_id": question_id,
            "question": question,
            "answer_type": answer_type,
            "answerable": answerable,
            "annotation_status": annotation_status,
            "gold_evidence_ids": gold_id_values,
            "gold_evidence": _gold_evidence_summaries(gold_id_values, known_evidence_metadata),
        }
        _add_optional_template_suggestions(question_summary, row)
        question_summaries.append(question_summary)

        if not question_id:
            _add_gold_issue(issues, line_number, question_id, "question_id is required")
        elif question_id in seen_question_ids:
            _add_gold_issue(issues, line_number, question_id, "duplicate question_id")
        seen_question_ids.add(question_id)

        if not question:
            _add_gold_issue(issues, line_number, question_id, "question is required")
        if not answer_type:
            _add_gold_issue(issues, line_number, question_id, "answer_type is required")
        else:
            answer_type_counts[answer_type] = answer_type_counts.get(answer_type, 0) + 1
        if not isinstance(row.get("gold_evidence_ids", []), list):
            _add_gold_issue(issues, line_number, question_id, "gold_evidence_ids must be a list")
        if not isinstance(row.get("answerable", True), bool):
            _add_gold_issue(issues, line_number, question_id, "answerable must be true or false")
        if not isinstance(row.get("required_points", []), list):
            _add_gold_issue(issues, line_number, question_id, "required_points must be a list")
        if not isinstance(row.get("forbidden_points", []), list):
            _add_gold_issue(issues, line_number, question_id, "forbidden_points must be a list")
        required_points = _string_list(row.get("required_points", []))
        forbidden_points = _string_list(row.get("forbidden_points", []))
        if annotation_status and annotation_status not in {"done", "verified", "approved"}:
            _add_gold_issue(
                issues,
                line_number,
                question_id,
                "annotation_status must be done, verified, or approved before benchmarking",
            )
        require_answer_points = bool(question) and annotation_status != "todo"
        if known_evidence_ids is not None:
            for evidence_id in gold_ids:
                evidence_id_value = str(evidence_id)
                if evidence_id_value not in known_evidence_ids:
                    missing_gold_evidence_ids.append(evidence_id_value)
                    _add_gold_issue(
                        issues,
                        line_number,
                        question_id,
                        f"gold_evidence_id not found in evidence store: {evidence_id_value}",
                    )
                else:
                    valid_gold_evidence_metadata.append(dict(known_evidence_metadata[evidence_id_value]))

        if answerable:
            answerable_questions += 1
            if not gold_ids:
                _add_gold_issue(
                    issues,
                    line_number,
                    question_id,
                    "answerable questions require at least one gold_evidence_id",
                )
            if require_answer_points and not required_points:
                _add_gold_issue(
                    issues,
                    line_number,
                    question_id,
                    "answerable questions require at least one required_point",
                )
            row_adequacy_issues = _gold_evidence_adequacy_issues(
                line_number=line_number,
                question_id=question_id,
                answer_type=answer_type,
                gold_ids=[str(evidence_id) for evidence_id in gold_ids],
                evidence_metadata=known_evidence_metadata,
            )
            for issue in row_adequacy_issues:
                gold_evidence_adequacy_issues.append(issue)
                _add_gold_issue(issues, line_number, question_id, str(issue["message"]))
            gold_evidence_quality_warnings.extend(
                _gold_evidence_quality_warnings(
                    line_number=line_number,
                    question_id=question_id,
                    answer_type=answer_type,
                    gold_ids=[str(evidence_id) for evidence_id in gold_ids],
                    evidence_metadata=known_evidence_metadata,
                )
            )
        else:
            unanswerable_questions += 1
            if gold_ids:
                _add_gold_issue(
                    issues,
                    line_number,
                    question_id,
                    "unanswerable questions must not have gold_evidence_ids",
                )
            if require_answer_points and not forbidden_points:
                _add_gold_issue(
                    issues,
                    line_number,
                    question_id,
                    "unanswerable questions require at least one forbidden_point",
                )

    required = [answer_type for answer_type in required_answer_types or [] if answer_type]
    missing_answer_types = sorted(answer_type for answer_type in required if answer_type_counts.get(answer_type, 0) <= 0)
    for answer_type in missing_answer_types:
        issues.append(
            {
                "line": 0,
                "question_id": "",
                "message": f"missing required answer_type: {answer_type}",
            }
        )
    min_per_answer_type = max(0, int(min_per_answer_type))
    underrepresented_answer_types: list[dict[str, object]] = []
    if min_per_answer_type > 0:
        answer_types_to_check = required or sorted(answer_type_counts)
        for answer_type in sorted(answer_types_to_check):
            count = int(answer_type_counts.get(answer_type, 0))
            if count >= min_per_answer_type:
                continue
            underrepresented_answer_types.append(
                {
                    "answer_type": answer_type,
                    "count": count,
                    "minimum": min_per_answer_type,
                }
            )
            issues.append(
                {
                    "line": 0,
                    "question_id": "",
                    "message": (
                        f"answer_type {answer_type} has {count} questions, "
                        f"below required {min_per_answer_type}"
                    ),
                }
            )

    return {
        "passed": not issues,
        "questions": len(rows),
        "answerable_questions": answerable_questions,
        "unanswerable_questions": unanswerable_questions,
        "answer_type_counts": dict(sorted(answer_type_counts.items())),
        "required_answer_types": required,
        "missing_answer_types": missing_answer_types,
        "min_per_answer_type": min_per_answer_type,
        "underrepresented_answer_types": underrepresented_answer_types,
        "annotation_progress": {
            "total_rows": len(rows),
            "completed_rows": completed_annotation_rows,
            "incomplete_rows": len(rows) - completed_annotation_rows,
            "empty_question_rows": empty_question_rows,
            "status_counts": dict(sorted(annotation_status_counts.items())),
        },
        "checked_evidence_store": known_evidence_ids is not None,
        "evidence_store_path": str(db_path) if db_path else "",
        "missing_gold_evidence_ids": sorted(set(missing_gold_evidence_ids)),
        "gold_evidence_adequacy_issues": gold_evidence_adequacy_issues,
        "gold_evidence_quality_warnings": gold_evidence_quality_warnings,
        "gold_evidence_coverage": _evidence_record_coverage(
            valid_gold_evidence_metadata,
            reference_count_label="gold_evidence_references",
        ),
        "question_summaries": question_summaries,
        "issues": issues,
    }


def _add_optional_template_suggestions(summary: dict[str, object], row: dict[str, Any]) -> None:
    suggested_question = str(row.get("suggested_question", "")).strip()
    if suggested_question:
        summary["suggested_question"] = suggested_question
    if "suggested_required_points" in row:
        summary["suggested_required_points"] = _string_list(row.get("suggested_required_points", []))
    if "suggested_forbidden_points" in row:
        summary["suggested_forbidden_points"] = _string_list(row.get("suggested_forbidden_points", []))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _load_gold_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _question_result(
    row: dict[str, Any],
    *,
    hits: list[dict[str, Any]],
    gold_ids: set[str],
    retrieved_gold_ids: set[str],
    quote_evidence_ids: set[str],
    cited_gold_ids: set[str],
    answer: dict[str, Any],
    claims: list[dict[str, Any]],
    answer_matches_points: bool | None,
) -> dict[str, Any]:
    answerable = bool(row.get("answerable", True))
    hit_ids = [str(hit.get("evidence_id", "")) for hit in hits if str(hit.get("evidence_id", ""))]
    missing_gold_ids = sorted(gold_ids.difference(retrieved_gold_ids))
    missing_cited_gold_ids = sorted(gold_ids.difference(cited_gold_ids))
    return {
        "question_id": str(row.get("question_id", "")),
        "question": str(row.get("question", "")),
        "answer_type": str(row.get("answer_type", "")),
        "answerable": answerable,
        "gold_evidence_ids": sorted(gold_ids),
        "retrieved_evidence_ids": hit_ids,
        "retrieved_gold_evidence_ids": sorted(retrieved_gold_ids),
        "missing_gold_evidence_ids": missing_gold_ids,
        "retrieval_hit": bool(retrieved_gold_ids) if answerable else False,
        "all_gold_retrieved": gold_ids.issubset(set(hit_ids)) if answerable and gold_ids else False,
        "gold_evidence_recall_at_k": _ratio(len(retrieved_gold_ids), len(gold_ids)),
        "quoted_evidence_ids": sorted(quote_evidence_ids),
        "cited_gold_evidence_ids": sorted(cited_gold_ids),
        "missing_cited_gold_evidence_ids": missing_cited_gold_ids,
        "answer_matches_points": answer_matches_points,
        "adequacy": dict(answer.get("adequacy", {}) or {}),
        "insufficient_evidence": bool(answer.get("answer", {}).get("insufficient_evidence", False)),
        "claim_support_counts": _claim_support_counts(claims),
    }


def _adequacy_thresholds_for_gold_answer_type(
    answer_type: str,
    *,
    profile: str,
    min_quotes: int,
    min_documents: int,
) -> dict[str, object]:
    return evidence_adequacy_thresholds(
        _question_type_for_gold_answer_type(answer_type),
        profile=profile,
        min_quotes=min_quotes,
        min_documents=min_documents,
    )


def _question_type_for_gold_answer_type(answer_type: str) -> str:
    normalized = answer_type.strip().lower()
    if normalized == "conflict_evidence":
        return "conflict"
    if normalized == "multi_paper_synthesis":
        return "synthesis"
    if "comparison" in normalized or "compare" in normalized:
        return "comparison"
    return ""


def _claim_support_counts(claims: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim in claims:
        status = str(claim.get("support_status", "") or "unset")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _load_evidence_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                """
                select
                  evidence_id,
                  doc_id,
                  title,
                  doi,
                  source_url,
                  html_path,
                  html_anchor,
                  section,
                  section_kind,
                  block_type,
                  text
                from evidence_spans
                order by evidence_id
                """
            )
        ]


def _load_evidence_metadata(db_path: Path) -> dict[str, dict[str, str]]:
    with sqlite3.connect(db_path) as connection:
        return {
            str(row[0]): {
                "evidence_id": str(row[0]),
                "doc_id": str(row[1]),
                "title": _nullable_text(row[2]),
                "doi": _nullable_text(row[3]),
                "html_path": _nullable_text(row[4]),
                "html_anchor": _nullable_text(row[5]),
                "section": _nullable_text(row[6]),
                "section_kind": _nullable_text(row[7]),
                "block_type": _nullable_text(row[8]),
                "text": _nullable_text(row[9]),
            }
            for row in connection.execute(
                """
                select
                    evidence_id,
                    doc_id,
                    title,
                    doi,
                    html_path,
                    html_anchor,
                    section,
                    section_kind,
                    block_type,
                    text
                from evidence_spans
                order by evidence_id
                """
            )
        }


def _nullable_text(value: object) -> str:
    return "" if value is None else str(value)


def _gold_evidence_summaries(
    gold_ids: list[str],
    evidence_metadata: dict[str, dict[str, str]] | None,
) -> list[dict[str, str]]:
    if evidence_metadata is None:
        return []
    return [dict(evidence_metadata[evidence_id]) for evidence_id in gold_ids if evidence_id in evidence_metadata]


def _gold_evidence_adequacy_issues(
    *,
    line_number: int,
    question_id: str,
    answer_type: str,
    gold_ids: list[str],
    evidence_metadata: dict[str, dict[str, str]] | None,
) -> list[dict[str, object]]:
    if not gold_ids:
        return []

    issues: list[dict[str, object]] = []
    answer_type = str(answer_type or "").strip()
    if answer_type in {"multi_paper_synthesis", "conflict_evidence"}:
        if len(gold_ids) < 2:
            issues.append(
                _gold_adequacy_issue(
                    line_number,
                    question_id,
                    answer_type,
                    f"answer_type {answer_type} requires at least 2 gold_evidence_ids",
                )
            )
        if evidence_metadata is not None:
            doc_ids = {
                str(evidence_metadata[evidence_id].get("doc_id", ""))
                for evidence_id in gold_ids
                if evidence_id in evidence_metadata
            }
            if len(doc_ids) < 2:
                issues.append(
                    _gold_adequacy_issue(
                        line_number,
                        question_id,
                        answer_type,
                        f"answer_type {answer_type} requires gold evidence from at least 2 source documents",
                    )
                )
    if answer_type == "numeric_extraction" and evidence_metadata is not None:
        has_numeric_evidence = any(
            re.search(r"\d", str(evidence_metadata[evidence_id].get("text", "")))
            for evidence_id in gold_ids
            if evidence_id in evidence_metadata
        )
        if not has_numeric_evidence:
            issues.append(
                _gold_adequacy_issue(
                    line_number,
                    question_id,
                    answer_type,
                    "answer_type numeric_extraction requires at least one gold evidence text containing a digit",
                )
            )
    return issues


def _gold_evidence_quality_warnings(
    *,
    line_number: int,
    question_id: str,
    answer_type: str,
    gold_ids: list[str],
    evidence_metadata: dict[str, dict[str, str]] | None,
) -> list[dict[str, object]]:
    if evidence_metadata is None or answer_type not in {"multi_paper_synthesis", "conflict_evidence"}:
        return []
    caption_like_ids = [
        evidence_id
        for evidence_id in gold_ids
        if evidence_id in evidence_metadata and _looks_like_figure_caption_text(evidence_metadata[evidence_id])
    ]
    if not caption_like_ids:
        return []
    return [
        {
            "line": line_number,
            "question_id": question_id,
            "answer_type": answer_type,
            "evidence_ids": caption_like_ids,
            "message": "gold evidence includes figure-caption-like text; review whether caption evidence is intended",
        }
    ]


def _gold_adequacy_issue(line_number: int, question_id: str, answer_type: str, message: str) -> dict[str, object]:
    return {
        "line": line_number,
        "question_id": question_id,
        "answer_type": answer_type,
        "message": message,
    }


def _template_candidates_for_answer_type(
    rows: list[dict[str, Any]],
    answer_type: str,
    *,
    limit: int,
) -> list[list[dict[str, Any]]]:
    if limit <= 0:
        return []
    if answer_type == "single_paper_fact":
        fact_rows = _balanced_single_candidate_rows(
            _section_rows(rows, {"results", "discussion", "abstract"}),
            limit=limit,
        )
        return [[row] for row in fact_rows]
    if answer_type == "single_paper_method":
        method_rows = _balanced_single_candidate_rows(_section_rows(rows, {"methods"}), limit=limit)
        return [[row] for row in method_rows]
    if answer_type == "numeric_extraction":
        numeric_rows = [
            row
            for row in _section_rows(rows, {"results", "methods", "abstract", "discussion"})
            if re.search(r"\d", str(row.get("text", "")))
        ]
        numeric_rows = _balanced_single_candidate_rows(numeric_rows, limit=limit)
        return [[row] for row in numeric_rows]
    if answer_type == "multi_paper_synthesis":
        return _paired_rows(rows, limit=limit, require_negation_contrast=False)
    if answer_type == "conflict_evidence":
        return _paired_rows(rows, limit=limit, require_negation_contrast=True)
    if answer_type == "unanswerable":
        return [[] for _ in range(limit)]
    return []


def _section_rows(rows: list[dict[str, Any]], section_kinds: set[str]) -> list[dict[str, Any]]:
    preferred_block_order = {"paragraph": 0, "table_row": 1, "caption": 2}
    preferred_section_order = {
        "results": 0,
        "methods": 1,
        "discussion": 2,
        "conclusion": 3,
        "abstract": 8,
    }
    filtered = [
        row
        for row in rows
        if str(row.get("section_kind", "")) in section_kinds
    ]
    return sorted(
        filtered,
        key=lambda row: (
            preferred_section_order.get(str(row.get("section_kind", "")), 9),
            preferred_block_order.get(str(row.get("block_type", "")), 9),
            str(row.get("doc_id", "")),
            str(row.get("evidence_id", "")),
        ),
    )


def _paired_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    require_negation_contrast: bool,
) -> list[list[dict[str, Any]]]:
    candidate_rows = _balanced_pair_candidate_rows(
        [
            row
            for row in _section_rows(rows, {"results", "discussion", "abstract"})
            if not _looks_like_figure_caption_text(row)
        ]
    )
    terms_by_index = [_content_terms(row) for row in candidate_rows]
    negated_by_index = [_contains_negation(row) for row in candidate_rows]
    postings_by_term: dict[str, list[int]] = {}
    pair_overlap: dict[tuple[int, int], int] = {}

    for right_index, terms in enumerate(terms_by_index):
        right_doc_id = str(candidate_rows[right_index].get("doc_id", ""))
        for term in sorted(terms):
            postings = postings_by_term.setdefault(term, [])
            for left_index in postings:
                if str(candidate_rows[left_index].get("doc_id", "")) == right_doc_id:
                    continue
                key = (left_index, right_index)
                pair_overlap[key] = pair_overlap.get(key, 0) + 1
            if len(postings) < MAX_PAIR_TERM_POSTINGS:
                postings.append(right_index)

    scored_pairs: list[tuple[int, str, str, dict[str, Any], dict[str, Any]]] = []
    for (left_index, right_index), overlap in pair_overlap.items():
        if overlap <= 0:
            continue
        left_negated = negated_by_index[left_index]
        right_negated = negated_by_index[right_index]
        if require_negation_contrast and left_negated == right_negated:
            continue
        left = candidate_rows[left_index]
        right = candidate_rows[right_index]
        score = overlap + (3 if left_negated != right_negated else 0)
        scored_pairs.append(
            (
                score,
                str(left.get("evidence_id", "")),
                str(right.get("evidence_id", "")),
                left,
                right,
            )
        )
    scored_pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2]))
    return [[left, right] for _, _, _, left, right in scored_pairs[:limit]]


def _looks_like_figure_caption_text(row: dict[str, Any]) -> bool:
    if str(row.get("block_type", "")).strip().lower() == "caption":
        return True
    text = str(row.get("text", "")).strip()
    return bool(
        re.match(r"^(fig\.?|figure)\s+\d", text, flags=re.IGNORECASE)
        or re.search(r"\bpanels?\s+show\b", text, flags=re.IGNORECASE)
        or re.match(r"^representative\s+(image|images|panel|panels|micrograph|micrographs)\b", text, flags=re.IGNORECASE)
    )


def _balanced_pair_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts_by_doc: dict[str, int] = {}
    for row in rows:
        doc_id = str(row.get("doc_id", ""))
        doc_count = counts_by_doc.get(doc_id, 0)
        if doc_count >= MAX_PAIR_CANDIDATE_ROWS_PER_DOC:
            continue
        selected.append(row)
        counts_by_doc[doc_id] = doc_count + 1
        if len(selected) >= MAX_PAIR_CANDIDATE_ROWS:
            break
    return selected


def _balanced_single_candidate_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows_by_doc: dict[str, list[dict[str, Any]]] = {}
    doc_order: list[str] = []
    for row in rows:
        doc_id = str(row.get("doc_id", ""))
        if doc_id not in rows_by_doc:
            rows_by_doc[doc_id] = []
            doc_order.append(doc_id)
        rows_by_doc[doc_id].append(row)

    selected: list[dict[str, Any]] = []
    row_offset = 0
    while len(selected) < limit:
        progressed = False
        for doc_id in doc_order:
            doc_rows = rows_by_doc[doc_id]
            if row_offset >= len(doc_rows):
                continue
            selected.append(doc_rows[row_offset])
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
        row_offset += 1
    return selected


def _content_terms(row: dict[str, Any]) -> set[str]:
    terms = {
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", str(row.get("text", "")).lower())
        if term not in _STOP_TERMS
    }
    return terms


def _contains_negation(row: dict[str, Any]) -> bool:
    text = str(row.get("text", "")).lower()
    return bool(re.search(r"\b(no|not|none|without|lacked|failed|unchanged|did not)\b", text))


def _gold_template_row(answer_type: str, index: int, candidate_group: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = answer_type != "unanswerable"
    candidate_evidence = [_candidate_evidence(row) for row in candidate_group]
    return {
        "question_id": f"todo_{answer_type}_{index:04d}",
        "question": "",
        "candidate_question": _candidate_question(answer_type, candidate_group),
        "suggested_question": _suggested_question(answer_type, candidate_group),
        "answer_type": answer_type,
        "gold_evidence_ids": [str(row.get("evidence_id", "")) for row in candidate_group] if answerable else [],
        "required_points": [],
        "forbidden_points": [],
        "suggested_required_points": _suggested_required_points(answer_type, candidate_group),
        "suggested_forbidden_points": _suggested_forbidden_points(answer_type),
        "answerable": answerable,
        "annotation_status": "todo",
        "annotation_notes": _annotation_notes(answer_type),
        "candidate_evidence": candidate_evidence,
    }


def _candidate_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": str(row.get("evidence_id", "")),
        "doc_id": str(row.get("doc_id", "")),
        "title": str(row.get("title", "")),
        "doi": str(row.get("doi", "")),
        "section": str(row.get("section", "")),
        "section_kind": str(row.get("section_kind", "")),
        "block_type": str(row.get("block_type", "")),
        "text": str(row.get("text", "")),
        "html_path": str(row.get("html_path", "")),
        "html_anchor": str(row.get("html_anchor", "")),
    }


def _candidate_question(answer_type: str, candidate_group: list[dict[str, Any]]) -> str:
    if answer_type == "single_paper_fact":
        return "Write a factual question answered by the candidate evidence sentence."
    if answer_type == "single_paper_method":
        return "Write a methods question answered by the candidate evidence sentence."
    if answer_type == "numeric_extraction":
        return "Write a question whose answer requires extracting the numeric value in the candidate evidence."
    if answer_type == "multi_paper_synthesis":
        return "Write a synthesis question that requires using all candidate evidence spans."
    if answer_type == "conflict_evidence":
        return "Write a question about the apparent conflict or limitation across the candidate evidence spans."
    if answer_type == "unanswerable":
        return "Write a plausible question that is not answerable from the current evidence store."
    return "Write and validate a benchmark question for this answer_type."


def _suggested_question(answer_type: str, candidate_group: list[dict[str, Any]]) -> str:
    titles = _candidate_titles(candidate_group)
    title = titles[0] if titles else "the highlighted paper"
    section = _section_label(candidate_group[0]) if candidate_group else "the highlighted evidence"
    if answer_type == "single_paper_fact":
        return f"What does {title} report in {section}?"
    if answer_type == "single_paper_method":
        return f"What method detail does {title} describe in {section}?"
    if answer_type == "numeric_extraction":
        return f"What numeric value does {title} report in {section}?"
    if answer_type == "multi_paper_synthesis":
        return f"How do {_join_natural(titles)} compare based on the highlighted evidence?"
    if answer_type == "conflict_evidence":
        return f"How do {_join_natural(titles)} differ based on the highlighted evidence?"
    if answer_type == "unanswerable":
        return "Draft a plausible corpus question that should remain unanswered by the current evidence store."
    return "Draft a benchmark question, then verify it against the candidate evidence."


def _suggested_required_points(answer_type: str, candidate_group: list[dict[str, Any]]) -> list[str]:
    if answer_type == "unanswerable":
        return []
    points = [_short_point(str(row.get("text", ""))) for row in candidate_group]
    return [point for point in points if point]


def _suggested_forbidden_points(answer_type: str) -> list[str]:
    if answer_type == "unanswerable":
        return ["Do not answer unless the current evidence store contains direct supporting evidence."]
    return []


def _candidate_titles(candidate_group: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for row in candidate_group:
        title = str(row.get("title", "") or "untitled source").strip()
        if title and title not in seen:
            titles.append(title)
            seen.add(title)
    return titles


def _section_label(row: dict[str, Any]) -> str:
    section = str(row.get("section", "") or row.get("section_kind", "") or "").strip()
    return f"the {section} section" if section else "the highlighted evidence"


def _join_natural(values: list[str]) -> str:
    if not values:
        return "the highlighted papers"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _short_point(value: str, *, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _annotation_notes(answer_type: str) -> str:
    if answer_type == "unanswerable":
        return (
            "Leave gold_evidence_ids empty. Add forbidden_points that should not appear in a correct abstaining answer."
        )
    return (
        "Replace the empty question with a human-written question, verify each gold_evidence_id, "
        "and add required_points/forbidden_points before running bench-validate."
    )


_STOP_TERMS = {
    "about",
    "across",
    "after",
    "also",
    "before",
    "between",
    "cohort",
    "could",
    "from",
    "have",
    "into",
    "more",
    "paper",
    "show",
    "showed",
    "study",
    "that",
    "than",
    "their",
    "there",
    "these",
    "this",
    "using",
    "were",
    "with",
}


def _add_gold_issue(
    issues: list[dict[str, object]],
    line_number: int,
    question_id: str,
    message: str,
) -> None:
    issues.append({"line": line_number, "question_id": question_id, "message": message})


def _answer_text(result: dict[str, Any]) -> str:
    claims = list(result.get("answer", {}).get("answer", []) or [])
    return " ".join(str(claim.get("text", "")) for claim in claims).lower()


def _answer_matches_points(
    answer_text: str,
    *,
    required_points: list[str],
    forbidden_points: list[str],
) -> bool:
    lower_required = [point.lower() for point in required_points]
    lower_forbidden = [point.lower() for point in forbidden_points]
    return all(point in answer_text for point in lower_required) and not any(
        point in answer_text for point in lower_forbidden
    )


def _is_reference_hit(hit: dict[str, Any]) -> bool:
    section = " ".join(
        str(hit.get(field, "")).strip().casefold()
        for field in ("section_kind", "section", "block_type", "block_type_name")
        if str(hit.get(field, "")).strip()
    )
    return bool(re.search(r"(?:reference|bibliography|works cited|literature cited|参考文献|引用文献)", section))


def _gold_facets(row: dict[str, Any]) -> list[dict[str, object]]:
    raw = row.get("required_facets", row.get("facets", []))
    if not isinstance(raw, list):
        return []
    facets: list[dict[str, object]] = []
    for item in raw:
        if isinstance(item, dict):
            facet_id = " ".join(str(item.get("id", item.get("label", ""))).split()).strip()
            terms = [
                " ".join(str(term).split()).strip()
                for term in list(item.get("terms", []) or [])
                if " ".join(str(term).split()).strip()
            ]
        else:
            facet_id = " ".join(str(item).split()).strip()
            terms = [facet_id] if facet_id else []
        if facet_id and terms:
            facets.append({"id": facet_id, "terms": terms})
    return facets


def _coverage_ratio_for_facets(
    coverage: dict[str, Any],
    answer: dict[str, Any],
    facets: list[dict[str, object]],
) -> float:
    if coverage:
        try:
            ratio = float(coverage.get("coverage_ratio", ""))
        except (TypeError, ValueError):
            ratio = -1.0
        if ratio >= 0:
            return max(0.0, min(1.0, ratio))
    text = " ".join(str(claim.get("text", "")) for claim in list(answer.get("answer", []) or [])).casefold()
    covered = 0
    for facet in facets:
        terms = [str(term).casefold() for term in list(facet.get("terms", []) or [])]
        if any(term and term in text for term in terms):
            covered += 1
    return _ratio(covered, len(facets))


def _ratio(numerator: float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
