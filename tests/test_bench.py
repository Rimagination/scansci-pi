import io
import importlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from scansci_html import bench_import
from scansci_html import cli
from scansci_html.bench import (
    generate_gold_question_templates,
    run_benchmark,
    run_benchmark_comparison,
    validate_gold_questions,
)
from scansci_html.acceptance_workbench import build_local_acceptance_workbench
from scansci_html.bench_fetch import fetch_beir_dataset
from scansci_html.bench_leaderboard import (
    build_benchmark_leaderboard,
    render_leaderboard_chart_html,
    render_leaderboard_html,
    render_leaderboard_markdown,
)
from scansci_html.bench_external import (
    build_beir_external_store,
    build_scifact_external_store,
    external_query_variants,
    run_external_retrieval_benchmark,
)
from scansci_html.bench_mistakes import generate_mistake_cases, render_mistake_cases_report
from scansci_html.bench_mistakes import summarize_mistake_cases
from scansci_html.evidence_store import index_evidence_library
from scansci_html.render.gold_template import render_gold_template_report
from scansci_html.render.gold_validation import render_gold_validation_report


def test_run_benchmark_scores_retrieval_citation_and_abstention(tmp_path: Path):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)

    result = run_benchmark(db_path, gold_path, k=5)

    assert result["wall_time_seconds"] >= 0
    assert result["avg_wall_time_seconds_per_question"] >= 0
    metric_subset = {key: value for key, value in result.items() if key not in {
        "wall_time_seconds",
        "avg_wall_time_seconds_per_question",
    }}
    assert metric_subset == {
        "benchmark_mode": "core",
        "benchmark_target": "local_gold_evidence_answer",
        "metric_groups": {
            "core_retrieval": [
                "retrieval_recall_at_k",
                "all_gold_retrieval_recall_at_k",
                "gold_evidence_recall_at_k",
            ],
            "workflow_answer": [
                "answer_accuracy",
                "answerable_evidence_adequacy_rate",
                "citation_precision",
                "citation_recall",
                "citation_f1",
                "citation_verification_pass_rate",
                "unsupported_claim_rate",
                "abstention_accuracy",
            ],
        },
        "questions": 2,
        "answerable_questions": 1,
        "k": 5,
        "query_variants": 1,
        "max_followup_queries": 0,
        "paper_recall_limit": 0,
        "retrieval_recall_at_k": 1.0,
        "all_gold_retrieval_recall_at_k": 1.0,
        "gold_evidence_recall_at_k": 1.0,
        "answer_accuracy": 1.0,
        "adequacy_profile": "manual",
        "min_quotes": 1,
        "min_documents": 1,
        "answerable_evidence_adequacy_rate": 1.0,
        "citation_precision": 1.0,
        "citation_recall": 1.0,
        "citation_f1": 1.0,
        "citation_verification_pass_rate": 1.0,
        "unsupported_claim_rate": 0.0,
        "abstention_accuracy": 1.0,
    }


def test_build_benchmark_leaderboard_ranks_details_by_evidence_recall(tmp_path: Path):
    qasper_path = tmp_path / "qasper-details.json"
    scifact_path = tmp_path / "scifact-details.json"
    qasper_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "dataset": "qasper",
                    "questions": 100,
                    "answerable_questions": 80,
                    "scope": "gold-docs",
                    "k": 20,
                    "initial_limit": 20,
                    "dense_limit": 20,
                    "embedding_provider": "sentence-transformers:Qwen/Qwen3-Embedding-0.6B",
                    "reranker_score_cache_name": "qwen3-reranker-0.6b",
                    "retrieval_recall_at_k": 0.7,
                    "all_gold_retrieval_recall_at_k": 0.6,
                    "gold_evidence_recall_at_k": 0.62,
                    "wall_time_seconds": 12.5,
                    "embedding_cache_hits": 9,
                    "embedding_cache_misses": 1,
                },
                "questions": [],
            }
        ),
        encoding="utf-8",
    )
    scifact_path.write_text(
        json.dumps(
            {
                "dataset": "qasper",
                "questions": 100,
                "answerable_questions": 80,
                "scope": "gold-docs",
                "k": 20,
                "initial_limit": 20,
                "dense_limit": 0,
                "query_variants": 1,
                "embedding_provider": "local-hash-v1",
                "retrieval_trace_questions": 50,
                "retrieval_recall_at_k": 0.95,
                "all_gold_retrieval_recall_at_k": 0.9,
                "gold_evidence_recall_at_k": 0.91,
            }
        ),
        encoding="utf-8",
    )

    payload = build_benchmark_leaderboard(
        [qasper_path, scifact_path],
        labels=["QASPER Qwen3", "QASPER FTS"],
    )
    markdown = render_leaderboard_markdown(payload)
    html = render_leaderboard_html(payload)
    chart_html = render_leaderboard_chart_html(payload)

    assert payload["runs"] == 2
    assert payload["rank_scope"] == "comparison_group"
    assert payload["rows"][0]["rank"] == 1
    assert payload["rows"][0]["label"] == "QASPER FTS"
    assert payload["rows"][0]["candidate_pool"] == "initial=20,dense=0"
    assert payload["rows"][0]["retrieval_trace_questions"] == 50
    assert payload["rows"][0]["comparison_group"] == "target-unset/legacy/qasper/gold-docs/k20/q100"
    assert payload["rows"][1]["source_format"] == "nested_metrics"
    assert payload["rows"][1]["wall_time_seconds"] == 12.5
    assert payload["rows"][1]["embedding_cache_hit_rate"] == 0.9
    assert "Evidence recall@k" in markdown
    assert "paper-style validation" in markdown
    assert "optional acceptance" in markdown
    assert "final decision layer" not in markdown
    assert "QASPER FTS" in html
    assert "paper-style validation" in html
    assert "optional acceptance" in html
    assert "final decision layer" not in html
    assert "<svg" in chart_html
    assert "Evidence recall@k" in chart_html
    assert "91.0" in chart_html


def test_benchmark_leaderboard_separates_core_and_enhanced_modes(tmp_path: Path):
    core_path = tmp_path / "core.json"
    enhanced_path = tmp_path / "enhanced.json"
    base_metrics = {
        "benchmark_target": "local_gold_evidence_answer",
        "dataset": "local",
        "questions": 10,
        "scope": "full-library",
        "k": 20,
        "retrieval_recall_at_k": 0.8,
        "all_gold_retrieval_recall_at_k": 0.7,
        "gold_evidence_recall_at_k": 0.75,
    }
    core_path.write_text(
        json.dumps({"metrics": {**base_metrics, "benchmark_mode": "core"}}),
        encoding="utf-8",
    )
    enhanced_path.write_text(
        json.dumps({"metrics": {**base_metrics, "benchmark_mode": "enhanced", "gold_evidence_recall_at_k": 0.9}}),
        encoding="utf-8",
    )

    payload = build_benchmark_leaderboard([core_path, enhanced_path])

    groups = {row["comparison_group"] for row in payload["rows"]}
    assert groups == {
        "local_gold_evidence_answer/core/local/full-library/k20/q10",
        "local_gold_evidence_answer/enhanced/local/full-library/k20/q10",
    }
    assert all(row["rank"] == 1 for row in payload["rows"])


def test_run_benchmark_passes_embedding_provider_and_reranker(tmp_path: Path, monkeypatch):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)
    captured: dict[str, object] = {}
    embedding_provider = object()
    reranker = object()

    def fake_search_evidence_store(db_path_arg, question, *, limit, embedding_provider, reranker):
        captured["search"] = {
            "db_path": db_path_arg,
            "question": question,
            "limit": limit,
            "embedding_provider": embedding_provider,
            "reranker": reranker,
        }
        return [
            {
                "evidence_id": "10.1234_bench.s0001",
                "doc_id": "10.1234_bench",
                "text": "Model predictions explained cortical activity in language regions.",
            }
        ]

    def fake_answer_question(
        db_path_arg,
        question,
        *,
        limit,
        min_quotes,
        min_documents,
        adequacy_profile,
        embedding_provider,
        reranker,
        query_variants,
        max_followup_queries,
        paper_recall_limit,
    ):
        captured["answer"] = {
            "db_path": db_path_arg,
            "question": question,
            "limit": limit,
            "min_quotes": min_quotes,
            "min_documents": min_documents,
            "adequacy_profile": adequacy_profile,
            "embedding_provider": embedding_provider,
            "reranker": reranker,
            "query_variants": query_variants,
            "max_followup_queries": max_followup_queries,
            "paper_recall_limit": paper_recall_limit,
        }
        return {
            "quotes": [{"evidence_ids": ["10.1234_bench.s0001"]}],
            "adequacy": {"is_sufficient": True},
            "answer": {
                "answer": [
                    {
                        "text": "Model predictions explained cortical activity in language regions.",
                        "support_status": "supported",
                    }
                ],
                "insufficient_evidence": False,
            },
        }

    monkeypatch.setattr("scansci_html.bench.search_evidence_store", fake_search_evidence_store)
    monkeypatch.setattr("scansci_html.bench.answer_question", fake_answer_question)

    result = run_benchmark(
        db_path,
        gold_path,
        k=5,
        embedding_provider=embedding_provider,
        reranker=reranker,
    )

    assert result["retrieval_recall_at_k"] == 1.0
    assert captured["search"]["embedding_provider"] is embedding_provider
    assert captured["search"]["reranker"] is reranker
    assert captured["answer"]["embedding_provider"] is embedding_provider
    assert captured["answer"]["reranker"] is reranker
    assert captured["answer"]["query_variants"] == 1
    assert captured["answer"]["max_followup_queries"] == 0
    assert captured["answer"]["paper_recall_limit"] == 0


def test_run_benchmark_enhanced_mode_records_workflow_defaults(tmp_path: Path):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)

    result = run_benchmark(db_path, gold_path, k=5, benchmark_mode="enhanced")

    assert result["benchmark_mode"] == "enhanced"
    assert result["benchmark_target"] == "local_gold_evidence_answer"
    assert result["query_variants"] == 2
    assert result["max_followup_queries"] == 2
    assert result["paper_recall_limit"] == 50
    assert "workflow_answer" in result["metric_groups"]


