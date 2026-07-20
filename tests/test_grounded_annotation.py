import json
from pathlib import Path

from scansci_html import cli
from scansci_html.evidence_store import index_evidence_library
from scansci_html.grounded_annotation import build_grounding_queries, ground_draft_text, split_draft_segments
from scansci_html.render.grounded_annotation import render_grounded_annotation_report


def test_split_draft_segments_handles_sentences_and_list_items():
    segments = split_draft_segments(
        """
        Galunisertib reduced regulatory T cells. Survival improved!

        - IL-15 activated dendritic cells were used.
        """,
        min_segment_length=8,
    )

    assert [segment["text"] for segment in segments] == [
        "Galunisertib reduced regulatory T cells.",
        "Survival improved!",
        "IL-15 activated dendritic cells were used.",
    ]


def test_ground_draft_text_links_segments_to_candidate_evidence(tmp_path: Path):
    db_path = _build_grounding_store(tmp_path)

    payload = ground_draft_text(
        db_path,
        "Galunisertib reduced regulatory T cells. IL-15 activated dendritic cells improved survival.",
        limit=1,
    )

    assert payload["summary"]["segments"] == 2
    assert payload["summary"]["cited_segments"] == 2
    assert payload["schema_version"] == "grounded_annotation.v2"
    assert payload["summary"]["supported_segments"] == 2
    first_segment = payload["segments"][0]
    assert first_segment["status"] == "supported"
    assert first_segment["support_status"] == "supported"
    assert first_segment["best_support_score"] >= 68
    assert first_segment["citation_ids"] == ["1"]
    assert first_segment["evidence"][0]["evidence_id"] == "10.1234_gal.s0001"
    assert first_segment["evidence"][0]["support_status"] == "supported"
    assert "Galunisertib reduced regulatory T cells" in first_segment["evidence"][0]["exact_quote"]
    assert payload["evidence_cards"][0]["source_href"].endswith("#results-p1-s0001")


def test_render_grounded_annotation_report_contains_inline_citations_and_source_cards(tmp_path: Path):
    db_path = _build_grounding_store(tmp_path)
    payload = ground_draft_text(
        db_path,
        "Galunisertib reduced regulatory T cells.",
        limit=1,
    )

    html = render_grounded_annotation_report(payload)

    assert 'href="#source-1"' in html
    assert 'id="source-1"' in html
    assert 'id="source-frame"' in html
    assert 'data-review-action="confirmed"' in html
    assert 'data-filter="needs_review"' in html
    assert '<html lang="zh-CN">' in html
    assert "打开原文锚点" in html
    assert "已支持" in html
    assert "supported" in html
    assert "Galunisertib reduced regulatory T cells" in html


def test_render_grounded_annotation_report_hides_weak_candidate_evidence():
    payload = {
        "summary": {
            "segments": 1,
            "supported_segments": 0,
            "partial_support_segments": 0,
            "weak_candidate_segments": 1,
            "needs_review_segments": 1,
            "evidence_cards": 1,
        },
        "segments": [
            {
                "segment_id": "c0001",
                "text": "Draft claim needs stronger evidence.",
                "support_status": "weak_candidate",
                "best_support_score": 42,
                "evidence": [
                    {
                        "citation_id": "1",
                        "support_status": "weak_candidate",
                        "support_score": 42,
                        "exact_quote": "Weak quote should not be visible.",
                        "source_href": "paper.evidence.html#s0001",
                    }
                ],
                "alternatives": [
                    {
                        "support_status": "weak_candidate",
                        "support_score": 39,
                        "exact_quote": "Weak alternative should not be visible.",
                    }
                ],
            }
        ],
        "evidence_cards": [
            {
                "citation_id": "1",
                "support_status": "weak_candidate",
                "support_score": 42,
                "exact_quote": "Weak quote should not be visible.",
                "source_href": "paper.evidence.html#s0001",
            }
        ],
    }

    html = render_grounded_annotation_report(payload)

    assert "Draft claim needs stronger evidence." in html
    assert "证据不足" in html
    assert "没有达到引用阈值的证据" in html
    assert 'href="#source-1"' not in html
    assert 'id="source-1"' not in html
    assert "Weak quote should not be visible." not in html
    assert "Weak alternative should not be visible." not in html


def test_ground_draft_text_uses_query_variants_for_science_abbreviations(tmp_path: Path):
    db_path = _build_grounding_store(tmp_path)

    payload = ground_draft_text(
        db_path,
        "Tregs were reduced and DC therapy improved survival.",
        limit=1,
        min_matched_terms=2,
    )

    segment = payload["segments"][0]
    queries = [item["query"] for item in segment["queries"]]
    assert any("regulatory T cells" in query for query in queries)
    assert any("dendritic cells" in query for query in queries)
    assert segment["evidence"][0]["evidence_id"] in {"10.1234_gal.s0001", "10.1234_gal.s0002"}


def test_build_grounding_queries_returns_compact_variants():
    queries = build_grounding_queries(
        "rIL15-activated DC enhanced anti-lymphoma immunity in Tregs.",
        max_queries=4,
    )

    assert queries[0]["label"] == "claim"
    assert any("interleukin 15" in str(item["query"]) for item in queries)
    assert any("dendritic cells" in str(item["query"]) for item in queries)


def test_cli_annotate_ground_writes_html_and_json(tmp_path: Path, capsys):
    db_path = _build_grounding_store(tmp_path)
    output_path = tmp_path / "annotation.html"
    json_path = tmp_path / "annotation.json"

    exit_code = cli.main(
        [
            "annotate",
            "ground",
            "--db",
            str(db_path),
            "--text",
            "Galunisertib reduced regulatory T cells.",
            "--output",
            str(output_path),
            "--json-output",
            str(json_path),
            "--limit",
            "1",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output_path.exists()
    assert summary["cited_segments"] == 1
    assert summary["supported_segments"] == 1
    assert payload["segments"][0]["citation_ids"] == ["1"]
    assert payload["segments"][0]["support_status"] == "supported"
    assert 'href="#source-1"' in output_path.read_text(encoding="utf-8")


def _build_grounding_store(tmp_path: Path) -> Path:
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/gal">
          <h1>Galunisertib Immunotherapy Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Galunisertib reduced regulatory T cells after treatment. IL-15 activated dendritic cells improved survival in lymphoma models.</p>
        </article>
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "evidence.sqlite"
    index_evidence_library(
        library,
        db_path=db_path,
        inject_evidence_html=True,
        min_sentence_length=10,
    )
    return db_path
