from pathlib import Path

from scansci_html.evidence_store import build_library_overview, index_evidence_library
from scansci_html.knowledge_quality import assert_retrieval_quality_gate, evaluate_retrieval_gold_set


def test_gold_retrieval_gate_checks_routes_evidence_and_empty_adversarial_query(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "solar.html").write_text(
        "<article data-doi='10.1/solar'><h1>Solar biodiversity</h1><h2>Results</h2>"
        "<p>Plant richness increased where grazing maintained understory vegetation.</p></article>",
        encoding="utf-8",
    )
    (library / "wind.html").write_text(
        "<article data-doi='10.1/wind'><h1>Wind habitat</h1><h2>Results</h2>"
        "<p>Bird nesting response varied with turbine spacing and habitat condition.</p></article>",
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=db_path, min_sentence_length=10)
    build_library_overview(db_path)

    report = evaluate_retrieval_gold_set(
        db_path,
        [
            {
                "id": "exact-solar-fact",
                "query": "What maintained understory vegetation and increased plant richness?",
                "expected_route": "evidence-answer",
                "expected_doc_ids": ["10.1_solar"],
                "expected_evidence_ids": ["10.1_solar.s0001"],
            },
            {
                "id": "review-route",
                "query": "Review the research progress on solar biodiversity.",
                "expected_route": "evidence-review",
                "expected_doc_ids": ["10.1_solar"],
            },
            {
                "id": "unknown-boundary",
                "query": "Does this library prove zephyrium quorblax?",
                "expected_route": "evidence-answer",
                "expect_empty": True,
            },
        ],
    )

    assert report["card_first_rate"] == 1.0
    assert report["document_recall"] == 1.0
    assert report["evidence_recall"] == 1.0
    assert_retrieval_quality_gate(report)