def test_run_benchmark_comparison_runs_provider_presets(tmp_path: Path, monkeypatch):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)
    built_embeddings: list[tuple[str, str]] = []
    built_rerankers: list[tuple[str, str, int]] = []
    benchmark_calls: list[dict[str, object]] = []

    def fake_build_embedding_provider(provider, *, model="", **kwargs):
        built_embeddings.append((provider, model))
        return f"embedding:{provider}:{model}"

    def fake_build_reranker(provider, *, model_name="", batch_size=32):
        built_rerankers.append((provider, model_name, batch_size))
        return f"reranker:{provider}:{model_name}:{batch_size}"

    def fake_run_benchmark(
        db_path_arg,
        gold_path_arg,
        *,
        k,
        include_details,
        min_quotes,
        min_documents,
        adequacy_profile,
        embedding_provider,
        reranker,
        **kwargs,
    ):
        benchmark_calls.append(
            {
                "db_path": db_path_arg,
                "gold_path": gold_path_arg,
                "k": k,
                "include_details": include_details,
                "min_quotes": min_quotes,
                "min_documents": min_documents,
                "adequacy_profile": adequacy_profile,
                "embedding_provider": embedding_provider,
                "reranker": reranker,
                **kwargs,
            }
        )
        score = 1.0 if "sentence-transformers" in str(embedding_provider) else 0.5
        return {
            "questions": 2,
            "answerable_questions": 1,
            "retrieval_recall_at_k": score,
            "all_gold_retrieval_recall_at_k": score,
            "gold_evidence_recall_at_k": score,
            "answer_accuracy": score,
            "adequacy_profile": adequacy_profile,
            "min_quotes": min_quotes,
            "min_documents": min_documents,
            "answerable_evidence_adequacy_rate": score,
            "citation_precision": score,
            "citation_recall": score,
            "citation_f1": score,
            "unsupported_claim_rate": 0.0,
            "abstention_accuracy": score,
        }

    monkeypatch.setattr("scansci_html.bench.build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr("scansci_html.bench.build_reranker", fake_build_reranker)
    monkeypatch.setattr("scansci_html.bench.run_benchmark", fake_run_benchmark)

    result = run_benchmark_comparison(
        db_path,
        gold_path,
        presets=["baseline", "minilm"],
        k=7,
        min_quotes=2,
        min_documents=2,
        adequacy_profile="auto",
    )

    assert result["presets"] == ["baseline", "minilm"]
    assert [row["preset"] for row in result["rows"]] == ["baseline", "minilm"]
    assert result["rows"][0]["embedding_provider"] == "local"
    assert result["rows"][0]["reranker"] == "local"
    assert result["rows"][1]["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert result["rows"][1]["reranker_model"] == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert result["rows"][1]["retrieval_recall_at_k"] == 1.0
    assert result["benchmark_mode"] == "core"
    assert benchmark_calls[0]["benchmark_mode"] == "core"
    assert built_embeddings == [
        ("local", ""),
        ("sentence-transformers", "sentence-transformers/all-MiniLM-L6-v2"),
    ]
    assert built_rerankers == [
        ("local", "", 32),
        ("cross-encoder", "cross-encoder/ms-marco-MiniLM-L6-v2", 32),
    ]
    assert benchmark_calls[1]["k"] == 7
    assert benchmark_calls[1]["min_quotes"] == 2
    assert benchmark_calls[1]["min_documents"] == 2
    assert benchmark_calls[1]["adequacy_profile"] == "auto"


def test_run_benchmark_comparison_includes_qwen3_vl_preset(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "evidence.sqlite"
    db_path.write_text("db", encoding="utf-8")
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text("{}", encoding="utf-8")
    captured_presets: list[str] = []

    def fake_build_embedding_provider(provider, *, base_url="", api_key="", model="", dimensions=128, batch_size=32, max_seq_length=0):
        return object()

    def fake_build_reranker(provider, *, model_name="", batch_size=32):
        return object()

    def fake_run_benchmark(*args, **kwargs):
        return {
            "questions": 1,
            "answerable_questions": 1,
            "retrieval_recall_at_k": 0.0,
            "all_gold_retrieval_recall_at_k": 0.0,
            "gold_evidence_recall_at_k": 0.0,
            "answer_accuracy": 0.0,
            "adequacy_profile": kwargs.get("adequacy_profile", "auto"),
            "min_quotes": kwargs.get("min_quotes", 1),
            "min_documents": kwargs.get("min_documents", 1),
            "answerable_evidence_adequacy_rate": 0.0,
            "citation_precision": 0.0,
            "citation_recall": 0.0,
            "citation_f1": 0.0,
            "unsupported_claim_rate": 0.0,
            "abstention_accuracy": 0.0,
        }

    monkeypatch.setattr("scansci_html.bench.build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr("scansci_html.bench.build_reranker", fake_build_reranker)
    monkeypatch.setattr("scansci_html.bench.run_benchmark", fake_run_benchmark)

    result = run_benchmark_comparison(
        db_path,
        gold_path,
        presets=["qwen3-vl"],
        k=5,
    )

    captured_presets.extend(result["presets"])
    assert captured_presets == ["qwen3-vl"]
    assert result["rows"][0]["embedding_model"] == "Qwen/Qwen3-VL-Embedding-2B"
    assert result["rows"][0]["reranker_model"] == "Qwen/Qwen3-Reranker-0.6B"


def test_cli_bench_emits_benchmark_metrics(tmp_path: Path, capsys):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)

    exit_code = cli.main(["bench", "--db", str(db_path), "--gold", str(gold_path), "--k", "5"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["questions"] == 2
    assert payload["benchmark_mode"] == "core"
    assert payload["benchmark_target"] == "local_gold_evidence_answer"
    assert payload["query_variants"] == 1
    assert payload["max_followup_queries"] == 0
    assert payload["paper_recall_limit"] == 0
    assert payload["retrieval_recall_at_k"] == 1.0
    assert payload["all_gold_retrieval_recall_at_k"] == 1.0
    assert payload["gold_evidence_recall_at_k"] == 1.0
    assert payload["adequacy_profile"] == "auto"
    assert payload["min_quotes"] == 1
    assert payload["min_documents"] == 1
    assert payload["answerable_evidence_adequacy_rate"] == 1.0
    assert payload["citation_f1"] == 1.0
    assert payload["details_output_path"] == ""
    assert payload["details_html_output_path"] == ""


def test_cli_bench_passes_embedding_and_reranker_options(monkeypatch, capsys):
    captured: dict[str, object] = {}
    embedding_provider = object()
    reranker = object()

    def fake_build_embedding_provider(
        provider,
        *,
        base_url="",
        api_key="",
        model="",
        dimensions=128,
        batch_size=32,
        max_seq_length=0,
    ):
        captured["embedding_provider"] = (provider, base_url, api_key, model, dimensions)
        return embedding_provider

    def fake_build_reranker(provider, *, model_name="", batch_size=32):
        captured["reranker"] = (provider, model_name, batch_size)
        return reranker

    def fake_run_benchmark(
        db_path,
        gold_path,
        *,
        k,
        include_details,
        min_quotes,
        min_documents,
        adequacy_profile,
        embedding_provider,
        reranker,
        **kwargs,
    ):
        captured["benchmark"] = {
            "db_path": db_path,
            "gold_path": gold_path,
            "k": k,
            "include_details": include_details,
            "min_quotes": min_quotes,
            "min_documents": min_documents,
            "adequacy_profile": adequacy_profile,
            "embedding_provider": embedding_provider,
            "reranker": reranker,
            **kwargs,
        }
        return {
            "questions": 0,
            "answerable_questions": 0,
            "retrieval_recall_at_k": 0.0,
            "all_gold_retrieval_recall_at_k": 0.0,
            "gold_evidence_recall_at_k": 0.0,
            "answer_accuracy": 0.0,
            "adequacy_profile": adequacy_profile,
            "min_quotes": min_quotes,
            "min_documents": min_documents,
            "answerable_evidence_adequacy_rate": 0.0,
            "citation_precision": 0.0,
            "citation_recall": 0.0,
            "citation_f1": 0.0,
            "unsupported_claim_rate": 0.0,
            "abstention_accuracy": 0.0,
        }

    monkeypatch.setattr(cli, "build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr(cli, "build_reranker", fake_build_reranker)
    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)

    exit_code = cli.main(
        [
            "bench",
            "--db",
            "evidence.sqlite",
            "--gold",
            "gold.jsonl",
            "--k",
            "7",
            "--embedding-provider",
            "sentence-transformers",
            "--embedding-model",
            "sentence-transformers/all-MiniLM-L6-v2",
            "--reranker",
            "cross-encoder",
            "--reranker-model",
            "cross-encoder/ms-marco-MiniLM-L6-v2",
            "--reranker-batch-size",
            "5",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["embedding_provider"] == (
        "sentence-transformers",
        "",
        "",
        "sentence-transformers/all-MiniLM-L6-v2",
        128,
    )
    assert captured["reranker"] == ("cross-encoder", "cross-encoder/ms-marco-MiniLM-L6-v2", 5)
    assert captured["benchmark"]["embedding_provider"] is embedding_provider
    assert captured["benchmark"]["reranker"] is reranker
    assert captured["benchmark"]["k"] == 7
    assert captured["benchmark"]["benchmark_mode"] == "core"
    assert captured["benchmark"]["query_variants"] is None
    assert captured["benchmark"]["max_followup_queries"] is None
    assert captured["benchmark"]["paper_recall_limit"] is None
    assert payload["passed"] is True


def test_cli_bench_compare_writes_comparison_outputs(tmp_path: Path, monkeypatch, capsys):
    captured: dict[str, object] = {}
    output_path = tmp_path / "comparison.json"
    csv_output_path = tmp_path / "comparison.csv"

    def fake_run_benchmark_comparison(
        db_path,
        gold_path,
        *,
        presets,
        k,
        min_quotes,
        min_documents,
        adequacy_profile,
        **kwargs,
    ):
        captured["call"] = {
            "db_path": db_path,
            "gold_path": gold_path,
            "presets": presets,
            "k": k,
            "min_quotes": min_quotes,
            "min_documents": min_documents,
            "adequacy_profile": adequacy_profile,
            **kwargs,
        }
        return {
            "presets": presets,
            "k": k,
            "rows": [
                {
                    "preset": "baseline",
                    "embedding_provider": "local",
                    "embedding_model": "",
                    "reranker": "local",
                    "reranker_model": "",
                    "retrieval_recall_at_k": 0.5,
                    "citation_f1": 0.5,
                    "answer_accuracy": 0.5,
                    "unsupported_claim_rate": 0.25,
                },
                {
                    "preset": "minilm",
                    "embedding_provider": "sentence-transformers",
                    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
                    "reranker": "cross-encoder",
                    "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2",
                    "retrieval_recall_at_k": 1.0,
                    "citation_f1": 1.0,
                    "answer_accuracy": 1.0,
                    "unsupported_claim_rate": 0.0,
                },
            ],
        }

    monkeypatch.setattr(cli, "run_benchmark_comparison", fake_run_benchmark_comparison)

    exit_code = cli.main(
        [
            "bench-compare",
            "--db",
            "evidence.sqlite",
            "--gold",
            "gold.jsonl",
            "--presets",
            "baseline,minilm",
            "--k",
            "7",
            "--min-quotes",
            "2",
            "--min-documents",
            "2",
            "--output",
            str(output_path),
            "--csv-output",
            str(csv_output_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(output_path.read_text(encoding="utf-8"))
    csv_text = csv_output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert captured["call"]["presets"] == ["baseline", "minilm"]
    assert captured["call"]["k"] == 7
    assert captured["call"]["min_quotes"] == 2
    assert captured["call"]["min_documents"] == 2
    assert captured["call"]["benchmark_mode"] == "core"
    assert payload["output_path"] == str(output_path)
    assert payload["csv_output_path"] == str(csv_output_path)
    assert saved_payload["rows"][1]["preset"] == "minilm"
    assert "preset,embedding_provider,embedding_model,reranker,reranker_model" in csv_text
    assert "minilm,sentence-transformers,sentence-transformers/all-MiniLM-L6-v2,cross-encoder" in csv_text


def test_cli_bench_writes_details_output(tmp_path: Path, capsys):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)
    details_path = tmp_path / "benchmark-details.json"
    details_html_path = tmp_path / "benchmark-details.html"

    exit_code = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--k",
            "5",
            "--details-output",
            str(details_path),
            "--details-html-output",
            str(details_html_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    details = json.loads(details_path.read_text(encoding="utf-8"))
    html = details_html_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["details_output_path"] == str(details_path)
    assert payload["details_html_output_path"] == str(details_html_path)
    assert details["metrics"]["passed"] is True
    assert details["metrics"]["details_output_path"] == str(details_path)
    assert details["metrics"]["details_html_output_path"] == str(details_html_path)
    assert [question["question_id"] for question in details["questions"]] == ["q001", "q002"]
    assert details["questions"][0]["gold_evidence_ids"] == ["10.1234_bench.s0001"]
    assert details["questions"][0]["retrieval_hit"] is True
    assert details["questions"][0]["missing_gold_evidence_ids"] == []
    assert details["questions"][0]["adequacy"]["min_quotes"] == 1
    assert details["questions"][0]["adequacy"]["min_documents"] == 1
    assert details["questions"][0]["adequacy"]["profile"] == "auto"
    assert "ScanSci Benchmark Diagnostics" in html
    assert 'data-question-id="q001"' in html
    assert "Answerable adequacy" in html
    assert "10.1234_bench.s0001" in html


def test_cli_bench_leaderboard_writes_outputs(tmp_path: Path, capsys):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    output_path = tmp_path / "leaderboard.json"
    csv_path = tmp_path / "leaderboard.csv"
    markdown_path = tmp_path / "leaderboard.md"
    html_path = tmp_path / "leaderboard.html"
    chart_path = tmp_path / "leaderboard-chart.html"
    first_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "dataset": "qasper",
                    "questions": 10,
                    "scope": "gold-docs",
                    "k": 20,
                    "initial_limit": 20,
                    "dense_limit": 20,
                    "embedding_provider": "model-a",
                    "gold_evidence_recall_at_k": 0.5,
                    "all_gold_retrieval_recall_at_k": 0.4,
                    "retrieval_recall_at_k": 0.6,
                },
                "questions": [],
            }
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(
            {
                "dataset": "qasper",
                "questions": 10,
                "scope": "gold-docs",
                "k": 20,
                "initial_limit": 50,
                "dense_limit": 50,
                "embedding_provider": "model-b",
                "gold_evidence_recall_at_k": 0.7,
                "all_gold_retrieval_recall_at_k": 0.5,
                "retrieval_recall_at_k": 0.8,
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-leaderboard",
            "--details",
            str(first_path),
            str(second_path),
            "--labels",
            "Model A,Model B",
            "--output",
            str(output_path),
            "--csv-output",
            str(csv_path),
            "--markdown-output",
            str(markdown_path),
            "--html-output",
            str(html_path),
            "--chart-output",
            str(chart_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(output_path.read_text(encoding="utf-8"))
    csv_text = csv_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    chart_html = chart_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["runs"] == 2
    assert payload["rows"][0]["label"] == "Model B"
    assert payload["chart_output_path"] == str(chart_path)
    assert saved_payload["rows"][0]["rank"] == 1
    assert "rank,comparison_group,label,dataset" in csv_text
    assert "wall_time_seconds" in csv_text
    assert "Model B" in markdown
    assert "ScanSci Evidence Retrieval Leaderboard" in html
    assert "<svg" in chart_html
    assert "70.0" in chart_html


def test_cli_bench_passes_evidence_adequacy_thresholds(tmp_path: Path, capsys):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)
    details_path = tmp_path / "benchmark-details.json"

    exit_code = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--k",
            "5",
            "--min-quotes",
            "2",
            "--min-documents",
            "2",
            "--details-output",
            str(details_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    details = json.loads(details_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["min_quotes"] == 2
    assert payload["min_documents"] == 2
    assert payload["adequacy_profile"] == "auto"
    assert details["metrics"]["min_quotes"] == 2
    assert details["metrics"]["min_documents"] == 2
    assert details["metrics"]["adequacy_profile"] == "auto"
    assert details["metrics"]["answerable_evidence_adequacy_rate"] == 0.0
    assert details["questions"][0]["adequacy"]["min_quotes"] == 2
    assert details["questions"][0]["adequacy"]["min_documents"] == 2


def test_cli_bench_can_gate_on_answerable_evidence_adequacy(tmp_path: Path, capsys):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)

    exit_code = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--min-quotes",
            "2",
            "--min-documents",
            "2",
            "--min-answerable-evidence-adequacy",
            "1.0",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["answerable_evidence_adequacy_rate"] == 0.0
    assert payload["gate_failures"] == [
        "answerable_evidence_adequacy_rate 0.0 is below required 1.0"
    ]


def test_run_benchmark_uses_gold_answer_type_for_auto_adequacy_thresholds(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "answer-type-gold.jsonl"
    gold_rows = [
        {
            "question_id": "q001",
            "question": "What evidence reports biomass outcomes?",
            "answer_type": "conflict_evidence",
            "gold_evidence_ids": [
                "10.1234_template-a.s0002",
                "10.1234_template-b.s0001",
            ],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        }
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in gold_rows) + "\n", encoding="utf-8")

    result = run_benchmark(db_path, gold_path, k=5, include_details=True, adequacy_profile="auto")

    adequacy = result["question_results"][0]["adequacy"]
    assert adequacy["profile"] == "auto"
    assert adequacy["min_quotes"] == 2
    assert adequacy["min_documents"] == 2


def test_run_benchmark_reports_partial_gold_evidence_recall(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "multi-gold.jsonl"
    gold_rows = [
        {
            "question_id": "q001",
            "question": "What evidence conflicts on whether treatment increased biomass?",
            "answer_type": "conflict_evidence",
            "gold_evidence_ids": [
                "10.1234_template-a.s0002",
                "10.1234_template-b.s0001",
            ],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        }
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in gold_rows) + "\n", encoding="utf-8")

    result = run_benchmark(db_path, gold_path, k=1)

    assert result["retrieval_recall_at_k"] == 1.0
    assert result["all_gold_retrieval_recall_at_k"] == 0.0
    assert result["gold_evidence_recall_at_k"] == 0.5


def test_run_benchmark_can_include_question_diagnostics(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "multi-gold.jsonl"
    gold_rows = [
        {
            "question_id": "q001",
            "question": "What evidence conflicts on whether treatment increased biomass?",
            "answer_type": "conflict_evidence",
            "gold_evidence_ids": [
                "10.1234_template-a.s0002",
                "10.1234_template-b.s0001",
            ],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        }
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in gold_rows) + "\n", encoding="utf-8")

    result = run_benchmark(db_path, gold_path, k=1, include_details=True)

    question_results = result["question_results"]
    assert len(question_results) == 1
    assert question_results[0]["question_id"] == "q001"
    assert question_results[0]["gold_evidence_ids"] == [
        "10.1234_template-a.s0002",
        "10.1234_template-b.s0001",
    ]
    assert len(question_results[0]["retrieved_evidence_ids"]) == 1
    assert question_results[0]["retrieved_gold_evidence_ids"]
    assert question_results[0]["missing_gold_evidence_ids"]
    assert question_results[0]["retrieval_hit"] is True
    assert question_results[0]["all_gold_retrieved"] is False
    assert question_results[0]["gold_evidence_recall_at_k"] == 0.5
    assert question_results[0]["cited_gold_evidence_ids"]
    assert question_results[0]["missing_cited_gold_evidence_ids"]


def test_cli_bench_enforces_quality_gate_thresholds(tmp_path: Path, capsys):
    db_path, gold_path = _make_benchmark_fixture(tmp_path)

    passing_exit = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--min-retrieval-recall",
            "1.0",
            "--min-citation-f1",
            "1.0",
            "--min-all-gold-retrieval-recall",
            "1.0",
            "--min-gold-evidence-recall",
            "1.0",
        ]
    )
    passing_payload = json.loads(capsys.readouterr().out)

    failing_exit = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--min-retrieval-recall",
            "1.1",
            "--min-citation-f1",
            "1.0",
            "--min-all-gold-retrieval-recall",
            "1.0",
            "--min-gold-evidence-recall",
            "1.0",
        ]
    )
    failing_payload = json.loads(capsys.readouterr().out)

    assert passing_exit == 0
    assert passing_payload["passed"] is True
    assert passing_payload["gate_failures"] == []
    assert failing_exit == 1
    assert failing_payload["passed"] is False
    assert failing_payload["gate_failures"] == [
        "retrieval_recall_at_k 1.0 is below required 1.1"
    ]


def test_cli_bench_can_gate_on_strict_gold_evidence_recall(tmp_path: Path, capsys):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "multi-gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q001",
                "question": "What evidence conflicts on whether treatment increased biomass?",
                "answer_type": "conflict_evidence",
                "gold_evidence_ids": [
                    "10.1234_template-a.s0002",
                    "10.1234_template-b.s0001",
                ],
                "required_points": [],
                "forbidden_points": [],
                "answerable": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench",
            "--db",
            str(db_path),
            "--gold",
            str(gold_path),
            "--k",
            "1",
            "--min-retrieval-recall",
            "1.0",
            "--min-all-gold-retrieval-recall",
            "1.0",
            "--min-gold-evidence-recall",
            "1.0",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["retrieval_recall_at_k"] == 1.0
    assert payload["all_gold_retrieval_recall_at_k"] == 0.0
    assert payload["gold_evidence_recall_at_k"] == 0.5
    assert payload["gate_failures"] == [
        "all_gold_retrieval_recall_at_k 0.0 is below required 1.0",
        "gold_evidence_recall_at_k 0.5 is below required 1.0",
    ]


def test_validate_gold_questions_reports_type_coverage_and_passes_sample_gold():
    result = validate_gold_questions(
        Path("bench/gold_questions.sample.jsonl"),
        min_questions=3,
        required_answer_types=["single_paper_fact", "unanswerable", "conflict_evidence"],
    )

    assert result["passed"] is True
    assert result["questions"] == 3
    assert result["answerable_questions"] == 2
    assert result["unanswerable_questions"] == 1
    assert result["answer_type_counts"] == {
        "conflict_evidence": 1,
        "single_paper_fact": 1,
        "unanswerable": 1,
    }
    assert result["issues"] == []


def test_validate_gold_questions_flags_schema_and_coverage_issues(tmp_path: Path):
    gold_path = tmp_path / "bad-gold.jsonl"
    rows = [
        {
            "question_id": "dup",
            "question": "What evidence supports X?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": [],
            "answerable": True,
        },
        {
            "question_id": "dup",
            "question": "",
            "answer_type": "unanswerable",
            "gold_evidence_ids": ["doc1.s0001"],
            "answerable": False,
        },
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = validate_gold_questions(
        gold_path,
        min_questions=3,
        required_answer_types=["single_paper_fact", "conflict_evidence", "unanswerable"],
    )

    assert result["passed"] is False
    assert result["missing_answer_types"] == ["conflict_evidence"]
    messages = [issue["message"] for issue in result["issues"]]
    assert "minimum question count 3 not met" in messages
    assert "answerable questions require at least one gold_evidence_id" in messages
    assert "duplicate question_id" in messages
    assert "question is required" in messages
    assert "unanswerable questions must not have gold_evidence_ids" in messages


def test_validate_gold_questions_requires_answer_accuracy_points(tmp_path: Path):
    gold_path = tmp_path / "missing-answer-points.jsonl"
    rows = [
        {
            "question_id": "q001",
            "question": "What evidence supports X?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["doc1.s0001"],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        },
        {
            "question_id": "q002",
            "question": "What evidence supports unavailable Y?",
            "answer_type": "unanswerable",
            "gold_evidence_ids": [],
            "required_points": [],
            "forbidden_points": [],
            "answerable": False,
        },
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = validate_gold_questions(gold_path)

    assert result["passed"] is False
    messages = [issue["message"] for issue in result["issues"]]
    assert "answerable questions require at least one required_point" in messages
    assert "unanswerable questions require at least one forbidden_point" in messages


def test_validate_gold_questions_flags_answer_types_below_minimum_count():
    result = validate_gold_questions(
        Path("bench/gold_questions.sample.jsonl"),
        min_questions=3,
        required_answer_types=["single_paper_fact", "unanswerable", "conflict_evidence"],
        min_per_answer_type=2,
    )

    assert result["passed"] is False
    assert result["min_per_answer_type"] == 2
    assert result["underrepresented_answer_types"] == [
        {"answer_type": "conflict_evidence", "count": 1, "minimum": 2},
        {"answer_type": "single_paper_fact", "count": 1, "minimum": 2},
        {"answer_type": "unanswerable", "count": 1, "minimum": 2},
    ]
    messages = [issue["message"] for issue in result["issues"]]
    assert "answer_type conflict_evidence has 1 questions, below required 2" in messages
    assert "answer_type single_paper_fact has 1 questions, below required 2" in messages
    assert "answer_type unanswerable has 1 questions, below required 2" in messages


def test_validate_gold_questions_rejects_unfinished_annotation_templates(tmp_path: Path):
    gold_path = tmp_path / "unfinished-template.jsonl"
    row = {
        "question_id": "todo_single_paper_fact_0001",
        "question": "What evidence supports X?",
        "answer_type": "single_paper_fact",
        "gold_evidence_ids": ["doc1.s0001"],
        "answerable": True,
        "annotation_status": "todo",
    }
    gold_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = validate_gold_questions(gold_path)

    assert result["passed"] is False
    assert result["issues"] == [
        {
            "line": 1,
            "question_id": "todo_single_paper_fact_0001",
            "message": "annotation_status must be done, verified, or approved before benchmarking",
        }
    ]
    assert result["checked_evidence_store"] is False
    assert result["missing_gold_evidence_ids"] == []


def test_validate_gold_questions_reports_annotation_progress_and_suggestions(tmp_path: Path):
    gold_path = tmp_path / "mixed-annotation-template.jsonl"
    rows = [
        {
            "question_id": "todo_single_paper_fact_0001",
            "question": "",
            "suggested_question": "What did Paper <One> report?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["doc1.s0001"],
            "required_points": [],
            "forbidden_points": [],
            "suggested_required_points": ["Evidence <must> be checked."],
            "suggested_forbidden_points": [],
            "answerable": True,
            "annotation_status": "todo",
        },
        {
            "question_id": "q002",
            "question": "What evidence reports biomass?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["doc2.s0001"],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
            "annotation_status": "verified",
        },
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = validate_gold_questions(gold_path)

    assert result["annotation_progress"] == {
        "total_rows": 2,
        "completed_rows": 1,
        "incomplete_rows": 1,
        "empty_question_rows": 1,
        "status_counts": {"todo": 1, "verified": 1},
    }
    first_summary = result["question_summaries"][0]
    assert first_summary["suggested_question"] == "What did Paper <One> report?"
    assert first_summary["suggested_required_points"] == ["Evidence <must> be checked."]
    assert first_summary["suggested_forbidden_points"] == []


def test_validate_gold_questions_can_verify_gold_ids_against_evidence_store(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "gold-with-db.jsonl"
    rows = [
        {
            "question_id": "q001",
            "question": "What evidence reports biomass?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["10.1234_template-a.s0002"],
            "required_points": ["Treatment increased biomass by 18 percent."],
            "forbidden_points": [],
            "answerable": True,
        },
        {
            "question_id": "q002",
            "question": "What evidence reports an unavailable fact?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["10.1234_template-a.s9999"],
            "required_points": ["The answer must cite the unavailable fact if present."],
            "forbidden_points": [],
            "answerable": True,
        },
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = validate_gold_questions(gold_path, db_path=db_path)

    source_html_path = (tmp_path / "template-library" / "treatment-a.html").as_posix()
    assert result["passed"] is False
    assert result["checked_evidence_store"] is True
    assert result["evidence_store_path"] == str(db_path)
    assert result["missing_gold_evidence_ids"] == ["10.1234_template-a.s9999"]
    assert result["gold_evidence_coverage"] == {
        "gold_evidence_references": 1,
        "unique_evidence_spans": 1,
        "source_documents": 1,
        "source_document_counts": {
            "10.1234_template-a": 1,
        },
        "section_kind_counts": {
            "results": 1,
        },
        "block_type_counts": {
            "paragraph": 1,
        },
    }
    assert result["question_summaries"] == [
        {
            "line": 1,
            "question_id": "q001",
            "question": "What evidence reports biomass?",
            "answer_type": "single_paper_fact",
            "answerable": True,
            "annotation_status": "",
            "gold_evidence_ids": ["10.1234_template-a.s0002"],
            "gold_evidence": [
                {
                    "evidence_id": "10.1234_template-a.s0002",
                    "doc_id": "10.1234_template-a",
                    "title": "Template A",
                    "doi": "10.1234/template-a",
                    "html_path": source_html_path,
                    "html_anchor": "results-a-s0001",
                    "section": "Results",
                    "section_kind": "results",
                    "block_type": "paragraph",
                    "text": "Treatment increased biomass by 18 percent in the greenhouse cohort.",
                }
            ],
        },
        {
            "line": 2,
            "question_id": "q002",
            "question": "What evidence reports an unavailable fact?",
            "answer_type": "single_paper_fact",
            "answerable": True,
            "annotation_status": "",
            "gold_evidence_ids": ["10.1234_template-a.s9999"],
            "gold_evidence": [],
        },
    ]
    assert result["issues"] == [
        {
            "line": 2,
            "question_id": "q002",
            "message": "gold_evidence_id not found in evidence store: 10.1234_template-a.s9999",
        }
    ]


def test_validate_gold_questions_checks_gold_evidence_adequacy_against_answer_type(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "gold-with-weak-evidence.jsonl"
    rows = [
        {
            "question_id": "q001",
            "question": "What evidence synthesizes biomass outcomes?",
            "answer_type": "multi_paper_synthesis",
            "gold_evidence_ids": ["10.1234_template-a.s0002"],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        },
        {
            "question_id": "q002",
            "question": "What evidence conflicts within the current corpus?",
            "answer_type": "conflict_evidence",
            "gold_evidence_ids": ["10.1234_template-a.s0001", "10.1234_template-a.s0002"],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        },
        {
            "question_id": "q003",
            "question": "What numeric value was extracted?",
            "answer_type": "numeric_extraction",
            "gold_evidence_ids": ["10.1234_template-a.s0001"],
            "required_points": [],
            "forbidden_points": [],
            "answerable": True,
        },
    ]
    gold_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = validate_gold_questions(gold_path, db_path=db_path)

    assert result["passed"] is False
    assert result["gold_evidence_adequacy_issues"] == [
        {
            "line": 1,
            "question_id": "q001",
            "answer_type": "multi_paper_synthesis",
            "message": "answer_type multi_paper_synthesis requires at least 2 gold_evidence_ids",
        },
        {
            "line": 1,
            "question_id": "q001",
            "answer_type": "multi_paper_synthesis",
            "message": "answer_type multi_paper_synthesis requires gold evidence from at least 2 source documents",
        },
        {
            "line": 2,
            "question_id": "q002",
            "answer_type": "conflict_evidence",
            "message": "answer_type conflict_evidence requires gold evidence from at least 2 source documents",
        },
        {
            "line": 3,
            "question_id": "q003",
            "answer_type": "numeric_extraction",
            "message": "answer_type numeric_extraction requires at least one gold evidence text containing a digit",
        },
    ]
    messages = [issue["message"] for issue in result["issues"]]
    assert "answer_type multi_paper_synthesis requires at least 2 gold_evidence_ids" in messages
    assert "answer_type conflict_evidence requires gold evidence from at least 2 source documents" in messages
    assert "answer_type numeric_extraction requires at least one gold evidence text containing a digit" in messages


def test_validate_gold_questions_reports_nonfatal_gold_evidence_quality_warnings(tmp_path: Path):
    library = tmp_path / "quality-warning-library"
    library.mkdir()
    (library / "plant.html").write_text(
        """
        <article class="paper" data-doi="10.1234/plant-a">
          <h1>Plant Treatment A</h1>
          <h2>Results</h2>
          <p id="plant-a">Treatment increased biomass and root growth in greenhouse plants.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "caption.html").write_text(
        """
        <article class="paper" data-doi="10.1234/caption-b">
          <h1>Caption Heavy B</h1>
          <h2>Results</h2>
          <p id="caption-b">Fig. 2. Representative panels show treatment biomass growth field plants measured values for orbital simulation results.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "quality-warning-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)
    gold_path = tmp_path / "quality-warning-gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q001",
                "question": "How do the two highlighted studies compare?",
                "answer_type": "multi_paper_synthesis",
                "gold_evidence_ids": ["10.1234_plant-a.s0001", "10.1234_caption-b.s0001"],
                "required_points": ["The answer must compare the plant and caption evidence."],
                "forbidden_points": [],
                "answerable": True,
                "annotation_status": "verified",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = validate_gold_questions(gold_path, db_path=db_path)

    assert result["passed"] is True
    assert result["issues"] == []
    assert result["gold_evidence_quality_warnings"] == [
        {
            "line": 1,
            "question_id": "q001",
            "answer_type": "multi_paper_synthesis",
            "evidence_ids": ["10.1234_caption-b.s0001"],
            "message": "gold evidence includes figure-caption-like text; review whether caption evidence is intended",
        }
    ]


def test_validate_gold_questions_reports_quality_warning_for_caption_block_type(tmp_path: Path):
    library = tmp_path / "caption-block-warning-library"
    library.mkdir()
    (library / "plant.html").write_text(
        """
        <article class="paper" data-doi="10.1234/plant-a">
          <h1>Plant Treatment A</h1>
          <h2>Results</h2>
          <p id="plant-a">Treatment increased biomass and root growth in greenhouse plants.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "caption.html").write_text(
        """
        <article class="paper" data-doi="10.1234/caption-block-b">
          <h1>Caption Block B</h1>
          <h2>Results</h2>
          <figcaption id="caption-b">Image summary shows treated biomass growth under microscopy field conditions.</figcaption>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "caption-block-warning-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)
    gold_path = tmp_path / "caption-block-warning-gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q001",
                "question": "How do the two highlighted studies compare?",
                "answer_type": "multi_paper_synthesis",
                "gold_evidence_ids": ["10.1234_plant-a.s0001", "10.1234_caption-block-b.s0001"],
                "required_points": ["The answer must compare the plant and caption-block evidence."],
                "forbidden_points": [],
                "answerable": True,
                "annotation_status": "verified",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = validate_gold_questions(gold_path, db_path=db_path)

    assert result["passed"] is True
    assert result["issues"] == []
    assert result["gold_evidence_quality_warnings"] == [
        {
            "line": 1,
            "question_id": "q001",
            "answer_type": "multi_paper_synthesis",
            "evidence_ids": ["10.1234_caption-block-b.s0001"],
            "message": "gold evidence includes figure-caption-like text; review whether caption evidence is intended",
        }
    ]


def test_cli_bench_validate_emits_gold_validation_summary(capsys):
    exit_code = cli.main(
        [
            "bench-validate",
            "--gold",
            "bench/gold_questions.sample.jsonl",
            "--min-questions",
            "3",
            "--require-answer-types",
            "single_paper_fact,unanswerable,conflict_evidence",
            "--min-per-answer-type",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["questions"] == 3
    assert payload["min_per_answer_type"] == 1
    assert payload["underrepresented_answer_types"] == []


def test_cli_bench_validate_can_verify_gold_ids_against_evidence_store(tmp_path: Path, capsys):
    db_path = _make_template_fixture(tmp_path)
    gold_path = tmp_path / "bad-gold-id.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q001",
                "question": "What evidence reports biomass?",
                "answer_type": "single_paper_fact",
                "gold_evidence_ids": ["missing.s0001"],
                "required_points": [],
                "forbidden_points": [],
                "answerable": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["bench-validate", "--gold", str(gold_path), "--db", str(db_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["checked_evidence_store"] is True
    assert payload["missing_gold_evidence_ids"] == ["missing.s0001"]


def test_render_gold_validation_report_summarizes_issues_and_escapes_html():
    payload = {
        "passed": False,
        "questions": 2,
        "answerable_questions": 1,
        "unanswerable_questions": 1,
        "answer_type_counts": {"single_paper_fact": 1, "unanswerable": 1},
        "required_answer_types": ["single_paper_fact", "conflict_evidence"],
        "missing_answer_types": ["conflict_evidence"],
        "min_per_answer_type": 2,
        "annotation_progress": {
            "total_rows": 2,
            "completed_rows": 1,
            "incomplete_rows": 1,
            "empty_question_rows": 1,
            "status_counts": {"todo": 1, "verified": 1},
        },
        "underrepresented_answer_types": [
            {"answer_type": "single_paper_fact", "count": 1, "minimum": 2}
        ],
        "checked_evidence_store": True,
        "evidence_store_path": "evidence.sqlite",
        "missing_gold_evidence_ids": ["missing.s0001"],
        "gold_evidence_adequacy_issues": [
            {
                "line": 1,
                "question_id": "q001",
                "answer_type": "multi_paper_synthesis",
                "message": "answer_type multi_paper_synthesis requires at least 2 gold_evidence_ids",
            }
        ],
        "gold_evidence_quality_warnings": [
            {
                "line": 1,
                "question_id": "q001",
                "answer_type": "multi_paper_synthesis",
                "evidence_ids": ["doc1.s0001"],
                "message": "gold evidence includes figure-caption-like text; review <carefully>",
            }
        ],
        "gold_evidence_coverage": {
            "gold_evidence_references": 1,
            "unique_evidence_spans": 1,
            "source_documents": 1,
            "source_document_counts": {"doc1": 1},
            "section_kind_counts": {"results": 1},
            "block_type_counts": {"paragraph": 1},
        },
        "question_summaries": [
            {
                "line": 1,
                "question_id": "q001",
                "question": "What evidence synthesizes biomass outcomes?",
                "answer_type": "multi_paper_synthesis",
                "answerable": True,
                "annotation_status": "todo",
                "suggested_question": "What did Paper <One> report?",
                "suggested_required_points": ["Evidence <must> be checked."],
                "suggested_forbidden_points": ["Do not infer <unsafe> claims."],
                "gold_evidence_ids": ["doc1.s0001", "doc2.s0001"],
                "gold_evidence": [
                    {
                        "evidence_id": "doc1.s0001",
                        "doc_id": "doc1",
                        "title": "Paper <One>",
                        "doi": "10.1234/example",
                        "html_path": "paper.evidence.html",
                        "html_anchor": "results-p1-s0001",
                        "section": "Results",
                        "section_kind": "results",
                        "block_type": "paragraph",
                        "text": "Evidence <must> be escaped.",
                    }
                ],
            }
        ],
        "issues": [
            {
                "line": 1,
                "question_id": "q001",
                "message": "question is required",
            },
            {
                "line": 2,
                "question_id": "q<script>",
                "message": "question is required <script>alert(1)</script>",
            }
        ],
    }

    html = render_gold_validation_report(payload)

    assert "ScanSci Gold Validation Report" in html
    assert "Passed" in html
    assert "false" in html
    assert "missing.s0001" in html
    assert "conflict_evidence" in html
    assert "Underrepresented answer types" in html
    assert "Annotation progress" in html
    assert "completed_rows: 1" in html
    assert "Gold evidence coverage" in html
    assert "gold_evidence_references: 1" in html
    assert "source_documents: 1" in html
    assert "section_kind_counts: results=1" in html
    assert "Gold evidence quality warnings" in html
    assert "review &lt;carefully&gt;" in html
    assert "requires at least 2 gold_evidence_ids" in html
    assert "Issues by question" in html
    assert 'data-question-id="q001"' in html
    assert 'href="#question-q001"' in html
    assert "multi_paper_synthesis" in html
    assert "status:" in html
    assert "todo" in html
    assert "Suggested question" in html
    assert "What did Paper &lt;One&gt; report?" in html
    assert "Evidence &lt;must&gt; be checked." in html
    assert "Do not infer &lt;unsafe&gt; claims." in html
    assert "What evidence synthesizes biomass outcomes?" in html
    assert "doc1.s0001" in html
    assert 'data-evidence-id="doc1.s0001"' in html
    assert 'href="paper.evidence.html#results-p1-s0001"' in html
    assert "Paper &lt;One&gt;" in html
    assert "Evidence &lt;must&gt; be escaped." in html
    assert "Evidence <must> be escaped." not in html
    assert "<script>alert(1)</script>" not in html
    assert "q&lt;script&gt;" in html


def test_cli_bench_validate_writes_html_report(tmp_path: Path, capsys):
    gold_path = tmp_path / "bad-gold.jsonl"
    html_output_path = tmp_path / "gold-validation.html"
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q001",
                "question": "",
                "answer_type": "single_paper_fact",
                "gold_evidence_ids": [],
                "answerable": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-validate",
            "--gold",
            str(gold_path),
            "--min-questions",
            "2",
            "--html-output",
            str(html_output_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    html = html_output_path.read_text(encoding="utf-8")
    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["html_output_path"] == str(html_output_path)
    assert "ScanSci Gold Validation Report" in html
    assert "minimum question count 2 not met" in html
    assert "question is required" in html


def test_generate_gold_question_templates_marks_rows_for_human_annotation(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)

    payload = generate_gold_question_templates(
        db_path,
        questions_per_type=1,
        answer_types=[
            "single_paper_fact",
            "single_paper_method",
            "numeric_extraction",
            "conflict_evidence",
            "unanswerable",
        ],
    )

    assert payload["missing_answer_types"] == []
    assert payload["answer_type_counts"] == {
        "conflict_evidence": 1,
        "numeric_extraction": 1,
        "single_paper_fact": 1,
        "single_paper_method": 1,
        "unanswerable": 1,
    }
    templates = payload["templates"]
    assert all(row["annotation_status"] == "todo" for row in templates)
    assert all(row["question"] == "" for row in templates)
    assert all(row["suggested_question"] for row in templates)
    fact_row = next(row for row in templates if row["answer_type"] == "single_paper_fact")
    assert "Template A" in fact_row["suggested_question"]
    assert "Results" in fact_row["suggested_question"]
    assert fact_row["suggested_required_points"] == [
        "Treatment increased biomass by 18 percent in the greenhouse cohort."
    ]
    method_row = next(row for row in templates if row["answer_type"] == "single_paper_method")
    assert method_row["gold_evidence_ids"]
    assert method_row["candidate_evidence"][0]["section_kind"] == "methods"
    conflict_row = next(row for row in templates if row["answer_type"] == "conflict_evidence")
    assert len(conflict_row["gold_evidence_ids"]) == 2
    assert any("did not increase biomass" in item["text"] for item in conflict_row["candidate_evidence"])
    assert "Template A" in conflict_row["suggested_question"]
    assert "Template B" in conflict_row["suggested_question"]
    assert len(conflict_row["suggested_required_points"]) == 2
    unanswerable_row = next(row for row in templates if row["answer_type"] == "unanswerable")
    assert unanswerable_row["gold_evidence_ids"] == []
    assert unanswerable_row["candidate_evidence"] == []
    assert unanswerable_row["suggested_required_points"] == []
    assert unanswerable_row["suggested_forbidden_points"]


def test_generate_gold_question_templates_reports_template_coverage_for_human_review(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)

    payload = generate_gold_question_templates(
        db_path,
        questions_per_type=1,
        answer_types=[
            "single_paper_fact",
            "single_paper_method",
            "conflict_evidence",
            "unanswerable",
        ],
    )

    assert payload["template_coverage"] == {
        "candidate_evidence_references": 4,
        "unique_evidence_spans": 3,
        "source_documents": 2,
        "source_document_counts": {
            "10.1234_template-a": 3,
            "10.1234_template-b": 1,
        },
        "section_kind_counts": {
            "methods": 1,
            "results": 3,
        },
        "block_type_counts": {
            "paragraph": 4,
        },
    }
    fact_row = next(row for row in payload["templates"] if row["answer_type"] == "single_paper_fact")
    assert fact_row["candidate_evidence"][0]["doc_id"] == "10.1234_template-a"


def test_generate_gold_question_templates_balances_single_evidence_candidates_by_document(tmp_path: Path):
    library = tmp_path / "balanced-template-library"
    library.mkdir()
    (library / "a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/template-a">
          <h1>Template A</h1>
          <h2>Results</h2>
          <p id="results-a1">Treatment increased biomass by 18 percent in greenhouse cohort one.</p>
          <p id="results-a2">Treatment increased biomass by 21 percent in greenhouse cohort two.</p>
          <p id="results-a3">Treatment increased biomass by 24 percent in greenhouse cohort three.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/template-b">
          <h1>Template B</h1>
          <h2>Results</h2>
          <p id="results-b1">Treatment increased biomass by 11 percent in the field cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "c.html").write_text(
        """
        <article class="paper" data-doi="10.1234/template-c">
          <h1>Template C</h1>
          <h2>Results</h2>
          <p id="results-c1">Treatment increased biomass by 9 percent in the validation cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "balanced-template-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    payload = generate_gold_question_templates(
        db_path,
        questions_per_type=3,
        answer_types=["single_paper_fact"],
    )

    dois = [
        row["candidate_evidence"][0]["doi"]
        for row in payload["templates"]
        if row["answer_type"] == "single_paper_fact"
    ]
    assert dois == [
        "10.1234/template-a",
        "10.1234/template-b",
        "10.1234/template-c",
    ]


def test_generate_gold_question_templates_prefers_body_sections_over_abstract(tmp_path: Path):
    library = tmp_path / "section-priority-template-library"
    library.mkdir()
    (library / "a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/section-priority-a">
          <h1>Section Priority A</h1>
          <h2>Abstract</h2>
          <p id="abstract-a">Abstract summary reports biomass changed by 1 percent.</p>
          <h2>Results</h2>
          <p id="results-a">Results report biomass changed by 42 percent in the field cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "section-priority-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    payload = generate_gold_question_templates(
        db_path,
        questions_per_type=1,
        answer_types=["single_paper_fact", "numeric_extraction"],
    )

    fact_row = next(row for row in payload["templates"] if row["answer_type"] == "single_paper_fact")
    numeric_row = next(row for row in payload["templates"] if row["answer_type"] == "numeric_extraction")
    assert fact_row["candidate_evidence"][0]["section_kind"] == "results"
    assert numeric_row["candidate_evidence"][0]["section_kind"] == "results"
    assert "42 percent" in fact_row["suggested_required_points"][0]
    assert "42 percent" in numeric_row["suggested_required_points"][0]


def test_generate_gold_question_templates_avoids_figure_caption_only_pairing(tmp_path: Path):
    library = tmp_path / "coherent-pair-library"
    library.mkdir()
    (library / "a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/plant-a">
          <h1>Plant Treatment A</h1>
          <h2>Results</h2>
          <p id="plant-a">Treatment increased biomass and root growth in greenhouse plants.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/planet-b">
          <h1>Planet Figure B</h1>
          <h2>Results</h2>
          <p id="planet-b">Fig. 2. Representative panels show treatment biomass growth field plants measured values for orbital simulation results.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "c.html").write_text(
        """
        <article class="paper" data-doi="10.1234/plant-c">
          <h1>Plant Treatment C</h1>
          <h2>Results</h2>
          <p id="plant-c">Treatment did not increase biomass or root growth in field plants.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "coherent-pair-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    payload = generate_gold_question_templates(
        db_path,
        questions_per_type=1,
        answer_types=["conflict_evidence"],
    )

    row = payload["templates"][0]
    assert row["gold_evidence_ids"] == [
        "10.1234_plant-a.s0001",
        "10.1234_plant-c.s0001",
    ]
    assert "Planet Figure B" not in row["suggested_question"]


def test_cli_bench_template_writes_jsonl_and_summary(tmp_path: Path, capsys):
    db_path = _make_template_fixture(tmp_path)
    output_path = tmp_path / "gold-template.jsonl"
    html_output_path = tmp_path / "gold-template.html"

    exit_code = cli.main(
        [
            "bench-template",
            "--db",
            str(db_path),
            "--output",
            str(output_path),
            "--html-output",
            str(html_output_path),
            "--questions-per-type",
            "1",
            "--answer-types",
            "single_paper_fact,unanswerable",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert exit_code == 0
    assert payload["rows"] == 2
    assert payload["output_path"] == str(output_path)
    assert payload["html_output_path"] == str(html_output_path)
    assert "templates" not in payload
    assert payload["template_coverage"]["candidate_evidence_references"] == 1
    assert payload["template_coverage"]["source_documents"] == 1
    assert [row["answer_type"] for row in rows] == ["single_paper_fact", "unanswerable"]
    assert rows[0]["annotation_status"] == "todo"
    html = html_output_path.read_text(encoding="utf-8")
    assert "ScanSci Gold Annotation Template" in html
    assert "Template coverage" in html
    assert "Source documents: 1" in html
    assert "data-evidence-id" in html


def test_render_gold_template_report_links_candidate_evidence_and_escapes_html():
    rows = [
        {
            "question_id": "todo_single_paper_fact_0001",
            "question": "",
            "candidate_question": "Write a question.",
            "suggested_question": "What did Paper <One> report?",
            "answer_type": "single_paper_fact",
            "gold_evidence_ids": ["doc.s0001"],
            "required_points": ["safe point"],
            "forbidden_points": [],
            "suggested_required_points": ["Evidence <must> be escaped."],
            "suggested_forbidden_points": ["Do not copy <unsafe> claims."],
            "answerable": True,
            "annotation_status": "todo",
            "annotation_notes": "Review <script>alert(1)</script>",
            "candidate_evidence": [
                {
                    "evidence_id": "doc.s0001",
                    "doc_id": "doc",
                    "title": "Paper <One>",
                    "doi": "10.1234/example",
                    "section": "Results",
                    "section_kind": "results",
                    "block_type": "paragraph",
                    "text": "Evidence <must> be escaped.",
                    "html_path": "paper.evidence.html",
                    "html_anchor": "results-p1-s0001",
                }
            ],
        }
    ]

    html = render_gold_template_report(rows)

    assert "Template coverage" in html
    assert "Source documents: 1" in html
    assert "Section kinds: results=1" in html
    assert "Block types: paragraph=1" in html
    assert 'href="paper.evidence.html#results-p1-s0001"' in html
    assert 'data-evidence-id="doc.s0001"' in html
    assert "Suggested question" in html
    assert "What did Paper &lt;One&gt; report?" in html
    assert "Suggested required points" in html
    assert "Suggested forbidden points" in html
    assert "Do not copy &lt;unsafe&gt; claims." in html
    assert "Paper &lt;One&gt;" in html
    assert "Evidence &lt;must&gt; be escaped." in html
    assert "<script>alert(1)</script>" not in html


def test_cli_bench_template_report_renders_existing_template(tmp_path: Path, capsys):
    template_path = tmp_path / "template.jsonl"
    output_path = tmp_path / "template-report.html"
    template_path.write_text(
        json.dumps(
            {
                "question_id": "todo_unanswerable_0001",
                "question": "",
                "candidate_question": "Write an unanswerable question.",
                "answer_type": "unanswerable",
                "gold_evidence_ids": [],
                "required_points": [],
                "forbidden_points": [],
                "answerable": False,
                "annotation_status": "todo",
                "candidate_evidence": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-template-report",
            "--template",
            str(template_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {"rows": 1, "output_path": str(output_path)}
    assert "todo_unanswerable_0001" in output_path.read_text(encoding="utf-8")


def test_build_local_acceptance_workbench_keeps_generated_gold_as_human_review_template(tmp_path: Path):
    db_path = _make_template_fixture(tmp_path)
    output_dir = tmp_path / "acceptance-workbench"

    payload = build_local_acceptance_workbench(
        db_path,
        output_dir,
        questions_per_type=1,
        answer_types=["single_paper_fact", "unanswerable"],
        min_questions=2,
        required_answer_types=["single_paper_fact", "unanswerable"],
        min_per_answer_type=1,
    )

    template_path = output_dir / "gold_questions.template.jsonl"
    template_html_path = output_dir / "gold_questions.template.html"
    validation_html_path = output_dir / "gold-validation.template.html"
    draft_path = output_dir / "review-draft.template.md"
    readme_path = output_dir / "README.zh.md"
    manifest_path = output_dir / "acceptance-workbench.manifest.json"

    assert payload["status"] == "needs_human_review"
    assert payload["artifacts"] == {
        "template_jsonl": str(template_path),
        "template_html": str(template_html_path),
        "validation_html": str(validation_html_path),
        "review_draft_template": str(draft_path),
        "readme": str(readme_path),
        "manifest": str(manifest_path),
    }
    assert all(path.exists() for path in [
        template_path,
        template_html_path,
        validation_html_path,
        draft_path,
        readme_path,
        manifest_path,
    ])
    rows = [json.loads(line) for line in template_path.read_text(encoding="utf-8").splitlines()]
    assert [row["answer_type"] for row in rows] == ["single_paper_fact", "unanswerable"]
    assert all(row["annotation_status"] == "todo" for row in rows)
    assert all(row["question"] == "" for row in rows)
    assert payload["validation"]["passed"] is False
    assert payload["validation"]["annotation_progress"]["completed_rows"] == 0
    assert "annotation_status must be done, verified, or approved before benchmarking" in {
        issue["message"] for issue in payload["validation"]["issues"]
    }
    assert "scansci bench validate" in readme_path.read_text(encoding="utf-8")
    assert "scansci annotate ground" in readme_path.read_text(encoding="utf-8")
    assert "Draft claims for grounded annotation review" in draft_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "needs_human_review"
    assert manifest["template_summary"]["rows"] == 2


def test_cli_bench_acceptance_writes_local_workbench(tmp_path: Path, capsys):
    db_path = _make_template_fixture(tmp_path)
    output_dir = tmp_path / "cli-acceptance"

    exit_code = cli.main(
        [
            "bench-acceptance",
            "--db",
            str(db_path),
            "--output-dir",
            str(output_dir),
            "--questions-per-type",
            "1",
            "--answer-types",
            "single_paper_fact,unanswerable",
            "--min-questions",
            "2",
            "--require-answer-types",
            "single_paper_fact,unanswerable",
            "--min-per-answer-type",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "needs_human_review"
    assert payload["output_dir"] == str(output_dir)
    assert (output_dir / "README.zh.md").exists()


def test_fetch_beir_dataset_downloads_and_reports_standard_paths(tmp_path: Path):
    zip_bytes = _beir_zip_bytes(
        {
            "climate-fever/corpus.jsonl": json.dumps({"_id": "doc-1", "text": "Climate text."}) + "\n",
            "climate-fever/queries.jsonl": json.dumps({"_id": "q1", "text": "Climate query?"}) + "\n",
            "climate-fever/qrels/test.tsv": "query-id\tcorpus-id\tscore\nq1\tdoc-1\t1\n",
        }
    )
    session = _ZipDownloadSession(zip_bytes)

    payload = fetch_beir_dataset(
        "climate-fever",
        tmp_path / "external" / "beir",
        session=session,
        timeout=7,
    )

    assert session.calls == [
        {
            "url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/climate-fever.zip",
            "stream": True,
            "timeout": 7,
        }
    ]
    assert payload["dataset"] == "climate-fever"
    assert payload["downloaded"] is True
    assert payload["extracted"] is True
    assert payload["ready"] is True
    assert payload["corpus_path"].endswith("climate-fever\\corpus.jsonl") or payload["corpus_path"].endswith(
        "climate-fever/corpus.jsonl"
    )
    assert payload["qrels_paths"]["test"].endswith("test.tsv")
    assert "scansci bench-import beir" in payload["import_command"]


def test_fetch_beir_dataset_rejects_zip_members_outside_output_dir(tmp_path: Path):
    zip_bytes = _beir_zip_bytes({"../evil.txt": "bad"})
    session = _ZipDownloadSession(zip_bytes)

    with pytest.raises(ValueError, match="escapes output directory"):
        fetch_beir_dataset("climate-fever", tmp_path / "external" / "beir", session=session)

    assert not (tmp_path / "external" / "evil.txt").exists()


def test_cli_bench_fetch_beir_passes_download_options(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_fetch_beir_dataset(dataset, output_dir, *, url, force, timeout):
        captured.update(
            {
                "dataset": dataset,
                "output_dir": output_dir,
                "url": url,
                "force": force,
                "timeout": timeout,
            }
        )
        return {
            "dataset": "climate-fever",
            "ready": True,
            "data_path": "external/beir/climate-fever",
        }

    monkeypatch.setattr(cli, "fetch_beir_dataset", fake_fetch_beir_dataset)

    exit_code = cli.main(
        [
            "bench-fetch",
            "beir",
            "--dataset-name",
            "climate-fever",
            "--output-dir",
            "external/beir",
            "--url",
            "https://example.test/climate-fever.zip",
            "--force",
            "--timeout",
            "9",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured == {
        "dataset": "climate-fever",
        "output_dir": Path("external/beir"),
        "url": "https://example.test/climate-fever.zip",
        "force": True,
        "timeout": 9.0,
    }
    assert payload["ready"] is True


def test_cli_bench_import_qasper_converts_highlighted_evidence(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper.jsonl"
    output_path = tmp_path / "gold_questions.external.qasper.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "id": "paper-001",
                "title": "QASPER Paper",
                "abstract": "A paper abstract.",
                "qas": {
                    "question": ["What did the paper report?", "What was missing?"],
                    "question_id": ["qasper-q1", "qasper-q2"],
                    "answers": [
                        {
                            "answer": [
                                {
                                    "unanswerable": False,
                                    "free_form_answer": "The method improved accuracy.",
                                    "extractive_spans": ["improved accuracy"],
                                    "yes_no": None,
                                    "highlighted_evidence": ["The method improved accuracy on the test set."],
                                    "evidence": ["The method improved accuracy on the test set."],
                                }
                            ]
                        },
                        {
                            "answer": [
                                {
                                    "unanswerable": True,
                                    "free_form_answer": "",
                                    "extractive_spans": [],
                                    "yes_no": None,
                                    "highlighted_evidence": [],
                                    "evidence": [],
                                }
                            ]
                        },
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-import",
            "qasper",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "qasper"
    assert payload["rows"] == 2
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["question_id"] == "qasper:paper-001:qasper-q1"
    assert rows[0]["answer_type"] == "external_qasper"
    assert rows[0]["gold_evidence_ids"] == ["qasper:paper-001:qasper-q1.e0001"]
    assert rows[0]["required_points"] == ["The method improved accuracy."]
    assert rows[0]["external_source"]["dataset"] == "qasper"
    assert rows[0]["candidate_evidence"][0]["text"] == "The method improved accuracy on the test set."
    assert rows[0]["annotation_status"] == "imported"
    assert rows[1]["answerable"] is False
    assert rows[1]["forbidden_points"] == ["Do not answer from this corpus; QASPER marks this question unanswerable."]


def test_cli_bench_import_qasper_converts_raw_release_mapping(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    output_path = tmp_path / "gold_questions.external.qasper.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "paper_raw_001": {
                    "title": "Raw QASPER Paper",
                    "abstract": "A paper abstract.",
                    "qas": [
                        {
                            "question": "Which dataset did the paper use?",
                            "question_id": "raw-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Dataset A.",
                                        "extractive_spans": ["Dataset A"],
                                        "yes_no": None,
                                        "highlighted_evidence": ["The experiments used Dataset A."],
                                        "evidence": ["The experiments used Dataset A in all runs."],
                                    }
                                }
                            ],
                        }
                    ],
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-import",
            "qasper",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 1
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["question_id"] == "qasper:paper_raw_001:raw-q1"
    assert rows[0]["required_points"] == ["Dataset A."]
    assert rows[0]["gold_evidence_ids"] == ["qasper:paper_raw_001:raw-q1.e0001"]
    assert rows[0]["candidate_evidence"][0]["text"] == "The experiments used Dataset A."


def test_cli_bench_import_scifact_converts_claims_and_rationales(tmp_path: Path, capsys):
    claims_path = tmp_path / "claims.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "gold_questions.external.scifact.jsonl"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 123,
                "title": "SciFact Paper",
                "abstract": [
                    "Background sentence.",
                    "Treatment reduced symptoms in the cohort.",
                    "Unrelated sentence.",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claims_path.write_text(
        json.dumps(
            {
                "id": 7,
                "claim": "Treatment reduced symptoms.",
                "evidence": {
                    "123": [
                        {
                            "sentences": [1],
                            "label": "SUPPORT",
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps({"id": 8, "claim": "No evidence claim.", "evidence": {}})
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-import",
            "scifact",
            "--claims",
            str(claims_path),
            "--corpus",
            str(corpus_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "scifact"
    assert payload["rows"] == 2
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["question_id"] == "scifact:7"
    assert rows[0]["question"] == "Verify this scientific claim: Treatment reduced symptoms."
    assert rows[0]["answer_type"] == "external_scifact_claim_verification"
    assert rows[0]["gold_evidence_ids"] == ["scifact:123.s0002"]
    assert rows[0]["required_points"] == ["The claim is supported by the cited SciFact rationale."]
    assert rows[0]["external_source"]["label"] == "SUPPORT"
    assert rows[0]["candidate_evidence"][0]["text"] == "Treatment reduced symptoms in the cohort."
    assert rows[1]["answerable"] is False
    assert rows[1]["forbidden_points"] == ["Do not support or refute this claim without SciFact evidence."]


def test_cli_bench_import_scifact_preserves_zero_claim_id(tmp_path: Path, capsys):
    claims_path = tmp_path / "claims.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "gold_questions.external.scifact.jsonl"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 0,
                "title": "Zero ID Paper",
                "abstract": ["Zero-index evidence."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claims_path.write_text(
        json.dumps(
            {
                "id": 0,
                "claim": "Zero-index evidence exists.",
                "evidence": {"0": [{"sentences": [0], "label": "CONTRADICT"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-import",
            "scifact",
            "--claims",
            str(claims_path),
            "--corpus",
            str(corpus_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["question_id"] == "scifact:0"
    assert rows[0]["gold_evidence_ids"] == ["scifact:0.s0001"]
    assert rows[0]["required_points"] == ["The claim is refuted by the cited SciFact rationale."]


def test_cli_bench_import_beir_converts_qrels_to_external_gold(tmp_path: Path, capsys):
    corpus_path = tmp_path / "corpus.jsonl"
    queries_path = tmp_path / "queries.jsonl"
    qrels_path = tmp_path / "qrels.tsv"
    output_path = tmp_path / "gold_questions.external.climate-fever.jsonl"
    corpus_path.write_text(
        json.dumps(
            {
                "_id": "doc-1",
                "title": "Climate Paper",
                "text": "Carbon dioxide increases radiative forcing in climate models.",
            }
        )
        + "\n"
        + json.dumps(
            {
                "_id": "doc-2",
                "title": "Distractor Paper",
                "text": "This document discusses unrelated calibration details.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            {
                "_id": "q1",
                "text": "Which document discusses carbon dioxide radiative forcing?",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    qrels_path.write_text(
        "query-id\tcorpus-id\tscore\nq1\tdoc-1\t1\nq1\tdoc-2\t0\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-import",
            "beir",
            "--corpus",
            str(corpus_path),
            "--queries",
            str(queries_path),
            "--qrels",
            str(qrels_path),
            "--dataset-name",
            "climate-fever",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "climate-fever"
    assert payload["rows"] == 1
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["question_id"] == "climate-fever:q1"
    assert rows[0]["answer_type"] == "external_climate_fever_document_retrieval"
    assert rows[0]["gold_evidence_ids"] == ["climate-fever:doc-1.s0001"]
    assert rows[0]["external_source"]["format"] == "beir"
    assert rows[0]["external_source"]["positive_doc_ids"] == ["doc-1"]
    assert rows[0]["candidate_evidence"][0]["text"] == (
        "Carbon dioxide increases radiative forcing in climate models."
    )


def test_cli_bench_import_beir_escapes_unicode_line_separators(tmp_path: Path, capsys):
    corpus_path = tmp_path / "corpus.jsonl"
    queries_path = tmp_path / "queries.jsonl"
    qrels_path = tmp_path / "qrels.tsv"
    output_path = tmp_path / "gold_questions.external.scidocs.jsonl"
    corpus_path.write_text(
        json.dumps(
            {
                "_id": "doc-1",
                "title": "SciDocs Paper",
                "text": "First finding\u2028Second finding\u0085Third finding\u2029Fourth finding",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    queries_path.write_text(json.dumps({"_id": "q1", "text": "Which paper has the finding?"}) + "\n", encoding="utf-8")
    qrels_path.write_text("query-id\tcorpus-id\tscore\nq1\tdoc-1\t1\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "bench-import",
            "beir",
            "--corpus",
            str(corpus_path),
            "--queries",
            str(queries_path),
            "--qrels",
            str(qrels_path),
            "--dataset-name",
            "scidocs",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["candidate_evidence"][0]["text"] == (
        "First finding\u2028Second finding\u0085Third finding\u2029Fourth finding"
    )


def test_import_scierc_ie_rows_converts_dygiepp_entities_and_relations(tmp_path: Path):
    input_path = tmp_path / "scierc.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "doc_key": "science-paper-1",
                "sentences": [
                    ["Neural", "networks", "solve", "image", "classification", "."],
                    ["The", "method", "uses", "ImageNet", "."],
                ],
                "ner": [
                    [[0, 1, "Method"], [3, 4, "Task"]],
                    [[9, 9, "Dataset"]],
                ],
                "relations": [
                    [[0, 1, 3, 4, "USED-FOR"]],
                    [],
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    importer = getattr(bench_import, "import_scierc_ie_rows", None)
    assert importer is not None
    rows = importer(input_path, benchmark_split="blind")

    assert len(rows) == 1
    row = rows[0]
    assert row["record_id"] == "scierc:science-paper-1"
    assert row["benchmark_task"] == "entity_relation_extraction"
    assert row["source_text"] == "Neural networks solve image classification. The method uses ImageNet."
    assert row["entities"] == [
        {"text": "Neural networks", "type": "Method", "start_token": 0, "end_token": 1},
        {"text": "image classification", "type": "Task", "start_token": 3, "end_token": 4},
        {"text": "ImageNet", "type": "Dataset", "start_token": 9, "end_token": 9},
    ]
    assert row["relations"] == [
        {
            "head": "Neural networks",
            "tail": "image classification",
            "type": "USED-FOR",
            "head_start_token": 0,
            "head_end_token": 1,
            "tail_start_token": 3,
            "tail_end_token": 4,
        }
    ]
    assert row["annotation_status"] == "imported"
    assert row["benchmark_split"] == "blind"
    assert row["external_source"] == {
        "dataset": "scierc",
        "format": "dygiepp",
        "doc_key": "science-paper-1",
        "benchmark_split": "blind",
    }


def test_cli_bench_import_scienceie_converts_brat_entities_and_relations(tmp_path: Path, capsys):
    input_dir = tmp_path / "scienceie"
    input_dir.mkdir()
    (input_dir / "S001.txt").write_text(
        "Graph neural networks improve citation classification.",
        encoding="utf-8",
    )
    (input_dir / "S001.ann").write_text(
        "T1\tMethod 0 21\tGraph neural networks\n"
        "T2\tTask 30 53\tcitation classification\n"
        "R1\tUSED-FOR Arg1:T1 Arg2:T2\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "gold_entities.external.scienceie.jsonl"

    exit_code = cli.main(
        [
            "bench-import",
            "scienceie",
            "--input",
            str(input_dir),
            "--output",
            str(output_path),
            "--benchmark-split",
            "blind",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "scienceie"
    assert payload["rows"] == 1
    row = json.loads(output_path.read_text(encoding="utf-8").strip())
    assert row["record_id"] == "scienceie:S001"
    assert row["benchmark_task"] == "entity_relation_extraction"
    assert row["source_text"] == "Graph neural networks improve citation classification."
    assert row["entities"] == [
        {
            "entity_id": "T1",
            "text": "Graph neural networks",
            "type": "Method",
            "start_char": 0,
            "end_char": 21,
        },
        {
            "entity_id": "T2",
            "text": "citation classification",
            "type": "Task",
            "start_char": 30,
            "end_char": 53,
        },
    ]
    assert row["relations"] == [
        {
            "relation_id": "R1",
            "head": "Graph neural networks",
            "tail": "citation classification",
            "type": "USED-FOR",
            "head_id": "T1",
            "tail_id": "T2",
        }
    ]
    assert row["external_source"] == {
        "dataset": "scienceie",
        "format": "brat",
        "doc_id": "S001",
            "benchmark_split": "blind",
    }


def test_ie_bench_scores_entity_candidates_against_imported_gold(tmp_path: Path):
    gold_path = tmp_path / "gold_entities.jsonl"
    predictions_path = tmp_path / "entity-candidates.jsonl"
    metrics_path = tmp_path / "ie-metrics.json"
    gold_path.write_text(
        json.dumps(
            {
                "record_id": "scierc:doc1",
                "entities": [
                    {"text": "Graph neural networks", "type": "Method"},
                    {"text": "citation classification", "type": "Task"},
                ],
            }
        )
        + "\n"
        + json.dumps(
            {
                "record_id": "scienceie:doc2",
                "entities": [{"text": "ImageNet", "type": "Dataset"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps({"surface_form": "Graph neural networks", "entity_type": "Method"}) + "\n"
        + json.dumps({"surface_form": "Citation Classification", "entity_type": "Method"}) + "\n"
        + json.dumps({"surface_form": "Distractor", "entity_type": "Method"}) + "\n",
        encoding="utf-8",
    )

    module = importlib.import_module("scansci_html.ie_bench")
    evaluator = getattr(module, "evaluate_ie_entities", None)
    assert evaluator is not None
    metrics = evaluator(gold_path, predictions_path, output_path=metrics_path)

    assert metrics["gold_entities"] == 3
    assert metrics["predicted_entities"] == 3
    assert metrics["entity_matches"] == 2
    assert metrics["entity_precision"] == pytest.approx(2 / 3)
    assert metrics["entity_recall"] == pytest.approx(2 / 3)
    assert metrics["entity_f1"] == pytest.approx(2 / 3)
    assert metrics["typed_entity_matches"] == 1
    assert metrics["typed_entity_precision"] == pytest.approx(1 / 3)
    assert metrics["typed_entity_recall"] == pytest.approx(1 / 3)
    assert metrics["typed_entity_f1"] == pytest.approx(1 / 3)
    assert json.loads(metrics_path.read_text(encoding="utf-8")) == metrics


def test_cli_ie_bench_scores_entity_candidates(tmp_path: Path, capsys):
    gold_path = tmp_path / "gold_entities.jsonl"
    predictions_path = tmp_path / "entity-candidates.jsonl"
    metrics_path = tmp_path / "ie-metrics.json"
    gold_path.write_text(
        json.dumps({"entities": [{"text": "ImageNet", "type": "Dataset"}]}) + "\n",
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps({"text": "imagenet", "type": "Dataset"}) + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "ie-bench",
            "--gold",
            str(gold_path),
            "--predictions",
            str(predictions_path),
            "--output",
            str(metrics_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entity_f1"] == 1.0
    assert payload["typed_entity_f1"] == 1.0
    assert payload["output_path"] == str(metrics_path)


def test_cli_entity_candidates_extracts_scientific_ngrams_from_jsonl(tmp_path: Path, capsys):
    input_path = tmp_path / "gold_entities.external.scienceie.jsonl"
    output_path = tmp_path / "entity-candidates.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "record_id": "scienceie:S001",
                "source_text": "Graph neural networks improve citation classification.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "entity-candidates",
            "--input-jsonl",
            str(input_path),
            "--output",
            str(output_path),
            "--profile",
            "scientific-ngram",
            "--max-candidates",
            "50",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "scientific-ngram"
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert any(row["normalized"] == "citation classification" for row in rows)


def test_build_beir_external_store_writes_document_level_spans(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    db_path = tmp_path / "beir-evidence.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "_id": "doc-1",
                "title": "Climate Paper",
                "text": "Carbon dioxide increases radiative forcing in climate models.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_beir_external_store(corpus_path, db_path, dataset="climate-fever")

    assert payload["dataset"] == "climate-fever"
    assert payload["documents"] == 1
    assert payload["spans"] == 1
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select evidence_id, doc_id, section_kind, text from evidence_spans"
        ).fetchone()
    assert row == (
        "climate-fever:doc-1.s0001",
        "doc-1",
        "document",
        "Carbon dioxide increases radiative forcing in climate models.",
    )


def test_cli_bench_external_beir_builds_store_and_scores_retrieval(tmp_path: Path, capsys):
    corpus_path = tmp_path / "corpus.jsonl"
    queries_path = tmp_path / "queries.jsonl"
    qrels_path = tmp_path / "qrels.tsv"
    gold_path = tmp_path / "gold_questions.external.climate-fever.jsonl"
    db_path = tmp_path / "beir-evidence.sqlite"
    details_path = tmp_path / "beir-details.json"
    corpus_path.write_text(
        json.dumps(
            {
                "_id": "doc-1",
                "title": "Climate Paper",
                "text": "Carbon dioxide increases radiative forcing in climate models.",
            }
        )
        + "\n"
        + json.dumps(
            {
                "_id": "doc-2",
                "title": "Distractor Paper",
                "text": "This document discusses unrelated calibration details.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps(
            {
                "_id": "q1",
                "text": "carbon dioxide radiative forcing climate models",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    qrels_path.write_text("query-id\tcorpus-id\tscore\nq1\tdoc-1\t1\n", encoding="utf-8")
    assert (
        cli.main(
            [
                "bench-import",
                "beir",
                "--corpus",
                str(corpus_path),
                "--queries",
                str(queries_path),
                "--qrels",
                str(qrels_path),
                "--dataset-name",
                "climate-fever",
                "--output",
                str(gold_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "beir",
            "--corpus",
            str(corpus_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--dataset-name",
            "climate-fever",
            "--k",
            "1",
            "--initial-limit",
            "5",
            "--dense-limit",
            "0",
            "--min-retrieval-recall",
            "1.0",
            "--details-output",
            str(details_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "climate-fever"
    assert payload["external_corpus_documents"] == 2
    assert payload["external_corpus_spans"] == 2
    assert payload["retrieval_recall_at_k"] == 1.0
    assert payload["gold_evidence_recall_at_k"] == 1.0
    assert payload["passed"] is True
    details = json.loads(details_path.read_text(encoding="utf-8"))
    assert details["questions"][0]["retrieved_evidence_ids"] == ["climate-fever:doc-1.s0001"]
    assert details["questions"][0]["retrieved_gold_evidence_ids"] == ["climate-fever:doc-1.s0001"]


def test_cli_bench_external_qasper_builds_store_and_scores_retrieval(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    gold_path = tmp_path / "gold_questions.external.qasper.jsonl"
    db_path = tmp_path / "qasper-evidence.sqlite"
    details_path = tmp_path / "qasper-details.json"
    input_path.write_text(
        json.dumps(
            {
                "paper_qasper_001": {
                    "title": "External QASPER Paper",
                    "abstract": "A paper abstract.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "The method improved accuracy on the benchmark. A distractor sentence discusses latency.",
                            ],
                        }
                    ],
                    "qas": [
                        {
                            "question": "What did the method improve?",
                            "question_id": "qasper-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Accuracy.",
                                        "extractive_spans": ["accuracy"],
                                        "yes_no": None,
                                        "highlighted_evidence": [
                                            "The method improved accuracy on the benchmark."
                                        ],
                                        "evidence": [
                                            "The method improved accuracy on the benchmark. A distractor sentence discusses latency."
                                        ],
                                    }
                                }
                            ],
                        }
                    ],
                },
                "paper_qasper_002": {
                    "title": "Unused QASPER Paper",
                    "abstract": "A second abstract.",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "The second method changed calibration on a separate benchmark.",
                            ],
                        }
                    ],
                    "qas": [
                        {
                            "question": "What did the second method change?",
                            "question_id": "qasper-q2",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Calibration.",
                                        "extractive_spans": ["calibration"],
                                        "yes_no": None,
                                        "highlighted_evidence": [
                                            "The second method changed calibration on a separate benchmark."
                                        ],
                                        "evidence": [
                                            "The second method changed calibration on a separate benchmark."
                                        ],
                                    }
                                }
                            ],
                        }
                    ],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert cli.main(["bench-import", "qasper", "--input", str(input_path), "--output", str(gold_path)]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "qasper",
            "--input",
            str(input_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "3",
            "--limit",
            "1",
            "--initial-limit",
            "0",
            "--dense-limit",
            "1",
            "--min-retrieval-recall",
            "1.0",
            "--min-all-gold-retrieval-recall",
            "1.0",
            "--min-gold-evidence-recall",
            "1.0",
            "--details-output",
            str(details_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "qasper"
    assert payload["questions"] == 1
    assert payload["gold_labeled_questions"] == 1
    assert payload["external_corpus_documents"] == 1
    assert payload["external_corpus_spans"] >= 2
    assert payload["external_gold_spans"] == 0
    assert payload["mapped_gold_evidence"] == 1
    assert payload["unmapped_gold_evidence"] == 0
    assert payload["initial_limit"] == 0
    assert payload["dense_limit"] == 1
    assert payload["embedding_cache_rows"] == payload["external_corpus_spans"]
    assert payload["retrieval_recall_at_k"] == 1.0
    assert payload["all_gold_retrieval_recall_at_k"] == 1.0
    assert payload["gold_evidence_recall_at_k"] == 1.0
    assert payload["passed"] is True
    details = json.loads(details_path.read_text(encoding="utf-8"))
    assert len(details["questions"][0]["retrieved_evidence_ids"]) <= 1
    assert details["questions"][0]["retrieved_evidence_ids"] == [
        "qasper:paper_qasper_001.raw.s0001"
    ]
    assert details["questions"][0]["retrieved_gold_evidence_ids"] == [
        "qasper:paper_qasper_001:qasper-q1.e0001"
    ]
    assert details["questions"][0]["mapped_gold_evidence_ids"] == {
        "qasper:paper_qasper_001:qasper-q1.e0001": ["qasper:paper_qasper_001.raw.s0001"]
    }
    with sqlite3.connect(db_path) as connection:
        cache_rows = connection.execute("select count(*) from external_embedding_cache").fetchone()[0]
        gold_spans = connection.execute("select count(*) from evidence_spans where section_kind = 'gold'").fetchone()[0]
        synthetic_gold_spans = connection.execute(
            "select count(*) from evidence_spans where evidence_id = ?",
            ("qasper:paper_qasper_001:qasper-q1.e0001",),
        ).fetchone()[0]
    assert cache_rows == payload["external_corpus_spans"]
    assert gold_spans == 0
    assert synthetic_gold_spans == 0


def test_cli_bench_external_scifact_builds_store_and_scores_retrieval(tmp_path: Path, capsys):
    claims_path = tmp_path / "claims.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold_questions.external.scifact.jsonl"
    db_path = tmp_path / "scifact-evidence.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 321,
                "title": "External SciFact Paper",
                "abstract": [
                    "A background sentence about unrelated biology.",
                    "Treatment reduced symptoms in the cohort.",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claims_path.write_text(
        json.dumps(
            {
                "id": 9,
                "claim": "Treatment reduced symptoms.",
                "evidence": {"321": [{"sentences": [1], "label": "SUPPORT"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        cli.main(
            [
                "bench-import",
                "scifact",
                "--claims",
                str(claims_path),
                "--corpus",
                str(corpus_path),
                "--output",
                str(gold_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "scifact",
            "--corpus",
            str(corpus_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "1",
            "--min-retrieval-recall",
            "1.0",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "scifact"
    assert payload["questions"] == 1
    assert payload["external_corpus_spans"] == 2
    assert payload["retrieval_recall_at_k"] == 1.0
    assert payload["gold_evidence_recall_at_k"] == 1.0
    assert payload["passed"] is True


def test_cli_bench_external_accepts_embedding_provider(tmp_path: Path, capsys, monkeypatch):
    claims_path = tmp_path / "claims.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold_questions.external.scifact.jsonl"
    db_path = tmp_path / "scifact-evidence.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 321,
                "title": "External SciFact Paper",
                "abstract": [
                    "Treatment reduced symptoms in the cohort.",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    claims_path.write_text(
        json.dumps(
            {
                "id": 9,
                "claim": "Treatment reduced symptoms.",
                "evidence": {"321": [{"sentences": [0], "label": "SUPPORT"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        cli.main(
            [
                "bench-import",
                "scifact",
                "--claims",
                str(claims_path),
                "--corpus",
                str(corpus_path),
                "--output",
                str(gold_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    provider_calls = []

    class FakeEmbeddingProvider:
        dimensions = 4

        def embed_texts(self, texts):
            return [[1.0, 0.0, 0.0, 0.0] for _text in texts]

    def fake_build_embedding_provider(
        provider,
        *,
        base_url="",
        api_key="",
        model="",
        dimensions=128,
        batch_size=32,
        max_seq_length=0,
    ):
        provider_calls.append((provider, model, batch_size))
        return FakeEmbeddingProvider()

    monkeypatch.setattr(cli, "build_embedding_provider", fake_build_embedding_provider)

    exit_code = cli.main(
        [
            "bench-external",
            "scifact",
            "--corpus",
            str(corpus_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "1",
            "--embedding-provider",
            "sentence-transformers",
            "--embedding-model",
            "local-test-model",
            "--embedding-batch-size",
            "4",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert provider_calls == [("sentence-transformers", "local-test-model", 4)]
    assert payload["embedding_provider"] == "sentence-transformers:local-test-model"


def test_external_benchmark_uses_provider_query_embedding_when_available(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": 1,
                        "title": "Relevant Paper",
                        "abstract": ["Relevant answer evidence appears in this paper."],
                    }
                ),
                json.dumps(
                    {
                        "doc_id": 2,
                        "title": "Distractor Paper",
                        "abstract": ["Distractor evidence appears in this paper."],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class PromptAwareProvider:
        dimensions = 2

        def embed_texts(self, texts):
            vectors = []
            for text in texts:
                if "Relevant answer evidence" in text:
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

        def embed_query(self, query):
            return [1.0, 0.0]

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=1,
        embedding_provider=PromptAwareProvider(),
        embedding_provider_name="prompt-aware-test",
    )

    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["wall_time_seconds"] >= 0
    assert metrics["avg_wall_time_seconds_per_question"] >= 0


def test_external_benchmark_skips_query_embedding_when_dense_disabled(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["Needle answer evidence appears in this paper."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class NoQueryProvider:
        dimensions = 2

        def embed_texts(self, texts):
            raise AssertionError("text embeddings should not be computed when dense retrieval is disabled")

        def embed_query(self, query):
            raise AssertionError("query embeddings should not be computed when dense retrieval is disabled")

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=5,
        dense_limit=0,
        embedding_provider=NoQueryProvider(),
        embedding_provider_name="dense-disabled-test",
    )

    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["query_embedding_cache_hits"] == 0
    assert metrics["query_embedding_cache_misses"] == 0


def test_external_query_variants_expand_question_without_gold_leakage():
    variants = external_query_variants("Which datasets did they experiment with?", max_queries=3)

    assert variants[0] == "Which datasets did they experiment with?"
    assert any("corpus" in variant or "evaluation" in variant for variant in variants[1:])
    assert all("Europarl" not in variant and "MultiUN" not in variant for variant in variants)


def test_external_benchmark_multi_query_can_recover_synonym_retrieval(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["The evaluation corpus contains carefully annotated examples."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "Which dataset did they experiment with?",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    baseline = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=5,
        dense_limit=0,
        query_variants=1,
    )
    expanded = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=5,
        dense_limit=0,
        query_variants=3,
        include_details=True,
    )

    assert baseline["retrieval_recall_at_k"] == 0.0
    assert expanded["retrieval_recall_at_k"] == 1.0
    assert expanded["query_variants"] == 3
    assert expanded["question_results"][0]["retrieval_queries"] == external_query_variants(
        "Which dataset did they experiment with?",
        max_queries=3,
    )


def test_external_benchmark_reports_retrieval_trace_metrics(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["Needle answer evidence appears in this paper."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle answer",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=5,
        dense_limit=0,
        include_details=True,
    )

    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["retrieval_trace_questions"] == 1
    assert metrics["retrieval_search_calls"] == 1
    assert metrics["retrieval_queries"] == 1
    assert metrics["retrieval_fts_candidates"] == 1
    assert metrics["retrieval_dense_candidates"] == 0
    assert metrics["retrieval_unique_candidates"] == 1
    assert metrics["retrieval_reranked_candidates"] == 1
    assert metrics["retrieval_returned_hits"] == 1
    assert metrics["avg_search_calls_per_question"] == 1.0
    assert metrics["avg_fts_candidates_per_question"] == 1.0
    assert metrics["retrieval_route_counts"] == {"fts": 1}
    question = metrics["question_results"][0]
    assert question["retrieved_route_counts"] == {"fts": 1}
    assert question["retrieval_trace"][0]["stage"] == "search"
    assert question["retrieval_trace"][0]["dense_limit"] == 0
    assert question["retrieval_trace"][0]["returned_hits"] == 1


def test_external_benchmark_reports_float_table_subset_metrics(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["FLOAT SELECTED: Table 2: Main results report 91 percent accuracy."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "q-float",
                        "question": "What accuracy was reported in the table?",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                        "candidate_evidence": [
                            {
                                "evidence_id": "scifact:1.s0001",
                                "text": "FLOAT SELECTED: Table 2: Main results.",
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "question_id": "q-text",
                        "question": "Which method was used?",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                        "candidate_evidence": [
                            {
                                "evidence_id": "scifact:1.s0001",
                                "text": "The methods section describes a baseline.",
                            }
                        ],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=5,
        dense_limit=0,
        include_details=True,
    )

    assert metrics["float_table_gold_labeled_questions"] == 1
    assert metrics["float_table_retrieval_recall_at_k"] == 1.0
    assert metrics["float_table_gold_evidence_recall_at_k"] == 1.0
    assert metrics["non_float_table_gold_labeled_questions"] == 1
    assert metrics["non_float_table_retrieval_recall_at_k"] == 0.0
    assert metrics["question_results"][0]["gold_evidence_kinds"] == {"scifact:1.s0001": "float_or_table"}
    assert metrics["question_results"][1]["gold_evidence_kinds"] == {"scifact:1.s0001": "text"}


def test_generate_mistake_cases_classifies_retrieval_and_float_failures():
    details = {
        "metrics": {"dataset": "qasper", "k": 20, "gold_evidence_recall_at_k": 0.5},
        "questions": [
            {
                "question_id": "qasper:paper:q1",
                "question": "What accuracy does the proposed system achieve?",
                "answerable": True,
                "gold_evidence_ids": ["gold-float", "gold-text"],
                "retrieved_evidence_ids": ["raw-distractor"],
                "retrieved_gold_evidence_ids": ["gold-text"],
                "missing_gold_evidence_ids": ["gold-float"],
                "unmapped_gold_evidence_ids": ["gold-float"],
                "gold_evidence_recall_at_k": 0.5,
            }
        ],
    }
    gold_rows = [
        {
            "question_id": "qasper:paper:q1",
            "candidate_evidence": [
                {
                    "evidence_id": "gold-float",
                    "text": "FLOAT SELECTED: Table 2: Main results.",
                },
                {"evidence_id": "gold-text", "text": "The system is evaluated on held-out data."},
            ],
        }
    ]

    cases = generate_mistake_cases(
        details,
        gold_rows=gold_rows,
        details_path="bench/qasper-details.json",
        gold_path="bench/gold.jsonl",
        created_at="2026-06-22",
    )
    summary = summarize_mistake_cases(cases)
    html = render_mistake_cases_report(cases, title="Mistakes")

    assert len(cases) == 1
    assert cases[0]["failure_type"] == "format_loss"
    assert cases[0]["tags"] == ["float_or_table_evidence", "partial_retrieval", "unmapped_gold"]
    assert cases[0]["gold_evidence"] == ["gold-float", "gold-text"]
    assert cases[0]["predicted_evidence"] == ["raw-distractor"]
    assert "bench/qasper-details.json" in cases[0]["links"]
    assert summary["total_cases"] == 1
    assert summary["failure_type_counts"] == {"format_loss": 1}
    assert summary["tag_counts"] == {
        "float_or_table_evidence": 1,
        "partial_retrieval": 1,
        "unmapped_gold": 1,
    }
    assert "format_loss: 1" in html
    assert "gold-float" in html


def test_generate_mistake_cases_uses_trace_for_under_search_diagnosis():
    details = {
        "metrics": {"dataset": "qasper", "k": 20},
        "questions": [
            {
                "question_id": "q-under-search",
                "question": "Which dataset was used?",
                "answerable": True,
                "gold_evidence_ids": ["gold-dataset"],
                "retrieved_evidence_ids": [],
                "retrieved_gold_evidence_ids": [],
                "missing_gold_evidence_ids": ["gold-dataset"],
                "unmapped_gold_evidence_ids": [],
                "gold_evidence_recall_at_k": 0.0,
                "retrieval_queries": ["Which dataset was used?", "dataset corpus benchmark"],
                "retrieval_trace_summary": {
                    "search_calls": 2,
                    "queries": 2,
                    "fts_candidates": 0,
                    "dense_candidates": 0,
                    "unique_candidates": 0,
                    "reranked_candidates": 0,
                    "returned_hits": 0,
                    "route_counts": {},
                },
                "retrieval_trace": [
                    {
                        "stage": "search",
                        "query": "Which dataset was used?",
                        "scope_doc_count": 1,
                        "fts_candidates": 0,
                        "dense_candidates": 0,
                        "unique_candidates": 0,
                        "reranked_candidates": 0,
                        "returned_hits": 0,
                        "route_counts": {},
                    },
                    {
                        "stage": "search",
                        "query": "dataset corpus benchmark",
                        "scope_doc_count": 1,
                        "fts_candidates": 0,
                        "dense_candidates": 0,
                        "unique_candidates": 0,
                        "reranked_candidates": 0,
                        "returned_hits": 0,
                        "route_counts": {},
                    },
                ],
            }
        ],
    }

    cases = generate_mistake_cases(details, created_at="2026-06-23")

    assert len(cases) == 1
    assert cases[0]["failure_type"] == "under_search"
    assert cases[0]["tags"] == ["retrieval_miss", "under_search", "bad_query_variant"]
    assert any("retrieval_trace_summary=" in item for item in cases[0]["evidence"])
    assert "exact term extraction" in cases[0]["next_action"]


def test_generate_mistake_cases_uses_trace_for_empty_scope_diagnosis():
    details = {
        "metrics": {"dataset": "qasper", "k": 20},
        "questions": [
            {
                "question_id": "q-empty-scope",
                "question": "Which result is reported?",
                "answerable": True,
                "gold_evidence_ids": ["gold-result"],
                "retrieved_evidence_ids": [],
                "retrieved_gold_evidence_ids": [],
                "missing_gold_evidence_ids": ["gold-result"],
                "unmapped_gold_evidence_ids": [],
                "gold_evidence_recall_at_k": 0.0,
                "retrieval_trace_summary": {
                    "search_calls": 1,
                    "queries": 1,
                    "fts_candidates": 0,
                    "dense_candidates": 0,
                    "unique_candidates": 0,
                    "reranked_candidates": 0,
                    "returned_hits": 0,
                    "route_counts": {},
                },
                "retrieval_trace": [
                    {
                        "stage": "search",
                        "query": "Which result is reported?",
                        "scope_doc_count": 0,
                        "fts_candidates": 0,
                        "dense_candidates": 0,
                        "unique_candidates": 0,
                        "reranked_candidates": 0,
                        "returned_hits": 0,
                        "route_counts": {},
                    }
                ],
            }
        ],
    }

    cases = generate_mistake_cases(details, created_at="2026-06-23")

    assert len(cases) == 1
    assert cases[0]["failure_type"] == "wrong_scope"
    assert cases[0]["tags"] == ["retrieval_miss", "wrong_scope", "under_search"]
    assert "scope filters" in cases[0]["next_action"]


def test_generate_mistake_cases_uses_trace_for_wrong_route_diagnosis():
    details = {
        "metrics": {"dataset": "scifact", "k": 20},
        "questions": [
            {
                "question_id": "q-wrong-route",
                "question": "Does the intervention improve survival?",
                "answerable": True,
                "gold_evidence_ids": ["gold-support"],
                "retrieved_evidence_ids": ["raw-distractor"],
                "retrieved_gold_evidence_ids": [],
                "missing_gold_evidence_ids": ["gold-support"],
                "unmapped_gold_evidence_ids": [],
                "gold_evidence_recall_at_k": 0.0,
                "retrieval_queries": ["Does the intervention improve survival?", "intervention survival"],
                "retrieved_route_counts": {"dense": 1, "query-1": 1},
                "retrieval_trace_summary": {
                    "search_calls": 2,
                    "queries": 2,
                    "fts_candidates": 0,
                    "dense_candidates": 4,
                    "unique_candidates": 4,
                    "reranked_candidates": 4,
                    "returned_hits": 2,
                    "route_counts": {"dense": 1, "query-1": 1},
                },
                "retrieval_trace": [
                    {
                        "stage": "search",
                        "query": "Does the intervention improve survival?",
                        "scope_doc_count": 0,
                        "fts_candidates": 0,
                        "dense_candidates": 4,
                        "unique_candidates": 4,
                        "reranked_candidates": 4,
                        "returned_hits": 2,
                        "route_counts": {"dense": 2},
                    },
                    {
                        "stage": "search",
                        "query": "intervention survival",
                        "scope_doc_count": 0,
                        "fts_candidates": 0,
                        "dense_candidates": 0,
                        "unique_candidates": 0,
                        "reranked_candidates": 0,
                        "returned_hits": 0,
                        "route_counts": {},
                    },
                ],
            }
        ],
    }

    cases = generate_mistake_cases(details, created_at="2026-06-23")

    assert len(cases) == 1
    assert cases[0]["failure_type"] == "wrong_route"
    assert cases[0]["tags"] == ["retrieval_miss", "bad_query_variant", "wrong_route"]
    assert "route weights" in cases[0]["next_action"]


def test_cli_bench_mistakes_writes_jsonl_and_html(tmp_path: Path, capsys):
    details_path = tmp_path / "details.json"
    gold_path = tmp_path / "gold.jsonl"
    output_path = tmp_path / "mistakes.jsonl"
    html_path = tmp_path / "mistakes.html"
    details_path.write_text(
        json.dumps(
            {
                "metrics": {"dataset": "qasper", "k": 20},
                "questions": [
                    {
                        "question_id": "q1",
                        "question": "What accuracy was reported?",
                        "answerable": True,
                        "gold_evidence_ids": ["gold-float"],
                        "retrieved_evidence_ids": ["raw-distractor"],
                        "retrieved_gold_evidence_ids": [],
                        "missing_gold_evidence_ids": ["gold-float"],
                        "unmapped_gold_evidence_ids": ["gold-float"],
                        "gold_evidence_recall_at_k": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "candidate_evidence": [
                    {"evidence_id": "gold-float", "text": "FLOAT SELECTED: Table 2: Main results."}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-mistakes",
            "--details",
            str(details_path),
            "--gold",
            str(gold_path),
            "--output",
            str(output_path),
            "--html-output",
            str(html_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    html = html_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["cases"] == 1
    assert payload["summary"]["failure_type_counts"] == {"format_loss": 1}
    assert rows[0]["failure_type"] == "format_loss"
    assert rows[0]["tags"] == ["float_or_table_evidence", "retrieval_miss", "unmapped_gold"]
    assert "gold-float" in html


def test_external_benchmark_filters_split_and_suppresses_blind_details(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": 1,
                        "title": "Dev Paper",
                        "abstract": ["Development evidence names the dev answer."],
                    }
                ),
                json.dumps(
                    {
                        "doc_id": 2,
                        "title": "Blind Paper",
                        "abstract": ["Blind evidence names the hidden answer."],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "dev-q",
                        "benchmark_split": "dev",
                        "question": "Which evidence names the dev answer?",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                    }
                ),
                json.dumps(
                    {
                        "question_id": "blind-q",
                        "benchmark_split": "blind",
                        "question": "Which evidence names the hidden answer?",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:2.s0001"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        include_details=True,
        initial_limit=2,
        dense_limit=0,
        benchmark_split="blind",
    )

    assert metrics["benchmark_split"] == "blind"
    assert metrics["details_policy"] == "aggregate_only"
    assert metrics["questions"] == 1
    assert metrics["gold_labeled_questions"] == 1
    assert "question_results" not in metrics


def test_external_benchmark_reads_utf8_bom_gold_jsonl(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "BOM Paper",
                "abstract": ["BOM-safe evidence appears here."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_payload = (
        json.dumps(
            {
                "question_id": "bom-q",
                "question": "Where does BOM-safe evidence appear?",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n"
    ).encode("utf-8")
    gold_path.write_bytes(b"\xef\xbb\xbf" + gold_payload)
    build_scifact_external_store(corpus_path, db_path)

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=1,
        dense_limit=0,
    )

    assert metrics["questions"] == 1
    assert metrics["gold_evidence_recall_at_k"] == 1.0


def test_cli_bench_external_blind_details_are_aggregate_only(tmp_path: Path, monkeypatch, capsys):
    details_path = tmp_path / "blind-details.json"
    captured: dict[str, object] = {}

    def fake_build_scifact_external_store(corpus_path, db_path, *, doc_ids=None):
        return {"documents": 1, "spans": 1, "gold_spans": 0, "gold_evidence_map_rows": 0}

    def fake_run_external_retrieval_benchmark(
        db_path,
        gold_path,
        *,
        k,
        limit,
        include_details,
        per_document_limit,
        initial_limit,
        dense_limit,
        scope,
        embedding_provider,
        embedding_provider_name,
        reranker,
        embedding_cache_batch_size,
        reranker_cache_name,
        checkpoint_path,
        query_variants,
        benchmark_split,
    ):
        captured["benchmark_split"] = benchmark_split
        captured["include_details"] = include_details
        return {
            "questions": 1,
            "answerable_questions": 1,
            "unanswerable_questions": 0,
            "gold_labeled_questions": 1,
            "answerable_without_gold_evidence": 0,
            "k": k,
            "initial_limit": initial_limit,
            "dense_limit": dense_limit,
            "per_document_limit": per_document_limit,
            "query_variants": query_variants,
            "benchmark_split": benchmark_split,
            "details_policy": "aggregate_only",
            "scope": scope,
            "embedding_provider": embedding_provider_name,
            "embedding_cache_batch_size": embedding_cache_batch_size,
            "embedding_cache_rows": 0,
            "embedding_cache_hits": 0,
            "embedding_cache_misses": 0,
            "query_embedding_cache_rows": 0,
            "query_embedding_cache_hits": 0,
            "query_embedding_cache_misses": 0,
            "reranker_score_cache_rows": 0,
            "reranker_score_cache_hits": 0,
            "reranker_score_cache_misses": 0,
            "reranker_score_cache_name": "",
            "checkpoint_path": "",
            "checkpoint_resumed_questions": 0,
            "checkpoint_written_questions": 0,
            "mapped_gold_evidence": 1,
            "unmapped_gold_evidence": 0,
            "retrieval_recall_at_k": 1.0,
            "all_gold_retrieval_recall_at_k": 1.0,
            "gold_evidence_recall_at_k": 1.0,
            "question_results": [
                {
                    "question_id": "blind-q",
                    "gold_evidence_ids": ["secret-gold"],
                    "missing_gold_evidence_ids": ["secret-gold"],
                }
            ],
        }

    monkeypatch.setattr(cli, "build_scifact_external_store", fake_build_scifact_external_store)
    monkeypatch.setattr(cli, "run_external_retrieval_benchmark", fake_run_external_retrieval_benchmark)

    exit_code = cli.main(
        [
            "bench-external",
            "scifact",
            "--corpus",
            "corpus.jsonl",
            "--gold",
            "gold.jsonl",
            "--db",
            "external.sqlite",
            "--benchmark-split",
            "blind",
            "--details-output",
            str(details_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    details = json.loads(details_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured["benchmark_split"] == "blind"
    assert captured["include_details"] is True
    assert payload["benchmark_split"] == "blind"
    assert payload["details_policy"] == "aggregate_only"
    assert "questions" not in details
    assert "secret-gold" not in details_path.read_text(encoding="utf-8")


def test_cli_bench_mistakes_refuses_blind_details(tmp_path: Path, capsys):
    details_path = tmp_path / "blind-details.json"
    output_path = tmp_path / "mistakes.jsonl"
    details_path.write_text(
        json.dumps(
            {
                "metrics": {"dataset": "qasper", "benchmark_split": "blind", "details_policy": "full"},
                "questions": [
                    {
                        "question_id": "blind-q",
                        "answerable": True,
                        "gold_evidence_ids": ["secret-gold"],
                        "missing_gold_evidence_ids": ["secret-gold"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "bench-mistakes",
            "--details",
            str(details_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["error"] == "blind_benchmark_details_are_not_for_mistake_analysis"
    assert not output_path.exists()


def test_external_benchmark_caches_repeated_query_embeddings(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["Relevant answer evidence appears in this paper."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "q1",
                        "question": "needle",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                    }
                ),
                json.dumps(
                    {
                        "question_id": "q2",
                        "question": "needle",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class CountingProvider:
        dimensions = 2

        def __init__(self):
            self.query_calls = 0

        def embed_texts(self, texts):
            return [[1.0, 0.0] for _text in texts]

        def embed_query(self, query):
            self.query_calls += 1
            return [1.0, 0.0]

    provider = CountingProvider()
    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=1,
        embedding_provider=provider,
        embedding_provider_name="query-cache-test",
    )

    assert provider.query_calls == 1
    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["query_embedding_cache_hits"] == 1
    assert metrics["query_embedding_cache_misses"] == 1
    assert metrics["query_embedding_cache_rows"] == 1


def test_external_benchmark_reuses_persistent_query_embedding_cache(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        json.dumps(
            {
                "doc_id": 1,
                "title": "Relevant Paper",
                "abstract": ["Relevant answer evidence appears in this paper."],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class WarmProvider:
        dimensions = 2

        def embed_texts(self, texts):
            return [[1.0, 0.0] for _text in texts]

        def embed_query(self, query):
            return [1.0, 0.0]

    class CacheOnlyProvider:
        dimensions = 2

        def embed_texts(self, texts):
            raise AssertionError("text embeddings should be loaded from cache")

        def embed_query(self, query):
            raise AssertionError("query embeddings should be loaded from cache")

    run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=1,
        embedding_provider=WarmProvider(),
        embedding_provider_name="persistent-query-cache-test",
    )
    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=1,
        embedding_provider=CacheOnlyProvider(),
        embedding_provider_name="persistent-query-cache-test",
    )

    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["embedding_cache_hits"] == 1
    assert metrics["query_embedding_cache_hits"] == 1
    assert metrics["query_embedding_cache_misses"] == 0


def test_external_embedding_cache_commits_completed_batches(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "doc_id": index,
                    "title": f"Paper {index}",
                    "abstract": [f"Evidence sentence {index} appears here."],
                }
            )
            for index in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class FailingAfterFirstBatchProvider:
        dimensions = 2

        def __init__(self):
            self.calls = 0

        def embed_texts(self, texts):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("stop after first cache batch")
            return [[1.0, 0.0] for _text in texts]

        def embed_query(self, query):
            return [1.0, 0.0]

    with pytest.raises(RuntimeError, match="stop after first cache batch"):
        run_external_retrieval_benchmark(
            db_path,
            gold_path,
            k=1,
            initial_limit=0,
            dense_limit=1,
            embedding_provider=FailingAfterFirstBatchProvider(),
            embedding_provider_name="batch-cache-test",
            embedding_cache_batch_size=1,
        )

    with sqlite3.connect(db_path) as connection:
        cached_rows = connection.execute(
            "select count(*) from external_embedding_cache where provider = ?",
            ("batch-cache-test",),
        ).fetchone()[0]
    assert cached_rows == 1


def test_external_benchmark_uses_configured_reranker(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": 1,
                        "title": "Relevant Paper",
                        "abstract": ["Relevant answer evidence appears in this paper."],
                    }
                ),
                json.dumps(
                    {
                        "doc_id": 2,
                        "title": "Distractor Paper",
                        "abstract": ["Distractor evidence appears in this paper."],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class DenseProvider:
        dimensions = 2

        def embed_texts(self, texts):
            vectors = []
            for text in texts:
                if "Relevant answer evidence" in text:
                    vectors.append([0.9, 0.0])
                else:
                    vectors.append([1.0, 0.0])
            return vectors

        def embed_query(self, query):
            return [1.0, 0.0]

    class PromoteRelevantReranker:
        def rerank(self, query, candidates):
            ranked = []
            for candidate in candidates:
                hit = dict(candidate)
                hit["score"] = 1.0 if "Relevant answer evidence" in hit["text"] else 0.0
                ranked.append(hit)
            return sorted(ranked, key=lambda hit: -hit["score"])

    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=2,
        embedding_provider=DenseProvider(),
        embedding_provider_name="dense-rerank-test",
        reranker=PromoteRelevantReranker(),
    )

    assert metrics["retrieval_recall_at_k"] == 1.0


def test_external_benchmark_reuses_persistent_reranker_score_cache(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": 1,
                        "title": "Relevant Paper",
                        "abstract": ["Relevant answer evidence appears in this paper."],
                    }
                ),
                json.dumps(
                    {
                        "doc_id": 2,
                        "title": "Distractor Paper",
                        "abstract": ["Distractor evidence appears in this paper."],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "needle",
                "answerable": True,
                "gold_evidence_ids": ["scifact:1.s0001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class DenseProvider:
        dimensions = 2

        def embed_texts(self, texts):
            return [[1.0, 0.0] for _text in texts]

        def embed_query(self, query):
            return [1.0, 0.0]

    class CountingReranker:
        def __init__(self):
            self.calls = 0

        def rerank(self, query, candidates):
            self.calls += 1
            ranked = []
            for candidate in candidates:
                hit = dict(candidate)
                hit["score"] = 1.0 if "Relevant answer evidence" in hit["text"] else 0.0
                ranked.append(hit)
            return sorted(ranked, key=lambda hit: -hit["score"])

    class CacheOnlyReranker:
        def rerank(self, query, candidates):
            raise AssertionError("reranker scores should be loaded from cache")

    warm_reranker = CountingReranker()
    warm_metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=2,
        embedding_provider=DenseProvider(),
        embedding_provider_name="reranker-cache-emb-test",
        reranker=warm_reranker,
        reranker_cache_name="counting-reranker-test",
    )
    cached_metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=2,
        embedding_provider=DenseProvider(),
        embedding_provider_name="reranker-cache-emb-test",
        reranker=CacheOnlyReranker(),
        reranker_cache_name="counting-reranker-test",
    )

    assert warm_reranker.calls == 1
    assert warm_metrics["reranker_score_cache_misses"] == 2
    assert cached_metrics["retrieval_recall_at_k"] == 1.0
    assert cached_metrics["reranker_score_cache_hits"] == 2
    assert cached_metrics["reranker_score_cache_misses"] == 0
    assert cached_metrics["reranker_score_cache_rows"] == 2


def test_external_benchmark_checkpoint_resumes_completed_questions(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    db_path = tmp_path / "scifact.sqlite"
    checkpoint_path = tmp_path / "checkpoint.jsonl"
    corpus_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": 1,
                        "title": "Paper One",
                        "abstract": ["First answer evidence appears in this paper."],
                    }
                ),
                json.dumps(
                    {
                        "doc_id": 2,
                        "title": "Paper Two",
                        "abstract": ["Second answer evidence appears in this paper."],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "q1",
                        "question": "needle one",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:1.s0001"],
                    }
                ),
                json.dumps(
                    {
                        "question_id": "q2",
                        "question": "needle two",
                        "answerable": True,
                        "gold_evidence_ids": ["scifact:2.s0001"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    build_scifact_external_store(corpus_path, db_path)

    class DenseProvider:
        dimensions = 2

        def embed_texts(self, texts):
            vectors = []
            for text in texts:
                vectors.append([1.0, 0.0] if "First answer evidence" in text else [0.0, 1.0])
            return vectors

        def embed_query(self, query):
            return [1.0, 0.0] if "one" in query else [0.0, 1.0]

    class FailingAfterFirstQuestionReranker:
        def __init__(self):
            self.calls = 0

        def rerank(self, query, candidates):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("stop after first checkpoint")
            ranked = []
            for candidate in candidates:
                hit = dict(candidate)
                hit["score"] = 1.0 if "First answer evidence" in hit["text"] else 0.0
                ranked.append(hit)
            return sorted(ranked, key=lambda hit: -hit["score"])

    class SecondQuestionReranker:
        def __init__(self):
            self.calls = 0

        def rerank(self, query, candidates):
            self.calls += 1
            ranked = []
            for candidate in candidates:
                hit = dict(candidate)
                hit["score"] = 1.0 if "Second answer evidence" in hit["text"] else 0.0
                ranked.append(hit)
            return sorted(ranked, key=lambda hit: -hit["score"])

    with pytest.raises(RuntimeError, match="stop after first checkpoint"):
        run_external_retrieval_benchmark(
            db_path,
            gold_path,
            k=1,
            initial_limit=0,
            dense_limit=2,
            embedding_provider=DenseProvider(),
            embedding_provider_name="checkpoint-emb-test",
            reranker=FailingAfterFirstQuestionReranker(),
            checkpoint_path=checkpoint_path,
        )

    checkpoint_lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
    assert len(checkpoint_lines) == 1
    assert json.loads(checkpoint_lines[0])["question_id"] == "q1"

    resume_reranker = SecondQuestionReranker()
    metrics = run_external_retrieval_benchmark(
        db_path,
        gold_path,
        k=1,
        initial_limit=0,
        dense_limit=2,
        embedding_provider=DenseProvider(),
        embedding_provider_name="checkpoint-emb-test",
        reranker=resume_reranker,
        checkpoint_path=checkpoint_path,
    )

    assert resume_reranker.calls == 1
    assert metrics["retrieval_recall_at_k"] == 1.0
    assert metrics["checkpoint_resumed_questions"] == 1
    assert metrics["checkpoint_written_questions"] == 1


def test_cli_bench_external_passes_reranker_options(monkeypatch, capsys):
    captured: dict[str, object] = {}
    embedding_provider = object()
    reranker = object()

    def fake_build_embedding_provider(
        provider,
        *,
        base_url="",
        api_key="",
        model="",
        dimensions=128,
        batch_size=32,
        max_seq_length=0,
    ):
        captured["embedding_provider"] = (provider, model, max_seq_length)
        return embedding_provider

    def fake_build_reranker(provider, *, model_name="", batch_size=32):
        captured["reranker"] = (provider, model_name, batch_size)
        return reranker

    def fake_build_scifact_external_store(corpus_path, db_path, *, doc_ids=None):
        captured["store"] = (corpus_path, db_path, doc_ids)
        return {"documents": 0, "spans": 0, "gold_spans": 0, "gold_evidence_map_rows": 0}

    def fake_run_external_retrieval_benchmark(
        db_path,
        gold_path,
        *,
        k,
        limit,
        include_details,
        per_document_limit,
        initial_limit,
        dense_limit,
        scope,
        embedding_provider,
        embedding_provider_name,
        reranker,
        embedding_cache_batch_size,
        reranker_cache_name,
        checkpoint_path,
        query_variants,
        benchmark_split,
    ):
        captured["benchmark"] = {
            "db_path": db_path,
            "gold_path": gold_path,
            "k": k,
            "limit": limit,
            "include_details": include_details,
            "per_document_limit": per_document_limit,
            "initial_limit": initial_limit,
            "dense_limit": dense_limit,
            "scope": scope,
            "embedding_provider": embedding_provider,
            "embedding_provider_name": embedding_provider_name,
            "reranker": reranker,
            "embedding_cache_batch_size": embedding_cache_batch_size,
            "reranker_cache_name": reranker_cache_name,
            "checkpoint_path": checkpoint_path,
            "query_variants": query_variants,
            "benchmark_split": benchmark_split,
        }
        return {
            "questions": 0,
            "answerable_questions": 0,
            "unanswerable_questions": 0,
            "gold_labeled_questions": 0,
            "answerable_without_gold_evidence": 0,
            "k": k,
            "initial_limit": initial_limit,
            "dense_limit": dense_limit,
            "per_document_limit": per_document_limit,
            "query_variants": query_variants,
            "benchmark_split": benchmark_split,
            "details_policy": "none",
            "scope": scope,
            "embedding_provider": embedding_provider_name,
            "embedding_cache_batch_size": embedding_cache_batch_size,
            "embedding_cache_rows": 0,
            "embedding_cache_hits": 0,
            "embedding_cache_misses": 0,
            "query_embedding_cache_rows": 0,
            "query_embedding_cache_hits": 0,
            "query_embedding_cache_misses": 0,
            "reranker_score_cache_rows": 0,
            "reranker_score_cache_hits": 0,
            "reranker_score_cache_misses": 0,
            "reranker_score_cache_name": "",
            "checkpoint_path": "",
            "checkpoint_resumed_questions": 0,
            "checkpoint_written_questions": 0,
            "mapped_gold_evidence": 0,
            "unmapped_gold_evidence": 0,
            "retrieval_recall_at_k": 0.0,
            "all_gold_retrieval_recall_at_k": 0.0,
            "gold_evidence_recall_at_k": 0.0,
        }

    monkeypatch.setattr(cli, "build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr(cli, "build_reranker", fake_build_reranker)
    monkeypatch.setattr(cli, "build_scifact_external_store", fake_build_scifact_external_store)
    monkeypatch.setattr(cli, "run_external_retrieval_benchmark", fake_run_external_retrieval_benchmark)

    exit_code = cli.main(
        [
            "bench-external",
            "scifact",
            "--corpus",
            "corpus.jsonl",
            "--gold",
            "gold.jsonl",
            "--db",
            "external.sqlite",
            "--k",
            "7",
            "--embedding-provider",
            "sentence-transformers",
            "--embedding-model",
            "Qwen/Qwen3-Embedding-0.6B",
            "--reranker",
            "cross-encoder",
            "--reranker-model",
            "Qwen/Qwen3-Reranker-0.6B",
            "--reranker-batch-size",
            "3",
            "--embedding-cache-batch-size",
            "17",
            "--embedding-max-seq-length",
            "512",
            "--reranker-cache-name",
            "qwen3-reranker-cache",
            "--checkpoint",
            "bench.checkpoint.jsonl",
            "--query-variants",
            "3",
        ]
    )

    assert exit_code == 0
    assert captured["embedding_provider"] == ("sentence-transformers", "Qwen/Qwen3-Embedding-0.6B", 512)
    assert captured["reranker"] == ("cross-encoder", "Qwen/Qwen3-Reranker-0.6B", 3)
    assert captured["benchmark"]["reranker"] is reranker
    assert captured["benchmark"]["embedding_cache_batch_size"] == 17
    assert captured["benchmark"]["reranker_cache_name"] == "qwen3-reranker-cache"
    assert captured["benchmark"]["checkpoint_path"] == Path("bench.checkpoint.jsonl")
    assert captured["benchmark"]["query_variants"] == 3
    assert captured["benchmark"]["benchmark_split"] == "dev"


def test_cli_bench_external_qasper_can_scope_retrieval_to_gold_documents(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    gold_path = tmp_path / "gold_questions.external.qasper.jsonl"
    db_path = tmp_path / "qasper-evidence.sqlite"
    details_path = tmp_path / "qasper-details.json"
    input_path.write_text(
        json.dumps(
            {
                "paper_qasper_001": {
                    "title": "Target Paper",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": ["The target system improved accuracy in controlled experiments."],
                        }
                    ],
                    "qas": [
                        {
                            "question": "What did the target system improve?",
                            "question_id": "qasper-scope-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Accuracy.",
                                        "extractive_spans": ["accuracy"],
                                        "highlighted_evidence": [
                                            "The target system improved accuracy in controlled experiments."
                                        ],
                                    }
                                }
                            ],
                        }
                    ],
                },
                "paper_qasper_002": {
                    "title": "Distractor Paper",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "The target system improved latency latency latency in a separate benchmark."
                            ],
                        }
                    ],
                    "qas": [],
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["bench-import", "qasper", "--input", str(input_path), "--output", str(gold_path)]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "qasper",
            "--input",
            str(input_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "5",
            "--scope",
            "gold-docs",
            "--details-output",
            str(details_path),
            "--min-retrieval-recall",
            "1.0",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "gold-docs"
    details = json.loads(details_path.read_text(encoding="utf-8"))
    retrieved_ids = details["questions"][0]["retrieved_evidence_ids"]
    assert retrieved_ids
    assert all(evidence_id.startswith("qasper:paper_qasper_001") for evidence_id in retrieved_ids)


def test_cli_bench_external_qasper_scopes_fts_before_candidate_limit(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    gold_path = tmp_path / "gold_questions.external.qasper.jsonl"
    db_path = tmp_path / "qasper-evidence.sqlite"
    input_path.write_text(
        json.dumps(
            {
                "paper_qasper_001": {
                    "title": "Target Paper",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": ["Accuracy on the controlled test set."],
                        }
                    ],
                    "qas": [
                        {
                            "question": "What did the target system achieve with improved accuracy?",
                            "question_id": "qasper-scoped-fts-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Accuracy.",
                                        "extractive_spans": ["accuracy"],
                                        "highlighted_evidence": [
                                            "Accuracy on the controlled test set."
                                        ],
                                    }
                                }
                            ],
                        }
                    ],
                },
                "paper_qasper_002": {
                    "title": "Distractor Paper",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": [
                                "The target system achieved improved accuracy accuracy accuracy accuracy in another paper."
                            ],
                        }
                    ],
                    "qas": [],
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["bench-import", "qasper", "--input", str(input_path), "--output", str(gold_path)]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "qasper",
            "--input",
            str(input_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "1",
            "--scope",
            "gold-docs",
            "--initial-limit",
            "1",
            "--dense-limit",
            "0",
            "--min-retrieval-recall",
            "1.0",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retrieval_recall_at_k"] == 1.0


def test_cli_bench_external_qasper_fts_matches_simple_inflections(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    gold_path = tmp_path / "gold_questions.external.qasper.jsonl"
    db_path = tmp_path / "qasper-evidence.sqlite"
    input_path.write_text(
        json.dumps(
            {
                "paper_qasper_001": {
                    "title": "Inflection Paper",
                    "full_text": [
                        {
                            "section_name": "Results",
                            "paragraphs": ["Improved accuracy on the controlled test set."],
                        }
                    ],
                    "qas": [
                        {
                            "question": "What does the method improve?",
                            "question_id": "qasper-inflection-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Accuracy.",
                                        "extractive_spans": ["accuracy"],
                                        "highlighted_evidence": [
                                            "Improved accuracy on the controlled test set."
                                        ],
                                    }
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["bench-import", "qasper", "--input", str(input_path), "--output", str(gold_path)]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "qasper",
            "--input",
            str(input_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "1",
            "--scope",
            "gold-docs",
            "--initial-limit",
            "1",
            "--dense-limit",
            "0",
            "--min-retrieval-recall",
            "1.0",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retrieval_recall_at_k"] == 1.0


def test_cli_bench_external_qasper_maps_gold_phrase_with_reordered_parenthetical(tmp_path: Path, capsys):
    input_path = tmp_path / "qasper-dev-v0.3.json"
    gold_path = tmp_path / "gold_questions.external.qasper.jsonl"
    db_path = tmp_path / "qasper-evidence.sqlite"
    input_path.write_text(
        json.dumps(
            {
                "paper_qasper_001": {
                    "title": "Loss Paper",
                    "full_text": [
                        {
                            "section_name": "Methods",
                            "paragraphs": ["For training, we minimize the Margin Ranking Loss (MR)."],
                        }
                    ],
                    "qas": [
                        {
                            "question": "Which loss is minimized during training?",
                            "question_id": "qasper-parenthetical-q1",
                            "answers": [
                                {
                                    "answer": {
                                        "unanswerable": False,
                                        "free_form_answer": "Margin Ranking Loss.",
                                        "extractive_spans": ["Margin Ranking Loss"],
                                        "highlighted_evidence": ["Margin Ranking (MR) Loss"],
                                    }
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["bench-import", "qasper", "--input", str(input_path), "--output", str(gold_path)]) == 0
    capsys.readouterr()

    exit_code = cli.main(
        [
            "bench-external",
            "qasper",
            "--input",
            str(input_path),
            "--gold",
            str(gold_path),
            "--db",
            str(db_path),
            "--k",
            "1",
            "--scope",
            "gold-docs",
            "--initial-limit",
            "1",
            "--dense-limit",
            "0",
            "--min-retrieval-recall",
            "1.0",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mapped_gold_evidence"] == 1
    assert payload["unmapped_gold_evidence"] == 0
    assert payload["retrieval_recall_at_k"] == 1.0


def _make_benchmark_fixture(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/bench">
          <h1>Benchmark Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Model predictions explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    gold_path = tmp_path / "gold.jsonl"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)
    gold_rows = [
        {
            "question_id": "q001",
            "question": "What evidence links models to cortical activity?",
            "gold_evidence_ids": ["10.1234_bench.s0001"],
            "required_points": ["Model predictions explained cortical activity"],
            "forbidden_points": ["survival"],
            "answerable": True,
        },
        {
            "question_id": "q002",
            "question": "What evidence links treatment to survival?",
            "gold_evidence_ids": [],
            "answerable": False,
        },
    ]
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )
    return db_path, gold_path


def _make_template_fixture(tmp_path: Path) -> Path:
    library = tmp_path / "template-library"
    library.mkdir()
    (library / "treatment-a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/template-a">
          <h1>Template A</h1>
          <h2>Methods</h2>
          <p id="methods-a">Samples were randomized before biomass measurement.</p>
          <h2>Results</h2>
          <p id="results-a">Treatment increased biomass by 18 percent in the greenhouse cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "treatment-b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/template-b">
          <h1>Template B</h1>
          <h2>Results</h2>
          <p id="results-b">Treatment did not increase biomass in the validation cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "template-evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)
    return db_path


def _beir_zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


class _ZipDownloadSession:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, stream: bool, timeout: float) -> object:
        self.calls.append({"url": url, "stream": stream, "timeout": timeout})
        return _ZipDownloadResponse(self.body)


class _ZipDownloadResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        return [self.body[index : index + chunk_size] for index in range(0, len(self.body), chunk_size)]
