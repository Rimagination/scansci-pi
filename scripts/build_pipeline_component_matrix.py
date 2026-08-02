from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench"

PUBLIC_RETRIEVAL_CSV = BENCH / "benchmark_performance.public-full-matrix-openscholar.csv"
FULL_DEV_RETRIEVAL_CSV = BENCH / "benchmark_performance.full-dev.csv"
SCIENCEIE_CSV = BENCH / "ie_matrix_scienceie.csv"
LIHUA_QWEN_CSV = BENCH / "lihua-10q-qwen3-30b-a3b.csv"
LIHUA_DEEPSEEK_CSV = BENCH / "lihua-10q-deepseek-v4-pro-202606.csv"

STACK_CSV = BENCH / "pipeline_component_matrix.csv"
COMPONENT_CSV = BENCH / "pipeline_component_leaderboard.csv"
REPORT_MD = BENCH / "pipeline_component_matrix.md"

PAPER_RETRIEVAL_DATASETS = {"qasper", "scifact"}
PUBLIC5_DATASETS = {"qasper", "scifact", "nfcorpus", "scidocs", "trec-covid"}


RETRIEVAL_COMPONENTS = {
    "fts": {
        "name": "FTS lexical",
        "component": "FTS/BM25-style lexical recall; no dense model; no reranker",
        "role": "fast smoke baseline",
    },
    "local_hash_hybrid": {
        "name": "LocalHash hybrid",
        "component": "FTS + local-hash dense fallback; no neural reranker",
        "role": "offline fallback baseline",
    },
    "minilm_dense": {
        "name": "MiniLM dense",
        "component": "sentence-transformers/all-MiniLM-L6-v2 dense retrieval",
        "role": "small dense baseline",
    },
    "bge_small_dense": {
        "name": "BGE-small dense",
        "component": "BAAI/bge-small-en-v1.5 dense retrieval",
        "role": "small dense baseline",
    },
    "qwen3_hybrid": {
        "name": "Qwen3 hybrid",
        "component": "Qwen/Qwen3-Embedding-0.6B hybrid retrieval; no reranker",
        "role": "larger embedding-only candidate",
    },
    "minilm_rerank": {
        "name": "MiniLM rerank",
        "component": "MiniLM dense + cross-encoder/ms-marco-MiniLM-L6-v2 reranker",
        "role": "current complete public-matrix default",
    },
    "qwen3_rerank": {
        "name": "Qwen3 rerank",
        "component": "Qwen/Qwen3-Embedding-0.6B + Qwen/Qwen3-Reranker-0.6B",
        "role": "high-accuracy paper QA candidate; partial dataset coverage",
    },
    "qwen3_openscholar_rerank": {
        "name": "Qwen3 + OpenScholar rerank",
        "component": "Qwen3 embedding + OpenScholar_Reranker",
        "role": "scientific reranker ablation; slow in current runs",
    },
}


IE_COMPONENTS = {
    "regex500": {
        "name": "Regex candidates",
        "component": "lightweight local regex candidate extractor",
        "role": "smoke/diagnostic entity baseline",
    },
    "ngram_all": {
        "name": "Scientific n-gram recall",
        "component": "broad n-gram candidate extractor",
        "role": "high-recall diagnostic, not final extractor",
    },
    "distilbert_min06": {
        "name": "DistilBERT keyphrase",
        "component": "ml6team/keyphrase-extraction-distilbert-inspec, score >= 0.6",
        "role": "best current span extractor",
    },
    "distilbert_min06_typed": {
        "name": "DistilBERT + type classifier",
        "component": "DistilBERT score >= 0.6 + ScienceIE train char-logreg typing",
        "role": "best current typed IE baseline",
    },
}


READER_COMPONENTS = {
    "none": {
        "name": "No LLM reader",
        "component": "retrieval/IE only; no answer synthesis",
        "role": "bulk extraction and indexing mode",
    },
    "qwen3_30b_a3b": {
        "name": "qwen3-30b-a3b",
        "component": "OpenAI-compatible hosted LLM used by official MiniRAG route",
        "role": "practical reader/generator candidate",
        "index_time_note": "~27m46s on LiHua-World 10Q subset",
        "qa_time_note": "~12m19s wall on LiHua-World 10Q subset",
    },
    "deepseek_v4_pro_202606": {
        "name": "deepseek/deepseek-v4-pro-202606",
        "component": "OpenAI-compatible hosted LLM used by official MiniRAG route",
        "role": "higher-accuracy but slower reader/generator candidate",
        "index_time_note": "~48m03s on LiHua-World 10Q subset",
        "qa_time_note": "~15m25s wall on LiHua-World 10Q subset",
    },
}


