"""Verify ScanSci knowledge-library ingestion, retrieval, Agent tools and readers."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import time

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.library_manager import import_library_folder
from scansci_html.research_agent import ResearchAgentRuntime
from scansci_html.retrieval import search_evidence_store
from scansci_html.webapp import NotebookWebApp
from scansci_html.workspace import initialize_notebook, load_workspace_summary


DEFAULT_QUERY = "光伏电站对植被覆盖、土壤水分和微气候有哪些一致结论与争议？"


def _index_snapshot(status: dict[str, object]) -> dict[str, object]:
    """Keep the observable parts of a background index run for gate reports."""

    run = dict(status.get("run", {}) or {})
    return {
        "ready": bool(status.get("ready")),
        "available": bool(status.get("available")),
        "completed": int(status.get("completed", 0) or 0),
        "total": int(status.get("total", 0) or 0),
        "state": str(status.get("state", "") or ""),
        "error": str(status.get("error", "") or ""),
        "run_id": str(run.get("run_id", "") or ""),
        "run_status": str(run.get("status", "") or ""),
        "run_error": str(run.get("error", "") or ""),
    }


def wait_for_semantic_index(
    runtime: ResearchAgentRuntime,
    notebook_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.5,
) -> dict[str, object]:
    """Exercise the same bind-then-background-index lifecycle as the desktop app.

    Importing a library deliberately does not block on vector construction.  A
    release check must consequently wait for the separately observable index
    run before it claims that hybrid retrieval works.  Otherwise an empty
    vector cache silently exercises only the lexical fallback.
    """

    started = runtime.start_evidence_index(str(notebook_id))
    started_run = dict(started or {})
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    history: list[dict[str, object]] = []
    last_snapshot: dict[str, object] = {}

    while True:
        snapshot = _index_snapshot(dict(runtime.evidence_index_status(str(notebook_id)) or {}))
        if snapshot != last_snapshot:
            history.append(snapshot)
            last_snapshot = snapshot
        if bool(snapshot.get("ready")):
            return {
                "ready": True,
                "started_run_id": str(started_run.get("run_id", "") or ""),
                "final": snapshot,
                "history": history,
            }
        if str(snapshot.get("run_status", "")) in {"failed", "cancelled"}:
            return {
                "ready": False,
                "reason": "index_run_terminal_failure",
                "started_run_id": str(started_run.get("run_id", "") or ""),
                "final": snapshot,
                "history": history,
            }
        if int(snapshot.get("total", 0) or 0) <= 0:
            return {
                "ready": False,
                "reason": "empty_vector_source",
                "started_run_id": str(started_run.get("run_id", "") or ""),
                "final": snapshot,
                "history": history,
            }
        if time.monotonic() >= deadline:
            return {
                "ready": False,
                "reason": "timeout",
                "started_run_id": str(started_run.get("run_id", "") or ""),
                "final": snapshot,
                "history": history,
            }
        time.sleep(max(0.0, float(poll_seconds)))


def _is_pdf(path: Path) -> bool:
    """Reject HTML/error pages that were saved with a ``.pdf`` suffix."""

    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _sample_pdfs(source: Path, limit: int) -> list[Path]:
    preferred = [
        "光伏电站对区域小气候-植被-土壤特征影响的Meta分析_丁成翔.pdf",
        "光伏电板对地表土壤颗粒及小气候的影响_赵鹏宇.pdf",
        "光伏电站建设对土壤和植被的影响_王涛.pdf",
        "西北地区光伏电站植被恢复模式研究综述_崔永琴.pdf",
        "生态脆弱区光伏电站植被修复策略_王大春.pdf",
        "浅谈光伏电站建设对荒漠地区治理意义——以甘肃为例_樊桢.pdf",
    ]
    found = [source / name for name in preferred if (source / name).is_file() and _is_pdf(source / name)]
    for path in sorted(source.rglob("*.pdf"), key=lambda item: (item.stat().st_size, item.name)):
        if _is_pdf(path) and path not in found:
            found.append(path)
        if len(found) >= limit:
            break
    return found[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=r"D:\光伏生态文献")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--with-model", action="store_true")
    parser.add_argument("--model", default="glm-4.7-flash")
    parser.add_argument(
        "--index-timeout",
        type=float,
        default=900.0,
        help="maximum seconds to wait for the automatic semantic index build",
    )
    parser.add_argument("--output", default=".scansci-diagnostics/knowledge-e2e.json")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    selected = _sample_pdfs(source, max(1, min(40, args.limit)))
    if not selected:
        raise FileNotFoundError(f"No PDF files found in {source}")
    root = (Path(".codex-tmp") / f"knowledge-e2e-{datetime.now().strftime('%Y%m%d-%H%M%S')}").resolve()
    sample = root / "source-sample"
    sample.mkdir(parents=True)
    for path in selected:
        shutil.copy2(path, sample / path.name)

    workspace = root / "workspace.sqlite"
    base_evidence = root / "evidence.sqlite"
    created = initialize_notebook(workspace, title="光伏生态文献", root_path=sample, metadata={"library_kind": "folder"})
    if args.with_model:
        settings = load_settings(workspace)
        settings["active_model"] = {"provider_id": "scansci-managed", "model_id": args.model}
        save_settings(workspace, settings)
    started = time.monotonic()
    imported = import_library_folder(
        workspace,
        base_evidence,
        notebook_id=str(created["notebook_id"]),
        folder_path=sample,
    )
    import_seconds = round(time.monotonic() - started, 2)
    notebook = load_workspace_summary(workspace, notebook_id=str(created["notebook_id"]))["notebooks"][0]
    evidence_db = Path(notebook["sources"][0]["evidence_db_path"])
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=base_evidence)
    index_started = time.monotonic()
    semantic_index = wait_for_semantic_index(
        runtime,
        str(created["notebook_id"]),
        timeout_seconds=args.index_timeout,
    )
    semantic_index["elapsed_seconds"] = round(time.monotonic() - index_started, 2)
    local_evidence = runtime._local_evidence_stack(evidence_db)
    trace: list[dict[str, object]] = []
    hits = search_evidence_store(
        evidence_db,
        args.query,
        limit=8,
        context_mode="block",
        trace=trace,
        embedding_provider=local_evidence.embedding_provider,
        reranker=local_evidence.reranker,
    )

    reader_ok = False
    original_ok = False
    if hits:
        app = NotebookWebApp(workspace=workspace, evidence_db=base_evidence)
        doc_id = str(hits[0]["doc_id"])
        reader = app.dispatch("GET", f"/api/sources/{doc_id}/reader", b"")
        reader_text = reader.body.decode("utf-8", errors="replace")
        reader_ok = reader.status == 200 and str(hits[0]["html_anchor"]) in reader_text and ":target" in reader_text
        original = app.dispatch("GET", f"/api/sources/{doc_id}/original", b"")
        original_ok = original.status == 200 and original.body.startswith(b"%PDF")

    agent_report: dict[str, object] = {"requested": bool(args.with_model)}
    if args.with_model:
        agent_started = time.monotonic()
        answer = runtime.answer_sync({
            "notebook_id": str(created["notebook_id"]),
            "question": args.query,
            "task_mode": "evidence",
            "thinking_level": "standard",
            "limit": 10,
        })
        reader_answer = dict(answer.get("reader_answer", {}) or {})
        runtime_meta = dict(answer.get("pi_agent", {}) or {})
        compatibility_failure = dict(runtime_meta.get("compatibility_failure", {}) or {})
        citations = list(reader_answer.get("citations", []) or [])
        tool_calls = [str(item.get("name", "")) for item in list(runtime_meta.get("tool_calls", []) or [])]
        agent_report = {
            "requested": True,
            "model_id": args.model,
            "elapsed_seconds": round(time.monotonic() - agent_started, 2),
            "answer_characters": len(str(reader_answer.get("text", ""))),
            "citation_count": len(citations),
            "citations_have_reader_urls": bool(citations) and all(str(item.get("reader_url", "")).startswith("/api/sources/") for item in citations),
            "harness": str(runtime_meta.get("harness", "")),
            "finalization": str(runtime_meta.get("finalization", "")),
            "compatibility_fallback": bool(runtime_meta.get("compatibility_fallback")),
            "compatibility_error": str(runtime_meta.get("compatibility_error", ""))[:500],
            # Keep the provider failure code machine-readable in the release
            # artifact.  A strict citation check may fail after a transient
            # upstream limit, and the gate must retry that case instead of
            # treating it as a product-quality regression.
            "compatibility_failure_reason": str(
                compatibility_failure.get("reason") or ""
            ),
            "compatibility_failure_retryable": bool(
                compatibility_failure.get("retryable")
            ),
            "tool_calls": tool_calls,
            "verification_passed": bool(dict(answer.get("citation_verification", {}) or {}).get("passed")),
        }

    summary = dict(imported.get("ingestion", {}).get("summary", {}) or {})
    checks = {
        "parsed_files": int(summary.get("completed", 0) or 0) >= max(1, len(selected) - 1),
        "indexed_documents": int(imported.get("indexed", {}).get("documents", 0) or 0) >= max(1, len(selected) - 1),
        "semantic_index_ready": bool(semantic_index.get("ready")),
        "qwen_embedding_active": bool(local_evidence.metadata.get("qwen_embedding_active")),
        "hybrid_retrieval": bool(hits) and any("dense" in list(hit.get("routes", []) or []) for hit in hits),
        "chinese_retrieval": bool(hits),
        "exact_evidence_reader": reader_ok,
        "original_pdf_reader": original_ok,
        "agent_citations": (not args.with_model) or int(agent_report.get("citation_count", 0) or 0) > 0,
        "agent_used_tools": (not args.with_model) or bool(agent_report.get("tool_calls")),
        # Delivery quality must not depend on a nominally OpenAI-compatible
        # gateway being able to serialize Pi tool calls.  Both execution paths
        # below are real, source-grounded tool workflows; the fallback is only
        # accepted if it still completes the verified-answer action.
        "agent_verified_tool_workflow": (not args.with_model)
        or (
            agent_report.get("harness") in {"pi-agent-sdk", "provider-neutral-workflow"}
            and "build_verified_answer" in list(agent_report.get("tool_calls", []) or [])
            and agent_report.get("finalization") in {"build_verified_answer", "verified-workflow"}
        ),
        "agent_citations_verified": (not args.with_model) or bool(agent_report.get("verification_passed")),
    }
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": str(source),
        "sample_files": [path.name for path in selected],
        "workspace": str(root),
        "import_seconds": import_seconds,
        "ingestion": summary,
        "indexed": imported.get("indexed", {}),
        "semantic_index": semantic_index,
        "retrieval": {
            "query": args.query,
            "runtime": local_evidence.metadata,
            "hits": [
                {
                    "title": hit.get("paper") or hit.get("title"),
                    "section": hit.get("section"),
                    "score": hit.get("score"),
                    "routes": hit.get("routes"),
                    "text": str(hit.get("text", ""))[:220],
                }
                for hit in hits[:5]
            ],
            "trace": trace,
        },
        "agent": agent_report,
        "checks": checks,
        "passed": all(checks.values()),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
