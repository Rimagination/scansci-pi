import json
from pathlib import Path

from scansci_html import cli
from scansci_html.annotation_layers import (
    build_overlay_viewer_payload,
    load_annotation_layers,
    write_annotation_layer,
)
from scansci_html.evidence_store import index_evidence_library
from scansci_html.grounded_annotation import ground_draft_text
from scansci_html.render.annotation_viewer import render_annotation_overlay_viewer


def test_write_and_load_annotation_layer_round_trips_items(tmp_path: Path):
    db_path = _build_store(tmp_path)
    payload = ground_draft_text(
        db_path,
        "Galunisertib reduced regulatory T cells.",
        limit=1,
    )
    layer_db = tmp_path / "annotation_layers.sqlite"

    summary = write_annotation_layer(
        layer_db,
        payload,
        layer_id="tregs",
        name="Tregs question",
        replace=True,
    )
    layers = load_annotation_layers(layer_db)

    assert summary["layer_id"] == "tregs"
    assert summary["items"] == 1
    assert layers[0]["layer_id"] == "tregs"
    assert layers[0]["items"][0]["evidence_id"] == "10.1234_gal.s0001"
    assert layers[0]["items"][0]["html_anchor"] == "results-p1-s0001"
    assert layers[0]["payload"]["schema_version"] == "grounded_annotation.v2"


def test_annotation_overlay_viewer_embeds_layers_and_overlay_script(tmp_path: Path):
    db_path = _build_store(tmp_path)
    payload = ground_draft_text(db_path, "Galunisertib reduced regulatory T cells.", limit=1)
    layer_db = tmp_path / "annotation_layers.sqlite"
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs", replace=True)

    viewer_payload = build_overlay_viewer_payload(db_path, layer_db)
    html = render_annotation_overlay_viewer(
        viewer_payload,
        output_path=tmp_path / "viewer.html",
    )

    assert viewer_payload["summary"]["layers"] == 1
    assert '<html lang="zh-CN">' in html
    assert "标注图层" in html
    assert "打开锚点" in html
    assert 'id="annotation-data"' in html
    assert 'data-layer-id="tregs"' in html
    assert "scansci-soft-layer-highlight" in html
    assert "scansci-soft-layer-active" in html
    assert 'role="button" tabindex="0"' in html
    assert "selectActiveItem" in html
    assert "setActiveCards" in html
    assert ".scansci-evidence-span::after," in html
    assert "content: none !important;" in html
    assert "results-p1-s0001" in html
    assert "Galunisertib reduced regulatory T cells" in html


def test_annotation_overlay_viewer_hides_weak_candidate_items_from_reader(tmp_path: Path):
    payload = {
        "summary": {"documents": 1, "layers": 1, "items": 2},
        "documents": [{"doc_id": "doc1", "title": "Paper", "evidence_html_path": ""}],
        "layers": [
            {
                "layer_id": "layer1",
                "name": "Layer",
                "summary": {"segments": 1},
                "items": [
                    {
                        "segment_id": "c0001",
                        "doc_id": "doc1",
                        "evidence_id": "doc1.s0001",
                        "html_anchor": "s0001",
                        "support_status": "supported",
                        "support_score": 91,
                        "quote": "Supported quote should be visible.",
                        "payload": {"segment": {"text": "Claim text."}},
                    },
                    {
                        "segment_id": "c0001",
                        "doc_id": "doc1",
                        "evidence_id": "doc1.s0002",
                        "html_anchor": "s0002",
                        "support_status": "weak_candidate",
                        "support_score": 41,
                        "quote": "Weak quote should not be visible.",
                        "payload": {"segment": {"text": "Claim text."}},
                    },
                ],
            }
        ],
    }

    html = render_annotation_overlay_viewer(payload, output_path=tmp_path / "viewer.html")

    assert "Supported quote should be visible." in html
    assert "Weak quote should not be visible." not in html
    assert "证据项: 1" in html


def test_cli_can_write_soft_layer_and_render_viewer_without_report_file(tmp_path: Path, capsys):
    db_path = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"

    exit_code = cli.main(
        [
            "annotate",
            "ground",
            "--db",
            str(db_path),
            "--text",
            "Galunisertib reduced regulatory T cells.",
            "--layer-db",
            str(layer_db),
            "--layer-id",
            "tregs",
            "--layer-name",
            "Tregs layer",
            "--limit",
            "1",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["output_path"] == ""
    assert summary["layer"]["layer_id"] == "tregs"
    assert layer_db.exists()

    viewer_path = tmp_path / "viewer.html"
    viewer_exit_code = cli.main(
        [
            "annotate",
            "viewer",
            "--db",
            str(db_path),
            "--layers",
            str(layer_db),
            "--output",
            str(viewer_path),
        ]
    )
    viewer_summary = json.loads(capsys.readouterr().out)

    assert viewer_exit_code == 0
    assert viewer_summary["layers"] == 1
    assert viewer_path.exists()
    assert "Tregs layer" in viewer_path.read_text(encoding="utf-8")


def _build_store(tmp_path: Path) -> Path:
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
