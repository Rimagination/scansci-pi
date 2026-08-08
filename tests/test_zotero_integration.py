from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from scansci_html.zotero_integration import (
    ZoteroIntegrationError,
    search_zotero_library,
    zotero_file_url,
    zotero_fulltext,
    zotero_import_records,
    zotero_status,
)


def _zotero_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data_dir = tmp_path / "Zotero"
    attachment_dir = data_dir / "storage" / "PDFKEY01"
    attachment_dir.mkdir(parents=True)
    pdf_path = attachment_dir / "forest.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture")
    (attachment_dir / ".zotero-ft-cache").write_text(
        "Tropical forest primary productivity depends on climate, canopy structure, and model assumptions.",
        encoding="utf-8",
    )
    database = data_dir / "zotero.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, dateModified TEXT, key TEXT);
        CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY, dateDeleted TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, orderIndex INTEGER);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, key TEXT);
        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER, orderIndex INTEGER);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER);
        CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
        INSERT INTO itemTypes VALUES (1, 'journalArticle'), (2, 'attachment');
        INSERT INTO items VALUES (1, 1, '2026-07-23', 'ITEM0001'), (2, 2, '2026-07-23', 'PDFKEY01');
        INSERT INTO fields VALUES
          (1, 'title'), (2, 'DOI'), (3, 'date'), (4, 'publicationTitle'), (5, 'abstractNote');
        INSERT INTO itemDataValues VALUES
          (1, 'Forest productivity models'), (2, '10.1000/forest'), (3, '2026'),
          (4, 'Ecology Journal'), (5, 'A comparison of model assumptions for tropical forests.');
        INSERT INTO itemData VALUES (1,1,1), (1,2,2), (1,3,3), (1,4,4), (1,5,5);
        INSERT INTO creators VALUES (1, 'Ada', 'Li');
        INSERT INTO itemCreators VALUES (1,1,0);
        INSERT INTO collections VALUES (1, '植被生产力模型', NULL, 'COLL0001');
        INSERT INTO collectionItems VALUES (1,1,0);
        INSERT INTO tags VALUES (1, 'forest'), (2, 'priority');
        INSERT INTO itemTags VALUES (1,1), (1,2);
        INSERT INTO itemAttachments VALUES (2,1,1,'application/pdf','storage:forest.pdf');
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(data_dir))
    return data_dir, pdf_path


def test_zotero_search_reads_real_metadata_collections_and_cached_fulltext(tmp_path: Path, monkeypatch) -> None:
    _data_dir, pdf_path = _zotero_fixture(tmp_path, monkeypatch)

    result = search_zotero_library("forest productivity", limit=5)

    assert result["connection"] == "local-database"
    assert result["read_only"] is True
    assert result["library"]["item_count"] == 1
    assert result["library"]["pdf_count"] == 1
    assert result["collections"][0]["name"] == "植被生产力模型"
    assert result["items"][0]["item_key"] == "ITEM0001"
    assert result["items"][0]["tags"] == ["forest", "priority"]
    assert result["items"][0]["attachments"][0]["path"] == str(pdf_path.resolve())
    assert result["items"][0]["evidence_kind"] == "zotero-indexed-fulltext"
    assert "primary productivity" in result["items"][0]["fulltext_excerpt"]


def test_zotero_inventory_query_and_offline_attachment_operations(tmp_path: Path, monkeypatch) -> None:
    _zotero_fixture(tmp_path, monkeypatch)

    result = search_zotero_library("总结核心主题", limit=5)
    fulltext = zotero_fulltext("PDFKEY01")
    file_result = zotero_file_url("PDFKEY01")
    status = zotero_status(timeout=0.05)

    assert result["mode"] == "inventory"
    assert result["items"][0]["title"] == "Forest productivity models"
    assert fulltext["connection"] == "local-fulltext-cache"
    assert file_result["exists"] is True
    assert status["database_readable"] is True
    assert status["read_mode"] == "local-database"

    wildcard = search_zotero_library("*", limit=5)
    assert wildcard["mode"] == "inventory"
    assert wildcard["count"] == 1


def test_zotero_status_does_not_fall_back_when_a_manual_directory_is_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_data_dir, _pdf_path = _zotero_fixture(tmp_path, monkeypatch)
    missing_data_dir = tmp_path / "Not-Zotero"

    status = zotero_status(data_dir=missing_data_dir, timeout=0.01)

    assert valid_data_dir.exists()
    assert status["installed"] is False
    assert status["database_readable"] is False
    assert status["read_mode"] == ("local-api" if status["api_running"] else "unavailable")


def test_zotero_connector_write_requires_explicit_confirmation() -> None:
    with pytest.raises(ZoteroIntegrationError, match="明确确认"):
        zotero_import_records("@article{x, title={X}}", record_format="bibtex", confirmed=False)
