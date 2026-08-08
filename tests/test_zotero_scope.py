from pathlib import Path
import sqlite3

from scansci_html.research_agent import ResearchAgentRuntime
from scansci_html.zotero_scope import (
    filter_zotero_result,
    infer_zotero_tag_scope,
    resolve_zotero_tag_scope,
    sync_zotero_document_tags,
)


def _evidence_store(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            create table source_documents (
              doc_id text primary key,
              title text,
              doi text,
              source_url text,
              html_path text,
              publication_year integer
            );
            insert into source_documents values
              ('doc-forest', 'Forest productivity models', '10.1000/forest', 'C:/Zotero/storage/FOREST/forest.pdf', '', 2025);
            insert into source_documents values
              ('doc-review', 'A review of model assumptions', '', 'C:/Zotero/storage/REVIEW/review.pdf', '', 2024);
            """
        )
    return path


def test_zotero_tag_scope_maps_items_to_indexed_documents(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    notebook = {
        "notebook_id": "zotero",
        "metadata": {
            "library_kind": "zotero",
            "zotero": {
                "items": [
                    {
                        "key": "FOREST",
                        "title": "Forest productivity models",
                        "doi": "https://doi.org/10.1000/forest",
                        "tags": ["forest", "priority"],
                    },
                    {
                        "key": "REVIEW",
                        "title": "A review of model assumptions",
                        "tags": ["review"],
                    },
                ]
            },
        },
    }

    result = resolve_zotero_tag_scope(
        notebook,
        database,
        {"type": "zotero-tag", "tags": ["priority"]},
    )

    assert result["status"] == "applied"
    assert result["matched_item_count"] == 1
    assert result["doc_ids"] == ["doc-forest"]


def test_sync_zotero_document_tags_refreshes_sidecar_without_touching_sources(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    result = sync_zotero_document_tags(
        database,
        [
            {
                "title": "Forest productivity models",
                "doi": "10.1000/forest",
                "tags": [{"tag": "priority"}, "forest"],
            },
            {"title": "not in the evidence store", "tags": ["ignored"]},
        ],
    )

    assert result == {
        "status": "ready",
        "matched_items": 1,
        "documents": 1,
        "tags": 2,
    }
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "select doc_id, tag, normalized_tag from document_tags order by tag"
        ).fetchall()
    assert rows == [
        ("doc-forest", "forest", "forest"),
        ("doc-forest", "priority", "priority"),
    ]


def test_zotero_tag_scope_supports_all_match_and_explicit_empty_result(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    notebook = {
        "metadata": {
            "zotero": {
                "items": [{"title": "Forest productivity models", "tags": ["forest"]}]
            }
        }
    }

    result = resolve_zotero_tag_scope(
        notebook,
        database,
        {"type": "zotero-tag", "tags": ["forest", "priority"], "match": "all"},
    )

    assert result["active"] is True
    assert result["status"] == "empty"
    assert result["doc_ids"] == []


def test_zotero_tag_scope_filters_metadata_results_and_catalog_rows(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    filtered = filter_zotero_result(
        {
            "count": 2,
            "items": [
                {"title": "Forest productivity models", "tags": ["priority"], "attachments": [{}]},
                {"title": "A review of model assumptions", "tags": ["review"], "attachments": []},
            ],
            "library": {"item_count": 2, "pdf_count": 1},
        },
        {"type": "zotero-tag", "tags": ["priority"]},
    )

    assert filtered["count"] == 1
    assert filtered["items"][0]["title"] == "Forest productivity models"
    assert filtered["library"] == {"item_count": 1, "pdf_count": 1}

    total, matched, rows = ResearchAgentRuntime._catalog_rows_from_evidence_db(
        database,
        [],
        preview_limit=10,
        scope_doc_ids={"doc-forest"},
    )
    assert (total, matched) == (1, 1)
    assert [row["doc_id"] for row in rows] == ["doc-forest"]


def test_infer_zotero_tag_scope_profiles_question_against_tagged_titles(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    notebook = {
        "metadata": {
            "library_kind": "zotero",
            "zotero": {
                "items": [
                    {"title": "Forest productivity models", "tags": ["forest ecology"]},
                    {"title": "A review of model assumptions", "tags": ["forest ecology"]},
                ]
            },
        }
    }

    result = infer_zotero_tag_scope(
        notebook,
        database,
        "Which forest productivity models are supported by the evidence?",
        max_scope_fraction=1.0,
    )

    assert result["active"] is True
    assert result["mode"] == "auto"
    assert result["tags"] == ["forest ecology"]
    assert set(result["doc_ids"]) == {"doc-forest", "doc-review"}


def test_normal_zotero_retrieval_keeps_tags_out_of_hard_filters(tmp_path: Path) -> None:
    database = _evidence_store(tmp_path / "evidence.sqlite")
    runtime = ResearchAgentRuntime(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=database,
    )
    notebook = {
        "notebook_id": "zotero",
        "metadata": {
            "library_kind": "zotero",
            "zotero": {
                "items": [
                    {"title": "Forest productivity models", "tags": ["priority"]},
                ]
            },
        },
    }

    resolution = runtime._knowledge_scope_resolution(notebook, database, {}, "priority")

    assert resolution == {"active": False, "status": "automatic-ranking"}
    assert runtime._knowledge_filters_for_notebook(notebook, database, {}, "priority") == {}
