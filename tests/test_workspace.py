import json
from pathlib import Path

from scansci_html import cli
from scansci_html.annotation_layers import write_annotation_layer
from scansci_html.evidence_store import index_evidence_library
from scansci_html.grounded_annotation import ground_draft_text
from scansci_html.workspace import (
    add_note_to_notebook,
    attach_annotation_layers_to_notebook,
    initialize_notebook,
    list_citation_records,
    load_workspace_summary,
    record_citation_audit,
    sync_sources_from_evidence_store,
)


def test_workspace_registers_notebook_sources_notes_and_layers(tmp_path: Path):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    payload = ground_draft_text(evidence_db, "Galunisertib reduced regulatory T cells.", limit=1)
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs layer", replace=True)
    workspace = tmp_path / "workspace.sqlite"

    notebook = initialize_notebook(
        workspace,
        notebook_id="immunotherapy",
        title="Immunotherapy review",
        root_path=tmp_path,
    )
    sources = sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="immunotherapy")
    note = add_note_to_notebook(
        workspace,
        notebook_id="immunotherapy",
        title="Tregs claim",
        body="Galunisertib reduced regulatory T cells.",
        note_type="grounded_draft",
    )
    layers = attach_annotation_layers_to_notebook(
        workspace,
        layer_db,
        notebook_id="immunotherapy",
        layer_ids=["tregs"],
        note_id=str(note["note_id"]),
    )
    summary = load_workspace_summary(workspace, notebook_id="immunotherapy")

    assert notebook["notebook_id"] == "immunotherapy"
    assert sources["sources"] == 1
    assert layers["layers"] == 1
    assert summary["counts"] == {
        "notebooks": 1,
        "sources": 1,
        "notes": 1,
        "layers": 1,
        "citations": 1,
        "citation_audits": 0,
    }
    notebook_summary = summary["notebooks"][0]
    assert notebook_summary["sources"][0]["doc_id"] == "10.1234_gal"
    assert notebook_summary["notes"][0]["note_id"] == note["note_id"]
    assert notebook_summary["layers"][0]["annotation_layer_id"] == "tregs"
    assert notebook_summary["layers"][0]["note_id"] == note["note_id"]
    assert notebook_summary["layers"][0]["sources"][0]["doc_id"] == "10.1234_gal"
    assert notebook_summary["layers"][0]["sources"][0]["evidence_count"] == 1


def test_workspace_syncs_citation_records_from_annotation_layers(tmp_path: Path):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    payload = ground_draft_text(evidence_db, "Galunisertib reduced regulatory T cells.", limit=1)
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs layer", replace=True)
    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="immunotherapy")
    note = add_note_to_notebook(
        workspace,
        notebook_id="immunotherapy",
        title="Tregs claim",
        body="Galunisertib reduced regulatory T cells.",
        note_type="grounded_draft",
    )

    attached = attach_annotation_layers_to_notebook(
        workspace,
        layer_db,
        notebook_id="immunotherapy",
        layer_ids=["tregs"],
        note_id=str(note["note_id"]),
    )
    records = list_citation_records(workspace, notebook_id="immunotherapy")
    summary = load_workspace_summary(workspace, notebook_id="immunotherapy")

    assert attached["citation_records"] == 1
    assert summary["counts"]["citations"] == 1
    assert summary["counts"]["citation_audits"] == 0
    assert len(records) == 1
    record = records[0]
    assert record["notebook_id"] == "immunotherapy"
    assert record["note_id"] == note["note_id"]
    assert record["annotation_layer_id"] == "tregs"
    assert record["citation_marker"] == "1"
    assert record["claim_text"] == "Galunisertib reduced regulatory T cells."
    assert "Galunisertib reduced regulatory T cells" in record["quote_snapshot"]
    assert record["source_location"]["kind"] == "html_anchor"
    assert record["source_location"]["html_anchor"]
    assert record["audits"] == []


