from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scansci_html.deep_research_evidence import (
    build_task_fulltext_evidence,
    task_evidence_reader_path,
)


def _paper_text(section: str) -> str:
    return f"""Abstract

This study reports a substantial and traceable finding about evidence-grounded retrieval for scientific research systems.

{section}

The evaluation compares two retrieval configurations across multiple realistic scientific questions and documents their failure boundaries.

Discussion

The results show that source-level traceability is necessary when a system produces a research synthesis from acquired full text.
"""


def test_task_fulltext_evidence_is_indexed_and_reader_is_run_scoped(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    first = tmp_path / "paper-one.txt"
    second = tmp_path / "paper-two.txt"
    first.write_text(_paper_text("Methods"), encoding="utf-8")
    second.write_text(_paper_text("Results"), encoding="utf-8")

    result = build_task_fulltext_evidence(
        workspace,
        "run-fulltext",
        [
            {"title": "Paper one", "doi": "10.1000/one", "files": [str(first)]},
            {"title": "Paper two", "doi": "10.1000/two", "files": [str(second)]},
        ],
        min_sentence_length=20,
    )

    assert result["evidence_level"] == "fulltext"
    assert result["index"]["documents"] == 2
    assert result["index"]["spans"] >= 6
    assert result["quality"]["passed"] is True
    assert not (tmp_path / "evidence.sqlite").exists()
    evidence_db = Path(result["evidence_db"])
    with sqlite3.connect(evidence_db) as connection:
        doc_id = str(connection.execute("select doc_id from source_documents order by doc_id limit 1").fetchone()[0])

    reader = task_evidence_reader_path(workspace, "run-fulltext", evidence_db, doc_id)
    assert reader.name.endswith(".evidence.html")
    assert 'data-evidence-id=' in reader.read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        task_evidence_reader_path(workspace, "other-run", evidence_db, doc_id)