STACKS = [
    {
        "stack_id": "daily_fast_accurate",
        "retrieval_method_id": "minilm_rerank",
        "ie_method_id": "distilbert_min06_typed",
        "reader_method_id": "qwen3_30b_a3b",
        "status": "recommended_default",
        "recommendation": (
            "Use as the default literature-library workflow: strong complete public retrieval coverage, "
            "best current IE baseline, and LLM only after evidence narrowing."
        ),
    },
    {
        "stack_id": "high_accuracy_paper_qa_candidate",
        "retrieval_method_id": "qwen3_rerank",
        "ie_method_id": "distilbert_min06_typed",
        "reader_method_id": "qwen3_30b_a3b",
        "status": "candidate_needs_full5",
        "recommendation": (
            "Best observed retrieval on QASPER/SciFact, but only partial public coverage and missing stable timing. "
            "Promote after full five-dataset rerun or cascade timing."
        ),
    },
    {
        "stack_id": "slow_scientific_reranker_ablation",
        "retrieval_method_id": "qwen3_openscholar_rerank",
        "ie_method_id": "distilbert_min06_typed",
        "reader_method_id": "deepseek_v4_pro_202606",
        "status": "ablation_only",
        "recommendation": (
            "Keep for small-candidate scientific reranker experiments. Current runs are much slower and do not "
            "beat MiniLM-Rerank on the complete retrieval matrix."
        ),
    },
    {
        "stack_id": "bulk_ie_no_generation",
        "retrieval_method_id": "minilm_rerank",
        "ie_method_id": "distilbert_min06_typed",
        "reader_method_id": "none",
        "status": "recommended_bulk_mode",
        "recommendation": (
            "Use for thousands of papers when the task is entity/keyphrase inventory and candidate evidence mining. "
            "Defer LLM synthesis to shortlisted questions or topics."
        ),
    },
    {
        "stack_id": "ci_smoke_fast",
        "retrieval_method_id": "fts",
        "ie_method_id": "regex500",
        "reader_method_id": "none",
        "status": "smoke_only",
        "recommendation": "Use only for quick health checks; not an accuracy route.",
    },
    {
        "stack_id": "high_recall_ie_diagnostic",
        "retrieval_method_id": "minilm_rerank",
        "ie_method_id": "ngram_all",
        "reader_method_id": "none",
        "status": "diagnostic_only",
        "recommendation": (
            "Use to inspect missed entities. It raises recall but the ScienceIE precision/F1 are too low for "
            "the main extractor."
        ),
    },
]


def main() -> None:
    BENCH.mkdir(parents=True, exist_ok=True)
    retrieval_summary = build_retrieval_summary()
    ie_summary = build_ie_summary()
    reader_summary = build_reader_summary()
    stacks = build_stack_rows(retrieval_summary, ie_summary, reader_summary)
    components = build_component_rows(retrieval_summary, ie_summary, reader_summary)

    write_csv(STACK_CSV, stacks)
    write_csv(COMPONENT_CSV, components)
    REPORT_MD.write_text(
        render_markdown(stacks, components, retrieval_summary, ie_summary, reader_summary),
        encoding="utf-8",
    )

    print(f"Wrote {STACK_CSV}")
    print(f"Wrote {COMPONENT_CSV}")
    print(f"Wrote {REPORT_MD}")


