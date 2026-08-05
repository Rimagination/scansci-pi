from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .bench import generate_gold_question_templates
from .coverage import build_corpus_coverage
from .embeddings import build_embedding_provider
from .entity_candidates import extract_entity_candidates_from_store
from .evidence_doctor import check_evidence_links
from .evidence_store import export_spans_jsonl, index_evidence_library, index_markdown_library
from .llm import build_chat_json_client
from .qa.agent import answer_question
from .render.gold_template import render_gold_template_report
from .render.report import render_answer_report
from .rerankers import CascadeReranker, build_reranker
from .review import build_review_matrix, write_review_matrix


@dataclass(frozen=True)
class LiteratureWorkflowConfig:
    library_dir: Path
    output_dir: Path
    db_path: Path
    source_format: str = "html"
    profile: str = "minilm"
    reindex: bool = False
    inject_evidence_html: bool = True
    min_sentence_length: int = 40
    questions: tuple[str, ...] = ()
    limit: int = 20
    max_quotes: int = 10
    min_quotes: int = 1
    min_documents: int = 1
    adequacy_profile: str = "auto"
    agentic_profile: str = "balanced"
    query_variants: int = 2
    max_followup_queries: int = 2
    paper_recall_limit: int = 50
    per_document_limit: int = 5
    context_mode: str = "sentence"
    quote_provider: str = "local"
    answer_provider: str = "local"
    verification_provider: str = "local"
    chat_provider: str = "openai-compatible"
    chat_base_url: str = ""
    chat_api_key: str = ""
    chat_model: str = ""
    chat_api_surface: str = "chat_completions"
    chat_responses_enabled: bool = False
    cascade_first_stage_limit: int = 50
    generate_gold_template: bool = False
    questions_per_type: int = 5
    entity_candidates: bool = True
    max_entity_candidates: int = 500
    max_entity_source_spans: int = 5000
    entity_candidate_profile: str = "regex"
    dry_run: bool = False


