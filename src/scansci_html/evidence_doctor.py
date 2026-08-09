from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from bs4 import BeautifulSoup


def check_evidence_links(
    db_path: str | Path,
    *,
    max_issues: int = 100,
) -> dict[str, Any]:
    db = Path(db_path)
    rows = _load_evidence_link_rows(db)
    soup_cache: dict[Path, BeautifulSoup | None] = {}
    issues: list[dict[str, str]] = []
    missing_files = 0
    missing_anchors = 0
    evidence_id_mismatches = 0

    for row in rows:
        evidence_id = str(row.get("evidence_id", ""))
        html_path_value = str(row.get("html_path", ""))
        html_anchor = str(row.get("html_anchor", ""))
        resolved_path = _resolve_html_path(html_path_value, db)
        if not resolved_path.exists():
            missing_files += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="missing_file",
                evidence_id=evidence_id,
                html_path=html_path_value,
                html_anchor=html_anchor,
                message="HTML path does not exist",
            )
            continue

        soup = soup_cache.get(resolved_path)
        if resolved_path not in soup_cache:
            soup = BeautifulSoup(resolved_path.read_text(encoding="utf-8"), "lxml")
            soup_cache[resolved_path] = soup
        if soup is None:
            continue

        anchor = soup.find(id=html_anchor)
        if anchor is None:
            missing_anchors += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="missing_anchor",
                evidence_id=evidence_id,
                html_path=html_path_value,
                html_anchor=html_anchor,
                message="HTML anchor id does not exist",
            )
            continue

        anchor_evidence_id = str(anchor.get("data-evidence-id", "") or "")
        if anchor_evidence_id != evidence_id:
            evidence_id_mismatches += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="evidence_id_mismatch",
                evidence_id=evidence_id,
                html_path=html_path_value,
                html_anchor=html_anchor,
                message=f"Anchor data-evidence-id is {anchor_evidence_id or '[missing]'}",
            )

    return {
        "passed": missing_files == 0 and missing_anchors == 0 and evidence_id_mismatches == 0,
        "spans": len(rows),
        "checked_files": len(soup_cache),
        "missing_files": missing_files,
        "missing_anchors": missing_anchors,
        "evidence_id_mismatches": evidence_id_mismatches,
        "issues_truncated": len(issues) < missing_files + missing_anchors + evidence_id_mismatches,
        "issues": issues,
    }


def assess_evidence_structure(
    db_path: str | Path,
    *,
    max_span_characters: int = 1_200,
    max_issues: int = 100,
    verify_source_text: bool = True,
) -> dict[str, Any]:
    """Audit the document → section → evidence foundation of one index.

    Anchor existence alone is not enough: a 50,000-character block can still
    have a valid anchor while being unusable as evidence.  This audit verifies
    structural identities, bounded evidence units, section-tree integrity and
    (when source files remain available) that stored evidence is present in
    the parsed original source.
    """

    db = Path(db_path)
    rows, section_count, orphan_sections = _load_structure_rows(db)
    source_text_cache: dict[Path, str] = {}
    issues: list[dict[str, str]] = []
    missing_structure = 0
    oversized = 0
    unverifiable = 0
    tiny = 0
    reference_spans = 0
    documents = {str(row.get("doc_id", "")) for row in rows}

    for row in rows:
        evidence_id = str(row.get("evidence_id", ""))
        text = str(row.get("text", ""))
        if not all(str(row.get(field, "")).strip() for field in ("section_id", "section_path", "source_locator")):
            missing_structure += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="missing_structure",
                evidence_id=evidence_id,
                html_path=str(row.get("html_path", "")),
                html_anchor=str(row.get("html_anchor", "")),
                message="Evidence span is missing section identity, path, or source locator",
            )
        if len(text) > max(1, int(max_span_characters)):
            oversized += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="oversized_span",
                evidence_id=evidence_id,
                html_path=str(row.get("html_path", "")),
                html_anchor=str(row.get("html_anchor", "")),
                message=f"Evidence span has {len(text)} characters (limit {int(max_span_characters)})",
            )
        if len(text.strip()) < 16:
            tiny += 1
        if str(row.get("section_kind", "")) == "references":
            reference_spans += 1
        if verify_source_text and not _span_text_is_in_source(row, db, source_text_cache):
            unverifiable += 1
            _add_issue(
                issues,
                max_issues,
                issue_type="source_text_mismatch",
                evidence_id=evidence_id,
                html_path=str(row.get("html_path", "")),
                html_anchor=str(row.get("html_anchor", "")),
                message="Stored evidence text is not found in the parsed source document",
            )

    claim_ready = missing_structure == 0 and unverifiable == 0 and orphan_sections == 0
    passed = claim_ready and oversized == 0
    warnings: list[str] = []
    if oversized:
        warnings.append(
            f"{oversized} oversized spans should be split for better retrieval precision; source fidelity and claim traceability remain intact."
        )
    if tiny:
        warnings.append(
            f"{tiny} short spans are retained for source fidelity; rank them below substantive evidence during retrieval."
        )
    return {
        "passed": passed,
        "claim_ready": claim_ready,
        "documents": len(documents),
        "spans": len(rows),
        "sections": section_count,
        "missing_structure_spans": missing_structure,
        "oversized_spans": oversized,
        "tiny_spans": tiny,
        "reference_spans": reference_spans,
        "source_text_mismatches": unverifiable,
        "orphan_sections": orphan_sections,
        "warnings": warnings,
        "issues_truncated": len(issues)
        < missing_structure + oversized + unverifiable,
        "issues": issues,
    }


