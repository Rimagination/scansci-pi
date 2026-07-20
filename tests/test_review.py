import csv
import json
from pathlib import Path

from scansci_html import cli
from scansci_html.annotation_layers import load_annotation_layers, write_annotation_layer
from scansci_html.review import (
    build_review_matrix,
    build_review_matrix_from_annotation_layers,
    filter_review_matrix_rows,
    write_review_matrix,
    write_review_transformation,
)


def _report_payload(question: str = "What evidence supports X?") -> dict:
    return {
        "question": question,
        "query_plan": {
            "question_type": "evidence",
            "filters": {
                "section_kinds": ["results"],
                "year_min": 2020,
            },
            "followup_queries": ["evidence supports x"],
        },
        "retrieval_queries": ["What evidence supports X?", "evidence supports x"],
        "adequacy": {
            "is_sufficient": True,
            "profile": "manual",
            "quote_count": 1,
            "min_quotes": 1,
            "document_count": 1,
            "min_documents": 1,
            "followup_reason": "",
        },
        "answer": {
            "answer": [
                {
                    "claim_id": "c0001",
                    "text": "Treatment increased biomass.",
                    "quote_ids": ["q0001"],
                    "support_status": "supported",
                    "verification_score": 0.92,
                }
            ]
        },
        "evidence_table": [
            {
                "quote_id": "q0001",
                "claim_target": "Treatment increased biomass.",
                "stance": "supports",
                "exact_quote": "Treatment increased biomass by 18%.",
                "paper": "Biomass Paper",
                "section": "Results",
                "section_kind": "results",
                "doi": "10.1234/biomass",
                "evidence_id": "doc1.s0001",
                "html_path": "paper.evidence.html",
                "html_anchor": "results-p1-s0001",
                "confidence": 0.82,
            }
        ],
    }


def _annotation_payload() -> dict:
    return {
        "schema_version": "grounded_annotation.v2",
        "source_text": "Qwen3 reranking improves evidence retrieval. Weak evidence should stay out.",
        "db_path": "evidence.sqlite",
        "segments": [
            {
                "segment_id": "c0001",
                "text": "Qwen3 reranking improves evidence retrieval.",
                "evidence": [
                    {
                        "citation_id": "1",
                        "evidence_id": "paper1.s0001",
                        "doc_id": "paper1",
                        "title": "Rerank Paper",
                        "doi": "10.1234/rerank",
                        "section": "Results",
                        "section_kind": "results",
                        "exact_quote": "Qwen3 reranking improved evidence retrieval recall.",
                        "support_score": 88.5,
                        "support_status": "supported",
                        "html_path": "paper1.evidence.html",
                        "html_anchor": "results-p1-s0001",
                        "source_href": "paper1.evidence.html#results-p1-s0001",
                        "retrieval_queries": [{"query": "Qwen3 reranking evidence retrieval"}],
                    }
                ],
            },
            {
                "segment_id": "c0002",
                "text": "Weak evidence should stay out.",
                "evidence": [
                    {
                        "citation_id": "2",
                        "evidence_id": "paper1.s0002",
                        "doc_id": "paper1",
                        "title": "Rerank Paper",
                        "doi": "10.1234/rerank",
                        "section": "Discussion",
                        "section_kind": "discussion",
                        "exact_quote": "The discussion is only tangentially related.",
                        "support_score": 18.0,
                        "support_status": "weak_candidate",
                        "html_path": "paper1.evidence.html",
                        "html_anchor": "discussion-p1-s0001",
                        "source_href": "paper1.evidence.html#discussion-p1-s0001",
                    }
                ],
            },
        ],
        "evidence_cards": [
            {
                "citation_id": "1",
                "evidence_id": "paper1.s0001",
                "doc_id": "paper1",
                "title": "Rerank Paper",
                "doi": "10.1234/rerank",
                "section": "Results",
                "section_kind": "results",
                "exact_quote": "Qwen3 reranking improved evidence retrieval recall.",
                "support_score": 88.5,
                "support_status": "supported",
                "publication_year": 2026,
                "html_path": "paper1.evidence.html",
                "html_anchor": "results-p1-s0001",
                "source_href": "paper1.evidence.html#results-p1-s0001",
            }
        ],
        "summary": {"segments": 2, "evidence_cards": 2},
    }


