"""Task-scoped full-text evidence for public Deep Research runs.

This module deliberately keeps acquired papers outside a user's persistent
knowledge libraries.  It turns each task download into structured HTML, then
uses the same document -> section -> evidence-span index used by local RAG so
that every statement in a Deep Research report can be opened at its source.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Any

from .evidence_doctor import assess_evidence_structure
from .evidence_store import index_evidence_library
from .ingestion import extract_local_document
from .resolver import safe_identifier_part


_SECTION_HEADINGS = {
    "abstract", "introduction", "background", "methods", "methodology",
    "materials and methods", "results", "discussion", "conclusion",
    "conclusions", "limitations", "references", "摘要", "引言", "背景",
    "方法", "材料与方法", "结果", "讨论", "结论", "局限性", "参考文献",
}


def task_evidence_root(workspace: str | Path, run_id: str) -> Path:
    """Return the private, task-only evidence directory for one research run."""

    safe_run_id = safe_identifier_part(str(run_id or "research-run"))
    return Path(workspace).resolve().parent / ".scansci" / "research-runs" / safe_run_id


def build_task_fulltext_evidence(
    workspace: str | Path,
    run_id: str,
    acquired: list[dict[str, Any]],
    *,
    min_sentence_length: int = 40,
) -> dict[str, Any]:
    """Extract and index acquired papers without importing them into a library.

    Returned paths are task artifacts, not user-library paths.  Failures are
    collected per paper so callers can honestly fall back to abstract-level
    evidence instead of silently treating a download as indexed full text.
    """

    root = task_evidence_root(workspace, run_id)
    source_dir = root / "sources"
    extracted_dir = root / "extracted"
    source_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    source_records: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for paper_index, raw_paper in enumerate(acquired, start=1):
        paper = dict(raw_paper or {})
        title = " ".join(str(paper.get("title", "")).split()) or f"Acquired paper {paper_index}"
        doi = str(paper.get("doi", "")).strip()
        arxiv_id = str(paper.get("arxiv_id", "")).strip()
        source_url = _canonical_source_url(doi=doi, arxiv_id=arxiv_id)
        for file_index, raw_path in enumerate(list(paper.get("files", []) or []), start=1):
            file_path = Path(str(raw_path)).expanduser()
            if not file_path.is_file():
                failures.append({"title": title, "file": str(file_path), "error": "Downloaded file is unavailable."})
                continue
            target_dir = extracted_dir / f"{paper_index:02d}-{file_index:02d}-{safe_identifier_part(file_path.stem)[:56]}"
            try:
                extracted = extract_local_document(file_path, output_dir=target_dir)
                text_path = Path(str(extracted.get("text_path", "")))
                text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.is_file() else ""
            except Exception as error:
                failures.append(
                    {"title": title, "file": str(file_path), "error": f"{type(error).__name__}: {error}"[:500]}
                )
                continue
            if len(_compact_text(text)) < 240:
                failures.append({"title": title, "file": str(file_path), "error": "Extracted text is too short for evidence indexing."})
                continue
            source_file = source_dir / f"{paper_index:02d}-{file_index:02d}-{safe_identifier_part(doi or arxiv_id or title)[:72]}.html"
            source_file.write_text(
                _evidence_html(title=title, doi=doi, source_url=source_url, text=text),
                encoding="utf-8",
            )
            source_records.append(
                {
                    "title": title,
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "source_url": source_url,
                    "original_file": str(file_path.resolve()),
                    "source_html": str(source_file.resolve()),
                    "parser": str(extracted.get("parser", "")),
                }
            )

    evidence_db = root / "evidence.sqlite"
    index = (
        index_evidence_library(
            source_dir,
            db_path=evidence_db,
            inject_evidence_html=True,
            min_sentence_length=max(16, int(min_sentence_length)),
        )
        if source_records
        else {"documents": 0, "spans": 0, "db_path": str(evidence_db), "evidence_html_files": 0}
    )
    quality = (
        assess_evidence_structure(evidence_db)
        if int(index.get("documents", 0) or 0) > 0
        else {"healthy": False, "documents": 0, "spans": 0, "issues": []}
    )
    return {
        "run_id": str(run_id),
        "root": str(root.resolve()),
        "evidence_db": str(evidence_db.resolve()),
        "source_records": source_records,
        "index": index,
        "quality": quality,
        "failures": failures,
        "evidence_level": _evidence_level(index, quality),
    }


def task_evidence_reader_path(
    workspace: str | Path,
    run_id: str,
    evidence_db: str | Path,
    doc_id: str,
) -> Path:
    """Resolve an indexed evidence HTML file, constrained to this task root."""

    import sqlite3

    root = task_evidence_root(workspace, run_id).resolve()
    database = Path(evidence_db).resolve()
    if root not in database.parents or not database.is_file():
        raise FileNotFoundError("Task evidence index does not exist")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "select evidence_html_path, html_path from source_documents where doc_id = ?",
            (str(doc_id),),
        ).fetchone()
    if row is None:
        raise FileNotFoundError("Task evidence source does not exist")
    candidate = Path(str(row[0] or row[1] or "")).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError("Task evidence source is unavailable")
    return candidate


def _evidence_level(index: dict[str, Any], quality: dict[str, Any]) -> str:
    documents = int(index.get("documents", 0) or 0)
    spans = int(index.get("spans", 0) or 0)
    claim_ready = task_evidence_claim_ready(quality)
    return "fulltext" if documents >= 2 and spans >= 3 and claim_ready else "partial_fulltext" if documents and spans else "none"


def task_evidence_claim_ready(quality: dict[str, Any]) -> bool:
    """Return whether indexed text is safe for claim-level citation.

    Oversized spans are a retrieval-precision warning, not evidence
    fabrication.  Missing structure, orphan sections, or source-text
    mismatches remain hard failures.  The fallback calculation keeps older
    task artifacts usable after upgrading.
    """

    if "claim_ready" in quality:
        return bool(quality.get("claim_ready"))
    critical_fields = ("missing_structure_spans", "source_text_mismatches", "orphan_sections")
    if any(field in quality for field in critical_fields):
        return all(int(quality.get(field, 0) or 0) == 0 for field in critical_fields)
    return bool(quality.get("passed", False))


def _canonical_source_url(*, doi: str, arxiv_id: str) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return ""


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _evidence_html(*, title: str, doi: str, source_url: str, text: str) -> str:
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n+", str(text or "")):
        normalized = _compact_text(block)
        if not normalized:
            continue
        if _looks_like_heading(normalized):
            blocks.append(f"<h2>{escape(normalized)}</h2>")
        else:
            blocks.append(f"<p>{escape(normalized)}</p>")
    body = "\n".join(blocks) or f"<p>{escape(_compact_text(text))}</p>"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title></head><body>"
        f"<article data-doi=\"{escape(doi, quote=True)}\" data-source-url=\"{escape(source_url, quote=True)}\">"
        f"<h1>{escape(title)}</h1>{body}</article></body></html>"
    )


def _looks_like_heading(value: str) -> bool:
    normalized = value.strip().strip("#:：. ")
    if normalized.casefold() in _SECTION_HEADINGS:
        return True
    return bool(re.match(r"^(?:\d+(?:\.\d+){0,3}\s+)?(?:abstract|introduction|methods?|results?|discussion|conclusions?)$", normalized, re.I))