def test_workspace_records_citation_audits_separately(tmp_path: Path):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    payload = ground_draft_text(evidence_db, "Galunisertib reduced regulatory T cells.", limit=1)
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs layer", replace=True)
    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="immunotherapy")
    note = add_note_to_notebook(
        workspace,
        notebook_id="immunotherapy",
        title="Tregs claim",
        body="Galunisertib reduced regulatory T cells.",
        note_type="grounded_draft",
    )
    attach_annotation_layers_to_notebook(
        workspace,
        layer_db,
        notebook_id="immunotherapy",
        layer_ids=["tregs"],
        note_id=str(note["note_id"]),
    )
    record = list_citation_records(workspace, notebook_id="immunotherapy")[0]

    audit = record_citation_audit(
        workspace,
        citation_record_id=str(record["citation_record_id"]),
        provider="local-overlap",
        verdict="supported",
        reasoning="The quote directly states the claim.",
        confidence=0.92,
    )
    records = list_citation_records(workspace, notebook_id="immunotherapy")
    summary = load_workspace_summary(workspace, notebook_id="immunotherapy")

    assert audit["citation_record_id"] == record["citation_record_id"]
    assert summary["counts"]["citation_audits"] == 1
    assert records[0]["review_state"] == "unreviewed"
    assert records[0]["audits"][0]["verdict"] == "supported"
    assert records[0]["audits"][0]["provider"] == "local-overlap"
    assert records[0]["audits"][0]["confidence"] == 0.92


def test_cli_notebook_workflow_registers_objects(tmp_path: Path, capsys):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    payload = ground_draft_text(evidence_db, "Galunisertib reduced regulatory T cells.", limit=1)
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs layer", replace=True)
    workspace = tmp_path / "workspace.sqlite"

    assert cli.main(
        [
            "notebook",
            "init",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
            "--title",
            "Review notebook",
        ]
    ) == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["notebook_id"] == "review"

    assert cli.main(
        [
            "notebook",
            "sync-sources",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
            "--evidence-db",
            str(evidence_db),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["sources"] == 1

    assert cli.main(
        [
            "notebook",
            "add-note",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
            "--note-id",
            "note_tregs",
            "--title",
            "Tregs claim",
            "--text",
            "Galunisertib reduced regulatory T cells.",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["note_id"] == "note_tregs"

    assert cli.main(
        [
            "notebook",
            "attach-layer",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
            "--layers",
            str(layer_db),
            "--layer-id",
            "tregs",
            "--note-id",
            "note_tregs",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["layers"] == 1

    assert cli.main(
        [
            "notebook",
            "summary",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
        ]
    ) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"] == {
        "notebooks": 1,
        "sources": 1,
        "notes": 1,
        "layers": 1,
        "citations": 1,
        "citation_audits": 0,
    }
    assert summary["notebooks"][0]["layers"][0]["note_id"] == "note_tregs"
    assert summary["notebooks"][0]["citations"][0]["citation_marker"] == "1"


def test_cli_notebook_citations_lists_records(tmp_path: Path, capsys):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    payload = ground_draft_text(evidence_db, "Galunisertib reduced regulatory T cells.", limit=1)
    write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs layer", replace=True)
    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="review")
    note = add_note_to_notebook(
        workspace,
        notebook_id="review",
        title="Tregs claim",
        body="Galunisertib reduced regulatory T cells.",
    )
    attach_annotation_layers_to_notebook(
        workspace,
        layer_db,
        notebook_id="review",
        layer_ids=["tregs"],
        note_id=str(note["note_id"]),
    )

    assert cli.main(
        [
            "notebook",
            "citations",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["citations"][0]["annotation_layer_id"] == "tregs"
    assert payload["citations"][0]["source_location"]["kind"] == "html_anchor"


def test_grounded_annotate_can_register_note_and_layer_in_workspace(tmp_path: Path, capsys):
    evidence_db = _build_store(tmp_path)
    layer_db = tmp_path / "annotation_layers.sqlite"
    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, evidence_db, notebook_id="review")

    exit_code = cli.main(
        [
            "grounded-annotate",
            "--db",
            str(evidence_db),
            "--text",
            "Galunisertib reduced regulatory T cells.",
            "--layer-db",
            str(layer_db),
            "--layer-id",
            "auto_tregs",
            "--layer-name",
            "Auto Tregs",
            "--workspace",
            str(workspace),
            "--notebook-id",
            "review",
            "--limit",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    summary = load_workspace_summary(workspace, notebook_id="review")
    assert exit_code == 0
    assert payload["workspace"]["note"]["note_type"] == "grounded_draft"
    assert payload["workspace"]["attached_layers"]["layers"] == 1
    assert summary["counts"] == {
        "notebooks": 1,
        "sources": 1,
        "notes": 1,
        "layers": 1,
        "citations": 1,
        "citation_audits": 0,
    }
    assert summary["notebooks"][0]["layers"][0]["annotation_layer_id"] == "auto_tregs"


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
