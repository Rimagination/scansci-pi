import json
import sqlite3
from pathlib import Path

import pytest

from scansci_html.app_settings import load_settings, save_settings, settings_path
from scansci_html.evidence_store import index_markdown_library
from scansci_html.library_manager import notebook_evidence_db
from scansci_html.vector_index import load_embedding_cache_rows, prewarm_embedding_cache
from scansci_html.vector_storage import configure_vector_index_root, migrate_vector_indexes
from scansci_html.webapp import NotebookWebApp
from scansci_html.workspace import load_workspace_summary, sync_sources_from_evidence_store


def test_general_settings_persist_vector_index_directory(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"

    saved = save_settings(
        workspace,
        {"general": {"directories": {"vector_index": r"D:\ScanSci\vectors"}}},
    )

    assert saved["general"]["directories"]["vector_index"] == r"D:\ScanSci\vectors"
    persisted = json.loads(settings_path(workspace).read_text(encoding="utf-8"))
    assert persisted["general"]["directories"]["vector_index"] == r"D:\ScanSci\vectors"


def test_notebook_evidence_db_uses_configured_vector_index_root(tmp_path: Path):
    evidence_db = tmp_path / "evidence.sqlite"
    custom_root = tmp_path / "vectors"
    try:
        configure_vector_index_root(custom_root)
        target = notebook_evidence_db(evidence_db, "kb_demo")
        assert target == custom_root / "evidence.libraries" / "kb_demo.sqlite"
    finally:
        configure_vector_index_root(None)


def test_notebook_evidence_db_keeps_isolated_collection_name_for_preview_db(tmp_path: Path):
    evidence_db = tmp_path / "evidence.libraries" / "kb_existing.sqlite"
    try:
        configure_vector_index_root(tmp_path / "vectors")
        target = notebook_evidence_db(evidence_db, "kb_next")
        assert target == tmp_path / "vectors" / "evidence.libraries" / "kb_next.sqlite"
    finally:
        configure_vector_index_root(None)


def test_migrate_vector_indexes_copies_db_and_updates_workspace_paths(tmp_path: Path):
    evidence_db = tmp_path / "evidence.sqlite"
    old_root = tmp_path / "old-vectors"
    new_root = tmp_path / "new-vectors"
    old_library_root = old_root / "evidence.libraries"
    old_library_root.mkdir(parents=True)
    old_db = old_library_root / "kb_demo.sqlite"
    with sqlite3.connect(old_db) as connection:
        connection.execute("create table source_documents (doc_id text primary key, title text, doi text, source_url text, publication_year integer, html_path text, evidence_html_path text)")
        connection.execute("insert into source_documents values ('doc-1', 'Paper', '', '', 2024, '', '')")
        connection.commit()

    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, old_db, notebook_id="kb_demo")

    result = migrate_vector_indexes(
        workspace=workspace,
        evidence_db=evidence_db,
        old_root=old_root,
        new_root=new_root,
    )

    new_db = new_root / "evidence.libraries" / "kb_demo.sqlite"
    assert result["migrated"] == 1
    assert new_db.is_file()
    assert old_db.is_file()
    summary = load_workspace_summary(workspace, notebook_id="kb_demo")
    assert summary["notebooks"][0]["sources"][0]["evidence_db_path"] == str(new_db)


def test_migrate_vector_indexes_rolls_back_created_destinations_on_failure(tmp_path: Path):
    evidence_db = tmp_path / "evidence.sqlite"
    old_root = tmp_path / "old-vectors"
    new_root = tmp_path / "new-vectors"
    old_library_root = old_root / "evidence.libraries"
    old_library_root.mkdir(parents=True)
    for name in ("kb_one.sqlite", "kb_two.sqlite"):
        with sqlite3.connect(old_library_root / name) as connection:
            connection.execute("create table marker (value text)")
            connection.execute("insert into marker values (?)", (name,))
            connection.commit()
    (new_root / "evidence.libraries").mkdir(parents=True)
    (new_root / "evidence.libraries" / "kb_two.sqlite").write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        migrate_vector_indexes(
            workspace=tmp_path / "workspace.sqlite",
            evidence_db=evidence_db,
            old_root=old_root,
            new_root=new_root,
        )

    assert not (new_root / "evidence.libraries" / "kb_one.sqlite").exists()
    assert (old_library_root / "kb_one.sqlite").is_file()