def build_retrieval_summary() -> dict[str, dict[str, Any]]:
    rows: list[dict[str, str]] = []
    rows.extend(read_csv(PUBLIC_RETRIEVAL_CSV))
    for row in read_csv(FULL_DEV_RETRIEVAL_CSV):
        if classify_retrieval_method(row) == "qwen3_rerank":
            rows.append(row)

    grouped: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        method_id = classify_retrieval_method(row)
        if not method_id:
            continue
        dataset = row.get("dataset", "")
        source = row.get("source_path", "")
        key = (method_id, dataset, source)
        if key in seen:
            continue
        seen.add(key)
        grouped.setdefault(method_id, []).append(row)

    summary: dict[str, dict[str, Any]] = {}
    for method_id, method_rows in sorted(grouped.items()):
        public_rows = [row for row in method_rows if row.get("dataset") in PUBLIC5_DATASETS]
        paper_rows = [row for row in method_rows if row.get("dataset") in PAPER_RETRIEVAL_DATASETS]
        info = RETRIEVAL_COMPONENTS.get(method_id, {})
        summary[method_id] = {
            "method_id": method_id,
            "name": info.get("name", method_id),
            "component": info.get("component", ""),
            "role": info.get("role", ""),
            "datasets": ",".join(sorted({row.get("dataset", "") for row in method_rows if row.get("dataset")})),
            "public5_coverage": len({row.get("dataset") for row in public_rows}),
            "paper_coverage": len({row.get("dataset") for row in paper_rows}),
            "public5_mean_retrieval_recall_at20": mean_float(row.get("retrieval_recall_at_k") for row in public_rows),
            "public5_mean_gold_evidence_recall_at20": mean_float(row.get("gold_evidence_recall_at_k") for row in public_rows),
            "public5_mean_seconds_per_question": mean_float(
                row.get("avg_wall_time_seconds_per_question") for row in public_rows
            ),
            "paper_mean_retrieval_recall_at20": mean_float(row.get("retrieval_recall_at_k") for row in paper_rows),
            "paper_mean_gold_evidence_recall_at20": mean_float(row.get("gold_evidence_recall_at_k") for row in paper_rows),
            "paper_mean_seconds_per_question": mean_float(
                row.get("avg_wall_time_seconds_per_question") for row in paper_rows
            ),
            "source": ";".join(sorted({row.get("source_path", "") for row in method_rows if row.get("source_path")})),
        }
    return summary


def build_ie_summary() -> dict[str, dict[str, Any]]:
    rows = [row for row in read_csv(SCIENCEIE_CSV) if row.get("split") == "test"]
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        method_id = row.get("method", "")
        info = IE_COMPONENTS.get(method_id, {})
        summary[method_id] = {
            "method_id": method_id,
            "name": info.get("name", method_id),
            "component": info.get("component", ""),
            "role": info.get("role", ""),
            "dataset": "ScienceIE test",
            "predicted_entities": int_or_blank(row.get("predicted_entities")),
            "entity_precision": float_or_blank(row.get("entity_precision")),
            "entity_recall": float_or_blank(row.get("entity_recall")),
            "entity_f1": float_or_blank(row.get("entity_f1")),
            "typed_entity_f1": float_or_blank(row.get("typed_entity_f1")),
            "source": row.get("predictions_path", ""),
        }
    return summary


def build_reader_summary() -> dict[str, dict[str, Any]]:
    summary = {
        "none": {
            "method_id": "none",
            **READER_COMPONENTS["none"],
            "dataset": "",
            "correct": "",
            "total": "",
            "answer_accuracy": "",
            "source": "",
            "index_time_note": "",
            "qa_time_note": "",
        }
    }
    for method_id, path in [
        ("qwen3_30b_a3b", LIHUA_QWEN_CSV),
        ("deepseek_v4_pro_202606", LIHUA_DEEPSEEK_CSV),
    ]:
        rows = read_csv(path)
        correct = sum(1 for row in rows if str(row.get("is_correct", "")).strip().lower() == "true")
        total = len(rows)
        info = READER_COMPONENTS[method_id]
        summary[method_id] = {
            "method_id": method_id,
            **info,
            "dataset": "MiniRAG LiHua-World 10Q subset",
            "correct": correct,
            "total": total,
            "answer_accuracy": correct / total if total else "",
            "source": str(path.relative_to(ROOT)),
            "index_time_note": info.get("index_time_note", ""),
            "qa_time_note": info.get("qa_time_note", ""),
        }
    return summary


