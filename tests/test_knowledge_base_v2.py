import json
import sqlite3
from pathlib import Path

from scansci_html.evidence_store import (
    build_library_overview,
    ensure_library_overview,
    index_markdown_library,
    knowledge_base_snapshot,
)
from scansci_html.research_agent import ResearchAgentRuntime
from scansci_html.research_runs import StageSpec
from scansci_html.workspace import initialize_notebook, sync_sources_from_evidence_store


def _write_markdown(path: Path, title: str, body: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n\n## Results\n\n{body or 'This evidence sentence is long enough to remain a traceable source fragment.'}\n",
        encoding="utf-8",
    )


def test_document_catalog_has_exactly_one_summary_for_each_of_420_documents(tmp_path: Path):
    library = tmp_path / "library"
    for index in range(420):
        _write_markdown(library / f"paper-{index:03d}.md", f"Paper {index:03d}")
    db_path = tmp_path / "evidence.sqlite"

    indexed = index_markdown_library(library, db_path=db_path, min_sentence_length=10, incremental=True)
    overview = build_library_overview(db_path)

    assert indexed["changed_documents"] == 420
    assert overview["documents"] == 420
    assert overview["document_cards"] == 420
    with sqlite3.connect(db_path) as connection:
        document_count, distinct_documents = connection.execute(
            "select count(*), count(distinct doc_id) from source_documents"
        ).fetchone()
        card_count, distinct_cards = connection.execute(
            "select count(*), count(distinct doc_id) from document_cards"
        ).fetchone()
        empty_summaries = connection.execute(
            "select count(*) from document_cards where trim(summary) = ''"
        ).fetchone()[0]

    assert (document_count, distinct_documents) == (420, 420)
    assert (card_count, distinct_cards) == (420, 420)
    assert empty_summaries == 0


def test_reopen_and_move_reuse_content_hash_index_version_and_source_locator(tmp_path: Path):
    original_root = tmp_path / "original"
    source = original_root / "paper.md"
    _write_markdown(
        source,
        "Stable source",
        "A source sentence keeps its section, paragraph, and character location after a move.",
    )
    db_path = tmp_path / "evidence.sqlite"

    first = index_markdown_library(original_root, db_path=db_path, min_sentence_length=10, incremental=True)
    with sqlite3.connect(db_path) as connection:
        before = connection.execute(
            """
            select d.doc_id, d.content_hash, r.source_fingerprint, r.index_version,
                   e.evidence_id, e.section_path, e.char_start, e.char_end,
                   e.source_locator, e.html_path
            from source_documents d
            join document_index_revisions r on r.doc_id = d.doc_id
            join evidence_spans e on e.doc_id = d.doc_id
            """
        ).fetchone()
    snapshot_before = knowledge_base_snapshot(db_path, knowledge_base_id="kb-stable")

    reopened = index_markdown_library(original_root, db_path=db_path, min_sentence_length=10, incremental=True)
    moved_root = tmp_path / "moved"
    moved_root.mkdir()
    source.rename(moved_root / "renamed-paper.md")
    rebound = index_markdown_library(moved_root, db_path=db_path, min_sentence_length=10, incremental=True)

    with sqlite3.connect(db_path) as connection:
        after = connection.execute(
            """
            select d.doc_id, d.content_hash, r.source_fingerprint, r.index_version,
                   e.evidence_id, e.section_path, e.char_start, e.char_end,
                   e.source_locator, e.html_path
            from source_documents d
            join document_index_revisions r on r.doc_id = d.doc_id
            join evidence_spans e on e.doc_id = d.doc_id
            """
        ).fetchone()
        evidence_count = connection.execute("select count(*) from evidence_spans").fetchone()[0]
    snapshot_after = knowledge_base_snapshot(db_path, knowledge_base_id="kb-stable")

    assert first["changed_documents"] == 1
    assert reopened["reused_documents"] == 1
    assert reopened["changed_documents"] == 0
    assert rebound["reused_documents"] == 1
    assert rebound["changed_documents"] == 0
    assert after[:4] == before[:4]
    assert after[4] == before[4]
    assert after[5:9] == before[5:9]
    assert Path(after[9]).resolve() == (moved_root / "renamed-paper.md").resolve()
    assert Path(after[9]).is_file()
    assert after[7] > after[6]
    assert after[8].startswith("anchor:")
    source_text = (moved_root / "renamed-paper.md").read_text(encoding="utf-8")
    assert "source sentence" in source_text
    assert evidence_count == 1
    assert snapshot_after["index_version"] == snapshot_before["index_version"]
    assert snapshot_after["evidence_snapshot"]["snapshot_id"] == snapshot_before["evidence_snapshot"]["snapshot_id"]


