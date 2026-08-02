import json
from pathlib import Path

from scansci_html import cli
from scansci_html.artifacts import discover_artifact_records
from scansci_html.data_availability import extract_data_availability_records
from scansci_html.references import extract_reference_records


def test_extract_reference_records_keeps_doi_and_no_doi_entries():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <h2>Results</h2>
      <p>Body DOI 10.9999/not-a-reference should not be used.</p>
      <h2>References</h2>
      <ol>
        <li id="ref-1">Smith J, Doe A. Dataset paper title. Nature Data 12, 1-4 (2020). https://doi.org/10.1000/alpha</li>
        <li id="ref-2">李四, 王五. 中文参考文献题名. 生态学报, 2021, 41(1): 1-9.</li>
      </ol>
    </article>
    """

    records = extract_reference_records(html, html_path=Path("paper.html"))

    assert [record.to_dict() for record in records] == [
        {
            "reference_id": "paper:ref-1",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "ref-1",
            "raw_text": "Smith J, Doe A. Dataset paper title. Nature Data 12, 1-4 (2020). https://doi.org/10.1000/alpha",
            "doi": "10.1000/alpha",
            "title": "Dataset paper title",
            "authors": "Smith J, Doe A",
            "year": 2020,
            "venue": "Nature Data",
            "language": "en",
            "record_type": "dataset_paper",
            "confidence": 0.8,
            "review_state": "unreviewed",
        },
        {
            "reference_id": "paper:ref-2",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "ref-2",
            "raw_text": "李四, 王五. 中文参考文献题名. 生态学报, 2021, 41(1): 1-9.",
            "doi": "",
            "title": "中文参考文献题名",
            "authors": "李四, 王五",
            "year": 2021,
            "venue": "生态学报",
            "language": "zh",
            "record_type": "unknown",
            "confidence": 0.55,
            "review_state": "unreviewed",
        },
    ]


def test_extract_data_availability_records_classifies_statement_and_links_artifacts():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <section>
        <h2>Data availability</h2>
        <p id="availability-p1">The source data are available at
          <a href="https://zenodo.org/records/12345">Zenodo</a> under a CC BY license.
        </p>
      </section>
    </article>
    """

    records = extract_data_availability_records(
        html,
        html_path=Path("paper.html"),
        source_url="https://example.org/paper",
    )

    assert [record.to_dict() for record in records] == [
        {
            "availability_id": "paper:data-availability-0001",
            "source_doc_id": "10.1234/source",
            "statement_text": "The source data are available at Zenodo under a CC BY license.",
            "source_html_path": "paper.html",
            "source_anchor": "availability-p1",
            "availability_status": "yes",
            "repository": "zenodo",
            "url": "https://zenodo.org/records/12345",
            "doi": "",
            "license": "CC BY",
            "files_available": False,
            "evidence_level": "metadata_page",
            "confidence": 0.8,
            "review_state": "unreviewed",
        }
    ]


def test_extract_data_availability_records_detects_by_request():
    html = """
    <article class="paper">
      <h2>Data availability</h2>
      <p id="availability-p1">Data are available from the corresponding author upon reasonable request.</p>
    </article>
    """

    records = extract_data_availability_records(html, html_path=Path("paper.html"))

    assert records[0].availability_status == "by_request"
    assert records[0].evidence_level == "statement_only"


def test_cli_investigate_references_writes_csv_and_jsonl(tmp_path: Path, capsys):
    html_path = tmp_path / "paper.html"
    csv_path = tmp_path / "references.csv"
    jsonl_path = tmp_path / "references.jsonl"
    html_path.write_text(
        """
        <article class="paper" data-doi="10.1234/source">
          <h2>References</h2>
          <ol><li id="ref-1">Smith J. Dataset paper title. Data Journal (2020). doi:10.1000/example</li></ol>
        </article>
        """,
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "investigate",
            "references",
            "--html",
            str(html_path),
            "--output",
            str(csv_path),
            "--jsonl-output",
            str(jsonl_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["output_path"] == str(csv_path)
    assert payload["jsonl_output_path"] == str(jsonl_path)
    assert "reference_id,source_doc_id,source_html_path" in csv_path.read_text(encoding="utf-8")
    assert json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])["doi"] == "10.1000/example"


def test_cli_investigate_artifacts_writes_csv(tmp_path: Path, capsys):
    html_path = tmp_path / "paper.html"
    csv_path = tmp_path / "artifacts.csv"
    html_path.write_text(
        """
        <article class="paper" data-doi="10.1234/source" data-source-url="https://example.org/paper">
          <h2>Supplementary information</h2>
          <p><a id="supp-1" href="/supplementary/source-data.xlsx?token=SECRET">Source data</a></p>
        </article>
        """,
        encoding="utf-8",
    )

    exit_code = cli.main(["investigate", "artifacts", "--html", str(html_path), "--output", str(csv_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["count"] == 1
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "artifact_id,source_doc_id,source_html_path" in csv_text
    assert "token=SECRET" not in csv_text
    assert "https://example.org/supplementary/source-data.xlsx" in csv_text


def test_cli_investigate_availability_writes_csv(tmp_path: Path, capsys):
    html_path = tmp_path / "paper.html"
    csv_path = tmp_path / "data_availability.csv"
    html_path.write_text(
        """
        <article class="paper" data-doi="10.1234/source">
          <h2>Data availability</h2>
          <p id="availability-p1">Data are available from the corresponding author upon reasonable request.</p>
        </article>
        """,
        encoding="utf-8",
    )

    exit_code = cli.main(["investigate", "availability", "--html", str(html_path), "--output", str(csv_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["count"] == 1
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "availability_id,source_doc_id,statement_text" in csv_text
    assert "by_request" in csv_text


def test_discover_artifact_records_sanitizes_urls_and_classifies_repositories():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <h2>Data availability</h2>
      <p id="data-availability">Source data are available at
        <a href="https://figshare.com/articles/dataset/example/123?token=SECRET">Figshare dataset</a>.
      </p>
      <h2>Supplementary information</h2>
      <p><a id="supp-1" href="/articles/supplementary.xlsx?nonce=SECRET">Supplementary Table 1</a></p>
    </article>
    """

    records = discover_artifact_records(
        html,
        html_path=Path("paper.html"),
        source_url="https://example.org/paper",
    )

    assert [record.to_dict() for record in records] == [
        {
            "artifact_id": "paper:artifact-0001",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "data-availability",
            "label": "Figshare dataset",
            "url": "https://figshare.com/articles/dataset/example/123",
            "doi": "",
            "repository": "figshare",
            "artifact_type": "dataset_record",
            "content_type": "",
            "size_bytes": "",
            "license": "",
            "access_status": "metadata_only",
            "downloaded_path": "",
            "checked_at": "",
            "review_state": "unreviewed",
        },
        {
            "artifact_id": "paper:artifact-0002",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "supp-1",
            "label": "Supplementary Table 1",
            "url": "https://example.org/articles/supplementary.xlsx",
            "doi": "",
            "repository": "publisher",
            "artifact_type": "xlsx",
            "content_type": "",
            "size_bytes": "",
            "license": "",
            "access_status": "unknown",
            "downloaded_path": "",
            "checked_at": "",
            "review_state": "unreviewed",
        },
    ]