def test_build_review_matrix_joins_evidence_rows_to_answer_claims():
    rows = build_review_matrix(_report_payload())

    assert rows == [
        {
            "question": "What evidence supports X?",
            "question_type": "evidence",
            "query_plan": (
                '{"filters":{"section_kinds":["results"],"year_min":2020},'
                '"followup_queries":["evidence supports x"],"question_type":"evidence"}'
            ),
            "retrieval_filters": '{"section_kinds":["results"],"year_min":2020}',
            "retrieval_queries": "What evidence supports X? | evidence supports x",
            "evidence_sufficient": True,
            "adequacy_profile": "manual",
            "adequacy_quote_count": 1,
            "adequacy_min_quotes": 1,
            "adequacy_document_count": 1,
            "adequacy_min_documents": 1,
            "adequacy_followup_reason": "",
            "claim_id": "c0001",
            "claim_text": "Treatment increased biomass.",
            "support_status": "supported",
            "verification_score": 0.92,
            "quote_id": "q0001",
            "stance": "supports",
            "exact_quote": "Treatment increased biomass by 18%.",
            "paper": "Biomass Paper",
            "section": "Results",
            "section_kind": "results",
            "doi": "10.1234/biomass",
            "evidence_id": "doc1.s0001",
            "html_path": "paper.evidence.html",
            "html_anchor": "results-p1-s0001",
            "confidence": 0.82,
        }
    ]


