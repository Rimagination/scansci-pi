from pathlib import Path
import sqlite3

import pytest

from scansci_html.evidence_store import index_evidence_library
from scansci_html.retrieval import search_evidence_store


def test_search_evidence_store_returns_reranked_sentence_hits_with_routes(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper_a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/a">
          <h1>Cortical Model Paper</h1>
          <h2>Results</h2>
          <p id="a-results">Model predictions explained cortical activity in language regions. The baseline captured motor activity.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "paper_b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/b">
          <h1>Fermentation Paper</h1>
          <h2>Discussion</h2>
          <p id="b-discussion">Fermentation performance depended on immobilized fungal biomass.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    hits = search_evidence_store(db_path, "cortical activity language model", limit=3)

    assert [hit["evidence_id"] for hit in hits[:2]] == [
        "10.1234_a.s0001",
        "10.1234_a.s0002",
    ]
    assert hits[0]["text"] == "Model predictions explained cortical activity in language regions."
    assert hits[0]["section_kind"] == "results"
    assert hits[0]["score"] > hits[1]["score"]
    assert "fts" in hits[0]["routes"]
    assert "dense" in hits[0]["routes"]
    assert hits[0]["matched_terms"] == ["cortical", "activity", "language", "model"]


def test_search_evidence_store_can_append_retrieval_trace(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/trace">
          <h1>Trace Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Cortical activity changed after treatment.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    trace = []
    hits = search_evidence_store(
        db_path,
        "cortical activity treatment",
        limit=1,
        initial_limit=5,
        per_document_limit=1,
        trace=trace,
    )

    assert [hit["evidence_id"] for hit in hits] == ["10.1234_trace.s0001"]
    assert len(trace) == 1
    event = trace[0]
    assert event["stage"] == "search"
    assert event["query"] == "cortical activity treatment"
    assert event["query_terms"] == ["cortical", "activity", "treatment"]
    assert event["fts_candidates"] == 1
    assert event["dense_candidates"] == 1
    assert event["unique_candidates"] == 1
    assert event["reranked_candidates"] == 1
    assert event["returned_hits"] == 1
    assert event["route_counts"] == {"dense": 1, "fts": 1}
    assert event["elapsed_ms"] >= 0.0


def test_search_evidence_store_can_start_with_paper_level_recall(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "target.html").write_text(
        """
        <article class="paper" data-doi="10.1234/target">
          <h1>Language Modeling Paper</h1>
          <h2>Abstract</h2>
          <p id="target-abstract">Language modeling experiments motivated the cortical activity analysis.</p>
          <h2>Results</h2>
          <p id="target-results">The model explained cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "distractor.html").write_text(
        """
        <article class="paper" data-doi="10.1234/distractor">
          <h1>Motor Control Paper</h1>
          <h2>Results</h2>
          <p id="distractor-results">Cortical activity changed during movement tasks.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    trace = []
    hits = search_evidence_store(
        db_path,
        "language modeling cortical activity",
        limit=5,
        paper_recall_limit=1,
        trace=trace,
    )

    assert {hit["doc_id"] for hit in hits} == {"10.1234_target"}
    assert hits[0]["paper_recall_rank"] == 1
    assert trace[0]["stage"] == "paper_recall"
    assert trace[0]["selected_doc_ids"] == ["10.1234_target"]
    assert trace[-1]["paper_recalled_documents"] == 1


def test_search_evidence_store_can_expand_hits_to_parent_block_context(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/context">
          <h1>Context Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">The cohort included 120 participants. Treatment increased cortical activity in language regions.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    sentence_hits = search_evidence_store(db_path, "cortical activity language", limit=1)
    block_hits = search_evidence_store(
        db_path,
        "cortical activity language",
        limit=1,
        context_mode="block",
    )

    assert sentence_hits[0]["text"] == "Treatment increased cortical activity in language regions."
    assert block_hits[0]["evidence_id"] == sentence_hits[0]["evidence_id"]
    assert block_hits[0]["span_text"] == "Treatment increased cortical activity in language regions."
    assert block_hits[0]["text"] == (
        "The cohort included 120 participants. "
        "Treatment increased cortical activity in language regions."
    )
    assert block_hits[0]["parent_text"] == block_hits[0]["text"]
    assert block_hits[0]["parent_block_id"] == "10.1234_context:results-p1"
    assert block_hits[0]["parent_evidence_ids"] == [
        "10.1234_context.s0001",
        "10.1234_context.s0002",
    ]


def test_search_evidence_store_applies_per_document_limit_after_reranking(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper_a.html").write_text(
        """
        <article class="paper" data-doi="10.1234/a">
          <h1>Repeated Evidence Paper</h1>
          <h2>Results</h2>
          <p id="a-results">Cortical activity increased after stimulation. Cortical activity remained elevated at follow up.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "paper_b.html").write_text(
        """
        <article class="paper" data-doi="10.1234/b">
          <h1>Independent Evidence Paper</h1>
          <h2>Results</h2>
          <p id="b-results">Cortical activity changed in an independent cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    hits = search_evidence_store(
        db_path,
        "cortical activity",
        limit=10,
        per_document_limit=1,
    )

    assert [hit["doc_id"] for hit in hits] == ["10.1234_a", "10.1234_b"]


def test_search_evidence_store_applies_publication_year_filter(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "old.html").write_text(
        """
        <article class="paper" data-doi="10.1234/old" data-publication-year="2019">
          <h1>Old Evidence Paper</h1>
          <h2>Results</h2>
          <p id="old-results">Cortical activity changed in the treatment cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "new.html").write_text(
        """
        <article class="paper" data-doi="10.1234/new" data-publication-year="2024">
          <h1>New Evidence Paper</h1>
          <h2>Results</h2>
          <p id="new-results">Cortical activity changed in the treatment cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "unknown.html").write_text(
        """
        <article class="paper" data-doi="10.1234/unknown">
          <h1>Unknown Year Paper</h1>
          <h2>Results</h2>
          <p id="unknown-results">Cortical activity changed in the treatment cohort.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    hits = search_evidence_store(
        db_path,
        "cortical activity treatment cohort",
        limit=10,
        filters={"year_min": 2020},
    )

    assert [hit["evidence_id"] for hit in hits] == ["10.1234_new.s0001"]
    assert hits[0]["publication_year"] == 2024


def test_search_evidence_store_applies_section_kind_filter(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/section-filter">
          <h1>Section Filter Paper</h1>
          <h2>Methods</h2>
          <p id="methods-p1">Samples were randomized before biomass measurement.</p>
          <h2>Results</h2>
          <p id="results-p1">Randomized samples produced higher biomass.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    hits = search_evidence_store(
        db_path,
        "randomized samples biomass",
        limit=10,
        filters={"section_kinds": ["methods"]},
    )

    assert [hit["evidence_id"] for hit in hits] == ["10.1234_section-filter.s0001"]
    assert hits[0]["section_kind"] == "methods"


def test_search_evidence_store_uses_provider_query_embedding_when_available(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "relevant.html").write_text(
        """
        <article class="paper" data-doi="10.1234/relevant">
          <h1>Relevant Paper</h1>
          <p id="relevant-p1">Relevant answer evidence appears in this paper.</p>
        </article>
        """,
        encoding="utf-8",
    )
    (library / "distractor.html").write_text(
        """
        <article class="paper" data-doi="10.1234/distractor">
          <h1>Distractor Paper</h1>
          <p id="distractor-p1">Distractor evidence appears in this paper.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    class PromptAwareProvider:
        dimensions = 2

        def embed_texts(self, texts):
            vectors = []
            for text in texts:
                if "Relevant answer evidence" in text:
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

        def embed_query(self, query):
            return [1.0, 0.0]

    hits = search_evidence_store(
        db_path,
        "needle",
        limit=1,
        initial_limit=0,
        embedding_provider=PromptAwareProvider(),
    )

    assert [hit["evidence_id"] for hit in hits] == ["10.1234_relevant.s0001"]


def test_search_evidence_store_returns_empty_for_empty_query(tmp_path: Path):
    db_path = tmp_path / "evidence.sqlite"
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        "<article class='paper'><h1>Paper</h1><p>Evidence exists.</p></article>",
        encoding="utf-8",
    )
    index_evidence_library(library, db_path=db_path, min_sentence_length=1)

    assert search_evidence_store(db_path, "the and of", limit=5) == []


def test_default_local_embeddings_are_cached_with_sqlite_vec(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        "<article class='paper' data-doi='10.1234/vector'><h1>Vector cache</h1>"
        "<p>Traceable cortical evidence improves scientific decisions.</p></article>",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)

    first_trace = []
    first = search_evidence_store(db_path, "cortical evidence", limit=1, trace=first_trace)
    second_trace = []
    second = search_evidence_store(db_path, "cortical evidence", limit=1, trace=second_trace)

    assert [item["evidence_id"] for item in first] == [item["evidence_id"] for item in second]
    assert first_trace[-1]["dense_backend"] == "sqlite-vec"
    assert second_trace[-1]["dense_backend"] == "sqlite-vec"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from scansci_vector_cache_meta").fetchone()[0] == 1
