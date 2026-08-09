import json
import sqlite3
from pathlib import Path

from scansci_html import cli
from scansci_html.evidence_doctor import assess_evidence_structure, check_evidence_links
from scansci_html.evidence_store import (
    build_library_overview,
    ensure_library_overview,
    export_spans_jsonl,
    index_evidence_library,
    index_markdown_library,
)


def test_index_evidence_library_writes_sqlite_fts_and_optional_sidecars(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "nature.html").write_text(
        """
        <article class="paper" data-doi="10.1038/nature-example" data-source-url="https://nature.example/article" data-publication-year="2024">
          <h1>Nature Example</h1>
          <h2>Abstract</h2>
          <p>Language models mapped human neural responses.</p>
          <h2>Results</h2>
          <p id="results-p1">Model predictions explained cortical activity. A control model explained less variance.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "science.html").write_text(
        """
        <article class="paper" data-doi="10.1126/science-example">
          <h1>Science Example</h1>
          <h2>Methods</h2>
          <p id="methods-p1">Pressure sensors were calibrated before deployment.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "wiley.html").write_text(
        """
        <article class="paper" data-doi="10.1002/wiley-example">
          <h1>Wiley Example</h1>
          <h2>Discussion</h2>
          <p id="discussion-p1">Fermentation performance depended on immobilized fungal biomass.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    summary = index_evidence_library(
        library,
        db_path=db_path,
        inject_evidence_html=True,
        min_sentence_length=10,
    )

    assert summary == {
        "documents": 3,
        "spans": 5,
        "db_path": str(db_path),
        "evidence_html_files": 3,
        "duplicate_documents_skipped": 0,
    }
    assert (library / "nature.evidence.html").exists()
    assert (library / "science.evidence.html").exists()
    assert (library / "wiley.evidence.html").exists()

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "select evidence_id, section_kind, text, publication_year, html_path from evidence_spans order by evidence_id"
        ).fetchall()
        documents = connection.execute(
            "select doc_id, publication_year, html_path, evidence_html_path from source_documents order by doc_id"
        ).fetchall()
        fts_rows = connection.execute(
            """
            select evidence_id
            from evidence_spans_fts
            where evidence_spans_fts match 'cortical'
            """
        ).fetchall()

    assert rows[0] == (
        "10.1002_wiley-example.s0001",
        "discussion",
        "Fermentation performance depended on immobilized fungal biomass.",
        None,
        (library / "wiley.evidence.html").as_posix(),
    )
    documents_by_id = {row[0]: row for row in documents}
    assert documents_by_id["10.1038_nature-example"] == (
        "10.1038_nature-example",
        2024,
        (library / "nature.html").as_posix(),
        (library / "nature.evidence.html").as_posix(),
    )
    assert documents_by_id["10.1002_wiley-example"] == (
        "10.1002_wiley-example",
        None,
        (library / "wiley.html").as_posix(),
        (library / "wiley.evidence.html").as_posix(),
    )
    assert fts_rows == [("10.1038_nature-example.s0002",)]


def test_index_evidence_library_skips_duplicate_doc_ids(tmp_path: Path):
    library = tmp_path / "library"
    duplicate_dir = library / "rerun"
    duplicate_dir.mkdir(parents=True)
    (library / "first.html").write_text(
        """
        <article class="paper" data-doi="10.1234/duplicate">
          <h1>First Capture</h1>
          <h2>Results</h2>
          <p>First capture has the sentence that should be indexed.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (duplicate_dir / "second.html").write_text(
        """
        <article class="paper" data-doi="10.1234/duplicate">
          <h1>Second Capture</h1>
          <h2>Results</h2>
          <p>Second capture should be skipped as a duplicate document.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    summary = index_evidence_library(
        library,
        db_path=db_path,
        inject_evidence_html=True,
        min_sentence_length=10,
    )

    assert summary == {
        "documents": 1,
        "spans": 1,
        "db_path": str(db_path),
        "evidence_html_files": 1,
        "duplicate_documents_skipped": 1,
    }
    assert (library / "first.evidence.html").exists()
    assert not (duplicate_dir / "second.evidence.html").exists()

    with sqlite3.connect(db_path) as connection:
        documents = connection.execute("select doc_id, html_path from source_documents").fetchall()
        spans = connection.execute("select evidence_id, text from evidence_spans").fetchall()

    assert documents == [("10.1234_duplicate", (library / "first.html").as_posix())]
    assert spans == [
        (
            "10.1234_duplicate.s0001",
            "First capture has the sentence that should be indexed.",
        )
    ]


def test_index_evidence_library_skips_rejected_preview_resource_pages(tmp_path: Path):
    library = tmp_path / "library"
    resource_dir = library / "_rejected_preview" / "article_browser_saved_files"
    resource_dir.mkdir(parents=True)
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/source">
          <h1>Source Paper</h1>
          <h2>Results</h2>
          <p>Source evidence should be indexed from the actual article.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (resource_dir / "dialog.html").write_text(
        """
        <html>
          <head><title>Document is current</title></head>
          <body><p>This browser dialog resource should not enter the evidence store.</p></body>
        </html>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    summary = index_evidence_library(
        library,
        db_path=db_path,
        inject_evidence_html=True,
        min_sentence_length=10,
    )

    assert summary["documents"] == 1
    assert summary["spans"] == 1
    assert (library / "paper.evidence.html").exists()
    assert not (resource_dir / "dialog.evidence.html").exists()

    with sqlite3.connect(db_path) as connection:
        documents = connection.execute("select doc_id from source_documents").fetchall()

    assert documents == [("10.1234_source",)]


def test_index_markdown_library_writes_sentence_evidence_store(tmp_path: Path):
    library = tmp_path / "markdown"
    library.mkdir()
    (library / "paper.md").write_text(
        """---
doi: 10.5555/markdown-source
source_url: https://publisher.example/markdown-source
publication_year: 2026
---
# Markdown Source Paper

## Abstract

Markdown parsing should preserve abstract evidence.

## Results

The markdown evidence store should keep result sentences. A second result sentence should survive too.

- List evidence remains searchable for retrieval.

| Treatment | Outcome |
| --- | --- |
| Shade | Biomass increased significantly in the Markdown table. |

## References

This reference sentence should not enter the evidence store.
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "markdown.sqlite"

    summary = index_markdown_library(library, db_path=db_path, min_sentence_length=10)

    assert summary == {
        "documents": 1,
        "spans": 6,
        "db_path": str(db_path),
        "duplicate_documents_skipped": 0,
    }
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "select evidence_id, section_kind, block_type, text, publication_year, html_path "
            "from evidence_spans order by evidence_id"
        ).fetchall()
        table_hits = connection.execute(
            """
            select evidence_id
            from evidence_spans_fts
            where evidence_spans_fts match 'biomass'
            """
        ).fetchall()
        reference_hits = connection.execute(
            """
            select evidence_id
            from evidence_spans_fts
            where evidence_spans_fts match 'reference'
            """
        ).fetchall()

    assert rows[0] == (
        "10.5555_markdown-source.s0001",
        "abstract",
        "paragraph",
        "Markdown parsing should preserve abstract evidence.",
        2026,
        (library / "paper.md").as_posix(),
    )
    assert rows[-1][1:4] == (
        "results",
        "table_row",
        "Shade | Biomass increased significantly in the Markdown table.",
    )
    assert table_hits == [("10.5555_markdown-source.s0006",)]
    assert reference_hits == []


def test_library_overview_uses_one_document_card_per_file_and_keeps_evidence_anchors(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "solar.md").write_text(
        """# Solar ecology review

## Abstract

Photovoltaic sites can alter plant richness through shading, runoff, and maintenance regimes.

## Results

Plant responses varied by habitat and by the spatial arrangement of photovoltaic arrays.
""",
        encoding="utf-8",
    )
    (library / "biodiversity.md").write_text(
        """# Biodiversity around solar farms

## Abstract

Solar farm biodiversity studies report different outcomes when grazing and vegetation management differ.

## Discussion

Cross-site comparison requires evidence that preserves the original study context and section.
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_markdown_library(library, db_path=db_path, min_sentence_length=10)

    overview = build_library_overview(db_path)

    assert overview["documents"] == 2
    assert overview["document_cards"] == 2
    assert overview["sections"] >= 4
    assert overview["graph_nodes"] >= 4
    assert overview["graph_edges"] >= 2
    with sqlite3.connect(db_path) as connection:
        cards = connection.execute(
            "select title, summary, anchor_evidence_ids_json, evidence_count from document_cards order by title"
        ).fetchall()
        anchored_edges = connection.execute(
            "select count(*) from knowledge_graph_edges where anchor_evidence_ids_json <> '[]'"
        ).fetchone()[0]
        evidence_count = connection.execute("select count(*) from evidence_spans").fetchone()[0]

    assert len(cards) == 2
    assert all(card[1] for card in cards)
    assert all(json.loads(card[2]) for card in cards)
    assert sum(card[3] for card in cards) == evidence_count
    assert anchored_edges >= 2
    # A second call must reuse the catalogue, not create a second card layer.
    assert ensure_library_overview(db_path) == overview


def test_incremental_markdown_index_reuses_unchanged_documents_and_versions_changed_source(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    first = library / "first.md"
    second = library / "second.md"
    first.write_text("# First\n\n## Results\n\nA stable evidence sentence remains reusable.", encoding="utf-8")
    second.write_text("# Second\n\n## Results\n\nAn editable evidence sentence starts in its first version.", encoding="utf-8")
    db_path = tmp_path / "evidence.sqlite"

    initial = index_markdown_library(library, db_path=db_path, min_sentence_length=10, incremental=True)
    build_library_overview(db_path)
    second.write_text("# Second\n\n## Results\n\nAn editable evidence sentence now has a second version.", encoding="utf-8")
    refreshed = index_markdown_library(library, db_path=db_path, min_sentence_length=10, incremental=True)

    assert initial["changed_documents"] == 2
    assert refreshed["reused_documents"] == 1
    assert refreshed["changed_documents"] == 1
    with sqlite3.connect(db_path) as connection:
        fingerprints = connection.execute(
            "select doc_id, source_fingerprint from document_index_revisions order by doc_id"
        ).fetchall()
        evidence = connection.execute("select text from evidence_spans order by evidence_id").fetchall()
    assert len(fingerprints) == 2
    assert any("second version" in row[0] for row in evidence)


def test_index_markdown_library_does_not_treat_inline_formula_pipes_as_table_rows(tmp_path: Path):
    library = tmp_path / "markdown"
    library.mkdir()
    (library / "formula.md").write_text(
        """# Formula Paper

## Methods

The objective contains | x | and | y | terms, but this prose line is not a Markdown table row.
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "formula.sqlite"

    index_markdown_library(library, db_path=db_path, min_sentence_length=10)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("select block_type, text from evidence_spans").fetchall()

    assert rows == [
        (
            "paragraph",
            "The objective contains | x | and | y | terms, but this prose line is not a Markdown table row.",
        )
    ]


def test_index_markdown_library_ignores_dependency_directories(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "research-note.md").write_text(
        "# Research note\n\nThe field observation is retained as traceable research evidence.",
        encoding="utf-8",
    )
    dependency = library / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "README.md").write_text(
        "# Package readme\n\nThis dependency documentation must not enter the evidence index.",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    summary = index_markdown_library(library, db_path=db_path, min_sentence_length=10)

    assert summary["documents"] == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select title from source_documents").fetchall() == [("Research note",)]


def test_index_markdown_library_keeps_distinct_chinese_notes_with_the_same_filename(tmp_path: Path):
    library = tmp_path / "vault"
    first = library / "研究一"
    second = library / "研究二"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "笔记.md").write_text("# 中文标题\n\n第一篇中文笔记包含可检索的实验观察。", encoding="utf-8")
    (second / "笔记.md").write_text("# 中文标题\n\n第二篇中文笔记包含不同的实验观察。", encoding="utf-8")
    db_path = tmp_path / "chinese-notes.sqlite"

    summary = index_markdown_library(library, db_path=db_path, min_sentence_length=1)

    assert summary["documents"] == 2
    assert summary["duplicate_documents_skipped"] == 0
    with sqlite3.connect(db_path) as connection:
        doc_ids = [row[0] for row in connection.execute("select doc_id from source_documents order by doc_id")]
    assert len(set(doc_ids)) == 2


def test_export_spans_jsonl_exports_current_sqlite_rows(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/export">
          <h1>Export Paper</h1>
          <h2>Results</h2>
          <p>Evidence rows should export to JSONL.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    jsonl_path = tmp_path / "spans.jsonl"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    summary = export_spans_jsonl(db_path, jsonl_path)

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert summary == {"spans": 1, "output_path": str(jsonl_path)}
    assert rows[0]["evidence_id"] == "10.1234_export.s0001"
    assert rows[0]["text"] == "Evidence rows should export to JSONL."


def test_check_evidence_links_passes_for_injected_sidecar_anchors(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/doctor">
          <h1>Doctor Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Evidence doctor should find this anchored sentence.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, inject_evidence_html=True, min_sentence_length=10)

    result = check_evidence_links(db_path)

    assert result == {
        "passed": True,
        "spans": 1,
        "checked_files": 1,
        "missing_files": 0,
        "missing_anchors": 0,
        "evidence_id_mismatches": 0,
        "issues_truncated": False,
        "issues": [],
    }


def test_check_evidence_links_flags_missing_sentence_anchors_without_sidecar(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/no-sidecar">
          <h1>No Sidecar Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Evidence doctor should report the missing sentence anchor.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    result = check_evidence_links(db_path)

    assert result["passed"] is False
    assert result["missing_anchors"] == 1
    assert result["issues"] == [
        {
            "type": "missing_anchor",
            "evidence_id": "10.1234_no-sidecar.s0001",
            "html_path": (library / "paper.html").as_posix(),
            "html_anchor": "results-p1-s0001",
            "message": "HTML anchor id does not exist",
        }
    ]


def test_cli_evidence_doctor_exits_nonzero_when_links_are_broken(tmp_path: Path, capsys):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/cli-doctor">
          <h1>CLI Doctor Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Evidence doctor should report broken links.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    exit_code = cli.main(["evidence-doctor", "--db", str(db_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["missing_anchors"] == 1


def test_markdown_pdf_style_text_splits_chinese_and_excludes_implicit_references(tmp_path: Path):
    library = tmp_path / "markdown"
    library.mkdir()
    (library / "paper.md").write_text(
        """---
title: "PDF-style source"
source_url: "C:/library/paper.pdf"
---

# 第 1 页

研究显示处理组的土壤含水率明显提高。第二次测量也得到相同趋势。该结论支持后续试验设计。

References

(1) Smith J. A reference should never become retrievable evidence. Journal 1, 1-10.
(2) Doe J. Another reference row.

# 第 2 页

(3) Roe J. A reference continued on the next PDF page must also be excluded.
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"

    index_markdown_library(library, db_path=db_path, min_sentence_length=6)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "select text, section_path, source_locator from evidence_spans order by sentence_index"
        ).fetchall()
        sections = connection.execute(
            "select section_title, parent_section_id from document_sections order by section_level, section_title"
        ).fetchall()

    assert [row[0] for row in rows] == [
        "研究显示处理组的土壤含水率明显提高。",
        "第二次测量也得到相同趋势。",
        "该结论支持后续试验设计。",
    ]
    assert {row[1] for row in rows} == {"第 1 页"}
    assert {row[2] for row in rows} == {"page:1"}
    assert sections == [("第 1 页", "")]

    quality = assess_evidence_structure(db_path)
    assert quality["passed"] is True
    assert quality["sections"] == 1
    assert quality["oversized_spans"] == 0
    assert quality["reference_spans"] == 0
    assert quality["source_text_mismatches"] == 0


def test_evidence_quality_audit_rejects_oversized_fragments(tmp_path: Path):
    library = tmp_path / "markdown"
    library.mkdir()
    # List items are intentionally atomic source evidence.  The doctor must
    # catch an oversized item even when its source anchor is structurally valid.
    (library / "long.md").write_text("# Long note\n\n- " + "x" * 1_300, encoding="utf-8")
    db_path = tmp_path / "evidence.sqlite"
    index_markdown_library(library, db_path=db_path, min_sentence_length=6)

    quality = assess_evidence_structure(db_path, max_span_characters=1_200)

    assert quality["passed"] is False
    assert quality["claim_ready"] is True
    assert quality["oversized_spans"] == 1
    assert quality["issues"][0]["type"] == "oversized_span"


def test_markdown_evidence_preserves_scientific_tilde_values(tmp_path: Path):
    library = tmp_path / "markdown"
    library.mkdir()
    (library / "value.md").write_text(
        "# Value note\n\nThe band gap remains ~0.3 eV after treatment.",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_markdown_library(library, db_path=db_path, min_sentence_length=6)

    with sqlite3.connect(db_path) as connection:
        text = connection.execute("select text from evidence_spans").fetchone()[0]

    assert text == "The band gap remains ~0.3 eV after treatment."
