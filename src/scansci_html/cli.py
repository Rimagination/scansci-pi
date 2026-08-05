from __future__ import annotations

import argparse
import csv
import getpass
import json
from pathlib import Path
import re
import sys

from .artifacts import ArtifactRecord, discover_artifact_records
from .bench import (
    generate_gold_question_templates,
    run_benchmark,
    run_benchmark_comparison,
    validate_gold_questions,
)
from .acceptance_workbench import build_local_acceptance_workbench
from .bench_fetch import fetch_beir_dataset
from .bench_import import (
    import_beir_rows,
    import_qasper_rows,
    import_scienceie_rows,
    import_scierc_ie_rows,
    import_scifact_rows,
)
from .bench_leaderboard import (
    build_benchmark_leaderboard,
    render_leaderboard_chart_html,
    render_leaderboard_html,
    render_leaderboard_markdown,
    write_leaderboard_csv,
)
from .bench_mistakes import generate_mistake_cases, render_mistake_cases_report, summarize_mistake_cases
from .bench_protocol import BENCHMARK_SPLITS, is_blind_benchmark_payload
from .bench_external import (
    build_beir_external_store,
    build_qasper_external_store,
    build_scifact_external_store,
    external_gold_document_ids,
    run_external_retrieval_benchmark,
)
from .browser_config import BrowserFetcherConfig, BrowserIdentityConfig
from .broker import BrokerService, enqueue_request, wait_for_response
from .browser import BrowserFetcher
from .citations import extract_reference_candidates
from .capability_doctor import doctor_capabilities
from .checkpoints import CheckpointError, CheckpointStore
from .cnki_reader import cnki_reader_counts, download_cnki_reader_images, render_cnki_reader_json
from .credentials import credential_names, credential_status, delete_credential, set_credential
from .data_availability import DataAvailabilityRecord, extract_data_availability_records
from .coverage import build_corpus_coverage
from .discovery import build_discovery_provider
from .evidence import index_html_library
from .evidence_agent import build_agent_next, build_agent_plan, build_agent_status
from .evidence_agent_runtime import LocalModelConfig, run_evidence_agent
from .evidence_doctor import check_evidence_links
from .evidence_store import export_spans_jsonl, index_evidence_library, index_markdown_library
from .embeddings import build_embedding_provider
from .annotation_layers import build_overlay_viewer_payload, write_annotation_layer
from .entity_candidates import (
    ENTITY_CANDIDATE_PROFILES,
    extract_entity_candidates_from_jsonl,
    extract_entity_candidates_from_store,
)
from .fetchers import HttpFetcher
from .grounded_annotation import ground_draft_text
from .ie_bench import evaluate_ie_entities
from .ie_model_candidates import DEFAULT_KEYPHRASE_MODEL, extract_ie_model_candidates_from_jsonl
from .ie_type_classifier import apply_text_type_classifier
from .llm import build_chat_json_client
from .literature_workflow import (
    LiteratureWorkflowConfig,
    load_workflow_questions,
    run_literature_workflow,
    safe_workflow_db_path,
)
from .models import SaveResult
from .opencli_bridge import build_opencli_bridge_diagnostics
from .official_sources import build_default_official_sources
from .qa.agent import answer_question
from .qa.verifier import (
    apply_verification_policy,
    verification_counts,
    verify_answer_claims,
    verify_answer_claims_with_llm,
)
from .references import ReferenceRecord, extract_reference_records
from .render.benchmark_details import render_benchmark_details_report
from .render.annotation_viewer import DISPLAYABLE_EVIDENCE_STATUSES, render_annotation_overlay_viewer
from .render.gold_template import render_gold_template_report
from .render.gold_validation import render_gold_validation_report
from .render.grounded_annotation import render_grounded_annotation_report
from .render.report import render_answer_report
from .retrieval import search_evidence_index, search_evidence_store
from .rerankers import build_reranker
from .review import (
    apply_review_matrix_to_annotation_layers,
    build_review_matrix,
    build_review_matrix_from_annotation_layers,
    confirmed_review_rows,
    filter_review_matrix_rows,
    read_review_matrix_rows,
    write_review_matrix,
    write_review_transformation,
)
from .service import batch_save_clean_html, save_clean_html
from .snapshots import RawHtmlSnapshotter
from .workspace import (
    add_note_to_notebook,
    attach_annotation_layers_to_notebook,
    initialize_notebook,
    list_citation_records,
    load_workspace_summary,
    sync_sources_from_evidence_store,
)


def _detect_program_name(argv0: str | None = None) -> str:
    name = Path(argv0 or sys.argv[0]).name
    stem = Path(name).stem.lower()
    if stem.startswith("scansci-html"):
        return "scansci-html"
    if stem.startswith("scansci"):
        return "scansci"
    return "scansci-html"


_LAYERED_COMMAND_ALIASES: dict[tuple[str, str], str] = {
    ("capture", "fetch"): "fetch",
    ("capture", "batch"): "batch",
    ("capture", "cnki-reader"): "cnki-reader",
    ("capture", "broker"): "broker",
    ("capture", "broker-submit"): "broker-submit",
    ("capture", "discover"): "discover",
    ("capture", "references"): "references",
    ("evidence", "index"): "index-v2",
    ("evidence", "index-jsonl"): "index",
    ("evidence", "index-md"): "index-md",
    ("evidence", "doctor"): "evidence-doctor",
    ("evidence", "coverage"): "corpus-coverage",
    ("rag", "search"): "search-v2",
    ("rag", "search-jsonl"): "search",
    ("rag", "ask"): "ask",
    ("rag", "local-ask"): "local-ask",
    ("rag", "workflow"): "workflow",
    ("rag", "verify"): "verify",
    ("annotate", "entities"): "entity-candidates",
    ("annotate", "model-entities"): "ie-model-candidates",
    ("annotate", "ie-model-candidates"): "ie-model-candidates",
    ("annotate", "classify-types"): "ie-type-classify",
    ("annotate", "types"): "ie-type-classify",
    ("annotate", "review"): "review-matrix",
    ("annotate", "review-matrix"): "review-matrix",
    ("annotate", "review-apply"): "review-apply",
    ("annotate", "apply-review"): "review-apply",
    ("annotate", "ground"): "grounded-annotate",
    ("annotate", "grounded"): "grounded-annotate",
    ("annotate", "cite"): "grounded-annotate",
    ("annotate", "viewer"): "annotation-viewer",
    ("annotate", "layers"): "annotation-viewer",
    ("bench", "run"): "bench",
    ("bench", "compare"): "bench-compare",
    ("bench", "leaderboard"): "bench-leaderboard",
    ("bench", "validate"): "bench-validate",
    ("bench", "acceptance"): "bench-acceptance",
    ("bench", "acceptance-workbench"): "bench-acceptance",
    ("bench", "template"): "bench-template",
    ("bench", "template-report"): "bench-template-report",
    ("bench", "mistakes"): "bench-mistakes",
    ("bench", "fetch"): "bench-fetch",
    ("bench", "import"): "bench-import",
    ("bench", "external"): "bench-external",
    ("bench", "ie"): "ie-bench",
    ("agent", "status"): "agent-status",
    ("agent", "next"): "agent-next",
    ("agent", "plan"): "agent-plan",
    ("agent", "run"): "agent-run",
    ("investigate", "references"): "investigate-references",
    ("investigate", "artifacts"): "investigate-artifacts",
    ("investigate", "availability"): "investigate-availability",
}

_LAYERED_COMMAND_EPILOG = """\
Layered command aliases:
  notebook init|sync-sources|add-note|attach-layer|citations|summary
  capture  fetch|batch|cnki-reader|broker|discover|references
  evidence index|index-jsonl|index-md|doctor|coverage
  rag      search|search-jsonl|ask|local-ask|workflow|verify
  annotate entities|model-entities|classify-types|review|ground|viewer|review-apply
  bench    run|compare|leaderboard|validate|acceptance|template|mistakes|fetch|import|external|ie
  agent   status|next|plan|run
  investigate references|artifacts|availability

Legacy flat commands remain supported. For example:
  scansci notebook init --workspace workspace.sqlite --title "My review"
  scansci capture fetch 10.1234/example --output-dir papers
  scansci evidence index --library-dir papers --db evidence.sqlite
  scansci rag search --db evidence.sqlite --query "method comparison"
  scansci annotate entities --db evidence.sqlite --output entity-candidates.jsonl
  scansci annotate ground --db evidence.sqlite --text "Claim to cite." --output annotation.html
  scansci annotate viewer --db evidence.sqlite --layers annotation_layers.sqlite --output viewer.html
  scansci bench run --db evidence.sqlite --gold bench/gold.jsonl
  scansci agent status --db evidence.sqlite --acceptance-dir bench/local-acceptance-workbench
  scansci agent plan --db evidence.sqlite --acceptance-dir bench/local-acceptance-workbench
  scansci agent run --db evidence.sqlite --acceptance-dir bench/local-acceptance-workbench --dry-run
  scansci investigate references --library-dir papers --output references.csv
"""


