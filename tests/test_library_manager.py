from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from scansci_html.evidence_store import index_evidence_library
from scansci_html.library_manager import connect_local_zotero, import_library_folder, register_zotero_library
from scansci_html.webapp import NotebookWebApp
from scansci_html.workspace import initialize_notebook, load_workspace_summary, sync_sources_from_evidence_store


def _paper(path: Path, title: str, sentence: str) -> None:
    path.write_text(
        f"<article><h1>{title}</h1><h2>Results</h2><p>{sentence}</p></article>",
        encoding="utf-8",
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    old_library = tmp_path / "old-library"
    old_library.mkdir()
    _paper(old_library / "old.html", "Old paper", "The original evidence remains available before switching folders.")
    evidence = tmp_path / "evidence.sqlite"
    index_evidence_library(old_library, db_path=evidence, inject_evidence_html=True, min_sentence_length=10)
    workspace = tmp_path / "workspace.sqlite"
    initialize_notebook(workspace, notebook_id="research", title="Research", root_path=old_library)
    sync_sources_from_evidence_store(workspace, evidence, notebook_id="research")
    return workspace, evidence


def test_import_library_folder_replaces_sources_and_persists_root(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    selected = tmp_path / "selected-library"
    selected.mkdir()
    _paper(selected / "one.html", "Paper one", "Treatment one improved the measured outcome in the study population.")
    _paper(selected / "two.html", "Paper two", "Treatment two showed a distinct response in an independent experiment.")

    result = import_library_folder(
        workspace,
        evidence,
        notebook_id="research",
        folder_path=selected,
    )

    notebook = result["notebook"]
    assert result["source_format"] == "html"
    assert result["indexed"]["documents"] == 2
    assert notebook["root_path"] == str(selected.resolve())
    assert notebook["counts"]["sources"] == 2
    assert {source["title"] for source in notebook["sources"]} == {"Paper one", "Paper two"}


def test_each_notebook_keeps_an_isolated_evidence_index(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    evidence = tmp_path / "evidence.sqlite"
    first = tmp_path / "first-library"
    second = tmp_path / "second-library"
    first.mkdir()
    second.mkdir()
    _paper(first / "first.html", "First paper", "The first library contains a unique ecological treatment result.")
    _paper(second / "second.html", "Second paper", "The second library contains a distinct photovoltaic microclimate result.")
    initialize_notebook(workspace, notebook_id="first", title="First", root_path=first)
    initialize_notebook(workspace, notebook_id="second", title="Second", root_path=second)

    import_library_folder(workspace, evidence, notebook_id="first", folder_path=first)
    import_library_folder(workspace, evidence, notebook_id="second", folder_path=second)

    summary = load_workspace_summary(workspace)
    notebooks = {item["notebook_id"]: item for item in summary["notebooks"]}
    first_db = Path(notebooks["first"]["sources"][0]["evidence_db_path"])
    second_db = Path(notebooks["second"]["sources"][0]["evidence_db_path"])
    assert first_db != second_db
    with sqlite3.connect(first_db) as connection:
        assert connection.execute("select title from source_documents").fetchall() == [("First paper",)]
    with sqlite3.connect(second_db) as connection:
        assert connection.execute("select title from source_documents").fetchall() == [("Second paper",)]


def test_invalid_folder_does_not_replace_existing_library(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="没有可索引"):
        import_library_folder(workspace, evidence, notebook_id="research", folder_path=empty)

    notebook = load_workspace_summary(workspace, notebook_id="research")["notebooks"][0]
    assert notebook["counts"]["sources"] == 1
    assert notebook["sources"][0]["title"] == "Old paper"


def test_import_library_folder_uses_sqlite_backup_when_windows_blocks_replace(tmp_path: Path, monkeypatch):
    workspace, evidence = _workspace(tmp_path)
    selected = tmp_path / "selected-library"
    selected.mkdir()
    _paper(selected / "new.html", "Replacement paper", "The fallback safely installs the newly selected evidence library.")

    def blocked_replace(source, destination):
        raise PermissionError("database is open")

    monkeypatch.setattr("scansci_html.library_manager.os.replace", blocked_replace)
    result = import_library_folder(workspace, evidence, notebook_id="research", folder_path=selected)

    assert result["notebook"]["counts"]["sources"] == 1
    assert result["notebook"]["sources"][0]["title"] == "Replacement paper"


def test_obsidian_vault_import_persists_the_library_kind(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    vault = tmp_path / "research-vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "# Field notebook\n\nThe Obsidian knowledge base preserves searchable experimental observations.",
        encoding="utf-8",
    )

    result = import_library_folder(
        workspace,
        evidence,
        notebook_id="research",
        folder_path=vault,
        library_kind="obsidian",
    )

    assert result["library_kind"] == "obsidian"
    assert result["notebook"]["metadata"]["library_kind"] == "obsidian"
    assert result["notebook"]["counts"]["sources"] == 1


def test_register_zotero_library_keeps_the_active_knowledge_root_and_lists_pdfs(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    zotero = tmp_path / "zotero-storage"
    zotero.mkdir()
    (zotero / "paper-one.pdf").write_bytes(b"%PDF-1.4\nexample")
    (zotero / "paper-two.pdf").write_bytes(b"%PDF-1.4\nexample")
    active_root = load_workspace_summary(workspace, notebook_id="research")["notebooks"][0]["root_path"]

    result = register_zotero_library(workspace, notebook_id="research", folder_path=zotero)

    assert result["zotero"]["pdf_count"] == 2
    assert result["notebook"]["root_path"] == active_root
    assert result["notebook"]["metadata"]["zotero"]["path"] == str(zotero.resolve())
    assert result["notebook"]["metadata"]["zotero"]["sample_titles"] == ["paper-one", "paper-two"]


def test_connect_local_zotero_reads_metadata_without_a_cloud_key(tmp_path: Path):
    workspace, _evidence = _workspace(tmp_path)

    class FakeZotero:
        def items(self, *, limit):
            assert limit == 120
            return [
                {
                    "key": "ABC123",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Evidence-linked interfaces",
                        "DOI": "10.1000/example",
                        "date": "2026",
                        "publicationTitle": "Research UI",
                        "creators": [{"firstName": "Ada", "lastName": "Li"}],
                    },
                },
                {"key": "PDF123", "data": {"itemType": "attachment", "contentType": "application/pdf"}},
            ]

    result = connect_local_zotero(workspace, notebook_id="research", client=FakeZotero())

    assert result["zotero"]["connection"] == "local-api"
    assert result["zotero"]["item_count"] == 1
    assert result["zotero"]["pdf_count"] == 1
    assert result["zotero"]["items"][0]["creators"] == ["Ada Li"]


def test_webapp_folder_endpoint_returns_refreshed_workspace(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    selected = tmp_path / "selected"
    selected.mkdir()
    _paper(selected / "new.html", "New paper", "The selected folder is now the active evidence library for this notebook.")
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence)

    response = app.dispatch(
        "POST",
        "/api/library/folder",
        json.dumps({"notebook_id": "research", "path": str(selected)}).encode("utf-8"),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["workspace"]["counts"]["sources"] == 1
    assert payload["notebook"]["root_path"] == str(selected.resolve())


def test_webapp_zotero_endpoint_registers_a_local_pdf_shelf(tmp_path: Path):
    workspace, evidence = _workspace(tmp_path)
    storage = tmp_path / "zotero" / "storage"
    storage.mkdir(parents=True)
    (storage / "paper.pdf").write_bytes(b"%PDF-1.4\nexample")
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence)

    response = app.dispatch(
        "POST",
        "/api/library/zotero",
        json.dumps({"notebook_id": "research", "path": str(storage)}).encode("utf-8"),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["zotero"]["pdf_count"] == 1
    assert payload["notebook"]["metadata"]["zotero"]["path"] == str(storage.resolve())


def test_webapp_first_folder_import_creates_a_notebook_automatically(tmp_path: Path):
    workspace = tmp_path / "fresh" / "workspace.sqlite"
    evidence = tmp_path / "fresh" / "evidence.sqlite"
    selected = tmp_path / "photovoltaic-literature"
    selected.mkdir()
    _paper(selected / "paper.html", "PV ecology", "Photovoltaic facilities can alter local microclimate and vegetation patterns.")
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence)

    response = app.dispatch(
        "POST",
        "/api/library/folder",
        json.dumps({"path": str(selected), "library_kind": "folder"}).encode("utf-8"),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["notebook"]["title"] == "photovoltaic-literature"
    assert payload["workspace"]["counts"]["sources"] == 1
