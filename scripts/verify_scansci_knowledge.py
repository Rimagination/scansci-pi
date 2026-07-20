"""Verify ScanSci knowledge-library ingestion, retrieval, Agent tools and readers."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import time

from scansci_html.library_manager import import_library_folder
from scansci_html.research_agent import ResearchAgentRuntime
from scansci_html.retrieval import search_evidence_store
from scansci_html.webapp import NotebookWebApp
from scansci_html.workspace import initialize_notebook, load_workspace_summary


DEFAULT_QUERY = "光伏电站对植被覆盖、土壤水分和微气候有哪些一致结论与争议？"


def _sample_pdfs(source: Path, limit: int) -> list[Path]:
    preferred = [
        "光伏电站建设对土壤和植被的影响_王涛.pdf",
        "西北地区光伏电站植被恢复模式研究综述_崔永琴.pdf",
        "生态脆弱区光伏电站植被修复策略_王大春.pdf",
        "浅谈光伏电站建设对荒漠地区治理意义——以甘肃为例_樊桢.pdf",
    ]
    found = [source / name for name in preferred if (source / name).is_file()]
    for path in sorted(source.rglob("*.pdf"), key=lambda item: (item.stat().st_size, item.name)):
        if path not in found:
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
    trace: list[dict[str, object]] = []
    hits = search_evidence_store(evidence_db, args.query, limit=8, context_mode="block", trace=trace)

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
        runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=base_evidence)
        agent_started = time.monotonic()
        answer = runtime.answer_sync({
            "notebook_id": str(created["notebook_id"]),
            "question": args.query,
            "task_mode": "evidence",
            "thinking_level": "standard",
            "limit": 10,
        })
        reader_answer = dict(answer.get("reader_answer", {}) or {})
        runtime_meta = dict(answer.get("deep_agent", {}) or {})
        citations = list(reader_answer.get("citations", []) or [])
        agent_report = {
            "requested": True,
            "elapsed_seconds": round(time.monotonic() - agent_started, 2),
            "answer_characters": len(str(reader_answer.get("text", ""))),
            "citation_count": len(citations),
            "citations_have_reader_urls": bool(citations) and all(str(item.get("reader_url", "")).startswith("/api/sources/") for item in citations),
            "tool_calls": [str(item.get("name", "")) for item in list(runtime_meta.get("tool_calls", []) or [])],
            "verification_passed": bool(dict(answer.get("citation_verification", {}) or {}).get("passed")),
        }

    summary = dict(imported.get("ingestion", {}).get("summary", {}) or {})
    checks = {
        "parsed_files": int(summary.get("completed", 0) or 0) >= max(1, len(selected) - 1),
        "indexed_documents": int(imported.get("indexed", {}).get("documents", 0) or 0) >= max(1, len(selected) - 1),
        "hybrid_retrieval": bool(hits) and any("dense" in list(hit.get("routes", []) or []) for hit in hits),
        "chinese_retrieval": bool(hits),
        "exact_evidence_reader": reader_ok,
        "original_pdf_reader": original_ok,
        "agent_citations": (not args.with_model) or int(agent_report.get("citation_count", 0) or 0) > 0,
        "agent_used_tools": (not args.with_model) or bool(agent_report.get("tool_calls")),
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
        "retrieval": {
            "query": args.query,
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
