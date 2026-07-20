import json
from pathlib import Path

from scansci_html.evidence import extract_evidence_blocks, index_html_library


def test_extract_evidence_blocks_keeps_doc_metadata_sections_and_anchors():
    html = """
    <!doctype html>
    <html>
      <head><title>Fallback Title</title></head>
      <body>
        <article class="paper" data-doi="10.1234/example" data-source-url="https://publisher.example/article">
          <h1>Evidence First Article</h1>
          <section id="abstract-section">
            <h2 id="abstract">Abstract</h2>
            <p>The blastopore lip induced a secondary axis in the host embryo.</p>
          </section>
          <section id="results-section">
            <h2 id="results">Results</h2>
            <p id="result-p1">Host cells were recruited into the induced pharynx.</p>
            <figure>
              <figcaption>Fig. 1. Transplantation outcomes across treatments.</figcaption>
            </figure>
          </section>
        </article>
      </body>
    </html>
    """

    blocks = extract_evidence_blocks(
        html,
        html_path=Path("library/article.html"),
        min_text_length=20,
    )

    assert [block.block_type for block in blocks] == ["paragraph", "paragraph", "caption"]
    assert blocks[0].doc_id == "10.1234_example"
    assert blocks[0].title == "Evidence First Article"
    assert blocks[0].doi == "10.1234/example"
    assert blocks[0].source_url == "https://publisher.example/article"
    assert blocks[0].html_path == "library/article.html"
    assert blocks[0].section == "Abstract"
    assert blocks[0].anchor == "evidence-0001"
    assert blocks[1].section == "Results"
    assert blocks[1].anchor == "result-p1"
    assert blocks[2].text == "Fig. 1. Transplantation outcomes across treatments."


def test_index_html_library_writes_jsonl_manifest_with_stable_blocks(tmp_path: Path):
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/library" data-source-url="https://publisher.example/library">
          <h1>Library Paper</h1>
          <h2>Methods</h2>
          <p>Embryos were treated with an inhibitor before scoring.</p>
          <p>Replicate-level counts were analysed with a mixed model.</p>
        </article>
        """,
        encoding="utf-8",
    )
    output = tmp_path / "evidence.jsonl"

    summary = index_html_library(html_dir, output_path=output, min_text_length=20)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert summary == {"documents": 1, "blocks": 2, "output_path": str(output)}
    assert [row["block_id"] for row in rows] == [
        "10.1234_library:evidence-0001",
        "10.1234_library:evidence-0002",
    ]
    assert rows[0]["section"] == "Methods"
    assert rows[0]["html_path"].endswith("paper.html")
