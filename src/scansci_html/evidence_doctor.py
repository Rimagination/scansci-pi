from __future__ import annotations

from pathlib import Path
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