def _normalize_layered_argv(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        return None
    if len(argv) < 2:
        return list(argv)
    layer = argv[0].strip().lower()
    action = argv[1].strip().lower()
    target = _LAYERED_COMMAND_ALIASES.get((layer, action))
    if not target:
        return list(argv)
    return [target, *argv[2:]]


def _add_layered_entry_parsers(subparsers: argparse._SubParsersAction) -> None:
    for layer, help_text, actions in [
        (
            "capture",
            "Layer 1: document discovery, capture, and clean-HTML preprocessing.",
            ["fetch", "batch", "cnki-reader", "broker", "broker-submit", "discover", "references"],
        ),
        (
            "evidence",
            "Layer 2: build and validate reusable evidence stores.",
            ["index", "index-jsonl", "index-md", "doctor", "coverage"],
        ),
        (
            "rag",
            "Core layer: retrieval, rerank, evidence QA, and citation verification.",
            ["search", "search-jsonl", "ask", "local-ask", "workflow", "verify"],
        ),
        (
            "annotate",
            "Application layer: evidence-bound entity extraction and review.",
            ["entities", "model-entities", "classify-types", "review", "ground", "grounded", "cite", "viewer", "layers"],
        ),
        (
            "agent",
            "Agent layer: deterministic evidence-workbench orchestration.",
            ["status", "next", "plan", "run"],
        ),
        (
            "investigate",
            "Application layer: research data availability investigation exports.",
            ["references", "artifacts", "availability"],
        ),
    ]:
        layer_parser = subparsers.add_parser(layer, help=help_text, description=help_text)
        action_parsers = layer_parser.add_subparsers(dest=f"{layer}_command")
        for action in actions:
            target = _LAYERED_COMMAND_ALIASES[(layer, action)]
            action_parsers.add_parser(action, help=f"Alias for `{target}`.")


def build_parser(*, prog: str = "scansci-html") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Evidence-first scholarly HTML capture, retrieval, and review tooling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_LAYERED_COMMAND_EPILOG,
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_layered_entry_parsers(subparsers)
    notebook = subparsers.add_parser("notebook", help="Manage Notebook/Source/Note/Layer workspace objects.")
    notebook_subparsers = notebook.add_subparsers(dest="notebook_command", required=True)
    notebook_init = notebook_subparsers.add_parser("init", help="Create or update a notebook workspace.")
    _add_workspace_options(notebook_init)
    notebook_init.add_argument("--title", default="", help="Notebook title. Defaults to the current directory name.")
    notebook_init.add_argument("--description", default="", help="Notebook description.")
    notebook_init.add_argument("--root", default="", help="Notebook root path. Defaults to the current directory.")

    notebook_sources = notebook_subparsers.add_parser(
        "sync-sources",
        help="Register Source objects from an evidence.sqlite source_documents table.",
    )
    _add_workspace_options(notebook_sources)
    notebook_sources.add_argument("--evidence-db", required=True, help="Path to evidence.sqlite.")

    notebook_note = notebook_subparsers.add_parser("add-note", help="Register a Note object.")
    _add_workspace_options(notebook_note)
    notebook_note.add_argument("--note-id", default="", help="Stable note id. Auto-generated if omitted.")
    notebook_note.add_argument("--title", required=True, help="Note title.")
    notebook_note.add_argument(
        "--note-type",
        default="research_note",
        help="Note type, e.g. research_note, question, grounded_draft, review_draft.",
    )
    notebook_note_input = notebook_note.add_mutually_exclusive_group(required=True)
    notebook_note_input.add_argument("--text", help="Note body text.")
    notebook_note_input.add_argument("--input", "-i", help="Path to a UTF-8 note body file.")

    notebook_layer = notebook_subparsers.add_parser(
        "attach-layer",
        help="Attach annotation layer objects to a notebook, optionally linking them to a Note.",
    )
    _add_workspace_options(notebook_layer)
    notebook_layer.add_argument("--layers", required=True, help="Path to annotation_layers.sqlite.")
    notebook_layer.add_argument(
        "--layer-id",
        action="append",
        default=None,
        help="Only attach this annotation layer id. Repeatable. Defaults to all layers.",
    )
    notebook_layer.add_argument("--note-id", default="", help="Optional Note id this layer annotates.")

    notebook_citations = notebook_subparsers.add_parser(
        "citations",
        help="List evidence-bound CitationRecord objects in the workspace.",
    )
    _add_workspace_options(notebook_citations)
    notebook_citations.add_argument("--note-id", default="", help="Only list citations attached to this Note id.")
    notebook_citations.add_argument(
        "--layer-object-id",
        default="",
        help="Only list citations attached to this workspace layer object id.",
    )
    notebook_citations.add_argument(
        "--support-status",
        action="append",
        default=None,
        help="Only include this support status. Repeatable. Defaults to all stored citation records.",
    )

    notebook_summary = notebook_subparsers.add_parser("summary", help="Print Notebook/Source/Note/Layer summary.")
    _add_workspace_options(notebook_summary)

    serve = subparsers.add_parser("serve", help="Run the local ScanSci Notebook web application.")
    serve.add_argument("--workspace", default="workspace.sqlite", help="Path to the Notebook workspace SQLite store.")
    serve.add_argument("--evidence-db", default="html-papers/evidence.sqlite", help="Path to the SQLite evidence store.")
    serve.add_argument("--host", default="127.0.0.1", help="Host interface to bind. Defaults to localhost only.")
    serve.add_argument("--port", type=int, default=8765, help="Port to bind for the local Notebook web application.")
    serve.add_argument("--open", action="store_true", help="Open the local Notebook URL in the default browser.")

    desktop = subparsers.add_parser("desktop", help="Open the local ScanSci Notebook in a native desktop window.")
    desktop.add_argument("--workspace", default="workspace.sqlite", help="Path to the Notebook workspace SQLite store.")
    desktop.add_argument("--evidence-db", default="html-papers/evidence.sqlite", help="Path to the SQLite evidence store.")
    desktop.add_argument("--title", default="ScanSci", help="Desktop window title.")

    fetch = subparsers.add_parser("fetch", help="Fetch one DOI, DOI URL, or article URL.")
    fetch.add_argument("identifier", help="DOI, DOI URL, or article URL.")
    _add_fetch_options(fetch)

    batch = subparsers.add_parser("batch", help="Fetch a fixed list without substituting failures.")
    batch.add_argument("--input-file", "-i", required=True, help="Text file with one DOI or URL per line.")
    batch.add_argument("--manifest-json", default="", help="Optional path for the JSON result manifest.")
    batch.add_argument("--manifest-csv", default="", help="Optional path for the CSV result manifest.")
    _add_fetch_options(batch)

    cnki_reader = subparsers.add_parser(
        "cnki-reader",
        help="Render a captured CNKI reader xml/data JSON response as clean offline HTML.",
    )
    cnki_reader.add_argument("--input", "-i", required=True, help="Captured CNKI xml/data JSON response.")
    cnki_reader.add_argument("--output", "-o", required=True, help="Clean HTML output path.")
    cnki_reader.add_argument("--source-url", default="", help="Optional CNKI reader URL; sensitive query keys are removed.")
    cnki_reader.add_argument("--tablename", default="", help="Optional CNKI table name, e.g. cjfdlast2022.")
    cnki_reader.add_argument(
        "--include-images",
        action="store_true",
        help="Download CNKI reader figure attachments once and reference local files in the clean HTML.",
    )
    cnki_reader.add_argument(
        "--assets-dir",
        default="",
        help="Optional directory for downloaded CNKI figure assets. Defaults to OUTPUT_STEM_assets beside the HTML.",
    )
    cnki_reader.add_argument(
        "--image-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for each CNKI figure attachment request.",
    )

    broker = subparsers.add_parser("broker", help="Run a long-lived visible browser session broker.")
    broker.add_argument(
        "--broker-dir",
        default="",
        help="Directory used for broker request and response JSON files.",
    )
    broker.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between broker queue polls when idle.",
    )
    _add_fetch_options(broker)

    broker_submit = subparsers.add_parser("broker-submit", help="Submit one DOI or URL to a running broker.")
    broker_submit.add_argument("identifier", help="DOI, DOI URL, or article URL.")
    broker_submit.add_argument(
        "--broker-dir",
        required=True,
        help="Directory used by the running broker.",
    )
    broker_submit.add_argument(
        "--wait-response",
        action="store_true",
        help="Wait until the broker writes the result response.",
    )
    broker_submit.add_argument(
        "--timeout-seconds",
        type=float,
        default=900.0,
        help="Maximum wait time for --wait-response.",
    )
    index = subparsers.add_parser("index", help="Build a JSONL evidence index from an HTML library.")
    index.add_argument("--library-dir", "-l", required=True, help="Directory containing saved .html papers.")
    index.add_argument("--output", "-o", required=True, help="Path for the JSONL evidence index.")
    index.add_argument(
        "--min-text-length",
        type=int,
        default=40,
        help="Minimum block text length required before indexing an evidence block.",
    )
    index_v2 = subparsers.add_parser(
        "index-v2",
        help="Build a sentence-level SQLite evidence store from an HTML library.",
    )
    index_v2.add_argument("--library-dir", "-l", required=True, help="Directory containing saved .html papers.")
    index_v2.add_argument("--db", required=True, help="Path for the SQLite evidence store.")
    index_v2.add_argument(
        "--jsonl-output",
        default="",
        help="Optional JSONL export path for sentence-level evidence spans.",
    )
    index_v2.add_argument(
        "--inject-evidence-html",
        action="store_true",
        help="Write parallel *.evidence.html files with sentence-level anchors.",
    )
    index_v2.add_argument(
        "--min-sentence-length",
        type=int,
        default=40,
        help="Minimum sentence length required before indexing an evidence span.",
    )
    index_md = subparsers.add_parser(
        "index-md",
        help="Build a sentence-level SQLite evidence store from a Markdown library.",
    )
    index_md.add_argument("--library-dir", "-l", required=True, help="Directory containing Markdown documents.")
    index_md.add_argument("--db", required=True, help="Path for the SQLite evidence store.")
    index_md.add_argument(
        "--jsonl-output",
        default="",
        help="Optional JSONL export path for sentence-level evidence spans.",
    )
    index_md.add_argument(
        "--min-sentence-length",
        type=int,
        default=40,
        help="Minimum sentence length required before indexing an evidence span.",
    )
    evidence_doctor = subparsers.add_parser(
        "evidence-doctor",
        help="Validate evidence store links to local HTML anchors.",
    )
    evidence_doctor.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    evidence_doctor.add_argument(
        "--max-issues",
        type=int,
        default=100,
        help="Maximum number of link issues to include in JSON output.",
    )
    doctor = subparsers.add_parser("doctor", help="Run read-only Agent capability diagnostics.")
    doctor_subparsers = doctor.add_subparsers(dest="doctor_command", required=True)
    capabilities_doctor = doctor_subparsers.add_parser("capabilities", help="Inspect installed harnesses and local capabilities.")
    capabilities_doctor.add_argument("--root", default=".", help="Workspace root to inspect.")
    capabilities_doctor.add_argument("--evidence-db", default="", help="Optional evidence database path.")
    capabilities_doctor.add_argument("--live", action="store_true", help="Record an explicit live request; external processes remain opt-in.")
    capabilities_doctor.add_argument("--json", action="store_true", help="Emit JSON (the default output format).")
    checkpoint = subparsers.add_parser("checkpoint", help="Create, list, or restore local file checkpoints.")
    checkpoint_subparsers = checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_create = checkpoint_subparsers.add_parser("create", help="Snapshot files before an edit.")
    checkpoint_create.add_argument("--root", default=".", help="Workspace root.")
    checkpoint_create.add_argument("--file", action="append", default=[], help="Workspace-relative file to snapshot. Repeatable.")
    checkpoint_create.add_argument("--turn-id", default="", help="Logical turn identifier.")
    checkpoint_create.add_argument("--label", default="", help="Human-readable checkpoint label.")
    checkpoint_list = checkpoint_subparsers.add_parser("list", help="List local checkpoints.")
    checkpoint_list.add_argument("--root", default=".", help="Workspace root.")
    checkpoint_restore = checkpoint_subparsers.add_parser("restore", help="Restore a checkpoint explicitly.")
    checkpoint_restore.add_argument("--root", default=".", help="Workspace root.")
    checkpoint_restore.add_argument("--id", required=True, help="Checkpoint id.")
    checkpoint_restore.add_argument("--mode", choices=["code", "conversation", "both"], default="code")
    search = subparsers.add_parser("search", help="Search a JSONL evidence index.")
    search.add_argument("--index", "-i", required=True, help="Path to an evidence JSONL index.")
    search.add_argument("--query", "-q", required=True, help="Question or search query.")
    search.add_argument("--limit", type=int, default=5, help="Maximum number of evidence hits.")
    search_v2 = subparsers.add_parser("search-v2", help="Search a sentence-level SQLite evidence store.")
    search_v2.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    search_v2.add_argument("--query", "-q", required=True, help="Question or search query.")
    search_v2.add_argument("--limit", type=int, default=5, help="Maximum number of evidence hits.")
    search_v2.add_argument(
        "--initial-limit",
        type=int,
        default=200,
        help="Maximum number of initial retrieval candidates.",
    )
    search_v2.add_argument(
        "--paper-recall-limit",
        type=int,
        default=0,
        help="First recall this many source documents, then search evidence only inside them. 0 disables paper-level recall.",
    )
    search_v2.add_argument(
        "--per-document-limit",
        type=int,
        default=5,
        help="Maximum number of reranked hits returned per source document.",
    )
    search_v2.add_argument(
        "--trace-output",
        default="",
        help="Optional path for search trace JSON with route/candidate counts and timing.",
    )
    _add_context_mode_option(search_v2)
    search_v2.add_argument(
        "--year-min",
        type=int,
        default=0,
        help="Only return evidence from documents with publication_year >= this value.",
    )
    search_v2.add_argument(
        "--section-kind",
        action="append",
        default=None,
        choices=[
            "abstract",
            "introduction",
            "methods",
            "results",
            "discussion",
            "conclusion",
            "references",
            "other",
        ],
        help="Only return evidence from this normalized section kind. Repeatable.",
    )
    _add_provider_options(search_v2)
    ask = subparsers.add_parser("ask", help="Generate an evidence-only HTML answer report.")
    ask.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    ask.add_argument("--question", "-q", required=True, help="Research question to answer from evidence.")
    ask.add_argument("--output", "-o", required=True, help="Path for the HTML answer report.")
    ask.add_argument("--json-output", default="", help="Optional path for the structured answer JSON.")
    ask.add_argument("--limit", type=int, default=12, help="Maximum retrieval hits before quote extraction.")
    ask.add_argument("--max-quotes", type=int, default=8, help="Maximum quotes to keep in the evidence table.")
    ask.add_argument(
        "--min-quotes",
        type=int,
        default=1,
        help="Minimum validated quotes required before evidence is considered sufficient.",
    )
    ask.add_argument(
        "--min-documents",
        type=int,
        default=1,
        help="Minimum distinct source documents required before evidence is considered sufficient.",
    )
    ask.add_argument(
        "--adequacy-profile",
        default="auto",
        choices=["auto", "manual"],
        help="Evidence adequacy policy. auto raises thresholds for comparison/conflict/synthesis questions.",
    )
    _add_agentic_retrieval_options(ask)
    ask.add_argument(
        "--quote-provider",
        default="local",
        choices=["local", "llm"],
        help="Quote extraction provider.",
    )
    ask.add_argument(
        "--answer-provider",
        default="local",
        choices=["local", "llm"],
        help="Answer synthesis provider.",
    )
    ask.add_argument(
        "--verification-provider",
        default="local",
        choices=["local", "llm"],
        help="Claim verification provider.",
    )
    ask.add_argument(
        "--per-document-limit",
        type=int,
        default=5,
        help="Maximum number of reranked hits returned per source document.",
    )
    _add_context_mode_option(ask)
    _add_provider_options(ask)
    _add_chat_options(ask)
    local_ask = subparsers.add_parser(
        "local-ask",
        help="Index a local HTML library when needed, then generate an evidence-only answer report.",
    )
    local_ask.add_argument("--library-dir", "-l", required=True, help="Directory containing saved .html papers.")
    local_ask.add_argument("--db", required=True, help="SQLite evidence store path to create or reuse.")
    local_ask.add_argument("--question", "-q", required=True, help="Research question to answer from evidence.")
    local_ask.add_argument("--output", "-o", required=True, help="Path for the HTML answer report.")
    local_ask.add_argument("--json-output", default="", help="Optional path for the structured answer JSON.")
    local_ask.add_argument(
        "--reindex",
        action="store_true",
        help="Rebuild the evidence store even when --db already exists.",
    )
    local_ask.add_argument(
        "--inject-evidence-html",
        action="store_true",
        help="Write parallel *.evidence.html files with sentence-level anchors before answering.",
    )
    local_ask.add_argument(
        "--min-sentence-length",
        type=int,
        default=40,
        help="Minimum sentence length required before indexing an evidence span.",
    )
    local_ask.add_argument("--limit", type=int, default=12, help="Maximum retrieval hits before quote extraction.")
    local_ask.add_argument("--max-quotes", type=int, default=8, help="Maximum quotes to keep in the evidence table.")
    local_ask.add_argument(
        "--min-quotes",
        type=int,
        default=1,
        help="Minimum validated quotes required before evidence is considered sufficient.",
    )
    local_ask.add_argument(
        "--min-documents",
        type=int,
        default=1,
        help="Minimum distinct source documents required before evidence is considered sufficient.",
    )
    local_ask.add_argument(
        "--adequacy-profile",
        default="auto",
        choices=["auto", "manual"],
        help="Evidence adequacy policy. auto raises thresholds for comparison/conflict/synthesis questions.",
    )
    _add_agentic_retrieval_options(local_ask)
    local_ask.add_argument(
        "--quote-provider",
        default="local",
        choices=["local", "llm"],
        help="Quote extraction provider.",
    )
    local_ask.add_argument(
        "--answer-provider",
        default="local",
        choices=["local", "llm"],
        help="Answer synthesis provider.",
    )
    local_ask.add_argument(
        "--verification-provider",
        default="local",
        choices=["local", "llm"],
        help="Claim verification provider.",
    )
    local_ask.add_argument(
        "--per-document-limit",
        type=int,
        default=5,
        help="Maximum number of reranked hits returned per source document.",
    )
    _add_context_mode_option(local_ask)
    _add_provider_options(local_ask)
    _add_chat_options(local_ask)
    workflow = subparsers.add_parser(
        "workflow",
        help="Run the recommended literature RAG workflow over a local HTML or Markdown library.",
    )
    workflow.add_argument("--library-dir", "-l", required=True, help="Directory containing HTML or Markdown papers.")
    workflow.add_argument("--output-dir", "-o", required=True, help="Directory for workflow artifacts.")
    workflow.add_argument(
        "--db",
        default="",
        help="SQLite evidence store path. Defaults to <output-dir>/evidence.sqlite.",
    )
    workflow.add_argument(
        "--source-format",
        default="html",
        choices=["html", "markdown"],
        help="Input library format.",
    )
    workflow.add_argument(
        "--profile",
        default="minilm",
        choices=["local", "minilm", "onefind-bge", "qwen3", "qwen3-vl", "qwen3-cascade"],
        help="Retrieval/rerank profile. local is dependency-light; qwen3-vl swaps in Qwen3-VL-Embedding-2B; qwen3-cascade runs MiniLM then Qwen3 rerank.",
    )
    workflow.add_argument("--reindex", action="store_true", help="Rebuild the evidence store even if it exists.")
    workflow.add_argument(
        "--inject-evidence-html",
        dest="inject_evidence_html",
        action="store_true",
        default=True,
        help="Write *.evidence.html sidecars when indexing HTML sources.",
    )
    workflow.add_argument(
        "--no-inject-evidence-html",
        dest="inject_evidence_html",
        action="store_false",
        help="Do not write *.evidence.html sidecars when indexing HTML sources.",
    )
    workflow.add_argument(
        "--min-sentence-length",
        type=int,
        default=40,
        help="Minimum sentence length required before indexing an evidence span.",
    )
    workflow.add_argument(
        "--question",
        action="append",
        default=None,
        help="Research question to answer from the evidence store. Repeatable.",
    )
    workflow.add_argument(
        "--questions-file",
        default="",
        help="Optional text or JSONL file with one question per line.",
    )
    workflow.add_argument("--limit", type=int, default=20, help="Maximum retrieval hits before quote extraction.")
    workflow.add_argument("--max-quotes", type=int, default=10, help="Maximum quotes kept per answer report.")
    workflow.add_argument("--min-quotes", type=int, default=1, help="Minimum validated quotes for answer sufficiency.")
    workflow.add_argument(
        "--min-documents",
        type=int,
        default=1,
        help="Minimum distinct source documents for answer sufficiency.",
    )
    workflow.add_argument(
        "--adequacy-profile",
        default="auto",
        choices=["auto", "manual"],
        help="Evidence adequacy policy for ask reports.",
    )
    _add_agentic_retrieval_options(workflow)
    workflow.add_argument(
        "--per-document-limit",
        type=int,
        default=5,
        help="Maximum reranked hits returned per source document.",
    )
    _add_context_mode_option(workflow)
    workflow.add_argument(
        "--quote-provider",
        default="local",
        choices=["local", "llm"],
        help="Quote extraction provider.",
    )
    workflow.add_argument(
        "--answer-provider",
        default="local",
        choices=["local", "llm"],
        help="Answer synthesis provider.",
    )
    workflow.add_argument(
        "--verification-provider",
        default="local",
        choices=["local", "llm"],
        help="Claim verification provider.",
    )
    _add_chat_options(workflow)
    workflow.add_argument(
        "--cascade-first-stage-limit",
        type=int,
        default=50,
        help="For qwen3-cascade, keep this many MiniLM-ranked candidates before Qwen3 rerank.",
    )
    workflow.add_argument(
        "--generate-gold-template",
        action="store_true",
        help="Generate an optional local-acceptance gold-question template from the evidence store.",
    )
    workflow.add_argument(
        "--questions-per-type",
        type=int,
        default=5,
        help="Rows per answer_type when --generate-gold-template is enabled.",
    )
    workflow.add_argument(
        "--entity-candidates",
        dest="entity_candidates",
        action="store_true",
        default=True,
        help="Export lightweight evidence-bound entity candidates.",
    )
    workflow.add_argument(
        "--no-entity-candidates",
        dest="entity_candidates",
        action="store_false",
        help="Skip lightweight entity candidate export.",
    )
    workflow.add_argument(
        "--max-entity-candidates",
        type=int,
        default=500,
        help="Maximum entity candidates to write.",
    )
    workflow.add_argument(
        "--max-entity-source-spans",
        type=int,
        default=5000,
        help="Maximum evidence spans scanned for entity candidates; 0 scans all spans.",
    )
    workflow.add_argument(
        "--entity-candidate-profile",
        default="regex",
        choices=sorted(ENTITY_CANDIDATE_PROFILES),
        help="Entity candidate extraction profile.",
    )
    workflow.add_argument("--dry-run", action="store_true", help="Write the plan/manifest without executing stages.")
    verify = subparsers.add_parser("verify", help="Verify answer claims against a saved ask JSON report.")
    verify.add_argument("--report", required=True, help="Path to the structured ask JSON report.")
    verify.add_argument("--output", "-o", required=True, help="Path for the verified JSON report.")
    verify.add_argument(
        "--verification-provider",
        default="local",
        choices=["local", "llm"],
        help="Claim verification provider.",
    )
    _add_chat_options(verify)
    review_matrix = subparsers.add_parser(
        "review-matrix",
        help="Export ask reports or annotation layers as an evidence-bound review matrix.",
    )
    review_matrix.add_argument(
        "--report",
        action="append",
        default=None,
        help="Path to a structured ask JSON report. Repeat to merge multiple reports into one matrix.",
    )
    review_matrix.add_argument(
        "--layers",
        default="",
        help="Path to an annotation layer SQLite store. Use this to export grounded annotation evidence.",
    )
    review_matrix.add_argument(
        "--layer-id",
        action="append",
        default=None,
        help="Only include this annotation layer id. Repeatable. Defaults to all layers.",
    )
    review_matrix.add_argument("--output", "-o", required=True, help="Path for the exported matrix.")
    review_matrix.add_argument(
        "--format",
        default="csv",
        choices=["csv", "json", "html", "md"],
        help="Review matrix or transformation output format.",
    )
    review_matrix.add_argument(
        "--template",
        default="matrix",
        choices=["matrix", "glossary", "timeline", "methods", "report"],
        help="Export matrix rows directly, or transform confirmed evidence into a reusable review template.",
    )
    review_matrix.add_argument(
        "--support-status",
        action="append",
        default=None,
        help="Keep only rows with this support status. Repeatable.",
    )
    review_matrix.add_argument(
        "--question-type",
        action="append",
        default=None,
        help="Keep only rows from this planned question type. Repeatable.",
    )
    review_matrix.add_argument(
        "--section-kind",
        action="append",
        default=None,
        help="Keep only rows from this normalized section kind. Repeatable.",
    )
    review_matrix.add_argument(
        "--review-state",
        action="append",
        default=None,
        help="Keep only rows with this review state. Repeatable.",
    )
    review_matrix.add_argument(
        "--confirmed-only",
        action="store_true",
        help="Keep only confirmed/approved/verified rows before exporting.",
    )
    review_matrix.add_argument(
        "--evidence-sufficient",
        choices=["true", "false"],
        default="",
        help="Keep only rows whose ask report evidence adequacy matched this value.",
    )
    review_matrix.add_argument(
        "--columns",
        default="",
        help="Comma-separated review matrix columns to export. Defaults to all columns.",
    )
    review_apply = subparsers.add_parser(
        "review-apply",
        help="Apply reviewed matrix states back to an annotation layer SQLite store.",
    )
    review_apply.add_argument("--layers", required=True, help="Path to the annotation layer SQLite store.")
    review_apply.add_argument("--review", required=True, help="CSV or JSON matrix containing item_id and review_state.")
    review_apply.add_argument(
        "--format",
        default="",
        choices=["", "csv", "json"],
        help="Input matrix format. Defaults to the file extension.",
    )
    review_apply.add_argument(
        "--state-column",
        default="review_state",
        help="Column containing the state to write, e.g. confirmed, rejected, needs_evidence.",
    )
    grounded_annotate = subparsers.add_parser(
        "grounded-annotate",
        help="Annotate draft claims with NotebookLM-style evidence citations and review UI.",
    )
    grounded_annotate.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    grounded_input = grounded_annotate.add_mutually_exclusive_group(required=True)
    grounded_input.add_argument("--text", help="Draft text to annotate.")
    grounded_input.add_argument("--input", "-i", help="Path to a UTF-8 draft text or Markdown file.")
    grounded_annotate.add_argument("--output", "-o", default="", help="Optional path for the HTML annotation report.")
    grounded_annotate.add_argument("--json-output", default="", help="Optional path for structured annotation JSON.")
    grounded_annotate.add_argument(
        "--layer-db",
        default="",
        help="Optional SQLite annotation layer store. When set, this run is saved as a soft annotation layer.",
    )
    grounded_annotate.add_argument("--layer-id", default="", help="Stable annotation layer id. Auto-generated if omitted.")
    grounded_annotate.add_argument("--layer-name", default="", help="Human-readable annotation layer name.")
    grounded_annotate.add_argument(
        "--workspace",
        default="",
        help="Optional Notebook workspace SQLite store. Requires --layer-db and records a Note -> Layer link.",
    )
    grounded_annotate.add_argument("--notebook-id", default="default", help="Notebook id for --workspace.")
    grounded_annotate.add_argument("--note-id", default="", help="Existing Note id for --workspace. Auto-created if omitted.")
    grounded_annotate.add_argument(
        "--replace-layer",
        action="store_true",
        help="Replace an existing layer with the same --layer-id.",
    )
    grounded_annotate.add_argument("--limit", type=int, default=3, help="Maximum candidate evidence cards per segment.")
    grounded_annotate.add_argument(
        "--initial-limit",
        type=int,
        default=200,
        help="Maximum number of initial retrieval candidates per segment.",
    )
    grounded_annotate.add_argument(
        "--paper-recall-limit",
        type=int,
        default=0,
        help="First recall this many source documents per segment, then search evidence only inside them. 0 disables it.",
    )
    grounded_annotate.add_argument(
        "--per-document-limit",
        type=int,
        default=3,
        help="Maximum number of reranked hits returned per source document.",
    )
    grounded_annotate.add_argument(
        "--min-matched-terms",
        type=int,
        default=1,
        help="Minimum lexical matched terms required before a hit becomes a citation candidate.",
    )
    grounded_annotate.add_argument(
        "--min-segment-length",
        type=int,
        default=8,
        help="Skip draft segments shorter than this many characters.",
    )
    grounded_annotate.add_argument(
        "--max-segments",
        type=int,
        default=0,
        help="Maximum draft segments to annotate. 0 annotates all segments.",
    )
    grounded_annotate.add_argument(
        "--query-variants",
        type=int,
        default=4,
        help="Maximum deterministic query variants to run per draft segment.",
    )
    grounded_annotate.add_argument(
        "--candidate-pool-multiplier",
        type=int,
        default=5,
        help="Retrieve this many times --limit candidates before local claim-evidence verification.",
    )
    grounded_annotate.add_argument(
        "--max-alternatives",
        type=int,
        default=3,
        help="Keep this many non-selected alternatives per claim in diagnostics.",
    )
    _add_context_mode_option(grounded_annotate)
    _add_provider_options(grounded_annotate)
    annotation_viewer = subparsers.add_parser(
        "annotation-viewer",
        help="Render a reusable soft-annotation overlay viewer from annotation layers.",
    )
    annotation_viewer.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    annotation_viewer.add_argument("--layers", required=True, help="Path to the SQLite annotation layer store.")
    annotation_viewer.add_argument("--output", "-o", required=True, help="Path for the reusable viewer HTML.")
    annotation_viewer.add_argument(
        "--layer-id",
        action="append",
        default=None,
        help="Only include this layer id. Repeatable. Defaults to all layers.",
    )
    annotation_viewer.add_argument("--doc-id", default="", help="Optional source document id to show first.")
    annotation_viewer.add_argument("--title", default="ScanSci 软标注图层", help="Viewer HTML title.")
    bench = subparsers.add_parser("bench", help="Run a gold-evidence benchmark against the evidence store.")
    bench.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    bench.add_argument("--gold", required=True, help="Gold questions JSONL path.")
    bench.add_argument("--k", type=int, default=20, help="Retrieval cutoff for recall@k.")
    bench.add_argument(
        "--min-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when retrieval_recall_at_k is below this threshold.",
    )
    bench.add_argument(
        "--min-all-gold-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when all_gold_retrieval_recall_at_k is below this threshold.",
    )
    bench.add_argument(
        "--min-gold-evidence-recall",
        type=float,
        default=0.0,
        help="Fail when gold_evidence_recall_at_k is below this threshold.",
    )
    bench.add_argument(
        "--min-citation-f1",
        type=float,
        default=0.0,
        help="Fail when citation_f1 is below this threshold.",
    )
    bench.add_argument(
        "--min-answerable-evidence-adequacy",
        type=float,
        default=0.0,
        help="Fail when answerable_evidence_adequacy_rate is below this threshold.",
    )
    bench.add_argument(
        "--details-output",
        default="",
        help="Optional path for per-question benchmark diagnostics JSON.",
    )
    bench.add_argument(
        "--details-html-output",
        default="",
        help="Optional path for per-question benchmark diagnostics HTML.",
    )
    bench.add_argument(
        "--min-quotes",
        type=int,
        default=1,
        help="Minimum validated quotes required by the answer pipeline during benchmark runs.",
    )
    bench.add_argument(
        "--min-documents",
        type=int,
        default=1,
        help="Minimum distinct source documents required by the answer pipeline during benchmark runs.",
    )
    bench.add_argument(
        "--adequacy-profile",
        default="auto",
        choices=["auto", "manual"],
        help="Evidence adequacy policy used by the answer pipeline during benchmark runs.",
    )
    _add_benchmark_workflow_options(bench)
    _add_provider_options(bench)
    bench_compare = subparsers.add_parser(
        "bench-compare",
        help="Run multiple benchmark provider presets and compare metrics.",
    )
    bench_compare.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    bench_compare.add_argument("--gold", required=True, help="Gold questions JSONL path.")
    bench_compare.add_argument("--k", type=int, default=20, help="Retrieval cutoff for recall@k.")
    bench_compare.add_argument(
        "--presets",
        default="baseline,minilm",
        help="Comma-separated benchmark presets: baseline,minilm,qwen3-vl,bge-small.",
    )
    bench_compare.add_argument(
        "--min-quotes",
        type=int,
        default=1,
        help="Minimum validated quotes required by the answer pipeline during benchmark runs.",
    )
    bench_compare.add_argument(
        "--min-documents",
        type=int,
        default=1,
        help="Minimum distinct source documents required by the answer pipeline during benchmark runs.",
    )
    bench_compare.add_argument(
        "--adequacy-profile",
        default="auto",
        choices=["auto", "manual"],
        help="Evidence adequacy policy used by the answer pipeline during benchmark runs.",
    )
    _add_benchmark_workflow_options(bench_compare)
    bench_compare.add_argument(
        "--output",
        default="",
        help="Optional path for benchmark comparison JSON.",
    )
    bench_compare.add_argument(
        "--csv-output",
        default="",
        help="Optional path for benchmark comparison CSV table.",
    )
    bench_leaderboard = subparsers.add_parser(
        "bench-leaderboard",
        help="Build a leaderboard from benchmark details JSON files.",
    )
    bench_leaderboard.add_argument(
        "--details",
        nargs="+",
        required=True,
        help="One or more benchmark details JSON files.",
    )
    bench_leaderboard.add_argument(
        "--labels",
        default="",
        help="Optional comma-separated labels matching --details order.",
    )
    bench_leaderboard.add_argument(
        "--sort-by",
        default="gold_evidence_recall_at_k",
        help="Metric field used for ranking. Defaults to gold_evidence_recall_at_k.",
    )
    bench_leaderboard.add_argument("--output", "-o", default="", help="Optional leaderboard JSON path.")
    bench_leaderboard.add_argument("--csv-output", default="", help="Optional leaderboard CSV path.")
    bench_leaderboard.add_argument("--markdown-output", default="", help="Optional leaderboard Markdown path.")
    bench_leaderboard.add_argument("--html-output", default="", help="Optional leaderboard HTML path.")
    bench_leaderboard.add_argument("--chart-output", default="", help="Optional grouped bar chart HTML path.")
    bench_leaderboard.add_argument(
        "--chart-metric",
        default="",
        help="Metric field used for the grouped bar chart. Defaults to --sort-by.",
    )
    bench_validate = subparsers.add_parser(
        "bench-validate",
        help="Validate gold questions JSONL schema and answer-type coverage.",
    )
    bench_validate.add_argument("--gold", required=True, help="Gold questions JSONL path.")
    bench_validate.add_argument(
        "--db",
        default="",
        help="Optional SQLite evidence store used to verify gold_evidence_ids exist.",
    )
    bench_validate.add_argument(
        "--min-questions",
        type=int,
        default=0,
        help="Fail when the gold file contains fewer questions.",
    )
    bench_validate.add_argument(
        "--require-answer-types",
        default="",
        help="Comma-separated answer_type values that must appear at least once.",
    )
    bench_validate.add_argument(
        "--min-per-answer-type",
        type=int,
        default=0,
        help="Fail when any required answer_type has fewer than this many questions.",
    )
    bench_validate.add_argument(
        "--html-output",
        default="",
        help="Optional path for an HTML validation report.",
    )
    bench_acceptance = subparsers.add_parser(
        "bench-acceptance",
        help="Build a local acceptance-set review workbench from an evidence store.",
    )
    bench_acceptance.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    bench_acceptance.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated template, validation, draft, README, and manifest files.",
    )
    bench_acceptance.add_argument(
        "--questions-per-type",
        type=int,
        default=2,
        help="Maximum template rows to generate for each answer_type.",
    )
    bench_acceptance.add_argument(
        "--answer-types",
        default="",
        help="Comma-separated answer_type values to generate. Defaults to the recommended benchmark set.",
    )
    bench_acceptance.add_argument(
        "--min-questions",
        type=int,
        default=0,
        help="Validation minimum question count for the reviewed local gold file.",
    )
    bench_acceptance.add_argument(
        "--require-answer-types",
        default="",
        help="Comma-separated answer_type values required by validation.",
    )
    bench_acceptance.add_argument(
        "--min-per-answer-type",
        type=int,
        default=0,
        help="Validation minimum rows per required answer_type.",
    )
    agent_status = subparsers.add_parser(
        "agent-status",
        help="Report deterministic Evidence Agent state for the local workbench.",
    )
    _add_agent_state_options(agent_status)
    agent_next = subparsers.add_parser(
        "agent-next",
        help="Suggest deterministic next actions for the local evidence workbench.",
    )
    _add_agent_state_options(agent_next)
    agent_next.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of next actions to include.",
    )
    agent_plan = subparsers.add_parser(
        "agent-plan",
        help="Report deterministic Evidence Agent stages and action plan.",
    )
    _add_agent_state_options(agent_plan)
    agent_plan.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of plan actions to include.",
    )
    agent_run = subparsers.add_parser(
        "agent-run",
        help="Run the bounded Evidence Agent loop and write an auditable manifest.",
    )
    _add_agent_state_options(agent_run)
    agent_run.add_argument(
        "--execute",
        action="store_true",
        help="Execute safe internal actions. Defaults to dry-run when omitted.",
    )
    agent_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Record the selected action without executing it. This is the default.",
    )
    agent_run.add_argument(
        "--max-steps",
        type=int,
        default=3,
        help="Maximum observe/decide/act loop iterations.",
    )
    agent_run.add_argument(
        "--run-output",
        default="",
        help="Optional path for the run manifest JSON.",
    )
    agent_run.add_argument(
        "--control-plane",
        default="codex",
        choices=["codex", "human", "automation"],
        help="Supervisor/control-plane identity recorded in the run manifest.",
    )
    agent_run.add_argument(
        "--supervisor-note",
        default="",
        help="Optional note from the supervising control plane for audit context.",
    )
    agent_run.add_argument(
        "--autonomy-level",
        default="",
        choices=["", "L0", "L1", "L2", "L3", "L4"],
        help="Optional explicit autonomy level. Defaults to L1 for dry-run and L2 for --execute.",
    )
    agent_run.add_argument(
        "--local-model-base-url",
        default="",
        help="OpenAI-compatible local model base URL, for example http://localhost:11434/v1.",
    )
    agent_run.add_argument(
        "--local-model",
        default="",
        help="Local model name used only to choose among allowed actions.",
    )
    agent_run.add_argument(
        "--local-model-api-key-env",
        default="",
        help="Optional environment variable containing the local model API key.",
    )
    agent_run.add_argument(
        "--local-model-timeout",
        type=float,
        default=30.0,
        help="Local model request timeout in seconds.",
    )
    bench_template = subparsers.add_parser(
        "bench-template",
        help="Generate a human-annotation template JSONL from an evidence store.",
    )
    bench_template.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    bench_template.add_argument("--output", "-o", required=True, help="Path for the template JSONL file.")
    bench_template.add_argument(
        "--questions-per-type",
        type=int,
        default=2,
        help="Maximum template rows to generate for each answer_type.",
    )
    bench_template.add_argument(
        "--answer-types",
        default="",
        help="Comma-separated answer_type values to generate. Defaults to the recommended benchmark set.",
    )
    bench_template.add_argument(
        "--html-output",
        default="",
        help="Optional path for an HTML human-review report of the generated template.",
    )
    bench_template_report = subparsers.add_parser(
        "bench-template-report",
        help="Render an existing gold-question template JSONL as an HTML human-review report.",
    )
    bench_template_report.add_argument("--template", required=True, help="Gold template JSONL path.")
    bench_template_report.add_argument("--output", "-o", required=True, help="Path for the HTML review report.")
    bench_mistakes = subparsers.add_parser(
        "bench-mistakes",
        help="Convert benchmark details into structured mistake cases for the quality ledger.",
    )
    bench_mistakes.add_argument("--details", required=True, help="Benchmark details JSON path.")
    bench_mistakes.add_argument("--output", "-o", required=True, help="Output mistake cases JSONL path.")
    bench_mistakes.add_argument(
        "--gold",
        default="",
        help="Optional gold questions JSONL path used to classify float/table evidence failures.",
    )
    bench_mistakes.add_argument(
        "--html-output",
        default="",
        help="Optional HTML report path for human review.",
    )
    bench_mistakes.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Maximum mistake cases to write; 0 writes all cases.",
    )
    bench_fetch = subparsers.add_parser(
        "bench-fetch",
        help="Download and unpack public benchmark datasets into local external/ directories.",
    )
    bench_fetch_subparsers = bench_fetch.add_subparsers(dest="bench_fetch_dataset", required=True)
    bench_fetch_beir = bench_fetch_subparsers.add_parser(
        "beir",
        help="Download and unpack an official BEIR-format dataset zip.",
    )
    bench_fetch_beir.add_argument(
        "--dataset-name",
        required=True,
        help="BEIR dataset identifier, e.g. climate-fever or scifact.",
    )
    bench_fetch_beir.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the dataset zip and extracted folder will be stored.",
    )
    bench_fetch_beir.add_argument(
        "--url",
        default="",
        help="Optional explicit dataset zip URL. Defaults to the official BEIR public dataset URL pattern.",
    )
    bench_fetch_beir.add_argument(
        "--force",
        action="store_true",
        help="Download and extract again even when the dataset already appears ready.",
    )
    bench_fetch_beir.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP download timeout in seconds.",
    )
    bench_import = subparsers.add_parser(
        "bench-import",
        help="Convert public benchmark datasets into ScanSci external gold JSONL.",
    )
    bench_import_subparsers = bench_import.add_subparsers(dest="bench_import_dataset", required=True)
    bench_import_qasper = bench_import_subparsers.add_parser(
        "qasper",
        help="Convert local QASPER JSON/JSONL into gold_questions.external.qasper.jsonl.",
    )
    bench_import_qasper.add_argument("--input", required=True, help="QASPER JSON or JSONL input path.")
    bench_import_qasper.add_argument("--output", "-o", required=True, help="Output external gold JSONL path.")
    bench_import_qasper.add_argument("--limit", type=int, default=0, help="Optional maximum rows to write.")
    bench_import_scifact = bench_import_subparsers.add_parser(
        "scifact",
        help="Convert local SciFact claims/corpus JSONL into an external claim-verification benchmark.",
    )
    bench_import_scifact.add_argument("--claims", required=True, help="SciFact claims JSONL path.")
    bench_import_scifact.add_argument("--corpus", required=True, help="SciFact corpus JSONL path.")
    bench_import_scifact.add_argument("--output", "-o", required=True, help="Output external gold JSONL path.")
    bench_import_scifact.add_argument("--limit", type=int, default=0, help="Optional maximum rows to write.")
    bench_import_beir = bench_import_subparsers.add_parser(
        "beir",
        help="Convert BEIR corpus/queries/qrels files into an external document-retrieval benchmark.",
    )
    bench_import_beir.add_argument("--corpus", required=True, help="BEIR corpus.jsonl path.")
    bench_import_beir.add_argument("--queries", required=True, help="BEIR queries.jsonl path.")
    bench_import_beir.add_argument("--qrels", required=True, help="BEIR qrels TSV path.")
    bench_import_beir.add_argument(
        "--dataset-name",
        default="beir",
        help="Dataset identifier used in synthetic evidence IDs, e.g. climate-fever.",
    )
    bench_import_beir.add_argument("--output", "-o", required=True, help="Output external gold JSONL path.")
    bench_import_beir.add_argument("--limit", type=int, default=0, help="Optional maximum rows to write.")
    bench_import_beir.add_argument(
        "--max-evidence-per-query",
        type=int,
        default=0,
        help="Maximum positive documents kept per query; 0 keeps all qrels positives.",
    )
    bench_import_beir.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Benchmark split label written to imported rows.",
    )
    bench_import_scierc = bench_import_subparsers.add_parser(
        "scierc",
        help="Convert SciERC/DyGIE++ JSONL into an external information-extraction benchmark.",
    )
    bench_import_scierc.add_argument("--input", required=True, help="SciERC DyGIE++ JSON or JSONL input path.")
    bench_import_scierc.add_argument("--output", "-o", required=True, help="Output external IE gold JSONL path.")
    bench_import_scierc.add_argument("--limit", type=int, default=0, help="Optional maximum rows to write.")
    bench_import_scierc.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Benchmark split label written to imported rows.",
    )
    bench_import_scienceie = bench_import_subparsers.add_parser(
        "scienceie",
        help="Convert ScienceIE BRAT .txt/.ann files into an external information-extraction benchmark.",
    )
    bench_import_scienceie.add_argument("--input", required=True, help="ScienceIE directory or single .txt path.")
    bench_import_scienceie.add_argument("--output", "-o", required=True, help="Output external IE gold JSONL path.")
    bench_import_scienceie.add_argument("--limit", type=int, default=0, help="Optional maximum rows to write.")
    bench_import_scienceie.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Benchmark split label written to imported rows.",
    )
    bench_external = subparsers.add_parser(
        "bench-external",
        help="Build an external benchmark evidence store and score retrieval against imported gold rows.",
    )
    bench_external_subparsers = bench_external.add_subparsers(dest="bench_external_dataset", required=True)
    bench_external_qasper = bench_external_subparsers.add_parser(
        "qasper",
        help="Score retrieval on QASPER full_text plus imported highlighted evidence.",
    )
    bench_external_qasper.add_argument("--input", required=True, help="QASPER raw JSON input path.")
    bench_external_qasper.add_argument("--gold", required=True, help="Imported QASPER external gold JSONL path.")
    bench_external_qasper.add_argument("--db", required=True, help="Output SQLite evidence store path.")
    bench_external_qasper.add_argument("--k", type=int, default=20, help="Retrieval cutoff for recall@k.")
    bench_external_qasper.add_argument("--limit", type=int, default=0, help="Optional maximum gold rows to score.")
    bench_external_qasper.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Gold split to score. Blind split suppresses per-question diagnostics by default.",
    )
    bench_external_qasper.add_argument(
        "--scope",
        choices=["gold-docs", "corpus"],
        default="gold-docs",
        help="Retrieval scope. QASPER questions are paper-bound, so the default searches only gold row documents.",
    )
    bench_external_qasper.add_argument(
        "--initial-limit",
        type=int,
        default=200,
        help="Maximum FTS/BM25 candidates per query before reranking.",
    )
    bench_external_qasper.add_argument(
        "--dense-limit",
        type=int,
        default=200,
        help="Maximum dense candidates per query before reranking; 0 disables dense retrieval.",
    )
    _add_external_query_options(bench_external_qasper)
    _add_embedding_options(bench_external_qasper)
    _add_external_embedding_cache_options(bench_external_qasper)
    _add_reranker_options(bench_external_qasper)
    _add_external_benchmark_resume_options(bench_external_qasper)
    bench_external_qasper.add_argument(
        "--per-document-limit",
        type=int,
        default=0,
        help="Maximum retrieved rows per source document; 0 disables the cap.",
    )
    bench_external_qasper.add_argument(
        "--min-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when retrieval_recall_at_k is below this threshold.",
    )
    bench_external_qasper.add_argument(
        "--min-all-gold-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when all_gold_retrieval_recall_at_k is below this threshold.",
    )
    bench_external_qasper.add_argument(
        "--min-gold-evidence-recall",
        type=float,
        default=0.0,
        help="Fail when gold_evidence_recall_at_k is below this threshold.",
    )
    bench_external_qasper.add_argument(
        "--details-output",
        default="",
        help="Optional path for per-question external retrieval diagnostics JSON.",
    )
    bench_external_scifact = bench_external_subparsers.add_parser(
        "scifact",
        help="Score retrieval on the SciFact corpus against imported claim rationales.",
    )
    bench_external_scifact.add_argument("--corpus", required=True, help="SciFact corpus JSONL path.")
    bench_external_scifact.add_argument("--gold", required=True, help="Imported SciFact external gold JSONL path.")
    bench_external_scifact.add_argument("--db", required=True, help="Output SQLite evidence store path.")
    bench_external_scifact.add_argument("--k", type=int, default=20, help="Retrieval cutoff for recall@k.")
    bench_external_scifact.add_argument("--limit", type=int, default=0, help="Optional maximum gold rows to score.")
    bench_external_scifact.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Gold split to score. Blind split suppresses per-question diagnostics by default.",
    )
    bench_external_scifact.add_argument(
        "--scope",
        choices=["corpus", "gold-docs"],
        default="corpus",
        help="Retrieval scope. SciFact defaults to corpus-level claim evidence retrieval.",
    )
    bench_external_scifact.add_argument(
        "--initial-limit",
        type=int,
        default=200,
        help="Maximum FTS/BM25 candidates per query before reranking.",
    )
    bench_external_scifact.add_argument(
        "--dense-limit",
        type=int,
        default=200,
        help="Maximum dense candidates per query before reranking; 0 disables dense retrieval.",
    )
    _add_external_query_options(bench_external_scifact)
    _add_embedding_options(bench_external_scifact)
    _add_external_embedding_cache_options(bench_external_scifact)
    _add_reranker_options(bench_external_scifact)
    _add_external_benchmark_resume_options(bench_external_scifact)
    bench_external_scifact.add_argument(
        "--per-document-limit",
        type=int,
        default=0,
        help="Maximum retrieved rows per source document; 0 disables the cap.",
    )
    bench_external_scifact.add_argument(
        "--min-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when retrieval_recall_at_k is below this threshold.",
    )
    bench_external_scifact.add_argument(
        "--min-all-gold-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when all_gold_retrieval_recall_at_k is below this threshold.",
    )
    bench_external_scifact.add_argument(
        "--min-gold-evidence-recall",
        type=float,
        default=0.0,
        help="Fail when gold_evidence_recall_at_k is below this threshold.",
    )
    bench_external_scifact.add_argument(
        "--details-output",
        default="",
        help="Optional path for per-question external retrieval diagnostics JSON.",
    )
    bench_external_beir = bench_external_subparsers.add_parser(
        "beir",
        help="Score retrieval on a BEIR corpus against imported qrels-derived gold rows.",
    )
    bench_external_beir.add_argument("--corpus", required=True, help="BEIR corpus.jsonl path.")
    bench_external_beir.add_argument("--gold", required=True, help="Imported BEIR external gold JSONL path.")
    bench_external_beir.add_argument("--db", required=True, help="Output SQLite evidence store path.")
    bench_external_beir.add_argument(
        "--dataset-name",
        default="beir",
        help="Dataset identifier used in synthetic evidence IDs, e.g. climate-fever.",
    )
    bench_external_beir.add_argument("--k", type=int, default=20, help="Retrieval cutoff for recall@k.")
    bench_external_beir.add_argument("--limit", type=int, default=0, help="Optional maximum gold rows to score.")
    bench_external_beir.add_argument(
        "--benchmark-split",
        choices=BENCHMARK_SPLITS,
        default="dev",
        help="Gold split to score. Blind split suppresses per-question diagnostics by default.",
    )
    bench_external_beir.add_argument(
        "--scope",
        choices=["corpus", "gold-docs"],
        default="corpus",
        help="Retrieval scope. BEIR defaults to corpus-level document retrieval.",
    )
    bench_external_beir.add_argument(
        "--initial-limit",
        type=int,
        default=200,
        help="Maximum FTS/BM25 candidates per query before reranking.",
    )
    bench_external_beir.add_argument(
        "--dense-limit",
        type=int,
        default=200,
        help="Maximum dense candidates per query before reranking; 0 disables dense retrieval.",
    )
    _add_external_query_options(bench_external_beir)
    _add_embedding_options(bench_external_beir)
    _add_external_embedding_cache_options(bench_external_beir)
    _add_reranker_options(bench_external_beir)
    _add_external_benchmark_resume_options(bench_external_beir)
    bench_external_beir.add_argument(
        "--per-document-limit",
        type=int,
        default=0,
        help="Maximum retrieved rows per source document; 0 disables the cap.",
    )
    bench_external_beir.add_argument(
        "--min-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when retrieval_recall_at_k is below this threshold.",
    )
    bench_external_beir.add_argument(
        "--min-all-gold-retrieval-recall",
        type=float,
        default=0.0,
        help="Fail when all_gold_retrieval_recall_at_k is below this threshold.",
    )
    bench_external_beir.add_argument(
        "--min-gold-evidence-recall",
        type=float,
        default=0.0,
        help="Fail when gold_evidence_recall_at_k is below this threshold.",
    )
    bench_external_beir.add_argument(
        "--details-output",
        default="",
        help="Optional path for per-question external retrieval diagnostics JSON.",
    )
    ie_bench = subparsers.add_parser(
        "ie-bench",
        help="Score entity extraction predictions against imported SciERC/ScienceIE gold JSONL.",
    )
    ie_bench.add_argument("--gold", required=True, help="Imported IE gold JSONL path.")
    ie_bench.add_argument(
        "--predictions",
        required=True,
        help="Entity candidate JSONL path, for example output from entity extraction.",
    )
    ie_bench.add_argument("--output", "-o", default="", help="Optional metrics JSON output path.")
    entity_candidates = subparsers.add_parser(
        "entity-candidates",
        help="Export lightweight entity candidates from a SQLite evidence store or JSONL text rows.",
    )
    entity_source = entity_candidates.add_mutually_exclusive_group(required=True)
    entity_source.add_argument("--db", default="", help="SQLite evidence store path.")
    entity_source.add_argument("--input-jsonl", default="", help="JSONL rows containing a text field.")
    entity_candidates.add_argument("--output", "-o", required=True, help="Entity candidate JSONL output path.")
    entity_candidates.add_argument(
        "--profile",
        default="regex",
        choices=sorted(ENTITY_CANDIDATE_PROFILES),
        help="Entity candidate extraction profile.",
    )
    entity_candidates.add_argument("--max-candidates", type=int, default=500, help="Maximum candidates to write.")
    entity_candidates.add_argument(
        "--max-source-spans",
        type=int,
        default=5000,
        help="Maximum evidence spans scanned from --db; 0 scans all spans.",
    )
    entity_candidates.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Minimum corpus frequency required for a candidate.",
    )
    entity_candidates.add_argument(
        "--text-field",
        default="source_text",
        help="JSONL text field used with --input-jsonl.",
    )
    entity_candidates.add_argument(
        "--id-field",
        default="record_id",
        help="JSONL identifier field used with --input-jsonl.",
    )
    ie_model_candidates = subparsers.add_parser(
        "ie-model-candidates",
        help="Export model-backed IE candidates from imported benchmark JSONL text rows.",
    )
    ie_model_candidates.add_argument("--input-jsonl", required=True, help="JSONL rows containing a text field.")
    ie_model_candidates.add_argument("--output", "-o", required=True, help="Prediction JSONL output path.")
    ie_model_candidates.add_argument(
        "--model",
        default=DEFAULT_KEYPHRASE_MODEL,
        help="Hugging Face token-classification model name.",
    )
    ie_model_candidates.add_argument(
        "--cache-dir",
        default="",
        help="Optional local model cache directory, for example D:\\model\\huggingface.",
    )
    ie_model_candidates.add_argument(
        "--text-field",
        default="source_text",
        help="JSONL text field used as model input.",
    )
    ie_model_candidates.add_argument(
        "--id-field",
        default="record_id",
        help="JSONL identifier field copied to predictions.",
    )
    ie_model_candidates.add_argument("--max-rows", type=int, default=0, help="Optional maximum source rows to score.")
    ie_model_candidates.add_argument(
        "--max-candidates",
        type=int,
        default=0,
        help="Optional maximum total predicted entities to write; 0 keeps all.",
    )
    ie_model_candidates.add_argument("--batch-size", type=int, default=4, help="Model inference batch size.")
    ie_model_candidates.add_argument(
        "--device",
        default="auto",
        help="Model device: auto, cpu, cuda, or a numeric device id.",
    )
    ie_model_candidates.add_argument(
        "--aggregation-strategy",
        default="simple",
        choices=["none", "simple", "first", "average", "max"],
        help="Transformers token-classification aggregation strategy.",
    )
    ie_model_candidates.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Drop model spans below this confidence score.",
    )
    ie_model_candidates.add_argument(
        "--entity-type",
        default="Keyphrase",
        help="Entity type assigned to model keyphrase spans.",
    )
    ie_type_classify = subparsers.add_parser(
        "ie-type-classify",
        help="Assign ScienceIE/SciERC-style entity types to prediction JSONL spans using train gold text labels.",
    )
    ie_type_classify.add_argument("--train-gold", required=True, help="Imported IE train gold JSONL path.")
    ie_type_classify.add_argument("--predictions", required=True, help="Prediction JSONL with entities to type.")
    ie_type_classify.add_argument("--output", "-o", required=True, help="Typed prediction JSONL output path.")
    ie_type_classify.add_argument(
        "--classifier",
        default="char-logreg",
        choices=["char-logreg"],
        help="Text classifier used to infer entity types.",
    )
    corpus_coverage = subparsers.add_parser(
        "corpus-coverage",
        help="Summarize documents, evidence spans, sections, and block types in an evidence store.",
    )
    corpus_coverage.add_argument("--db", required=True, help="Path to the SQLite evidence store.")
    discover = subparsers.add_parser("discover", help="Discover candidate papers through public scholarly APIs.")
    discover.add_argument("--query", "-q", required=True, help="Discovery query.")
    discover.add_argument(
        "--provider",
        default="openalex",
        choices=["openalex", "crossref", "semantic-scholar", "pubmed"],
        help="External discovery provider.",
    )
    discover.add_argument("--limit", type=int, default=10, help="Maximum papers to return.")
    references = subparsers.add_parser("references", help="Extract referenced DOI candidates from one saved HTML file.")
    references.add_argument("--html", required=True, help="Saved clean HTML file to inspect.")
    investigate_references = subparsers.add_parser(
        "investigate-references",
        help="Extract structured reference records from clean HTML.",
    )
    _add_investigation_input_options(investigate_references)
    _add_investigation_output_options(investigate_references)
    investigate_artifacts = subparsers.add_parser(
        "investigate-artifacts",
        help="Discover supplementary/source-data artifact records from clean HTML.",
    )
    _add_investigation_input_options(investigate_artifacts)
    _add_investigation_output_options(investigate_artifacts)
    investigate_availability = subparsers.add_parser(
        "investigate-availability",
        help="Parse data availability statements from clean HTML.",
    )
    _add_investigation_input_options(investigate_availability)
    _add_investigation_output_options(investigate_availability)
    credentials = subparsers.add_parser("credentials", help="Manage API keys in the system keyring.")
    credential_subparsers = credentials.add_subparsers(dest="credentials_command")
    credential_subparsers.add_parser("list", help="List configured credential names and redacted status.")
    credential_set = credential_subparsers.add_parser("set", help="Store a credential in the system keyring.")
    credential_set.add_argument("name", choices=credential_names(), help="Credential name to store.")
    credential_set.add_argument(
        "--value",
        default="",
        help="Credential value. Prefer omitting this so the value is read without echo.",
    )
    credential_set.add_argument(
        "--gui",
        action="store_true",
        help="Read the credential value from a local masked GUI prompt instead of the terminal.",
    )
    credential_delete = credential_subparsers.add_parser(
        "delete", help="Remove a credential from the system keyring."
    )
    credential_delete.add_argument("name", choices=credential_names(), help="Credential name to delete.")
    opencli_doctor = subparsers.add_parser(
        "opencli-bridge-doctor",
        help="Inspect the optional OpenCLI Browser Bridge extension and daemon.",
    )
    opencli_doctor.add_argument("--browser-profile", default="", help="CloakBrowser profile to probe when requested.")
    opencli_doctor.add_argument(
        "--browser-proxy-url",
        default="",
        help="Proxy URL used only for an optional runtime probe.",
    )
    opencli_doctor.add_argument(
        "--browser-extension-dir",
        dest="browser_extension_dirs",
        action="append",
        default=None,
        help="Unpacked Chrome extension directory to inspect. Repeatable.",
    )
    opencli_doctor.add_argument(
        "--opencli-extension-dir",
        dest="browser_extension_dirs",
        action="append",
        default=None,
        help="OpenCLI Browser Bridge extension directory to inspect.",
    )
    opencli_doctor.add_argument(
        "--disable-browser-extensions",
        action="store_true",
        help="Ignore configured extension paths for this diagnostic run.",
    )
    opencli_doctor.add_argument("--runtime-probe", action="store_true", help="Launch CloakBrowser to verify extension wiring.")
    opencli_doctor.add_argument(
        "--use-browser-profile",
        action="store_true",
        help="Use --browser-profile for --runtime-probe instead of a temporary profile.",
    )
    opencli_doctor.add_argument("--timeout-seconds", type=float, default=15.0, help="Probe timeout in seconds.")
    opencli_doctor.add_argument("--keep-open", action="store_true", help="Keep the probe browser open.")
    return parser