def run_literature_workflow(config: LiteratureWorkflowConfig) -> dict[str, object]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "workflow.manifest.json"
    plan_path = output_dir / "workflow.plan.md"
    evaluation_plan_path = output_dir / "paper-evaluation.plan.md"
    schema_path = output_dir / "extraction_schema.template.json"

    profile = workflow_profile(config.profile, cascade_first_stage_limit=config.cascade_first_stage_limit)
    manifest: dict[str, object] = {
        "workflow": "literature-rag",
        "profile": config.profile,
        "profile_settings": profile,
        "library_dir": str(config.library_dir),
        "source_format": config.source_format,
        "validation_protocol": "paper-style-public-benchmark-first",
        "db_path": str(config.db_path),
        "output_dir": str(output_dir),
        "steps": [],
        "artifacts": {
            "manifest": str(manifest_path),
            "plan": str(plan_path),
            "paper_evaluation_plan": str(evaluation_plan_path),
            "extraction_schema_template": str(schema_path),
        },
    }

    _write_text(plan_path, render_workflow_plan(config, profile))
    _write_text(evaluation_plan_path, render_paper_evaluation_plan(config))
    _write_json(schema_path, default_extraction_schema())
    _add_step(
        manifest,
        "plan",
        "written",
        {
            "plan": str(plan_path),
            "paper_evaluation_plan": str(evaluation_plan_path),
            "schema": str(schema_path),
        },
    )

    if config.dry_run:
        _add_step(manifest, "dry_run", "skipped_execution", {})
        _write_json(manifest_path, manifest)
        return manifest

    index_summary: dict[str, object] = {}
    should_index = config.reindex or not config.db_path.exists()
    if should_index:
        if config.source_format == "markdown":
            index_summary = index_markdown_library(
                config.library_dir,
                db_path=config.db_path,
                min_sentence_length=config.min_sentence_length,
            )
        else:
            index_summary = index_evidence_library(
                config.library_dir,
                db_path=config.db_path,
                inject_evidence_html=config.inject_evidence_html,
                min_sentence_length=config.min_sentence_length,
            )
        spans_jsonl = output_dir / "evidence-spans.jsonl"
        export_summary = export_spans_jsonl(config.db_path, spans_jsonl)
        index_summary["jsonl_output_path"] = str(export_summary["output_path"])
        _add_step(manifest, "index", "completed", {"db": str(config.db_path), "spans_jsonl": str(spans_jsonl)}, index_summary)
    else:
        _add_step(manifest, "index", "reused", {"db": str(config.db_path)})

    if config.source_format == "html":
        doctor = check_evidence_links(config.db_path)
        _add_step(manifest, "evidence_doctor", "passed" if doctor.get("passed") else "failed", {}, doctor)

    coverage = build_corpus_coverage(config.db_path)
    coverage_path = output_dir / "corpus-coverage.json"
    _write_json(coverage_path, coverage)
    _add_step(manifest, "corpus_coverage", "completed", {"coverage": str(coverage_path)}, coverage)

    if config.entity_candidates:
        entity_path = output_dir / "entity-candidates.jsonl"
        entity_summary = extract_entity_candidates_from_store(
            config.db_path,
            output_path=entity_path,
            max_candidates=config.max_entity_candidates,
            max_source_spans=config.max_entity_source_spans,
            profile=config.entity_candidate_profile,
        )
        _add_step(manifest, "entity_candidates", "completed", {"entity_candidates": str(entity_path)}, entity_summary)

    report_json_paths: list[Path] = []
    if config.questions:
        embedding_provider = _build_workflow_embedding_provider(profile)
        reranker = _build_workflow_reranker(profile)
        chat_client = _chat_client_from_config_if_needed(config)
        for index, question in enumerate(config.questions, start=1):
            stem = f"question-{index:03d}"
            html_path = reports_dir / f"{stem}.html"
            json_path = reports_dir / f"{stem}.json"
            report_payload = answer_question(
                config.db_path,
                question,
                limit=config.limit,
                max_quotes=config.max_quotes,
                min_quotes=config.min_quotes,
                min_documents=config.min_documents,
                adequacy_profile=config.adequacy_profile,
                agentic_profile=config.agentic_profile,
                query_variants=config.query_variants,
                max_followup_queries=config.max_followup_queries,
                paper_recall_limit=config.paper_recall_limit,
                per_document_limit=config.per_document_limit,
                context_mode=config.context_mode,
                embedding_provider=embedding_provider,
                reranker=reranker,
                quote_provider=config.quote_provider,
                answer_provider=config.answer_provider,
                verification_provider=config.verification_provider,
                chat_client=chat_client,
            )
            answer = dict(report_payload.get("answer", {}) or {})
            report_html = render_answer_report(
                answer,
                list(report_payload.get("evidence_table", []) or []),
                retrieval_metadata={
                    "query_plan": report_payload.get("query_plan", {}),
                    "agentic_trace": report_payload.get("agentic_trace", {}),
                    "retrieval_queries": report_payload.get("retrieval_queries", []),
                    "adequacy": report_payload.get("adequacy", {}),
                    "citation_verification": report_payload.get("citation_verification", {}),
                },
            )
            _write_text(html_path, report_html)
            _write_json(json_path, report_payload)
            report_json_paths.append(json_path)
            _add_step(
                manifest,
                f"ask:{stem}",
                "completed",
                {"html": str(html_path), "json": str(json_path)},
                {
                    "question": question,
                    "claims": len(answer.get("answer", []) or []),
                    "insufficient_evidence": bool(answer.get("insufficient_evidence", False)),
                    "evidence_rows": len(report_payload.get("evidence_table", []) or []),
                },
            )

        matrix_rows: list[dict[str, object]] = []
        for report_path in report_json_paths:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            matrix_rows.extend(build_review_matrix(report_payload))
        matrix_csv = output_dir / "review-matrix.csv"
        matrix_html = output_dir / "review-matrix.html"
        write_review_matrix(matrix_rows, matrix_csv, output_format="csv")
        write_review_matrix(matrix_rows, matrix_html, output_format="html")
        _add_step(
            manifest,
            "review_matrix",
            "completed",
            {"csv": str(matrix_csv), "html": str(matrix_html)},
            {"rows": len(matrix_rows), "reports": len(report_json_paths)},
        )

    if config.generate_gold_template:
        template_payload = generate_gold_question_templates(
            config.db_path,
            questions_per_type=config.questions_per_type,
        )
        template_rows = list(template_payload.get("templates", []) or [])
        template_path = output_dir / "gold_questions.template.jsonl"
        template_html = output_dir / "gold_questions.template.html"
        _write_jsonl(template_path, template_rows)
        _write_text(template_html, render_gold_template_report(template_rows))
        summary = dict(template_payload)
        summary.pop("templates", None)
        _add_step(
            manifest,
            "gold_template",
            "completed",
            {"jsonl": str(template_path), "html": str(template_html)},
            summary,
        )

    _write_json(manifest_path, manifest)
    return manifest


