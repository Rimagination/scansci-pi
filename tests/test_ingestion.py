from __future__ import annotations

import base64
from pathlib import Path

import fitz
from openpyxl import Workbook

from scansci_html.evidence_store import index_evidence_library
from scansci_html.ingestion import (
    ingest_sources,
    ingestion_context,
    ingestion_source_path,
    ingestion_source_text,
)
from scansci_html.library_manager import import_library_folder
from scansci_html.workspace import initialize_notebook, sync_sources_from_evidence_store


def _pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "Traceable evidence improves scientific review decisions.", fontsize=13)
    document.save(path)
    document.close()
    return path


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "seed.html").write_text(
        "<article><h1>Seed</h1><p>The seed evidence initializes the workspace.</p></article>",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.sqlite"
    index_evidence_library(seed, db_path=evidence, min_sentence_length=10)
    workspace = tmp_path / "workspace.sqlite"
    initialize_notebook(workspace, notebook_id="research", title="Research", root_path=seed)
    sync_sources_from_evidence_store(workspace, evidence, notebook_id="research")
    return workspace, evidence


def test_ingestion_accepts_data_urls_and_hides_private_paths(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    payload = base64.b64encode("A direct attachment can be used without a knowledge base.".encode()).decode()

    job = ingest_sources(
        workspace,
        [{"name": "note.txt", "data_url": f"data:text/plain;base64,{payload}"}],
    )

    source = job["sources"][0]
    assert job["status"] == "completed"
    assert source["parser"] in {"markitdown", "text"}
    assert "path" not in source
    assert "text_path" not in source
    assert "direct attachment" in ingestion_source_text(workspace, job["job_id"], source["source_id"])
    assert ingestion_source_path(workspace, job["job_id"], source["source_id"]).suffix == ".txt"


def test_pdf_ingestion_preserves_page_count_and_source_context(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    source_path = _pdf(tmp_path / "study.pdf")

    job = ingest_sources(workspace, [{"name": source_path.name, "path": str(source_path)}])

    assert job["sources"][0]["page_count"] == 1
    assert "Traceable evidence" in ingestion_context(workspace, job["job_id"])
    assert job["sources"][0]["file_url"].endswith("/file")


def test_xlsx_ingestion_has_a_packaged_openpyxl_fallback(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace.sqlite"
    source = tmp_path / "observations.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(["sample", "value"])
    sheet.append(["A", 42])
    workbook.save(source)
    monkeypatch.setattr("scansci_html.ingestion._markitdown_text", lambda _path: "")

    job = ingest_sources(workspace, [{"name": source.name, "path": str(source)}])
    text = ingestion_source_text(workspace, job["job_id"], job["sources"][0]["source_id"])

    assert job["sources"][0]["parser"] == "openpyxl"
    assert "## Results" in text
    assert "A | 42" in text


def test_pdf_only_folder_can_become_a_searchable_library(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    folder = tmp_path / "pdf-library"
    folder.mkdir()
    _pdf(folder / "paper.pdf")

    result = import_library_folder(workspace, evidence, notebook_id="research", folder_path=folder)

    assert result["source_format"] == "markdown"
    assert result["indexed"]["documents"] == 2
    assert result["notebook"]["counts"]["sources"] == 2
    assert result["notebook"]["metadata"]["imported_from_folder"] == str(folder.resolve())
