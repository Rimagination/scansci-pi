from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from scansci_html.bench_external import (
    build_qasper_external_store,
    build_scifact_external_store,
    external_gold_document_ids,
    run_external_retrieval_benchmark,
)
from scansci_html.embeddings import build_embedding_provider
from scansci_html.literature_workflow import workflow_profile
from scansci_html.rerankers import CascadeReranker, build_reranker


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench"


DATASETS = {
    "qasper": {
        "input": ROOT / "external" / "qasper" / "qasper-dev-v0.3.json",
        "gold": BENCH / "gold_questions.external.qasper.jsonl",
        "db": BENCH / "qasper-external-evidence.qwen3-cascade.sqlite",
        "scope": "gold-docs",
    },
    "scifact": {
        "corpus": ROOT / "external" / "scifact" / "data" / "corpus.jsonl",
        "gold": BENCH / "gold_questions.external.scifact.jsonl",
        "db": BENCH / "scifact-external-evidence.qwen3-cascade.sqlite",
        "scope": "corpus",
    },
}


def main() -> None:
    args = parse_args()
    dataset_names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    summary_csv = summary_csv_path(args)
    summary_md = summary_md_path(args)
    rows: list[dict[str, Any]] = []
    for dataset_name in dataset_names:
        row = run_dataset(dataset_name, args)
        rows.append(row)
        write_csv(summary_csv, rows)
        summary_md.write_text(render_markdown(rows, args), encoding="utf-8")
        print(json.dumps({"completed_dataset": dataset_name, "row": row}, ensure_ascii=False), flush=True)
    print(json.dumps({"rows": rows, "csv": str(summary_csv), "markdown": str(summary_md)}, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Qwen3 cascade external retrieval benchmarks on QASPER/SciFact."
    )
    parser.add_argument("--dataset", choices=["qasper", "scifact", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="Optional number of gold rows for smoke runs.")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--initial-limit", type=int, default=200)
    parser.add_argument("--dense-limit", type=int, default=200)
    parser.add_argument("--first-stage-keep", type=int, default=50)
    parser.add_argument("--embedding-cache-batch-size", type=int, default=512)
    parser.add_argument("--include-details", action="store_true")
    parser.add_argument("--no-checkpoint", action="store_true")
    return parser.parse_args()


def run_dataset(dataset_name: str, args: argparse.Namespace) -> dict[str, Any]:
    config = DATASETS[dataset_name]
    db_path = Path(config["db"])
    gold_path = Path(config["gold"])
    limit = int(args.limit or 0)

    if dataset_name == "qasper":
        store_payload = build_qasper_external_store(
            Path(config["input"]),
            gold_path,
            db_path,
            gold_limit=limit,
            benchmark_split="dev",
        )
    elif dataset_name == "scifact":
        store_payload = build_scifact_external_store(
            Path(config["corpus"]),
            db_path,
            doc_ids=external_gold_document_ids(gold_path, limit=limit, benchmark_split="dev") if limit > 0 else None,
        )
    else:  # pragma: no cover
        raise ValueError(f"Unsupported dataset: {dataset_name}")

    profile = workflow_profile("qwen3-cascade", cascade_first_stage_limit=int(args.first_stage_keep))
    embedding_provider = build_embedding_provider(
        str(profile.get("embedding_provider", "sentence-transformers")),
        model=str(profile.get("embedding_model", "")),
        max_seq_length=int(profile.get("embedding_max_seq_length", 0) or 0),
    )
    reranker = build_cascade_reranker(profile)
    resolved_checkpoint_path = checkpoint_path(dataset_name, args)
    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=int(args.k),
        limit=limit,
        include_details=bool(args.include_details),
        initial_limit=int(args.initial_limit),
        dense_limit=int(args.dense_limit),
        scope=str(config["scope"]),
        embedding_provider=embedding_provider,
        embedding_provider_name=str(profile.get("embedding_provider", "")) + ":" + str(profile.get("embedding_model", "")),
        reranker=reranker,
        embedding_cache_batch_size=int(args.embedding_cache_batch_size),
        reranker_cache_name=f"cascade:qwen3:{run_tag(args)}",
        checkpoint_path=None if args.no_checkpoint else resolved_checkpoint_path,
        benchmark_split="dev",
    )
    question_results = list(metrics.pop("question_results", []) or [])
    resolved_details_path = details_path(dataset_name, args)
    if args.include_details:
        resolved_details_path.write_text(
            json.dumps(
                {
                    "dataset": dataset_name,
                    "profile": "qwen3-cascade",
                    "profile_settings": profile,
                    "metrics": metrics,
                    "questions": question_results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    row = {
        "dataset": dataset_name,
        "profile": "qwen3-cascade",
        "questions": metrics.get("questions", 0),
        "scope": config["scope"],
        "k": int(args.k),
        "candidate_pool": f"initial={int(args.initial_limit)},dense={int(args.dense_limit)},minilm_keep={int(args.first_stage_keep)}",
        "embedding_provider": str(profile.get("embedding_provider", "")) + ":" + str(profile.get("embedding_model", "")),
        "reranker": "MiniLM -> Qwen3-Reranker-0.6B",
        "retrieval_recall_at_k": metrics.get("retrieval_recall_at_k", ""),
        "all_gold_retrieval_recall_at_k": metrics.get("all_gold_retrieval_recall_at_k", ""),
        "gold_evidence_recall_at_k": metrics.get("gold_evidence_recall_at_k", ""),
        "wall_time_seconds": metrics.get("wall_time_seconds", ""),
        "avg_wall_time_seconds_per_question": metrics.get("avg_wall_time_seconds_per_question", ""),
        "embedding_cache_hit_rate": metrics.get("embedding_cache_hit_rate", ""),
        "query_embedding_cache_hit_rate": metrics.get("query_embedding_cache_hit_rate", ""),
        "reranker_score_cache_hit_rate": metrics.get("reranker_score_cache_hit_rate", ""),
        "checkpoint_resumed_questions": metrics.get("checkpoint_resumed_questions", ""),
        "checkpoint_written_questions": metrics.get("checkpoint_written_questions", ""),
        "external_corpus_documents": store_payload.get("documents", 0),
        "external_corpus_spans": store_payload.get("spans", 0),
        "details_path": str(resolved_details_path) if args.include_details else "",
        "checkpoint_path": "" if args.no_checkpoint else str(resolved_checkpoint_path),
    }
    return row


def run_tag(args: argparse.Namespace) -> str:
    limit = int(args.limit or 0)
    limit_label = f"limit{limit}" if limit > 0 else "full"
    return f"k{int(args.k)}.minilm{int(args.first_stage_keep)}.{limit_label}"


def summary_csv_path(args: argparse.Namespace) -> Path:
    return BENCH / f"qwen3-cascade-{run_tag(args)}-benchmark.csv"


def summary_md_path(args: argparse.Namespace) -> Path:
    return BENCH / f"qwen3-cascade-{run_tag(args)}-benchmark.md"


def details_path(dataset_name: str, args: argparse.Namespace) -> Path:
    return BENCH / f"{dataset_name}-external-details.qwen3-cascade.{run_tag(args)}.json"


def checkpoint_path(dataset_name: str, args: argparse.Namespace) -> Path:
    return BENCH / f"{dataset_name}.qwen3-cascade.{run_tag(args)}.checkpoint.jsonl"


def build_cascade_reranker(profile: dict[str, Any]) -> CascadeReranker:
    reranker = dict(profile.get("reranker", {}) or {})
    stages = []
    for stage in list(reranker.get("stages", []) or []):
        stage_config = dict(stage)
        stages.append(
            (
                build_reranker(
                    str(stage_config.get("provider", "local")),
                    model_name=str(stage_config.get("model", "")),
                    batch_size=int(stage_config.get("batch_size", 32) or 32),
                ),
                stage_config.get("keep_top"),
            )
        )
    return CascadeReranker(stages)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(rows: list[dict[str, Any]], args: argparse.Namespace) -> str:
    fields = [
        "dataset",
        "questions",
        "gold_evidence_recall_at_k",
        "retrieval_recall_at_k",
        "all_gold_retrieval_recall_at_k",
        "avg_wall_time_seconds_per_question",
        "checkpoint_resumed_questions",
    ]
    lines = [
        "# Qwen3 Cascade Retrieval Benchmark",
        "",
        "Profile: `MiniLM cross-encoder -> Qwen3-Reranker-0.6B`.",
        "",
        f"- k: `{int(args.k)}`",
        f"- candidate pool: `initial={int(args.initial_limit)}, dense={int(args.dense_limit)}, MiniLM keep={int(args.first_stage_keep)}`",
        f"- limit: `{int(args.limit or 0)}` (`0` means full dev split)",
        "",
        "|" + "|".join(fields) + "|",
        "|" + "|".join(["---"] * len(fields)) + "|",
    ]
    for row in rows:
        lines.append("|" + "|".join(markdown_cell(row.get(field, "")) for field in fields) + "|")
    lines.extend(
        [
            "",
            "Notes:",
            "",
            "- Compare these rows against `bench/benchmark_performance.full-dev.csv` and `bench/benchmark_performance.public-full-matrix-openscholar.csv`.",
            "- Checkpointed rows are reused on reruns with the same config hash.",
            "",
        ]
    )
    return "\n".join(lines)


def markdown_cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value).replace("|", "\\|")


if __name__ == "__main__":
    main()