def _add_fetch_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", "-o", default="html-papers", help="Directory for .html files.")
    parser.add_argument("--browser", action="store_true", help="Use the visible built-in browser immediately.")
    parser.add_argument(
        "--browser-profile",
        default="",
        help="Persistent built-in browser profile directory for legal institution sessions.",
    )
    parser.add_argument(
        "--browser-proxy-url",
        default="",
        help="Proxy URL used only by the built-in browser identity, not by HTTP/API fetchers.",
    )
    parser.add_argument(
        "--browser-extension-dir",
        dest="browser_extension_dirs",
        action="append",
        default=None,
        help="Unpacked Chrome extension directory to load into CloakBrowser. Repeatable.",
    )
    parser.add_argument(
        "--opencli-extension-dir",
        dest="browser_extension_dirs",
        action="append",
        default=None,
        help="OpenCLI Browser Bridge extension directory to load into CloakBrowser.",
    )
    parser.add_argument(
        "--disable-browser-extensions",
        action="store_true",
        help="Do not load configured browser extensions for this run.",
    )
    parser.add_argument(
        "--institution",
        default="",
        help="Subscription institution search text for publisher institutional login.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser mode headlessly.")
    parser.add_argument(
        "--wait-login",
        type=int,
        default=0,
        help="Seconds to keep the visible browser open for manual SSO/CAPTCHA/login before reading DOM.",
    )
    parser.add_argument(
        "--hold-on-auth",
        dest="hold_on_auth",
        action="store_true",
        default=True,
        help="Keep the visible browser open at publisher/institution access gates until full text appears.",
    )
    parser.add_argument(
        "--no-hold-on-auth",
        dest="hold_on_auth",
        action="store_false",
        help="Return auth_required/no_access instead of holding the browser at an access gate.",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="After writing results, keep the browser process alive so session login state is not lost.",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--browser-timeout-ms",
        type=int,
        default=120_000,
        help="Browser navigation timeout in milliseconds.",
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=500,
        help="Minimum cleaned article text length required before writing HTML.",
    )
    parser.add_argument(
        "--no-auth-browser",
        action="store_true",
        help="Disable automatic browser retry when HTTP preflight indicates authorization is required.",
    )
    parser.add_argument(
        "--no-official-sources",
        action="store_true",
        help="Skip official structured-source probes such as PMC/JATS before publisher capture.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="",
        help="Optional directory for raw rendered-HTML evidence snapshots written after successful clean saves.",
    )
    parser.add_argument(
        "--no-download-assets",
        action="store_true",
        help="Write clean HTML with remote image URLs instead of downloading images beside the HTML file.",
    )
    parser.add_argument(
        "--retry-incomplete-rounds",
        type=int,
        default=-1,
        help=(
            "Batch-only retry rounds for auth_required/fetch_error items in the same live browser "
            "session. Default: 1 when a browser auth path is enabled, otherwise 0."
        ),
    )