def test_adding_one_file_updates_one_document_and_preserves_old_evidence_and_vectors(tmp_path: Path):
    library = tmp_path / "library"
    _write_markdown(library / "first.md", "First paper")
    _write_markdown(library / "second.md", "Second paper")
    db_path = tmp_path / "evidence.sqlite"
    index_markdown_library(library, db_path=db_path, min_sentence_length=10, incremental=True)
    build_library_overview(db_path)

    with sqlite3.connect(db_path) as connection:
        old_documents = [row[0] for row in connection.execute("select doc_id from source_documents order by doc_id")]
        old_evidence = connection.execute(
            "select evidence_id, doc_id, text from evidence_spans order by evidence_id"
        ).fetchall()
        old_revisions = connection.execute(
            "select doc_id, source_fingerprint, index_version from document_index_revisions order by doc_id"
        ).fetchall()
        connection.executemany(
            """
            insert into document_card_embeddings(
                doc_id, provider, dimensions, source_digest, embedding_json
            ) values (?, 'test-cache', 2, ?, ?)
            """,
            [(doc_id, fingerprint, json.dumps([0.1, 0.2])) for doc_id, fingerprint, _ in old_revisions],
        )
        connection.commit()
        old_vector_count = connection.execute("select count(*) from document_card_embeddings").fetchone()[0]

    _write_markdown(library / "third.md", "Third paper")
    result = index_markdown_library(library, db_path=db_path, min_sentence_length=10, incremental=True)

    with sqlite3.connect(db_path) as connection:
        new_evidence = connection.execute(
            "select evidence_id, doc_id, text from evidence_spans order by evidence_id"
        ).fetchall()
        new_revisions = connection.execute(
            "select doc_id, source_fingerprint, index_version from document_index_revisions order by doc_id"
        ).fetchall()
        new_vector_count = connection.execute("select count(*) from document_card_embeddings").fetchone()[0]
        old_vector_rows = connection.execute(
            "select doc_id from document_card_embeddings order by doc_id"
        ).fetchall()

    assert result["changed_documents"] == 1
    assert result["reused_documents"] == 2
    assert result["removed_documents"] == 0
    assert [row[:3] for row in new_evidence if row[1] in old_documents] == old_evidence
    assert len(new_evidence) == len(old_evidence) + 1
    assert new_vector_count == old_vector_count
    assert [row[0] for row in old_vector_rows] == old_documents
    assert [(row[0], row[1], row[2]) for row in new_revisions if row[0] in old_documents] == old_revisions


def test_old_conversation_persists_knowledge_identity_and_can_continue(tmp_path: Path):
    library = tmp_path / "library"
    _write_markdown(library / "paper.md", "Conversation source")
    evidence_db = tmp_path / "evidence.sqlite"
    index_markdown_library(library, db_path=evidence_db, min_sentence_length=10, incremental=True)
    build_library_overview(evidence_db)
    workspace = tmp_path / "workspace.sqlite"
    initialize_notebook(workspace, notebook_id="kb-old", title="Old knowledge base", root_path=library)
    sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="kb-old")
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=evidence_db)
    notebook = runtime._notebook("kb-old")
    knowledge_metadata = runtime._knowledge_run_metadata(notebook)
    run = runtime.store.create_run(
        notebook_id="kb-old",
        workflow_type="evidence_index",
        title="Old evidence conversation",
        input_payload={},
        stages=[StageSpec("index", "建立索引", "tool")],
        metadata=knowledge_metadata,
    )

    saved = runtime.store.get_run(run["run_id"])
    continued = runtime.continue_run_conversation(run["run_id"], {"content": "这个知识库有什么？"})
    continued_run = continued["run"]

    assert saved["metadata"]["knowledge_base_ids"] == ["kb-old"]
    assert saved["metadata"]["index_version"]["kb-old"] >= 1
    assert saved["metadata"]["evidence_snapshot"]["kb-old"]["document_count"] == 1
    assert continued["agent_runtime"]["harness"] == "knowledge-catalog"
    assert [message["role"] for message in continued_run["messages"]] == ["user", "assistant"]
    context = runtime._run_conversation_context(continued_run)
    assert "Bound knowledge bases: kb-old" in context
    assert "Evidence snapshot" in context