def build_stack_rows(
    retrieval_summary: dict[str, dict[str, Any]],
    ie_summary: dict[str, dict[str, Any]],
    reader_summary: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stack in STACKS:
        retrieval = retrieval_summary.get(stack["retrieval_method_id"], {})
        ie = ie_summary.get(stack["ie_method_id"], {})
        reader = reader_summary.get(stack["reader_method_id"], {})
        rows.append(
            {
                "stack_id": stack["stack_id"],
                "status": stack["status"],
                "retrieval_method_id": stack["retrieval_method_id"],
                "retrieval_component": retrieval.get("component", ""),
                "retrieval_datasets": retrieval.get("datasets", ""),
                "retrieval_paper_coverage": retrieval.get("paper_coverage", ""),
                "retrieval_paper_mean_gold_evidence_recall_at20": retrieval.get(
                    "paper_mean_gold_evidence_recall_at20", ""
                ),
                "retrieval_public5_coverage": retrieval.get("public5_coverage", ""),
                "retrieval_public5_mean_gold_evidence_recall_at20": retrieval.get(
                    "public5_mean_gold_evidence_recall_at20", ""
                ),
                "retrieval_public5_mean_seconds_per_question": retrieval.get(
                    "public5_mean_seconds_per_question", ""
                ),
                "ie_method_id": stack["ie_method_id"],
                "ie_component": ie.get("component", ""),
                "ie_dataset": ie.get("dataset", ""),
                "ie_entity_f1": ie.get("entity_f1", ""),
                "ie_typed_entity_f1": ie.get("typed_entity_f1", ""),
                "reader_method_id": stack["reader_method_id"],
                "reader_component": reader.get("component", ""),
                "reader_dataset": reader.get("dataset", ""),
                "reader_answer_accuracy": reader.get("answer_accuracy", ""),
                "reader_index_time_note": reader.get("index_time_note", ""),
                "reader_qa_time_note": reader.get("qa_time_note", ""),
                "recommendation": stack["recommendation"],
            }
        )
    return rows


def build_component_rows(
    retrieval_summary: dict[str, dict[str, Any]],
    ie_summary: dict[str, dict[str, Any]],
    reader_summary: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method_id, row in sorted(retrieval_summary.items()):
        rows.append(
            {
                "component_type": "retrieval",
                "component_id": method_id,
                "name": row.get("name", ""),
                "role": row.get("role", ""),
                "dataset_scope": "public5 plus paper QA",
                "coverage": row.get("datasets", ""),
                "primary_metric": "paper_mean_gold_evidence_recall_at20",
                "primary_score": row.get("paper_mean_gold_evidence_recall_at20", ""),
                "secondary_metric": "public5_mean_gold_evidence_recall_at20",
                "secondary_score": row.get("public5_mean_gold_evidence_recall_at20", ""),
                "seconds_per_question": row.get("public5_mean_seconds_per_question", ""),
                "source": row.get("source", ""),
            }
        )
    for method_id, row in sorted(ie_summary.items()):
        rows.append(
            {
                "component_type": "ie",
                "component_id": method_id,
                "name": row.get("name", ""),
                "role": row.get("role", ""),
                "dataset_scope": row.get("dataset", ""),
                "coverage": row.get("dataset", ""),
                "primary_metric": "entity_f1",
                "primary_score": row.get("entity_f1", ""),
                "secondary_metric": "typed_entity_f1",
                "secondary_score": row.get("typed_entity_f1", ""),
                "seconds_per_question": "",
                "source": row.get("source", ""),
            }
        )
    for method_id, row in sorted(reader_summary.items()):
        rows.append(
            {
                "component_type": "reader",
                "component_id": method_id,
                "name": row.get("name", ""),
                "role": row.get("role", ""),
                "dataset_scope": row.get("dataset", ""),
                "coverage": row.get("dataset", ""),
                "primary_metric": "answer_accuracy",
                "primary_score": row.get("answer_accuracy", ""),
                "secondary_metric": "correct/total",
                "secondary_score": format_correct_total(row),
                "seconds_per_question": row.get("qa_time_note", ""),
                "source": row.get("source", ""),
            }
        )
    return rows


def render_markdown(
    stacks: list[dict[str, Any]],
    components: list[dict[str, Any]],
    retrieval_summary: dict[str, dict[str, Any]],
    ie_summary: dict[str, dict[str, Any]],
    reader_summary: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "# ScanSci Four-Component Benchmark Matrix",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "This report combines the benchmark evidence we already have for four model/component classes:",
        "",
        "1. Retrieval and embedding.",
        "2. Reranking.",
        "3. Scientific IE/entity extraction.",
        "4. LLM reader/generator.",
        "",
        "The scores are intentionally reported by layer. Retrieval, IE, and reader results come from different benchmarks, so the stack table is an engineering selection matrix, not a single paper-style metric.",
        "",
        "## Recommended Stacks",
        "",
        markdown_table(
            stacks,
            [
                "stack_id",
                "status",
                "retrieval_method_id",
                "retrieval_paper_coverage",
                "retrieval_paper_mean_gold_evidence_recall_at20",
                "retrieval_public5_coverage",
                "retrieval_public5_mean_gold_evidence_recall_at20",
                "ie_method_id",
                "ie_entity_f1",
                "ie_typed_entity_f1",
                "reader_method_id",
                "reader_answer_accuracy",
                "recommendation",
            ],
        ),
        "",
        "## Retrieval Components",
        "",
        markdown_table(
            sorted(
                retrieval_summary.values(),
                key=lambda row: score_sort_key(row.get("paper_mean_gold_evidence_recall_at20")),
                reverse=True,
            ),
            [
                "method_id",
                "role",
                "paper_coverage",
                "paper_mean_gold_evidence_recall_at20",
                "public5_coverage",
                "public5_mean_gold_evidence_recall_at20",
                "public5_mean_seconds_per_question",
                "component",
            ],
        ),
        "",
        "## IE Components",
        "",
        markdown_table(
            sorted(ie_summary.values(), key=lambda row: score_sort_key(row.get("entity_f1")), reverse=True),
            [
                "method_id",
                "role",
                "dataset",
                "predicted_entities",
                "entity_precision",
                "entity_recall",
                "entity_f1",
                "typed_entity_f1",
                "component",
            ],
        ),
        "",
        "## LLM Reader Components",
        "",
        markdown_table(
            sorted(reader_summary.values(), key=lambda row: score_sort_key(row.get("answer_accuracy")), reverse=True),
            [
                "method_id",
                "role",
                "dataset",
                "correct",
                "total",
                "answer_accuracy",
                "index_time_note",
                "qa_time_note",
            ],
        ),
        "",
        "## Decision Notes",
        "",
        "- Current default: `daily_fast_accurate` or `bulk_ie_no_generation`, depending on whether answer synthesis is needed.",
        "- `qwen3_rerank` is the clearest candidate to beat MiniLM-Rerank on paper QA retrieval, but it currently has only QASPER/SciFact coverage in this matrix.",
        "- `qwen3_openscholar_rerank` is scientific-domain aware, but the existing runs are slow and do not beat MiniLM-Rerank on the complete public retrieval matrix.",
        "- For thousands of papers, do not run MiniRAG/GraphRAG-style LLM graph extraction across the whole library first. Retrieve and rerank cheaply, extract IE candidates locally, then spend LLM calls only on narrowed evidence or topics.",
        "",
        "## Generated Files",
        "",
        f"- Stack matrix CSV: `{STACK_CSV.relative_to(ROOT)}`",
        f"- Component leaderboard CSV: `{COMPONENT_CSV.relative_to(ROOT)}`",
        f"- Source retrieval CSVs: `{PUBLIC_RETRIEVAL_CSV.relative_to(ROOT)}`, `{FULL_DEV_RETRIEVAL_CSV.relative_to(ROOT)}`",
        f"- Source IE CSV: `{SCIENCEIE_CSV.relative_to(ROOT)}`",
        f"- Source reader reports: `{LIHUA_QWEN_CSV.relative_to(ROOT)}`, `{LIHUA_DEEPSEEK_CSV.relative_to(ROOT)}`",
        "",
    ]
    return "\n".join(lines)


def classify_retrieval_method(row: dict[str, str]) -> str:
    label = row.get("label", "")
    if label.endswith("MiniLM-Rerank"):
        return "minilm_rerank"
    if label.endswith("MiniLM-Dense"):
        return "minilm_dense"
    if label.endswith("BGE-small"):
        return "bge_small_dense"
    if label.endswith("Qwen3-Hybrid"):
        return "qwen3_hybrid"
    if label.endswith("Qwen3+OpenScholar"):
        return "qwen3_openscholar_rerank"
    if label.endswith("Qwen3-Rerank"):
        return "qwen3_rerank"
    if label.endswith("LocalHash"):
        return "local_hash_hybrid"
    if label.endswith("FTS"):
        return "fts"
    return ""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    output = ["|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"]
    for row in rows:
        output.append("|" + "|".join(markdown_cell(row.get(field, "")) for field in fields) + "|")
    return "\n".join(output)


def markdown_cell(value: Any) -> str:
    if isinstance(value, float):
        text = f"{value:.3f}"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def mean_float(values: Any) -> float | str:
    parsed = [value for value in (float_or_blank(value) for value in values) if isinstance(value, float)]
    if not parsed:
        return ""
    return sum(parsed) / len(parsed)


def float_or_blank(value: Any) -> float | str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return float(text)
    except ValueError:
        return ""


def int_or_blank(value: Any) -> int | str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return int(float(text))
    except ValueError:
        return ""


def score_sort_key(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return -1.0


def format_correct_total(row: dict[str, Any]) -> str:
    correct = row.get("correct", "")
    total = row.get("total", "")
    if correct == "" or total == "":
        return ""
    return f"{correct}/{total}"


if __name__ == "__main__":
    main()
