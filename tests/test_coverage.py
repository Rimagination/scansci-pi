import json
from pathlib import Path

from scansci_html import cli
from scansci_html.coverage import build_corpus_coverage
from scansci_html.evidence_store import index_evidence_library


def _make_coverage_store(tmp_path: Path) -> Path:
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper_a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/a">
          <h1>Coverage Paper A</h1>
          <h2>Results</h2>
          <p id="a-results">Treatment increased biomass. Treatment improved yield.</p>
          <h2>Methods</h2>
          <p id="a-methods">Samples were randomized before measurement.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "paper_b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/b">
          <h1>Coverage Paper B</h1>
          <h2>Discussion</h2>
          <p id="b-discussion">The validation cohort did not reproduce the biomass effect.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=5)
    return db_path


def test_build_corpus_coverage_summarizes_documents_sections_and_blocks(tmp_path: Path):
    db_path = _make_coverage_store(tmp_path)

    coverage = build_corpus_coverage(db_path)

    assert coverage["documents"] == 2
    assert coverage["evidence_spans"] == 4
    assert coverage["section_kind_counts"] == {"discussion": 1, "methods": 1, "results": 2}
    assert coverage["block_type_counts"] == {"paragraph": 4}
    assert coverage["document_summaries"][0] == {
        "doc_id": "10.1234_a",
        "title": "Coverage Paper A",
        "doi": "10.1234/a",
        "evidence_spans": 3,
        "section_kind_counts": {"methods": 1, "results": 2},
        "block_type_counts": {"paragraph": 3},
    }


def test_cli_corpus_coverage_emits_summary(tmp_path: Path, capsys):
    db_path = _make_coverage_store(tmp_path)

    exit_code = cli.main(["corpus-coverage", "--db", str(db_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["documents"] == 2
    assert payload["evidence_spans"] == 4
    assert payload["section_kind_counts"]["results"] == 2