def test_old_evidence_schema_fixture_migrates_without_losing_layer_counts(tmp_path: Path):
    source = tmp_path / "legacy.html"
    source.write_text("<article><h1>Legacy paper</h1><p>Legacy evidence remains traceable.</p></article>", encoding="utf-8")
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            create table source_documents (
              doc_id text primary key, title text not null, doi text, source_url text not null,
              publication_year integer, html_path text not null, evidence_html_path text not null
            );
            create table evidence_spans (
              evidence_id text primary key, doc_id text not null, title text not null, doi text,
              source_url text not null, publication_year integer, html_path text not null,
              html_anchor text not null, section text not null, section_kind text not null,
              block_id text not null, block_type text not null, sentence_index integer not null,
              char_start integer not null, char_end integer not null, text text not null,
              section_id text not null default '', parent_section_id text not null default '',
              section_path text not null default '', section_level integer not null default 0,
              source_locator text not null default ''
            );
            create table document_sections (
              section_id text primary key, doc_id text not null, parent_section_id text not null,
              section_title text not null, section_path text not null, section_kind text not null,
              section_level integer not null, source_locator text not null
            );
            create table document_cards (
              doc_id text primary key, title text not null, summary text not null,
              keywords_json text not null default '[]', anchor_evidence_ids_json text not null default '[]',
              section_count integer not null default 0, evidence_count integer not null default 0,
              summary_method text not null default 'extractive-evidence', source_digest text not null default ''
            );
            create table document_index_revisions (
              doc_id text primary key, source_fingerprint text not null,
              indexed_at text not null default current_timestamp
            );
            create table library_catalog_revisions (
              singleton integer primary key check(singleton = 1), catalog_revision integer not null default 0,
              card_schema_version integer not null default 0, updated_at text not null default current_timestamp
            );
            insert into library_catalog_revisions(singleton) values (1);
            create table knowledge_graph_nodes (
              node_id text primary key, node_type text not null, label text not null, metadata_json text not null default '{}'
            );
            create table knowledge_graph_edges (
              edge_id text primary key, source_node_id text not null, target_node_id text not null,
              edge_type text not null, weight real not null default 1.0,
              anchor_evidence_ids_json text not null default '[]', metadata_json text not null default '{}'
            );
            create table document_card_embeddings (
              doc_id text not null, provider text not null, dimensions integer not null,
              source_digest text not null, embedding_json text not null,
              updated_at text not null default current_timestamp,
              primary key(doc_id, provider, dimensions)
            );
            create virtual table evidence_spans_fts using fts5(evidence_id unindexed, doc_id unindexed, title, section, text);
            """
        )
        source_path = source.as_posix()
        connection.execute(
            "insert into source_documents(doc_id, title, doi, source_url, publication_year, html_path, evidence_html_path) values (?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "Legacy paper", "", "", 2021, source_path, ""),
        )
        connection.execute(
            """
            insert into evidence_spans(
              evidence_id, doc_id, title, doi, source_url, publication_year, html_path, html_anchor,
              section, section_kind, block_id, block_type, sentence_index, char_start, char_end, text,
              section_id, parent_section_id, section_path, section_level, source_locator
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy.s0001", "legacy", "Legacy paper", "", "", 2021, source_path,
                "evidence-block-0001-s0001", "Results", "results", "legacy:evidence-block-0001",
                "paragraph", 1, 0, 34, "Legacy evidence remains traceable.", "legacy.results",
                "", "Results", 2, "anchor:evidence-block-0001-s0001",
            ),
        )
        connection.execute(
            "insert into evidence_spans_fts(evidence_id, doc_id, title, section, text) values ('legacy.s0001', 'legacy', 'Legacy paper', 'Results', 'Legacy evidence remains traceable.')"
        )
        connection.commit()

    overview = ensure_library_overview(db_path)
    with sqlite3.connect(db_path) as connection:
        schema_version = connection.execute(
            "select schema_version from schema_meta where schema_name='evidence_store'"
        ).fetchone()[0]
        counts = {
            table: connection.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("source_documents", "document_cards", "document_sections", "evidence_spans")
        }
        revision_columns = [row[1] for row in connection.execute("pragma table_info(document_index_revisions)")]

    # The fixture predates the zotero document tag index migration; the
    # additive v4 migration must run without losing any recorded counts.
    assert schema_version == 4
    assert counts["source_documents"] == 1
    assert counts["document_cards"] == 1
    assert counts["evidence_spans"] == 1
    assert overview["documents"] == 1
    assert "index_version" in revision_columns