def workflow_profile(profile_name: str, *, cascade_first_stage_limit: int = 50) -> dict[str, object]:
    name = profile_name.strip().lower()
    if name == "local":
        return {
            "embedding_provider": "local",
            "embedding_model": "",
            "reranker": {"provider": "local", "model": ""},
        }
    if name == "minilm":
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "reranker": {
                "provider": "cross-encoder",
                "model": "cross-encoder/ms-marco-MiniLM-L6-v2",
                "batch_size": 32,
            },
        }
    if name == "onefind-bge":
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": "BAAI/bge-m3",
            "embedding_max_seq_length": 512,
            "reranker": {
                "provider": "cross-encoder",
                "model": "BAAI/bge-reranker-v2-m3",
                "batch_size": 16,
            },
        }
    if name == "qwen3":
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_max_seq_length": 512,
            "reranker": {
                "provider": "cross-encoder",
                "model": "Qwen/Qwen3-Reranker-0.6B",
                "batch_size": 16,
            },
        }
    if name == "qwen3-vl":
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": "Qwen/Qwen3-VL-Embedding-2B",
            "embedding_max_seq_length": 512,
            "reranker": {
                "provider": "cross-encoder",
                "model": "Qwen/Qwen3-Reranker-0.6B",
                "batch_size": 16,
            },
        }
    if name == "qwen3-cascade":
        return {
            "embedding_provider": "sentence-transformers",
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_max_seq_length": 512,
            "reranker": {
                "provider": "cascade",
                "stages": [
                    {
                        "provider": "cross-encoder",
                        "model": "cross-encoder/ms-marco-MiniLM-L6-v2",
                        "batch_size": 32,
                        "keep_top": int(cascade_first_stage_limit),
                    },
                    {
                        "provider": "cross-encoder",
                        "model": "Qwen/Qwen3-Reranker-0.6B",
                        "batch_size": 16,
                        "keep_top": None,
                    },
                ],
            },
        }
    raise ValueError(f"Unsupported literature workflow profile: {profile_name}")


def load_workflow_questions(inline_questions: list[str] | None, questions_file: str | Path | None) -> tuple[str, ...]:
    questions: list[str] = [question.strip() for question in inline_questions or [] if question.strip()]
    if questions_file:
        path = Path(questions_file)
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                payload = json.loads(line)
                question = str(payload.get("question", "")).strip()
            else:
                question = line
            if question:
                questions.append(question)
    return tuple(questions)