def _add_provider_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedding-provider",
        default="local",
        choices=["local", "openai-compatible", "sentence-transformers"],
        help="Embedding provider for dense retrieval.",
    )
    parser.add_argument(
        "--embedding-base-url",
        default="",
        help="OpenAI-compatible embedding API base URL; may also use SCANSCI_EMBEDDING_BASE_URL.",
    )
    parser.add_argument(
        "--embedding-api-key",
        default="",
        help="OpenAI-compatible embedding API key; may also use SCANSCI_EMBEDDING_API_KEY.",
    )
    parser.add_argument(
        "--embedding-model",
        default="",
        help="Embedding model name; may also use SCANSCI_EMBEDDING_MODEL.",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=32,
        help="Batch size for sentence-transformers embedding models.",
    )
    parser.add_argument(
        "--embedding-max-seq-length",
        type=int,
        default=0,
        help="Optional max sequence length for sentence-transformers models; 0 keeps the model default.",
    )
    parser.add_argument(
        "--reranker",
        default="local",
        choices=["local", "cross-encoder", "jina"],
        help="Reranker provider.",
    )
    parser.add_argument(
        "--reranker-model",
        default="",
        help="Reranker model name for cross-encoder or jina providers.",
    )
    parser.add_argument(
        "--reranker-batch-size",
        type=int,
        default=32,
        help="Batch size for cross-encoder reranking.",
    )


