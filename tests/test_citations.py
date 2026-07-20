import json
from pathlib import Path

from scansci_html import cli
from scansci_html.citations import extract_reference_candidates


def test_extract_reference_candidates_reads_reference_section_dois():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <h2>Results</h2>
      <p>Body DOI 10.9999/not-a-reference should not be used.</p>
      <h2>References</h2>
      <ol>
        <li id="ref-1">A cited paper. https://doi.org/10.1000/alpha</li>
        <li id="ref-2"><a href="https://doi.org/10.1000/beta">doi link</a></li>
      </ol>
    </article>
    """

    candidates = extract_reference_candidates(html, html_path=Path("paper.html"))

    assert [candidate.to_dict() for candidate in candidates] == [
        {
            "doi": "10.1000/alpha",
            "source_html_path": "paper.html",
            "source_anchor": "ref-1",
            "source_text": "A cited paper. https://doi.org/10.1000/alpha",
        },
        {
            "doi": "10.1000/beta",
            "source_html_path": "paper.html",
            "source_anchor": "ref-2",
            "source_text": "doi link",
        },
    ]


def test_cli_references_emits_reference_candidates(tmp_path: Path, capsys):
    html_path = tmp_path / "paper.html"
    html_path.write_text(
        """
        <article class="paper">
          <h1>Paper</h1>
          <h2>References</h2>
          <p id="ref-p">Reference text with DOI 10.1000/example.</p>
        </article>
        """,
        encoding="utf-8",
    )

    exit_code = cli.main(["references", "--html", str(html_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "html_path": str(html_path),
        "references": [
            {
                "doi": "10.1000/example",
                "source_html_path": str(html_path).replace("\\", "/"),
                "source_anchor": "ref-p",
                "source_text": "Reference text with DOI 10.1000/example.",
            }
        ],
    }
