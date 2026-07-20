from scansci_html.article_structure import extract_article_structure


def test_extract_article_structure_counts_sections_assets_and_references():
    html = """
    <article class="paper" data-doi="10.1234/structure" data-source-url="https://publisher.example/article">
      <h1>Structured Paper</h1>
      <section><h2>Abstract</h2><p>This abstract introduces the study.</p></section>
      <section><h2>Results</h2><p>The result body is visible.</p></section>
      <section><h2>Discussion</h2><p>The discussion body is visible.</p></section>
      <figure><img src="figure-1.png" alt="Figure 1"><figcaption>Figure 1.</figcaption></figure>
      <table><tr><td>A</td><td>B</td></tr></table>
      <section><h2>References and Notes</h2>
        <ol>
          <li>Reference one.</li>
          <li>Reference two.</li>
        </ol>
      </section>
    </article>
    """

    structure = extract_article_structure(
        html,
        source_url="https://publisher.example/article",
        doi="10.1234/structure",
    )

    assert structure.title == "Structured Paper"
    assert [section.heading for section in structure.sections] == [
        "Structured Paper",
        "Abstract",
        "Results",
        "Discussion",
        "References and Notes",
    ]
    assert structure.body_section_count == 2
    assert structure.has_body is True
    assert structure.has_endmatter is True
    assert structure.figure_count == 1
    assert structure.image_count == 1
    assert structure.table_count == 1
    assert structure.reference_count == 2
    assert structure.access_markers == []


def test_extract_article_structure_flags_access_gate_without_body():
    html = """
    <main>
      <h1>Science Preview</h1>
      <h2>Editor's summary</h2><p>Only the summary is visible.</p>
      <h2>Abstract</h2><p>Only the abstract is visible.</p>
      <a class="access-control">CHECK ACCESS</a>
      <p>Access content through your institution.</p>
    </main>
    """

    structure = extract_article_structure(
        html,
        source_url="https://www.science.org/doi/10.1126/science.aed5051",
        doi="10.1126/science.aed5051",
    )

    assert "check-access" in structure.access_markers
    assert "institutional-login" in structure.access_markers
    assert structure.has_body is False
    assert structure.blocking_warnings() == [
        "article structure shows access gate without body sections"
    ]


def test_extract_article_structure_detects_collapsed_references():
    html = """
    <article>
      <h1>Science Article</h1>
      <section><h2>Abstract</h2><p>The abstract is visible.</p></section>
      <section><h2>Results</h2><p>The full result body is visible.</p></section>
      <section><h2>Discussion</h2><p>The discussion body is visible.</p></section>
      <section><h2>References and Notes</h2>
        <ol><li>Reference one.</li><li>Reference two.</li><li>Reference three.</li></ol>
        <button>SHOW ALL REFERENCES</button>
      </section>
    </article>
    """

    structure = extract_article_structure(html)

    assert structure.collapsed_reference_markers == ["show-all-references"]
    assert structure.blocking_warnings() == [
        "article structure indicates collapsed references; expand references before saving"
    ]


def test_extract_article_structure_treats_dotted_numbered_headings_as_body():
    html = """
    <article class="paper">
      <h1>Numbered Paper</h1>
      <h2>1. Introduction</h2><p>The introduction body is visible.</p>
      <h2>2. Materials and methods</h2><p>The methods body is visible.</p>
      <h2>3. Results</h2><p>The results body is visible.</p>
    </article>
    """

    structure = extract_article_structure(html)

    assert structure.body_section_count == 3
    assert structure.has_body is True