def _add_embedding_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedding-provider",
        default="local",
        choices=["local", "openai-compatible", "sentence-transformers"],
        help="Embedding provider for dense retrieval.",
    )
    parser.add_argument(
        "--embedding-base-url",
        default="",
        help="OpenAI-compatible embedding API base URL; may also use SCANSCI_EMBEDDING_BASE_URL.",
    )
    parser.add_argument(
        "--embedding-api-key",
        default="",
        help="OpenAI-compatible embedding API key; may also use SCANSCI_EMBEDDING_API_KEY.",
    )
    parser.add_argument(
        "--embedding-model",
        default="",
        help="Embedding model name; may also use SCANSCI_EMBEDDING_MODEL.",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=32,
        help="Batch size for sentence-transformers embedding models.",
    )
    parser.add_argument(
        "--embedding-max-seq-length",
        type=int,
        default=0,
        help="Optional max sequence length for sentence-transformers models; 0 keeps the model default.",
    )


def _add_context_mode_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--context-mode",
        default="sentence",
        choices=["sentence", "block"],
        help="Return matched sentence text or expand each hit to its parent HTML block context.",
    )


def _add_agentic_retrieval_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agentic-profile",
        default="balanced",
        choices=["fast", "balanced", "deep", "custom"],
        help=(
            "Controlled agentic RAG profile. fast disables slow follow-ups; balanced keeps current staged defaults; "
            "deep raises multi-query, follow-up, and paper-level recall budgets."
        ),
    )
    parser.add_argument(
        "--query-variants",
        type=int,
        default=2,
        help="Number of planned query variants to run before evidence adequacy is assessed.",
    )
    parser.add_argument(
        "--max-followup-queries",
        type=int,
        default=2,
        help="Maximum planned follow-up queries to run when evidence adequacy fails.",
    )
    parser.add_argument(
        "--paper-recall-limit",
        type=int,
        default=50,
        help="First recall this many source documents before sentence-level evidence retrieval. 0 disables it.",
    )


def _add_benchmark_workflow_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--benchmark-mode",
        default="core",
        choices=["core", "enhanced"],
        help=(
            "core keeps benchmark retrieval comparable with single-query/no-follow-up settings; "
            "enhanced enables the staged RAG workflow defaults."
        ),
    )
    parser.add_argument(
        "--query-variants",
        type=int,
        default=None,
        help="Override planned query variants for benchmark runs. Defaults: core=1, enhanced=2.",
    )
    parser.add_argument(
        "--max-followup-queries",
        type=int,
        default=None,
        help="Override benchmark follow-up search budget. Defaults: core=0, enhanced=2.",
    )
    parser.add_argument(
        "--paper-recall-limit",
        type=int,
        default=None,
        help="Override benchmark paper-level recall. Defaults: core=0, enhanced=50.",
    )


def _add_external_embedding_cache_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedding-cache-batch-size",
        type=int,
        default=512,
        help="Number of missing evidence embeddings to compute before committing the external cache.",
    )


def _add_external_query_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--query-variants",
        type=int,
        default=1,
        help=(
            "Number of deterministic query-rewrite routes to try per benchmark question. "
            "Routes are fused with RRF; 1 disables multi-query expansion."
        ),
    )


def _add_external_benchmark_resume_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reranker-cache-name",
        default="",
        help=(
            "Stable SQLite score-cache name for external benchmark reranking. "
            "Defaults to the cross-encoder provider/model when --reranker cross-encoder."
        ),
    )
    parser.add_argument(
        "--checkpoint",
        default="",
        help="Optional JSONL checkpoint path; matching completed questions are reused and new rows are appended.",
    )


def _add_reranker_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reranker",
        default="local",
        choices=["local", "cross-encoder", "jina"],
        help="Reranker provider.",
    )
    parser.add_argument(
        "--reranker-model",
        default="",
        help="Reranker model name for cross-encoder or jina providers.",
    )
    parser.add_argument(
        "--reranker-batch-size",
        type=int,
        default=32,
        help="Batch size for cross-encoder reranking.",
    )


def _add_chat_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--chat-provider",
        default="openai-compatible",
        choices=["openai-compatible"],
        help="Chat JSON provider used when any LLM-backed step is selected.",
    )
    parser.add_argument(
        "--chat-base-url",
        default="",
        help="OpenAI-compatible chat API base URL; may also use SCANSCI_CHAT_BASE_URL.",
    )
    parser.add_argument(
        "--chat-api-key",
        default="",
        help="OpenAI-compatible chat API key; may also use SCANSCI_CHAT_API_KEY.",
    )
    parser.add_argument(
        "--chat-model",
        default="",
        help="OpenAI-compatible chat model; may also use SCANSCI_CHAT_MODEL.",
    )
    parser.add_argument(
        "--chat-api-surface",
        default="chat_completions",
        choices=["chat_completions", "responses", "auto"],
        help="Explicit model API surface; Responses requires provider support or --chat-responses-enabled.",
    )
    parser.add_argument(
        "--chat-responses-enabled",
        action="store_true",
        help="Declare that the configured OpenAI-compatible endpoint supports /responses.",
    )


def _add_workspace_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        default="workspace.sqlite",
        help="Path to the Notebook/Source/Note/Layer workspace SQLite store.",
    )
    parser.add_argument(
        "--notebook-id",
        default="default",
        help="Notebook id inside the workspace.",
    )