def render_workflow_plan(config: LiteratureWorkflowConfig, profile: dict[str, object]) -> str:
    questions = "\n".join(f"- {question}" for question in config.questions) or "- No ask reports requested."
    return "\n".join(
        [
            "# ScanSci literature RAG workflow plan",
            "",
            f"- Library: `{config.library_dir}`",
            f"- Source format: `{config.source_format}`",
            f"- Evidence store: `{config.db_path}`",
            f"- Output directory: `{config.output_dir}`",
            f"- Profile: `{config.profile}`",
            f"- Query variants: `{config.query_variants}`",
            f"- Max follow-up queries: `{config.max_followup_queries}`",
            f"- Paper recall limit: `{config.paper_recall_limit}`",
            f"- Reindex: `{config.reindex}`",
            f"- Dry run: `{config.dry_run}`",
            "",
            "## Retrieval profile",
            "",
            "```json",
            json.dumps(profile, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Questions",
            "",
            questions,
            "",
            "## Stages",
            "",
            "1. Build or reuse the evidence SQLite store.",
            "2. Validate HTML evidence anchors when the source format is HTML.",
            "3. Write corpus coverage diagnostics.",
            "4. Export lightweight evidence-bound entity candidates.",
            "5. Generate evidence-only ask reports for supplied questions.",
            "6. Merge ask reports into a review matrix.",
            "7. Follow the paper-style evaluation plan for public benchmark comparison.",
            "8. Optionally generate a local gold-question annotation template for acceptance testing.",
            "",
        ]
    )


def render_paper_evaluation_plan(config: LiteratureWorkflowConfig) -> str:
    local_template_line = (
        "Enabled for this run: a local acceptance template will be written because "
        "`generate_gold_template` is true."
        if config.generate_gold_template
        else "Disabled for this run: local gold templates are optional acceptance artifacts, not the default validation layer."
    )
    return "\n".join(
        [
            "# ScanSci paper-style evaluation plan",
            "",
            "Public benchmarks are the default validation layer. Local gold is an optional acceptance layer for a real user library.",
            "",
            "## Default validation order",
            "",
            "1. Reproduce public evidence retrieval benchmarks: QASPER, SciFact, and BEIR-format subsets such as NFCorpus, SciDocs, TREC-COVID, or Climate-FEVER.",
            "2. Compare methods only within the same dataset, split, scope, k, question count, and candidate budget.",
            "3. Use paper-style open evaluation for synthesis work: public or paper-defined benchmarks, synthetic questions when appropriate, LLM-as-judge, human or expert spot checks, and ablations.",
            "4. Add local acceptance tests only after the public route is stable, and report them separately from public benchmark scores.",
            "",
            "## Recommended commands",
            "",
            "```powershell",
            "scansci bench-import qasper --input .\\external\\qasper\\qasper-dev-v0.3.json --output .\\bench\\gold_questions.external.qasper.jsonl",
            "scansci bench-external qasper --input .\\external\\qasper\\qasper-dev-v0.3.json --gold .\\bench\\gold_questions.external.qasper.jsonl --db .\\bench\\qasper-external-evidence.sqlite --scope gold-docs --k 20",
            "",
            "scansci bench-import scifact --claims .\\external\\scifact\\data\\claims_dev.jsonl --corpus .\\external\\scifact\\data\\corpus.jsonl --output .\\bench\\gold_questions.external.scifact.jsonl",
            "scansci bench-external scifact --corpus .\\external\\scifact\\data\\corpus.jsonl --gold .\\bench\\gold_questions.external.scifact.jsonl --db .\\bench\\scifact-external-evidence.sqlite --scope corpus --k 20",
            "",
            "scansci bench-fetch beir --dataset-name climate-fever --output-dir .\\external\\beir",
            "scansci bench-import beir --corpus .\\external\\beir\\climate-fever\\corpus.jsonl --queries .\\external\\beir\\climate-fever\\queries.jsonl --qrels .\\external\\beir\\climate-fever\\qrels\\test.tsv --dataset-name climate-fever --output .\\bench\\gold_questions.external.climate-fever.jsonl",
            "scansci bench-external beir --corpus .\\external\\beir\\climate-fever\\corpus.jsonl --gold .\\bench\\gold_questions.external.climate-fever.jsonl --db .\\bench\\climate-fever-external-evidence.sqlite --dataset-name climate-fever --scope corpus --k 20",
            "```",
            "",
            "## Local acceptance",
            "",
            local_template_line,
            "",
            "Use local gold only to answer whether the system is reliable on this specific HTML/MinerU library. Do not merge local acceptance scores into public benchmark leaderboards.",
            "",
        ]
    )


def default_extraction_schema() -> dict[str, object]:
    return {
        "name": "evidence_bound_literature_extraction",
        "description": "Every extracted field must be backed by local evidence IDs and exact quotes.",
        "record": {
            "entity": "string",
            "entity_type": "string",
            "normalized_name": "string",
            "attributes": [
                {
                    "name": "string",
                    "value": "string",
                    "unit": "string|null",
                    "evidence_ids": ["string"],
                    "quotes": ["exact source quote"],
                    "confidence": "high|medium|low",
                }
            ],
            "relations": [
                {
                    "predicate": "string",
                    "object": "string",
                    "evidence_ids": ["string"],
                    "quotes": ["exact source quote"],
                    "confidence": "high|medium|low",
                }
            ],
            "insufficient_evidence": "boolean",
        },
    }


def _build_workflow_embedding_provider(profile: dict[str, object]) -> object:
    return build_embedding_provider(
        str(profile.get("embedding_provider", "local")),
        model=str(profile.get("embedding_model", "")),
        max_seq_length=int(profile.get("embedding_max_seq_length", 0) or 0),
    )


def _build_workflow_reranker(profile: dict[str, object]) -> object:
    reranker = dict(profile.get("reranker", {}) or {})
    if str(reranker.get("provider", "local")) != "cascade":
        return build_reranker(
            str(reranker.get("provider", "local")),
            model_name=str(reranker.get("model", "")),
            batch_size=int(reranker.get("batch_size", 32) or 32),
        )
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


def _chat_client_from_config_if_needed(config: LiteratureWorkflowConfig) -> object | None:
    if "llm" not in {config.quote_provider, config.answer_provider, config.verification_provider}:
        return None
    return build_chat_json_client(
        config.chat_provider,
        base_url=config.chat_base_url,
        api_key=config.chat_api_key,
        model=config.chat_model,
        api_surface=config.chat_api_surface,
        responses_enabled=config.chat_responses_enabled,
    )


def _add_step(
    manifest: dict[str, object],
    name: str,
    status: str,
    artifacts: dict[str, object],
    metrics: dict[str, object] | None = None,
) -> None:
    steps = list(manifest.get("steps", []) or [])
    step: dict[str, object] = {
        "name": name,
        "status": status,
        "artifacts": artifacts,
    }
    if metrics is not None:
        step["metrics"] = metrics
    steps.append(step)
    manifest["steps"] = steps


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_workflow_db_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "evidence.sqlite"


def safe_report_stem(question: str, index: int) -> str:
    prefix = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:48]
    return f"question-{index:03d}-{prefix or 'report'}"