def test_write_review_matrix_writes_csv_json_and_html(tmp_path: Path):
    rows = build_review_matrix(_report_payload())
    csv_path = tmp_path / "matrix.csv"
    json_path = tmp_path / "matrix.json"
    html_path = tmp_path / "matrix.html"

    write_review_matrix(rows, csv_path, output_format="csv")
    write_review_matrix(rows, json_path, output_format="json")
    write_review_matrix(rows, html_path, output_format="html")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    json_rows = json.loads(json_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")
    assert csv_rows[0]["quote_id"] == "q0001"
    assert csv_rows[0]["exact_quote"] == "Treatment increased biomass by 18%."
    assert csv_rows[0]["question_type"] == "evidence"
    assert csv_rows[0]["retrieval_filters"] == '{"section_kinds":["results"],"year_min":2020}'
    assert csv_rows[0]["retrieval_queries"] == "What evidence supports X? | evidence supports x"
    assert csv_rows[0]["evidence_sufficient"] == "True"
    assert json_rows[0]["quote_id"] == "q0001"
    assert json_rows[0]["question_type"] == "evidence"
    assert json_rows[0]["evidence_sufficient"] is True
    assert json_rows[0]["adequacy_profile"] == "manual"
    assert json_rows[0]["adequacy_quote_count"] == 1
    assert json_rows[0]["adequacy_min_quotes"] == 1
    assert json_rows[0]["adequacy_min_documents"] == 1
    assert 'href="paper.evidence.html#results-p1-s0001"' in html
    assert 'data-evidence-id="doc1.s0001"' in html
    assert "Treatment increased biomass by 18%." in html
    assert "What evidence supports X? | evidence supports x" in html
    assert "year_min" in html


def test_filter_review_matrix_rows_uses_review_filters():
    supported_row = build_review_matrix(_report_payload())[0]
    unsupported_row = {
        **supported_row,
        "question_type": "method",
        "support_status": "unsupported",
        "section_kind": "methods",
        "evidence_sufficient": False,
        "exact_quote": "No sufficient method evidence was available.",
    }

    rows = filter_review_matrix_rows(
        [supported_row, unsupported_row],
        support_statuses=["supported"],
        question_types=["evidence"],
        section_kinds=["results"],
        evidence_sufficient=True,
    )

    assert rows == [supported_row]


def test_write_review_matrix_can_select_columns_for_all_formats(tmp_path: Path):
    rows = build_review_matrix(_report_payload())
    fields = ["question", "claim_text", "exact_quote", "evidence_id"]
    csv_path = tmp_path / "matrix.csv"
    json_path = tmp_path / "matrix.json"
    html_path = tmp_path / "matrix.html"

    write_review_matrix(rows, csv_path, output_format="csv", fields=fields)
    write_review_matrix(rows, json_path, output_format="json", fields=fields)
    write_review_matrix(rows, html_path, output_format="html", fields=fields)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
        assert handle
    json_rows = json.loads(json_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")
    assert list(csv_rows[0].keys()) == fields
    assert list(json_rows[0].keys()) == fields
    assert "<th>claim_text</th>" in html
    assert "<th>support_status</th>" not in html
    assert 'href="paper.evidence.html#results-p1-s0001"' in html


def test_cli_review_matrix_exports_csv(tmp_path: Path, capsys):
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "matrix.csv"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")

    exit_code = cli.main(
        [
            "review-matrix",
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--format",
            "csv",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "reports": 1,
        "rows": 1,
        "output_path": str(output_path),
        "format": "csv",
    }
    csv_text = output_path.read_text(encoding="utf-8")
    assert "Treatment increased biomass by 18%." in csv_text
    assert "retrieval_queries" in csv_text
    assert "What evidence supports X? | evidence supports x" in csv_text


def test_cli_review_matrix_exports_html(tmp_path: Path, capsys):
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "matrix.html"
    report_path.write_text(json.dumps(_report_payload()), encoding="utf-8")

    exit_code = cli.main(
        [
            "review-matrix",
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--format",
            "html",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    html = output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload == {
        "reports": 1,
        "rows": 1,
        "output_path": str(output_path),
        "format": "html",
    }
    assert "ScanSci Review Matrix" in html
    assert 'data-support-status="supported"' in html
    assert 'href="paper.evidence.html#results-p1-s0001"' in html
    assert "retrieval_queries" in html
    assert "What evidence supports X? | evidence supports x" in html


def test_cli_review_matrix_merges_multiple_reports(tmp_path: Path, capsys):
    first_report_path = tmp_path / "first-report.json"
    second_report_path = tmp_path / "second-report.json"
    output_path = tmp_path / "matrix.csv"
    first_report_path.write_text(json.dumps(_report_payload("What evidence supports X?")), encoding="utf-8")
    second_report_path.write_text(json.dumps(_report_payload("What evidence supports Y?")), encoding="utf-8")

    exit_code = cli.main(
        [
            "review-matrix",
            "--report",
            str(first_report_path),
            "--report",
            str(second_report_path),
            "--output",
            str(output_path),
            "--format",
            "csv",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    csv_text = output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload == {
        "reports": 2,
        "rows": 2,
        "output_path": str(output_path),
        "format": "csv",
    }
    assert "What evidence supports X?" in csv_text
    assert "What evidence supports Y?" in csv_text


def test_cli_review_matrix_filters_rows_and_selects_columns(tmp_path: Path, capsys):
    report_payload = _report_payload()
    report_payload["answer"]["answer"].append(
        {
            "claim_id": "c0002",
            "text": "Treatment evidence was unavailable.",
            "quote_ids": ["q0002"],
            "support_status": "unsupported",
            "verification_score": 0.0,
        }
    )
    report_payload["evidence_table"].append(
        {
            "quote_id": "q0002",
            "claim_target": "Treatment evidence was unavailable.",
            "stance": "neutral",
            "exact_quote": "The methods did not report treatment biomass.",
            "paper": "Methods Paper",
            "section": "Methods",
            "section_kind": "methods",
            "doi": "10.1234/methods",
            "evidence_id": "doc2.s0001",
            "html_path": "methods.evidence.html",
            "html_anchor": "methods-p1-s0001",
            "confidence": 0.51,
        }
    )
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "matrix.csv"
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    exit_code = cli.main(
        [
            "review-matrix",
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--format",
            "csv",
            "--support-status",
            "supported",
            "--section-kind",
            "results",
            "--evidence-sufficient",
            "true",
            "--columns",
            "question,claim_text,evidence_id",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    with output_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert exit_code == 0
    assert payload == {
        "reports": 1,
        "rows": 1,
        "output_path": str(output_path),
        "format": "csv",
        "input_rows": 2,
        "columns": ["question", "claim_text", "evidence_id"],
    }
    assert list(csv_rows[0].keys()) == ["question", "claim_text", "evidence_id"]
    assert csv_rows[0]["evidence_id"] == "doc1.s0001"


def test_build_review_matrix_from_annotation_layers_exports_evidence_bound_rows(tmp_path: Path):
    layer_db = tmp_path / "layers.sqlite"
    write_annotation_layer(
        layer_db,
        _annotation_payload(),
        layer_id="rerank",
        name="Rerank evidence",
        question="Does reranking improve retrieval?",
        replace=True,
    )

    rows = build_review_matrix_from_annotation_layers(layer_db)

    assert len(rows) == 1
    assert rows[0]["layer_id"] == "rerank"
    assert rows[0]["item_id"] == "rerank:c0001:paper1.s0001:1"
    assert rows[0]["review_state"] == "unreviewed"
    assert rows[0]["question_type"] == "grounded_annotation"
    assert rows[0]["paper"] == "Rerank Paper"
    assert rows[0]["publication_year"] == 2026
    assert rows[0]["retrieval_queries"] == "Qwen3 reranking evidence retrieval"
    assert rows[0]["exact_quote"] == "Qwen3 reranking improved evidence retrieval recall."
    assert rows[0]["evidence_id"] == "paper1.s0001"


def test_write_review_transformation_uses_confirmed_rows_only(tmp_path: Path):
    layer_db = tmp_path / "layers.sqlite"
    write_annotation_layer(layer_db, _annotation_payload(), layer_id="rerank", replace=True)
    rows = build_review_matrix_from_annotation_layers(layer_db)
    rows[0]["review_state"] = "confirmed"
    unreviewed_row = {**rows[0], "item_id": "other", "review_state": "unreviewed", "claim_text": "Unreviewed claim"}
    output_path = tmp_path / "glossary.md"

    write_review_transformation([rows[0], unreviewed_row], output_path, template="glossary", output_format="md")

    markdown = output_path.read_text(encoding="utf-8")
    assert "# 术语表" in markdown
    assert "Qwen3 reranking improves evidence retrieval" in markdown
    assert "Unreviewed claim" not in markdown
    assert "[Rerank Paper](paper1.evidence.html#results-p1-s0001)" in markdown


def test_cli_review_matrix_layers_apply_and_report_template(tmp_path: Path, capsys):
    layer_db = tmp_path / "layers.sqlite"
    matrix_path = tmp_path / "matrix.csv"
    reviewed_path = tmp_path / "reviewed.csv"
    report_path = tmp_path / "report.md"
    write_annotation_layer(layer_db, _annotation_payload(), layer_id="rerank", name="Rerank", replace=True)

    exit_code = cli.main(
        [
            "review-matrix",
            "--layers",
            str(layer_db),
            "--output",
            str(matrix_path),
            "--format",
            "csv",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["rows"] == 1
    assert payload["layer_db_path"] == str(layer_db)
    with matrix_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())
    rows[0]["review_state"] = "confirmed"
    with reviewed_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    apply_exit_code = cli.main(
        [
            "review-apply",
            "--layers",
            str(layer_db),
            "--review",
            str(reviewed_path),
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    layers = load_annotation_layers(layer_db)
    assert apply_exit_code == 0
    assert apply_payload["updated"] == 1
    assert layers[0]["items"][0]["review_state"] == "confirmed"

    report_exit_code = cli.main(
        [
            "review-matrix",
            "--layers",
            str(layer_db),
            "--template",
            "report",
            "--output",
            str(report_path),
        ]
    )

    report_payload = json.loads(capsys.readouterr().out)
    markdown = report_path.read_text(encoding="utf-8")
    assert report_exit_code == 0
    assert report_payload["rows"] == 1
    assert report_payload["format"] == "md"
    assert report_payload["template"] == "report"
    assert "# 证据综述草稿" in markdown
    assert "Qwen3 reranking improved evidence retrieval recall." in markdown
    assert "paper1.evidence.html#results-p1-s0001" in markdown