def _add_investigation_input_options(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", default="", help="Single clean HTML file to inspect.")
    source.add_argument("--library-dir", default="", help="Directory of clean HTML files to inspect recursively.")


def _add_investigation_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", required=True, help="CSV output path.")
    parser.add_argument("--jsonl-output", default="", help="Optional JSONL output path.")


def _add_agent_state_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        default="html-papers/evidence.sqlite",
        help="Path to the SQLite evidence store.",
    )
    parser.add_argument(
        "--acceptance-dir",
        default="bench/local-acceptance-workbench",
        help="Path to the local acceptance workbench directory.",
    )
    parser.add_argument(
        "--workspace",
        default="workspace.sqlite",
        help="Path to the Notebook/Source/Note/Layer workspace SQLite store.",
    )
    parser.add_argument(
        "--annotation-layers",
        default="annotation_layers.sqlite",
        help="Path to the annotation layer SQLite store.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog=_detect_program_name())
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_normalize_layered_argv(raw_argv))
    if args.command not in {
        "notebook",
        "serve",
        "desktop",
        "fetch",
        "batch",
        "cnki-reader",
        "broker",
        "broker-submit",
        "index",
        "index-v2",
        "index-md",
        "evidence-doctor",
        "doctor",
        "checkpoint",
        "search",
        "search-v2",
        "ask",
        "local-ask",
        "workflow",
        "verify",
        "review-matrix",
        "review-apply",
        "grounded-annotate",
        "annotation-viewer",
        "bench",
        "bench-compare",
        "bench-leaderboard",
        "bench-validate",
        "bench-acceptance",
        "agent-status",
        "agent-next",
        "agent-plan",
        "agent-run",
        "bench-template",
        "bench-template-report",
        "bench-mistakes",
        "bench-fetch",
        "bench-import",
        "bench-external",
        "ie-bench",
        "entity-candidates",
        "ie-model-candidates",
        "ie-type-classify",
        "corpus-coverage",
        "discover",
        "references",
        "investigate-references",
        "investigate-artifacts",
        "investigate-availability",
        "credentials",
        "opencli-bridge-doctor",
    }:
        parser.print_help()
        return 2

    if args.command == "serve":
        from .webapp import serve_notebook

        serve_notebook(
            workspace=args.workspace,
            evidence_db=args.evidence_db,
            host=args.host,
            port=args.port,
            open_browser=args.open,
        )
        return 0

    if args.command == "desktop":
        from .desktop import launch_desktop

        launch_desktop(
            workspace=args.workspace,
            evidence_db=args.evidence_db,
            title=args.title,
        )
        return 0

    if args.command == "opencli-bridge-doctor":
        return _run_opencli_bridge_doctor(args)

    if args.command == "doctor":
        if args.doctor_command == "capabilities":
            payload = doctor_capabilities(
                Path(args.root),
                evidence_db=Path(args.evidence_db) if args.evidence_db else None,
                live=bool(args.live),
            )
            _emit_json(payload)
            return 0 if payload.get("status") != "failed" else 1
        parser.print_help()
        return 2

    if args.command == "checkpoint":
        store = CheckpointStore(Path(args.root))
        try:
            if args.checkpoint_command == "create":
                checkpoint = store.begin(turn_id=args.turn_id, label=args.label)
                checkpoint = store.capture_many(checkpoint.checkpoint_id, [Path(path) for path in args.file]) if args.file else checkpoint
                _emit_json(checkpoint.to_dict())
                return 0
            if args.checkpoint_command == "list":
                _emit_json({"checkpoints": [item.to_dict() for item in store.list()]})
                return 0
            if args.checkpoint_command == "restore":
                _emit_json(store.restore(args.id, mode=args.mode))
                return 0
        except (CheckpointError, OSError, ValueError) as error:
            _emit_json({"status": "error", "error": str(error)})
            return 1
        parser.print_help()
        return 2

    if args.command == "credentials":
        return _run_credentials(args)

    if args.command == "agent-status":
        payload = build_agent_status(
            Path(args.db),
            acceptance_dir=Path(args.acceptance_dir),
            workspace_path=Path(args.workspace),
            annotation_layers_path=Path(args.annotation_layers),
        )
        _emit_json(payload)
        return 0

    if args.command == "agent-next":
        payload = build_agent_next(
            Path(args.db),
            acceptance_dir=Path(args.acceptance_dir),
            workspace_path=Path(args.workspace),
            annotation_layers_path=Path(args.annotation_layers),
            limit=args.limit,
        )
        _emit_json(payload)
        return 0

    if args.command == "agent-plan":
        payload = build_agent_plan(
            Path(args.db),
            acceptance_dir=Path(args.acceptance_dir),
            workspace_path=Path(args.workspace),
            annotation_layers_path=Path(args.annotation_layers),
            limit=args.limit,
        )
        _emit_json(payload)
        return 0

    if args.command == "agent-run":
        payload = run_evidence_agent(
            Path(args.db),
            acceptance_dir=Path(args.acceptance_dir),
            workspace_path=Path(args.workspace),
            annotation_layers_path=Path(args.annotation_layers),
            dry_run=not bool(args.execute),
            max_steps=args.max_steps,
            run_output=Path(args.run_output) if args.run_output else None,
            model_config=LocalModelConfig(
                base_url=args.local_model_base_url,
                model=args.local_model,
                api_key_env=args.local_model_api_key_env,
                timeout_seconds=args.local_model_timeout,
            ),
            control_plane=args.control_plane,
            supervisor_note=args.supervisor_note,
            autonomy_level=args.autonomy_level,
        )
        _emit_json(payload)
        return 0 if payload.get("status") not in {"failed"} else 1

    if args.command == "notebook":
        if args.notebook_command == "init":
            payload = initialize_notebook(
                Path(args.workspace),
                notebook_id=args.notebook_id,
                title=args.title,
                description=args.description,
                root_path=Path(args.root) if args.root else Path.cwd(),
            )
            _emit_json(payload)
            return 0
        if args.notebook_command == "sync-sources":
            payload = sync_sources_from_evidence_store(
                Path(args.workspace),
                Path(args.evidence_db),
                notebook_id=args.notebook_id,
            )
            _emit_json(payload)
            return 0
        if args.notebook_command == "add-note":
            input_path = Path(args.input) if args.input else None
            body = input_path.read_text(encoding="utf-8") if input_path else str(args.text or "")
            payload = add_note_to_notebook(
                Path(args.workspace),
                notebook_id=args.notebook_id,
                note_id=args.note_id,
                title=args.title,
                body=body,
                note_type=args.note_type,
                source_path=input_path or "",
            )
            _emit_json(payload)
            return 0
        if args.notebook_command == "attach-layer":
            payload = attach_annotation_layers_to_notebook(
                Path(args.workspace),
                Path(args.layers),
                notebook_id=args.notebook_id,
                layer_ids=[str(value) for value in args.layer_id] if args.layer_id else None,
                note_id=args.note_id,
            )
            _emit_json(payload)
            return 0
        if args.notebook_command == "citations":
            citations = list_citation_records(
                Path(args.workspace),
                notebook_id=args.notebook_id,
                note_id=args.note_id,
                layer_object_id=args.layer_object_id,
                support_statuses=[str(value) for value in args.support_status] if args.support_status else None,
            )
            _emit_json(
                {
                    "workspace_path": str(Path(args.workspace)),
                    "notebook_id": args.notebook_id,
                    "count": len(citations),
                    "citations": citations,
                }
            )
            return 0
        if args.notebook_command == "summary":
            _emit_json(load_workspace_summary(Path(args.workspace), notebook_id=args.notebook_id))
            return 0

    if args.command == "broker":
        return _run_broker(args)

    if args.command == "broker-submit":
        return _submit_broker_request(args)

    if args.command == "cnki-reader":
        input_path = Path(args.input)
        output_path = Path(args.output)
        payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
        image_assets: dict[str, str] = {}
        image_warnings: list[str] = []
        if args.include_images:
            image_assets, image_warnings = download_cnki_reader_images(
                payload,
                output_path=output_path,
                assets_dir=Path(args.assets_dir) if args.assets_dir else None,
                source_url=args.source_url,
                timeout=args.image_timeout,
            )
        document = render_cnki_reader_json(
            payload,
            source_url=args.source_url,
            tablename=args.tablename,
            image_assets=image_assets,
        )
        _write_text(output_path, document.html)
        _emit_json(
            {
                "status": "success",
                "input_path": str(input_path),
                "output_path": str(output_path),
                "title": document.title,
                "source_url": document.source_url,
                "warnings": [*document.warnings, *image_warnings],
                "image_assets": len(image_assets),
                "counts": cnki_reader_counts(payload),
            }
        )
        return 0

    if args.command == "index":
        summary = index_html_library(
            Path(args.library_dir),
            output_path=Path(args.output),
            min_text_length=args.min_text_length,
        )
        _emit_json(summary)
        return 0

    if args.command == "index-v2":
        summary = index_evidence_library(
            Path(args.library_dir),
            db_path=Path(args.db),
            inject_evidence_html=args.inject_evidence_html,
            min_sentence_length=args.min_sentence_length,
        )
        if args.jsonl_output:
            export_summary = export_spans_jsonl(Path(args.db), Path(args.jsonl_output))
            summary["jsonl_output_path"] = export_summary["output_path"]
        _emit_json(summary)
        return 0

    if args.command == "index-md":
        summary = index_markdown_library(
            Path(args.library_dir),
            db_path=Path(args.db),
            min_sentence_length=args.min_sentence_length,
        )
        if args.jsonl_output:
            export_summary = export_spans_jsonl(Path(args.db), Path(args.jsonl_output))
            summary["jsonl_output_path"] = export_summary["output_path"]
        _emit_json(summary)
        return 0

    if args.command == "evidence-doctor":
        payload = check_evidence_links(Path(args.db), max_issues=args.max_issues)
        _emit_json(payload)
        return 0 if payload.get("passed") else 1

    if args.command == "search":
        hits = search_evidence_index(
            Path(args.index),
            args.query,
            limit=args.limit,
        )
        _emit_json(
            {
                "query": args.query,
                "hits": hits,
            }
        )
        return 0

    if args.command == "search-v2":
        trace: list[dict[str, object]] = []
        search_kwargs = {
            "limit": args.limit,
            "initial_limit": args.initial_limit,
            "per_document_limit": args.per_document_limit,
            "filters": _search_filters_from_args(args),
            "embedding_provider": _embedding_provider_from_args(args),
            "reranker": _reranker_from_args(args),
            "context_mode": args.context_mode,
        }
        if args.paper_recall_limit > 0:
            search_kwargs["paper_recall_limit"] = args.paper_recall_limit
        if args.trace_output:
            search_kwargs["trace"] = trace
        hits = search_evidence_store(Path(args.db), args.query, **search_kwargs)
        if args.trace_output:
            _write_json(
                Path(args.trace_output),
                {
                    "query": args.query,
                    "hits": hits,
                    "trace": trace,
                },
            )
        payload = {
            "query": args.query,
            "hits": hits,
        }
        if args.trace_output:
            payload["trace_output_path"] = str(Path(args.trace_output))
        _emit_json(payload)
        return 0

    if args.command == "ask":
        _emit_json(_run_answer_report(args, Path(args.db)))
        return 0

    if args.command == "local-ask":
        db_path = Path(args.db)
        indexed = bool(args.reindex) or not db_path.exists()
        index_summary: dict[str, object] = {}
        if indexed:
            index_summary = index_evidence_library(
                Path(args.library_dir),
                db_path=db_path,
                inject_evidence_html=args.inject_evidence_html,
                min_sentence_length=args.min_sentence_length,
            )
        payload = _run_answer_report(
            args,
            db_path,
            extra_payload={
                "indexed": indexed,
                "index": index_summary,
                "library_dir": str(Path(args.library_dir)),
                "db_path": str(db_path),
            },
        )
        _emit_json(payload)
        return 0

    if args.command == "workflow":
        _emit_json(_run_literature_workflow(args))
        return 0

    if args.command == "verify":
        report_path = Path(args.report)
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        answer_payload = dict(report_payload.get("answer", {}) or {})
        evidence_table = list(report_payload.get("evidence_table", []) or [])
        if args.verification_provider == "llm":
            verified_answer = verify_answer_claims_with_llm(
                answer_payload,
                evidence_table,
                chat_client=_chat_client_from_args(args),
            )
        else:
            verified_answer = verify_answer_claims(answer_payload, evidence_table)
        verified_answer = apply_verification_policy(verified_answer)
        verified_payload = dict(report_payload)
        verified_payload["answer"] = verified_answer
        output_path = Path(args.output)
        _write_json(output_path, verified_payload)
        summary = verification_counts(verified_answer)
        summary["output_path"] = str(output_path)
        _emit_json(summary)
        return 0

    if args.command == "review-matrix":
        report_paths = [Path(report) for report in (args.report or [])]
        if not report_paths and not args.layers:
            _emit_json({"error": "review-matrix requires at least one --report or --layers"})
            return 2
        rows: list[dict[str, object]] = []
        for report_path in report_paths:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            rows.extend(build_review_matrix(report_payload))
        if args.layers:
            rows.extend(
                build_review_matrix_from_annotation_layers(
                    Path(args.layers),
                    layer_ids=[str(value) for value in args.layer_id] if args.layer_id else None,
                    support_statuses=args.support_status,
                    review_states=args.review_state,
                    confirmed_only=args.confirmed_only,
                )
            )
        input_row_count = len(rows)
        rows = filter_review_matrix_rows(
            rows,
            support_statuses=args.support_status,
            question_types=args.question_type,
            section_kinds=args.section_kind,
            review_states=args.review_state,
            evidence_sufficient=_optional_bool_filter(args.evidence_sufficient),
        )
        if args.confirmed_only:
            rows = confirmed_review_rows(rows)
        columns = _comma_separated_values(args.columns) if args.columns else None
        output_path = Path(args.output)
        output_format = args.format
        if args.template == "matrix":
            if output_format == "md":
                _emit_json({"error": "matrix template supports csv, json, or html; use a transformation template for md"})
                return 2
            write_review_matrix(rows, output_path, output_format=output_format, fields=columns)
            output_row_count = len(rows)
        else:
            if columns:
                _emit_json({"error": "--columns is only supported with --template matrix"})
                return 2
            if output_format == "csv":
                output_format = "md"
            output_row_count = len(confirmed_review_rows(rows))
            write_review_transformation(rows, output_path, template=args.template, output_format=output_format)
        payload: dict[str, object] = {
            "reports": len(report_paths),
            "rows": output_row_count,
            "output_path": str(output_path),
            "format": output_format,
        }
        if args.layers:
            payload["layer_db_path"] = str(Path(args.layers))
        if args.template != "matrix":
            payload["template"] = args.template
        if input_row_count != len(rows):
            payload["input_rows"] = input_row_count
        if args.template != "matrix" and len(rows) != output_row_count:
            payload["matrix_rows"] = len(rows)
        if columns:
            payload["columns"] = columns
        _emit_json(payload)
        return 0

    if args.command == "review-apply":
        review_rows = read_review_matrix_rows(Path(args.review), input_format=args.format)
        summary = apply_review_matrix_to_annotation_layers(
            Path(args.layers),
            review_rows,
            state_column=args.state_column,
        )
        summary["layer_db_path"] = str(Path(args.layers))
        summary["review_path"] = str(Path(args.review))
        _emit_json(summary)
        return 0

    if args.command == "grounded-annotate":
        if not args.output and not args.json_output and not args.layer_db:
            _emit_json(
                {
                    "error": "grounded-annotate requires at least one of --output, --json-output, or --layer-db",
                }
            )
            return 2
        if args.workspace and not args.layer_db:
            _emit_json({"error": "grounded-annotate --workspace requires --layer-db"})
            return 2
        draft_text = _grounded_annotation_text_from_args(args)
        annotation_payload = ground_draft_text(
            Path(args.db),
            draft_text,
            limit=args.limit,
            initial_limit=args.initial_limit,
            paper_recall_limit=args.paper_recall_limit,
            per_document_limit=args.per_document_limit,
            context_mode=args.context_mode,
            min_segment_length=args.min_segment_length,
            max_segments=args.max_segments,
            min_matched_terms=args.min_matched_terms,
            query_variants=args.query_variants,
            candidate_pool_multiplier=args.candidate_pool_multiplier,
            max_alternatives=args.max_alternatives,
            embedding_provider=_embedding_provider_from_args(args),
            reranker=_reranker_from_args(args),
        )
        output_path = Path(args.output) if args.output else None
        if output_path:
            _write_text(output_path, render_grounded_annotation_report(annotation_payload, output_path=output_path))
        json_output_path = ""
        if args.json_output:
            json_path = Path(args.json_output)
            _write_json(json_path, annotation_payload)
            json_output_path = str(json_path)
        layer_summary: dict[str, object] = {}
        if args.layer_db:
            try:
                layer_summary = write_annotation_layer(
                    Path(args.layer_db),
                    annotation_payload,
                    layer_id=args.layer_id,
                    name=args.layer_name,
                    question=draft_text,
                    replace=args.replace_layer,
                )
            except ValueError as error:
                _emit_json({"error": str(error), "layer_db_path": str(Path(args.layer_db))})
                return 2
        summary = dict(annotation_payload.get("summary", {}) or {})
        summary["output_path"] = str(output_path) if output_path else ""
        summary["json_output_path"] = json_output_path
        if layer_summary:
            summary["layer"] = layer_summary
        if args.workspace and layer_summary:
            note_summary = (
                {"note_id": args.note_id, "created": False}
                if args.note_id
                else add_note_to_notebook(
                    Path(args.workspace),
                    notebook_id=args.notebook_id,
                    title=args.layer_name or _short_title_from_text(draft_text),
                    body=draft_text,
                    note_type="grounded_draft",
                )
            )
            attach_summary = attach_annotation_layers_to_notebook(
                Path(args.workspace),
                Path(args.layer_db),
                notebook_id=args.notebook_id,
                layer_ids=[str(layer_summary["layer_id"])],
                note_id=str(note_summary.get("note_id", "") or ""),
            )
            summary["workspace"] = {
                "workspace_path": str(Path(args.workspace)),
                "notebook_id": args.notebook_id,
                "note": note_summary,
                "attached_layers": attach_summary,
            }
        _emit_json(summary)
        return 0

    if args.command == "annotation-viewer":
        output_path = Path(args.output)
        viewer_payload = build_overlay_viewer_payload(
            Path(args.db),
            Path(args.layers),
            layer_ids=[str(value) for value in args.layer_id] if args.layer_id else None,
            doc_id=args.doc_id,
        )
        _write_text(
            output_path,
            render_annotation_overlay_viewer(
                viewer_payload,
                output_path=output_path,
                title=args.title,
            ),
        )
        summary = dict(viewer_payload.get("summary", {}) or {})
        summary["items"] = _count_displayable_layer_items(viewer_payload)
        summary["output_path"] = str(output_path)
        summary["layer_db_path"] = str(Path(args.layers))
        _emit_json(summary)
        return 0

    if args.command == "bench":
        metrics = run_benchmark(
            Path(args.db),
            Path(args.gold),
            k=args.k,
            include_details=bool(args.details_output or args.details_html_output),
            min_quotes=args.min_quotes,
            min_documents=args.min_documents,
            adequacy_profile=args.adequacy_profile,
            embedding_provider=_embedding_provider_from_args(args),
            reranker=_reranker_from_args(args),
            benchmark_mode=args.benchmark_mode,
            query_variants=args.query_variants,
            max_followup_queries=args.max_followup_queries,
            paper_recall_limit=args.paper_recall_limit,
        )
        question_results = list(metrics.pop("question_results", []) or [])
        gate_failures = _benchmark_gate_failures(
            metrics,
            min_retrieval_recall=args.min_retrieval_recall,
            min_all_gold_retrieval_recall=args.min_all_gold_retrieval_recall,
            min_gold_evidence_recall=args.min_gold_evidence_recall,
            min_citation_f1=args.min_citation_f1,
            min_answerable_evidence_adequacy=args.min_answerable_evidence_adequacy,
        )
        payload = dict(metrics)
        payload["passed"] = not gate_failures
        payload["gate_failures"] = gate_failures
        payload["details_output_path"] = str(Path(args.details_output)) if args.details_output else ""
        payload["details_html_output_path"] = (
            str(Path(args.details_html_output)) if args.details_html_output else ""
        )
        if args.details_output:
            _write_json(
                Path(args.details_output),
                {
                    "metrics": payload,
                    "questions": question_results,
                },
            )
        if args.details_html_output:
            _write_text(
                Path(args.details_html_output),
                render_benchmark_details_report(payload, question_results),
            )
        _emit_json(payload)
        return 1 if gate_failures else 0

    if args.command == "bench-compare":
        payload = run_benchmark_comparison(
            Path(args.db),
            Path(args.gold),
            presets=_comma_separated_values(args.presets),
            k=args.k,
            min_quotes=args.min_quotes,
            min_documents=args.min_documents,
            adequacy_profile=args.adequacy_profile,
            benchmark_mode=args.benchmark_mode,
            query_variants=args.query_variants,
            max_followup_queries=args.max_followup_queries,
            paper_recall_limit=args.paper_recall_limit,
        )
        payload["output_path"] = str(Path(args.output)) if args.output else ""
        payload["csv_output_path"] = str(Path(args.csv_output)) if args.csv_output else ""
        if args.output:
            _write_json(Path(args.output), payload)
        if args.csv_output:
            _write_benchmark_comparison_csv(Path(args.csv_output), list(payload.get("rows", []) or []))
        _emit_json(payload)
        return 0

    if args.command == "bench-leaderboard":
        payload = build_benchmark_leaderboard(
            [Path(path) for path in args.details],
            labels=_comma_separated_values(args.labels),
            sort_by=args.sort_by,
        )
        payload["output_path"] = str(Path(args.output)) if args.output else ""
        payload["csv_output_path"] = str(Path(args.csv_output)) if args.csv_output else ""
        payload["markdown_output_path"] = str(Path(args.markdown_output)) if args.markdown_output else ""
        payload["html_output_path"] = str(Path(args.html_output)) if args.html_output else ""
        payload["chart_output_path"] = str(Path(args.chart_output)) if args.chart_output else ""
        if args.output:
            _write_json(Path(args.output), payload)
        if args.csv_output:
            write_leaderboard_csv(Path(args.csv_output), list(payload.get("rows", []) or []))
        if args.markdown_output:
            _write_text(Path(args.markdown_output), render_leaderboard_markdown(payload))
        if args.html_output:
            _write_text(Path(args.html_output), render_leaderboard_html(payload))
        if args.chart_output:
            _write_text(
                Path(args.chart_output),
                render_leaderboard_chart_html(payload, metric=args.chart_metric or args.sort_by),
            )
        _emit_json(payload)
        return 0

    if args.command == "bench-validate":
        payload = validate_gold_questions(
            Path(args.gold),
            min_questions=args.min_questions,
            required_answer_types=_comma_separated_values(args.require_answer_types),
            min_per_answer_type=args.min_per_answer_type,
            db_path=Path(args.db) if args.db else None,
        )
        payload["html_output_path"] = args.html_output or ""
        if args.html_output:
            _write_text(Path(args.html_output), render_gold_validation_report(payload))
        _emit_json(payload)
        return 0 if payload.get("passed") else 1

    if args.command == "bench-acceptance":
        payload = build_local_acceptance_workbench(
            Path(args.db),
            Path(args.output_dir),
            questions_per_type=args.questions_per_type,
            answer_types=_comma_separated_values(args.answer_types) or None,
            min_questions=args.min_questions,
            required_answer_types=_comma_separated_values(args.require_answer_types),
            min_per_answer_type=args.min_per_answer_type,
        )
        _emit_json(payload)
        return 0

    if args.command == "bench-template":
        payload = generate_gold_question_templates(
            Path(args.db),
            questions_per_type=args.questions_per_type,
            answer_types=_comma_separated_values(args.answer_types) or None,
        )
        output_path = Path(args.output)
        template_rows = list(payload.get("templates", []) or [])
        _write_jsonl(output_path, template_rows)
        html_output_path = ""
        if args.html_output:
            html_path = Path(args.html_output)
            _write_text(html_path, render_gold_template_report(template_rows))
            html_output_path = str(html_path)
        summary = dict(payload)
        summary.pop("templates", None)
        summary["output_path"] = str(output_path)
        summary["html_output_path"] = html_output_path
        _emit_json(summary)
        return 0

    if args.command == "bench-template-report":
        rows = _read_jsonl(Path(args.template))
        output_path = Path(args.output)
        _write_text(output_path, render_gold_template_report(rows))
        _emit_json({"rows": len(rows), "output_path": str(output_path)})
        return 0

    if args.command == "bench-mistakes":
        details_path = Path(args.details)
        output_path = Path(args.output)
        details = json.loads(details_path.read_text(encoding="utf-8"))
        if is_blind_benchmark_payload(details):
            _emit_json(
                {
                    "error": "blind_benchmark_details_are_not_for_mistake_analysis",
                    "details_path": str(details_path),
                }
            )
            return 2
        gold_rows = _read_jsonl(Path(args.gold)) if args.gold else []
        cases = generate_mistake_cases(
            details,
            gold_rows=gold_rows,
            details_path=details_path,
            gold_path=Path(args.gold) if args.gold else "",
            max_cases=args.max_cases,
        )
        summary = summarize_mistake_cases(cases)
        _write_jsonl(output_path, cases)
        html_output_path = ""
        if args.html_output:
            html_output = Path(args.html_output)
            _write_text(html_output, render_mistake_cases_report(cases))
            html_output_path = str(html_output)
        _emit_json(
            {
                "cases": len(cases),
                "summary": summary,
                "output_path": str(output_path),
                "html_output_path": html_output_path,
            }
        )
        return 0

    if args.command == "bench-fetch":
        if args.bench_fetch_dataset == "beir":
            payload = fetch_beir_dataset(
                args.dataset_name,
                Path(args.output_dir),
                url=args.url,
                force=args.force,
                timeout=args.timeout,
            )
        else:  # pragma: no cover - argparse enforces known subcommands
            raise SystemExit(f"unsupported bench-fetch dataset: {args.bench_fetch_dataset}")
        _emit_json(payload)
        return 0 if bool(payload.get("ready", False)) else 1

    if args.command == "bench-import":
        output_path = Path(args.output)
        if args.bench_import_dataset == "qasper":
            rows = import_qasper_rows(Path(args.input), limit=args.limit)
            dataset_label = args.bench_import_dataset
        elif args.bench_import_dataset == "scifact":
            rows = import_scifact_rows(Path(args.claims), Path(args.corpus), limit=args.limit)
            dataset_label = args.bench_import_dataset
        elif args.bench_import_dataset == "beir":
            rows = import_beir_rows(
                Path(args.corpus),
                Path(args.queries),
                Path(args.qrels),
                dataset=args.dataset_name,
                limit=args.limit,
                max_evidence_per_query=args.max_evidence_per_query,
                benchmark_split=args.benchmark_split,
            )
            dataset_label = args.dataset_name
        elif args.bench_import_dataset == "scierc":
            rows = import_scierc_ie_rows(
                Path(args.input),
                limit=args.limit,
                benchmark_split=args.benchmark_split,
            )
            dataset_label = args.bench_import_dataset
        elif args.bench_import_dataset == "scienceie":
            rows = import_scienceie_rows(
                Path(args.input),
                limit=args.limit,
                benchmark_split=args.benchmark_split,
            )
            dataset_label = args.bench_import_dataset
        else:  # pragma: no cover - argparse enforces known subcommands
            raise SystemExit(f"unsupported bench-import dataset: {args.bench_import_dataset}")
        _write_jsonl(output_path, rows)
        _emit_json(
            {
                "dataset": dataset_label,
                "rows": len(rows),
                "output_path": str(output_path),
            }
        )
        return 0

    if args.command == "ie-bench":
        payload = evaluate_ie_entities(
            Path(args.gold),
            Path(args.predictions),
            output_path=Path(args.output) if args.output else None,
        )
        _emit_json(payload)
        return 0

    if args.command == "entity-candidates":
        output_path = Path(args.output)
        if args.db:
            payload = extract_entity_candidates_from_store(
                Path(args.db),
                output_path=output_path,
                max_candidates=args.max_candidates,
                max_source_spans=args.max_source_spans,
                min_count=args.min_count,
                profile=args.profile,
            )
        else:
            payload = extract_entity_candidates_from_jsonl(
                Path(args.input_jsonl),
                output_path=output_path,
                text_field=args.text_field,
                id_field=args.id_field,
                max_candidates=args.max_candidates,
                min_count=args.min_count,
                profile=args.profile,
            )
        _emit_json(payload)
        return 0

    if args.command == "ie-model-candidates":
        payload = extract_ie_model_candidates_from_jsonl(
            Path(args.input_jsonl),
            output_path=Path(args.output),
            model_name=args.model,
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
            text_field=args.text_field,
            id_field=args.id_field,
            max_rows=args.max_rows,
            max_candidates=args.max_candidates,
            batch_size=args.batch_size,
            device=args.device,
            aggregation_strategy=args.aggregation_strategy,
            min_score=args.min_score,
            entity_type=args.entity_type,
        )
        _emit_json(payload)
        return 0

    if args.command == "ie-type-classify":
        payload = apply_text_type_classifier(
            Path(args.train_gold),
            Path(args.predictions),
            output_path=Path(args.output),
            classifier=args.classifier,
        )
        _emit_json(payload)
        return 0

    if args.command == "bench-external":
        db_path = Path(args.db)
        if args.bench_external_dataset == "qasper":
            store_payload = build_qasper_external_store(
                Path(args.input),
                Path(args.gold),
                db_path,
                gold_limit=args.limit,
                benchmark_split=args.benchmark_split,
            )
        elif args.bench_external_dataset == "scifact":
            store_payload = build_scifact_external_store(
                Path(args.corpus),
                db_path,
                doc_ids=(
                    external_gold_document_ids(
                        Path(args.gold),
                        limit=args.limit,
                        benchmark_split=args.benchmark_split,
                    )
                    if args.limit > 0
                    else None
                ),
            )
        elif args.bench_external_dataset == "beir":
            store_payload = build_beir_external_store(
                Path(args.corpus),
                db_path,
                dataset=args.dataset_name,
                doc_ids=(
                    external_gold_document_ids(
                        Path(args.gold),
                        limit=args.limit,
                        benchmark_split=args.benchmark_split,
                    )
                    if args.limit > 0
                    else None
                ),
            )
        else:  # pragma: no cover - argparse enforces known subcommands
            raise SystemExit(f"unsupported bench-external dataset: {args.bench_external_dataset}")
        metrics = run_external_retrieval_benchmark(
            db_path,
            Path(args.gold),
            k=args.k,
            limit=args.limit,
            include_details=bool(args.details_output),
            per_document_limit=args.per_document_limit,
            initial_limit=args.initial_limit,
            dense_limit=args.dense_limit,
            scope=args.scope,
            embedding_provider=_embedding_provider_from_args(args),
            embedding_provider_name=_embedding_provider_name_from_args(args),
            reranker=_reranker_from_args(args),
            embedding_cache_batch_size=args.embedding_cache_batch_size,
            reranker_cache_name=_reranker_cache_name_from_args(args),
            checkpoint_path=Path(args.checkpoint) if args.checkpoint else None,
            query_variants=args.query_variants,
            benchmark_split=args.benchmark_split,
        )
        question_results = list(metrics.pop("question_results", []) or [])
        payload = {
            "dataset": str(store_payload.get("dataset") or args.bench_external_dataset),
            **metrics,
            "external_corpus_documents": int(store_payload.get("documents", 0)),
            "external_corpus_spans": int(store_payload.get("spans", 0)),
            "external_gold_spans": int(store_payload.get("gold_spans", 0)),
            "external_gold_evidence_map_rows": int(store_payload.get("gold_evidence_map_rows", 0)),
            "db_path": str(db_path),
            "details_output_path": str(Path(args.details_output)) if args.details_output else "",
        }
        gate_failures = _benchmark_gate_failures(
            payload,
            min_retrieval_recall=args.min_retrieval_recall,
            min_all_gold_retrieval_recall=args.min_all_gold_retrieval_recall,
            min_gold_evidence_recall=args.min_gold_evidence_recall,
            min_citation_f1=0.0,
            min_answerable_evidence_adequacy=0.0,
        )
        payload["passed"] = not gate_failures
        payload["gate_failures"] = gate_failures
        if args.details_output:
            details_payload = {"metrics": payload}
            if str(payload.get("details_policy", "")) == "full":
                details_payload["questions"] = question_results
            _write_json(Path(args.details_output), details_payload)
        _emit_json(payload)
        return 1 if gate_failures else 0

    if args.command == "corpus-coverage":
        _emit_json(build_corpus_coverage(Path(args.db)))
        return 0

    if args.command == "discover":
        provider = build_discovery_provider(args.provider)
        papers = provider.search(args.query, limit=args.limit)
        _emit_json(
            {
                "query": args.query,
                "provider": args.provider,
                "papers": [paper.to_dict() for paper in papers],
            }
        )
        return 0

    if args.command == "investigate-references":
        rows = _collect_investigation_rows(args, extractor=extract_reference_records)
        row_dicts = [row.to_dict() for row in rows]
        _write_dict_csv(Path(args.output), row_dicts, fieldnames=list(ReferenceRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), row_dicts)
        _emit_json(_investigation_payload(args, rows))
        return 0

    if args.command == "investigate-artifacts":
        rows = _collect_investigation_rows(args, extractor=discover_artifact_records)
        row_dicts = [row.to_dict() for row in rows]
        _write_dict_csv(Path(args.output), row_dicts, fieldnames=list(ArtifactRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), row_dicts)
        _emit_json(_investigation_payload(args, rows))
        return 0

    if args.command == "investigate-availability":
        rows = _collect_investigation_rows(args, extractor=extract_data_availability_records)
        row_dicts = [row.to_dict() for row in rows]
        _write_dict_csv(Path(args.output), row_dicts, fieldnames=list(DataAvailabilityRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), row_dicts)
        _emit_json(_investigation_payload(args, rows))
        return 0

    if args.command == "references":
        html_path = Path(args.html)
        references = extract_reference_candidates(
            html_path.read_text(encoding="utf-8"),
            html_path=html_path,
        )
        _emit_json(
            {
                "html_path": str(html_path),
                "references": [reference.to_dict() for reference in references],
            }
        )
        return 0

    output_dir = Path(args.output_dir)
    fetcher = _build_fetcher(args, output_dir)
    source_fetchers = _build_source_fetchers(args)
    auth_fetcher = None if args.browser or args.no_auth_browser else _build_auth_fetcher(args, output_dir)
    snapshotter = _build_snapshotter(args)

    if args.command == "fetch":
        result = save_clean_html(
            args.identifier,
            output_dir=output_dir,
            fetcher=fetcher,
            source_fetchers=source_fetchers,
            auth_fetcher=auth_fetcher,
            snapshotter=snapshotter,
            min_text_length=args.min_text_length,
            download_assets=not args.no_download_assets,
        )
        _emit_json(_result_payload(result))
        _keep_browser_open_if_requested(args, fetcher)
        return _exit_code([result])

    identifiers = _read_identifier_file(Path(args.input_file))
    results = batch_save_clean_html(
        identifiers,
        output_dir=output_dir,
        fetcher=fetcher,
        source_fetchers=source_fetchers,
        auth_fetcher=auth_fetcher,
        snapshotter=snapshotter,
        min_text_length=args.min_text_length,
        download_assets=not args.no_download_assets,
        retry_incomplete_rounds=_batch_retry_incomplete_rounds(args, auth_fetcher),
    )
    payload = _batch_payload(results)
    if args.manifest_json:
        _write_json(Path(args.manifest_json), payload)
    if args.manifest_csv:
        _write_csv(Path(args.manifest_csv), results)
    _emit_json(payload)
    _keep_browser_open_if_requested(args, fetcher)
    return _exit_code(results)