def _load_structure_rows(db_path: Path) -> tuple[list[dict[str, Any]], int, int]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {str(row[1]) for row in connection.execute("pragma table_info(evidence_spans)")}
        required = {"section_id", "section_path", "source_locator"}
        if not required.issubset(columns):
            rows = [
                {
                    **dict(row),
                    "section_id": "",
                    "section_path": "",
                    "source_locator": "",
                }
                for row in connection.execute(
                    "select evidence_id, doc_id, html_path, html_anchor, section_kind, text from evidence_spans"
                )
            ]
            return rows, 0, 0
        rows = [
            dict(row)
            for row in connection.execute(
                """
                select evidence_id, doc_id, html_path, html_anchor, section_kind, text,
                       section_id, section_path, source_locator
                from evidence_spans
                """
            )
        ]
        tables = {str(row[0]) for row in connection.execute("select name from sqlite_master where type = 'table'")}
        if "document_sections" not in tables:
            return rows, 0, 0
        section_count = int(connection.execute("select count(*) from document_sections").fetchone()[0])
        orphan_sections = int(
            connection.execute(
                """
                select count(*)
                from document_sections child
                left join document_sections parent on parent.section_id = child.parent_section_id
                where child.parent_section_id <> '' and parent.section_id is null
                """
            ).fetchone()[0]
        )
    return rows, section_count, orphan_sections


def _span_text_is_in_source(row: dict[str, Any], db_path: Path, cache: dict[Path, str]) -> bool:
    path = _resolve_html_path(str(row.get("html_path", "")), db_path)
    if not path.is_file():
        return False
    if path not in cache:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() in {".html", ".htm"}:
            raw = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
        elif path.suffix.lower() in {".md", ".markdown"}:
            # The index intentionally removes paired Markdown emphasis while
            # retaining its visible text.  Canonicalize the source in the same
            # way before deciding that an evidence span was altered.
            from .evidence_store import _strip_markdown_inline

            raw = "\n".join(_strip_markdown_inline(line) for line in raw.splitlines())
        cache[path] = _normalized_source_text(raw)
    text = _normalized_source_text(str(row.get("text", "")))
    return bool(text) and text in cache[path]


def _normalized_source_text(value: str) -> str:
    text = str(value or "")
    # Match ingestion._clean_text: PDF extractors frequently insert a visual
    # line-break space between two CJK characters.  It is not semantic and
    # should not make a faithfully stored evidence span look fabricated.
    text = re.sub(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])\s+(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_evidence_link_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                """
                select evidence_id, html_path, html_anchor
                from evidence_spans
                order by evidence_id
                """
            )
        ]


def _resolve_html_path(path_value: str, db_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    db_candidate = (db_path.parent / path).resolve()
    if db_candidate.exists():
        return db_candidate
    return cwd_candidate


def _add_issue(
    issues: list[dict[str, str]],
    max_issues: int,
    *,
    issue_type: str,
    evidence_id: str,
    html_path: str,
    html_anchor: str,
    message: str,
) -> None:
    if len(issues) >= max(0, int(max_issues)):
        return
    issues.append(
        {
            "type": issue_type,
            "evidence_id": evidence_id,
            "html_path": html_path,
            "html_anchor": html_anchor,
            "message": message,
        }
    )