def test_settings_api_applies_vector_index_directory_and_reports_migration(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    evidence_db = tmp_path / "evidence.sqlite"
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence_db)
    settings = load_settings(workspace)
    selected = tmp_path / "vectors"
    settings["general"]["directories"]["vector_index"] = str(selected)

    response = app.dispatch("POST", "/api/settings", json.dumps({"settings": settings}).encode("utf-8"))
    assert response.status == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["general"]["directories"]["vector_index"] == str(selected.resolve())
    assert payload["storage"]["applied"]["vector_index"] == str(selected.resolve())
    assert payload["storage"]["vector_index_migration"]["migrated"] == 0
    assert notebook_evidence_db(evidence_db, "kb_demo") == selected / "evidence.libraries" / "kb_demo.sqlite"
    configure_vector_index_root(None)


def test_settings_api_migrates_existing_default_indexes(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    evidence_db = tmp_path / "evidence.sqlite"
    old_db = tmp_path / "evidence.libraries" / "kb_demo.sqlite"
    old_db.parent.mkdir(parents=True)
    with sqlite3.connect(old_db) as connection:
        connection.execute("create table source_documents (doc_id text primary key, title text, doi text, source_url text, publication_year integer, html_path text, evidence_html_path text)")
        connection.execute("insert into source_documents values ('doc-1', 'Paper', '', '', 2024, '', '')")
        connection.commit()
    sync_sources_from_evidence_store(workspace, old_db, notebook_id="kb_demo")
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence_db)
    settings = load_settings(workspace)
    selected = tmp_path / "vectors"
    settings["general"]["directories"]["vector_index"] = str(selected)

    response = app.dispatch("POST", "/api/settings", json.dumps({"settings": settings}).encode("utf-8"))
    assert response.status == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["storage"]["vector_index_migration"]["migrated"] == 1
    assert (selected / "evidence.libraries" / "kb_demo.sqlite").is_file()
    summary = load_workspace_summary(workspace, notebook_id="kb_demo")
    assert summary["notebooks"][0]["sources"][0]["evidence_db_path"] == str(selected / "evidence.libraries" / "kb_demo.sqlite")
    configure_vector_index_root(None)


def test_vector_path_migration_reuses_active_generation_without_embedding(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.md").write_text(
        "# Paper\n\n## Results\n\nA stable vector survives a storage-directory move.",
        encoding="utf-8",
    )
    evidence_db = tmp_path / "evidence.sqlite"
    old_db = notebook_evidence_db(evidence_db, "kb_demo")
    index_markdown_library(library, db_path=old_db, min_sentence_length=10, incremental=True)

    class Provider:
        dimensions = 2
        cache_key = "sentence-transformers:path-migration-test"

        def __init__(self):
            self.calls: list[list[str]] = []

        def embed_query(self, _query):
            return [1.0, 0.0]

        def embed_texts(self, texts):
            self.calls.append([str(text) for text in texts])
            return [[1.0, 0.0] for _text in texts]

    first_provider = Provider()
    prewarm_embedding_cache(old_db, load_embedding_cache_rows(old_db), provider=first_provider)
    assert first_provider.calls

    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, old_db, notebook_id="kb_demo")
    new_root = tmp_path / "moved-vectors"
    result = migrate_vector_indexes(
        workspace=workspace,
        evidence_db=evidence_db,
        old_root=tmp_path,
        new_root=new_root,
    )
    assert result["migrated"] == 1

    new_db = new_root / "evidence.libraries" / "kb_demo.sqlite"
    second_provider = Provider()
    cache = prewarm_embedding_cache(new_db, load_embedding_cache_rows(new_db), provider=second_provider)

    assert cache["ready"] is True
    assert cache["embedded"] == 0
    assert cache["reused"] == 1
    assert second_provider.calls == []