def _run_answer_report(
    args: argparse.Namespace,
    db_path: Path,
    *,
    extra_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    chat_client = _chat_client_from_args_if_needed(
        args,
        args.quote_provider,
        args.answer_provider,
        args.verification_provider,
    )
    report_payload = answer_question(
        db_path,
        args.question,
        limit=args.limit,
        max_quotes=args.max_quotes,
        min_quotes=args.min_quotes,
        min_documents=args.min_documents,
        adequacy_profile=args.adequacy_profile,
        agentic_profile=getattr(args, "agentic_profile", "custom"),
        query_variants=getattr(args, "query_variants", 1),
        max_followup_queries=getattr(args, "max_followup_queries", 2),
        paper_recall_limit=getattr(args, "paper_recall_limit", 0),
        per_document_limit=args.per_document_limit,
        context_mode=args.context_mode,
        embedding_provider=_embedding_provider_from_args(args),
        reranker=_reranker_from_args(args),
        quote_provider=args.quote_provider,
        answer_provider=args.answer_provider,
        verification_provider=args.verification_provider,
        chat_client=chat_client,
    )
    answer = dict(report_payload.get("answer", {}) or {})
    evidence_table = list(report_payload.get("evidence_table", []) or [])
    quotes = list(report_payload.get("quotes", []) or [])
    report_html = render_answer_report(
        answer,
        evidence_table,
        retrieval_metadata={
            "query_plan": report_payload.get("query_plan", {}),
            "agentic_trace": report_payload.get("agentic_trace", {}),
            "retrieval_queries": report_payload.get("retrieval_queries", []),
            "adequacy": report_payload.get("adequacy", {}),
            "citation_verification": report_payload.get("citation_verification", {}),
        },
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html, encoding="utf-8")
    json_output_path = ""
    if args.json_output:
        json_path = Path(args.json_output)
        _write_json(json_path, report_payload)
        json_output_path = str(json_path)
    payload: dict[str, object] = {
        "question": args.question,
        "claims": len(answer.get("answer", []) or []),
        "quotes": len(quotes),
        "evidence_rows": len(evidence_table),
        "output_path": str(output_path),
        "json_output_path": json_output_path,
        "insufficient_evidence": bool(answer.get("insufficient_evidence", False)),
    }
    if extra_payload:
        payload.update(extra_payload)
    return payload


def _run_literature_workflow(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    db_path = Path(args.db) if args.db else safe_workflow_db_path(output_dir)
    config = LiteratureWorkflowConfig(
        library_dir=Path(args.library_dir),
        output_dir=output_dir,
        db_path=db_path,
        source_format=args.source_format,
        profile=args.profile,
        reindex=args.reindex,
        inject_evidence_html=args.inject_evidence_html,
        min_sentence_length=args.min_sentence_length,
        questions=load_workflow_questions(args.question, args.questions_file or None),
        limit=args.limit,
        max_quotes=args.max_quotes,
        min_quotes=args.min_quotes,
        min_documents=args.min_documents,
        adequacy_profile=args.adequacy_profile,
        agentic_profile=args.agentic_profile,
        query_variants=args.query_variants,
        max_followup_queries=args.max_followup_queries,
        paper_recall_limit=args.paper_recall_limit,
        per_document_limit=args.per_document_limit,
        context_mode=args.context_mode,
        quote_provider=args.quote_provider,
        answer_provider=args.answer_provider,
        verification_provider=args.verification_provider,
        chat_provider=args.chat_provider,
        chat_base_url=args.chat_base_url,
        chat_api_key=args.chat_api_key,
        chat_model=args.chat_model,
        chat_api_surface=args.chat_api_surface,
        chat_responses_enabled=args.chat_responses_enabled,
        cascade_first_stage_limit=args.cascade_first_stage_limit,
        generate_gold_template=args.generate_gold_template,
        questions_per_type=args.questions_per_type,
        entity_candidates=args.entity_candidates,
        max_entity_candidates=args.max_entity_candidates,
        max_entity_source_spans=args.max_entity_source_spans,
        entity_candidate_profile=args.entity_candidate_profile,
        dry_run=args.dry_run,
    )
    return run_literature_workflow(config)


def _build_fetcher(args: argparse.Namespace, output_dir: Path) -> object:
    if not args.browser:
        return HttpFetcher(timeout=args.timeout)
    return _new_browser_fetcher(args, output_dir, wait_login_seconds=args.wait_login)


def _embedding_provider_from_args(args: argparse.Namespace) -> object:
    return build_embedding_provider(
        args.embedding_provider,
        base_url=args.embedding_base_url,
        api_key=args.embedding_api_key,
        model=args.embedding_model,
        batch_size=getattr(args, "embedding_batch_size", 32),
        max_seq_length=getattr(args, "embedding_max_seq_length", 0),
    )


def _embedding_provider_name_from_args(args: argparse.Namespace) -> str:
    provider = str(args.embedding_provider or "local").strip()
    if provider == "local":
        return "local-hash-v1"
    model = str(args.embedding_model or "").strip() or "default"
    return f"{provider}:{model}"


def _search_filters_from_args(args: argparse.Namespace) -> dict[str, object]:
    filters: dict[str, object] = {}
    year_min = int(getattr(args, "year_min", 0) or 0)
    if year_min > 0:
        filters["year_min"] = year_min
    section_kinds = [str(item) for item in getattr(args, "section_kind", []) or [] if str(item)]
    if section_kinds:
        filters["section_kinds"] = section_kinds
    return filters


def _benchmark_gate_failures(
    metrics: dict[str, object],
    *,
    min_retrieval_recall: float,
    min_all_gold_retrieval_recall: float,
    min_gold_evidence_recall: float,
    min_citation_f1: float,
    min_answerable_evidence_adequacy: float,
) -> list[str]:
    failures: list[str] = []
    retrieval_recall = float(metrics.get("retrieval_recall_at_k", 0.0))
    all_gold_retrieval_recall = float(metrics.get("all_gold_retrieval_recall_at_k", 0.0))
    gold_evidence_recall = float(metrics.get("gold_evidence_recall_at_k", 0.0))
    citation_f1 = float(metrics.get("citation_f1", 0.0))
    answerable_evidence_adequacy = float(metrics.get("answerable_evidence_adequacy_rate", 0.0))
    if retrieval_recall < float(min_retrieval_recall):
        failures.append(
            f"retrieval_recall_at_k {retrieval_recall} is below required {float(min_retrieval_recall)}"
        )
    if all_gold_retrieval_recall < float(min_all_gold_retrieval_recall):
        failures.append(
            "all_gold_retrieval_recall_at_k "
            f"{all_gold_retrieval_recall} is below required {float(min_all_gold_retrieval_recall)}"
        )
    if gold_evidence_recall < float(min_gold_evidence_recall):
        failures.append(
            f"gold_evidence_recall_at_k {gold_evidence_recall} is below required {float(min_gold_evidence_recall)}"
        )
    if citation_f1 < float(min_citation_f1):
        failures.append(f"citation_f1 {citation_f1} is below required {float(min_citation_f1)}")
    if answerable_evidence_adequacy < float(min_answerable_evidence_adequacy):
        failures.append(
            "answerable_evidence_adequacy_rate "
            f"{answerable_evidence_adequacy} is below required {float(min_answerable_evidence_adequacy)}"
        )
    return failures


def _comma_separated_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _short_title_from_text(value: str, *, fallback: str = "Grounded draft") -> str:
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return fallback


def _optional_bool_filter(value: str) -> bool | None:
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized == "true"


def _build_auth_fetcher(args: argparse.Namespace, output_dir: Path) -> object | None:
    if args.no_auth_browser or args.browser:
        return None
    wait_login_seconds = args.wait_login if args.wait_login > 0 else 300
    return _new_browser_fetcher(args, output_dir, wait_login_seconds=wait_login_seconds)


def _batch_retry_incomplete_rounds(args: argparse.Namespace, auth_fetcher: object | None) -> int:
    configured = int(getattr(args, "retry_incomplete_rounds", -1))
    if configured >= 0:
        return configured
    return 1 if bool(getattr(args, "browser", False)) or auth_fetcher is not None else 0


def _build_source_fetchers(args: argparse.Namespace) -> list[object]:
    if args.no_official_sources:
        return []
    return build_default_official_sources(timeout=args.timeout)


def _chat_client_from_args_if_needed(args: argparse.Namespace, *providers: str) -> object | None:
    if any(str(provider).strip().lower() == "llm" for provider in providers):
        return _chat_client_from_args(args)
    return None


def _chat_client_from_args(args: argparse.Namespace) -> object:
    return build_chat_json_client(
        args.chat_provider,
        base_url=args.chat_base_url,
        api_key=args.chat_api_key,
        model=args.chat_model,
        api_surface=args.chat_api_surface,
        responses_enabled=args.chat_responses_enabled,
    )


def _reranker_from_args(args: argparse.Namespace) -> object:
    return build_reranker(
        args.reranker,
        model_name=getattr(args, "reranker_model", ""),
        batch_size=getattr(args, "reranker_batch_size", 32),
    )


def _reranker_cache_name_from_args(args: argparse.Namespace) -> str:
    explicit_name = str(getattr(args, "reranker_cache_name", "") or "").strip()
    if explicit_name:
        return explicit_name
    provider = str(getattr(args, "reranker", "local") or "local").strip()
    if provider == "local":
        return ""
    model_name = str(getattr(args, "reranker_model", "") or "").strip()
    return f"{provider}:{model_name or 'default'}"


def _build_snapshotter(args: argparse.Namespace) -> object | None:
    if not args.snapshot_dir:
        return None
    return RawHtmlSnapshotter(Path(args.snapshot_dir))


def _run_credentials(args: argparse.Namespace) -> int:
    if args.credentials_command == "list":
        _emit_json({"credentials": credential_status()})
        return 0
    if args.credentials_command == "set":
        value = _credential_value_from_args(args)
        set_credential(args.name, value)
        _emit_json({"status": "stored", "name": args.name})
        return 0
    if args.credentials_command == "delete":
        delete_credential(args.name)
        _emit_json({"status": "deleted", "name": args.name})
        return 0
    _emit_json({"status": "error", "error": "expected credentials subcommand"})
    return 2


def _run_opencli_bridge_doctor(args: argparse.Namespace) -> int:
    config = BrowserIdentityConfig.from_values(
        browser_extension_dirs=getattr(args, "browser_extension_dirs", None),
        browser_proxy_url=args.browser_proxy_url,
        browser_extensions_enabled=not args.disable_browser_extensions,
        chrome_profile_dir=args.browser_profile,
    )
    diagnostics = build_opencli_bridge_diagnostics(
        config,
        runtime_probe=args.runtime_probe,
        use_config_profile=args.use_browser_profile,
        timeout_sec=args.timeout_seconds,
        keep_open=args.keep_open,
    )
    _emit_json(diagnostics)
    return 0 if diagnostics.get("verdict") == "connected" else 1


def _grounded_annotation_text_from_args(args: argparse.Namespace) -> str:
    if getattr(args, "input", None):
        return Path(args.input).read_text(encoding="utf-8-sig")
    return str(getattr(args, "text", "") or "")


def _credential_value_from_args(args: argparse.Namespace) -> str:
    if args.value and args.gui:
        raise SystemExit("Use either --value or --gui, not both.")
    if args.gui:
        return _read_gui_secret(args.name).strip()
    return args.value or getpass.getpass(f"{args.name}: ")


def _read_gui_secret(name: str) -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except Exception as error:  # pragma: no cover - depends on local Python build
        raise RuntimeError("Tkinter is not available; use --value or the terminal prompt.") from error

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        value = simpledialog.askstring(
            "scansci-html credential",
            f"{name}:",
            show="*",
            parent=root,
        )
    finally:
        root.destroy()
    if not value:
        raise RuntimeError("No credential value entered.")
    return value


def _new_browser_fetcher(
    args: argparse.Namespace,
    output_dir: Path,
    *,
    wait_login_seconds: int,
) -> BrowserFetcher:
    config = BrowserFetcherConfig.from_cli_args(
        args,
        output_dir=output_dir,
        wait_login_seconds=wait_login_seconds,
    )
    return BrowserFetcher(**config.to_fetcher_kwargs())


def _run_broker(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    broker_dir = Path(args.broker_dir) if args.broker_dir else output_dir / ".scansci-broker"
    args.browser = True
    args.keep_browser_open = True
    fetcher = _new_browser_fetcher(args, output_dir, wait_login_seconds=args.wait_login)
    service = BrokerService(
        broker_dir=broker_dir,
        output_dir=output_dir,
        fetcher=fetcher,
        source_fetchers=_build_source_fetchers(args),
        snapshotter=_build_snapshotter(args),
        min_text_length=args.min_text_length,
        download_assets=not args.no_download_assets,
        poll_interval_seconds=args.poll_interval,
    )
    try:
        service.run_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        close = getattr(fetcher, "close", None)
        if close is not None:
            close()
    return 0


def _submit_broker_request(args: argparse.Namespace) -> int:
    broker_dir = Path(args.broker_dir)
    request_id = enqueue_request(broker_dir, args.identifier)
    if not args.wait_response:
        _emit_json({"request_id": request_id, "status": "queued"})
        return 0
    response = wait_for_response(
        broker_dir,
        request_id,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=0.5,
    )
    if response is None:
        _emit_json(
            {
                "request_id": request_id,
                "status": "timeout",
                "identifier": args.identifier,
                "error": "broker response timed out",
            }
        )
        return 1
    _emit_json(response)
    return _payload_exit_code(response)


def _read_identifier_file(path: Path) -> list[str]:
    identifiers: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        value = line.strip().lstrip("\ufeff")
        if value:
            identifiers.append(value)
    return identifiers


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _emit_json(payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")


def _result_payload(result: SaveResult) -> dict[str, object]:
    return {
        "status": result.status,
        "identifier": result.identifier,
        "doi": result.doi,
        "title": result.title,
        "source_url": result.source_url,
        "output_path": str(result.output_path) if result.output_path else "",
        "snapshot_path": str(result.snapshot_path) if result.snapshot_path else "",
        "warnings": list(result.warnings),
        "error": result.error,
        "structure": dict(result.structure),
    }


def _batch_payload(results: list[SaveResult]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return {
        "counts": counts,
        "results": [_result_payload(result) for result in results],
    }


def _count_displayable_layer_items(viewer_payload: dict[str, object]) -> int:
    total = 0
    for raw_layer in viewer_payload.get("layers", []) or []:
        layer = dict(raw_layer or {})
        for raw_item in layer.get("items", []) or []:
            item = dict(raw_item or {})
            if str(item.get("support_status", "") or "") in DISPLAYABLE_EVIDENCE_STATUSES:
                total += 1
    return total


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(_jsonl_dumps(row) + "\n")


def _jsonl_dumps(row: object) -> str:
    return (
        json.dumps(row, ensure_ascii=False)
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _collect_investigation_rows(args: argparse.Namespace, *, extractor: object) -> list[object]:
    paths = [Path(args.html)] if args.html else sorted(Path(args.library_dir).rglob("*.html"))
    rows: list[object] = []
    for html_path in paths:
        html_text = html_path.read_text(encoding="utf-8")
        rows.extend(extractor(html_text, html_path=html_path, source_url=_source_url_from_html(html_text)))
    return rows


def _source_url_from_html(html_text: str) -> str:
    match = re.search(r"""data-source-url=["']([^"']+)["']""", html_text)
    return match.group(1) if match else ""


def _write_dict_csv(path: Path, rows: list[dict[str, object]], *, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _investigation_payload(args: argparse.Namespace, rows: list[object]) -> dict[str, object]:
    return {
        "command": args.command,
        "count": len(rows),
        "output_path": str(Path(args.output)),
        "jsonl_output_path": str(Path(args.jsonl_output)) if args.jsonl_output else "",
    }


def _write_csv(path: Path, results: list[SaveResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "status",
                "identifier",
                "doi",
                "title",
                "source_url",
                "output_path",
                "snapshot_path",
                "warnings",
                "structure",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            row = _result_payload(result)
            row["warnings"] = "; ".join(result.warnings)
            row["structure"] = json.dumps(result.structure, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)


def _write_benchmark_comparison_csv(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "preset",
        "embedding_provider",
        "embedding_model",
        "reranker",
        "reranker_model",
        "retrieval_recall_at_k",
        "all_gold_retrieval_recall_at_k",
        "gold_evidence_recall_at_k",
        "answer_accuracy",
        "answerable_evidence_adequacy_rate",
        "citation_f1",
        "unsupported_claim_rate",
        "abstention_accuracy",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if not isinstance(row, dict):
                continue
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _keep_browser_open_if_requested(args: argparse.Namespace, fetcher: object) -> None:
    if not getattr(args, "keep_browser_open", False):
        return
    if not isinstance(fetcher, BrowserFetcher):
        return
    print(
        "Browser session is being kept open. Press Ctrl+C in the launching terminal when you are done.",
        file=sys.stderr,
    )
    try:
        while True:
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        fetcher.close()


def _exit_code(results: list[SaveResult]) -> int:
    if any(result.status == "fetch_error" for result in results):
        return 1
    if any(result.status in {"auth_required", "no_access"} for result in results):
        return 2
    return 0


def _payload_exit_code(payload: dict[str, object]) -> int:
    status = str(payload.get("status") or "")
    if status == "fetch_error":
        return 1
    if status in {"auth_required", "no_access"}:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
