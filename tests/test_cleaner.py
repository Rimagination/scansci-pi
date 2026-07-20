from scansci_html.cleaner import CleanHtmlRenderer


def test_cleaner_keeps_article_structure_and_removes_site_chrome():
    raw_html = """
    <html>
      <head>
        <title>Publisher Shell</title>
        <script>alert("noise")</script>
      </head>
      <body>
        <nav>Home | Articles</nav>
        <main>
          <article>
            <h1>Clean Article Title</h1>
            <p class="authors">A. Researcher and B. Scholar</p>
            <section>
              <h2>Abstract</h2>
              <p>This study has a detailed abstract.</p>
            </section>
            <section>
              <h2>Results</h2>
              <p>The full text contains enough scientific content to keep.</p>
              <figure>
                <img src="https://example.org/figure1.png" alt="Figure 1">
                <figcaption>Figure 1. A useful figure.</figcaption>
              </figure>
              <table>
                <caption>Table 1</caption>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Accuracy</td><td>0.95</td></tr>
              </table>
            </section>
          </article>
        </main>
        <aside class="related-content">Recommended articles</aside>
        <div class="share-tools">Share this article</div>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=100).render(
        raw_html,
        source_url="https://publisher.example/article",
        doi="10.1234/example",
    )

    assert document.title == "Clean Article Title"
    assert document.text_length > 120
    assert "Home | Articles" not in document.html
    assert "Recommended articles" not in document.html
    assert "Share this article" not in document.html
    assert "<script" not in document.html
    assert "Figure 1. A useful figure." in document.html
    assert "<table" in document.html
    assert 'data-source-url="https://publisher.example/article"' in document.html
    assert 'data-doi="10.1234/example"' in document.html
    assert document.html.count("<html") == 1
    assert document.html.count("<body") == 1
    assert '<article class="paper"' in document.html
    article_fragment = document.html.split('<article class="paper"', 1)[1]
    assert "<html" not in article_fragment
    assert "<body" not in article_fragment


def test_cleaner_reports_no_access_for_paywall_shell():
    raw_html = """
    <html>
      <body>
        <main>
          <h1>Interesting Article</h1>
          <p>Abstract only.</p>
          <p>Purchase this article or sign in through your institution to read the full text.</p>
        </main>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=80).render(
        raw_html,
        source_url="https://publisher.example/paywall",
        doi="10.1234/paywall",
    )

    assert document.has_fulltext is False
    assert document.access_status == "no_access"
    assert any("paywall" in warning for warning in document.warnings)


def test_cleaner_rejects_long_subscription_preview_without_main_body():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Subscription Preview Article</h1>
          <section><h2>Abstract</h2>
            <p>This abstract is long enough to describe the paper but it is still only a preview.</p>
          </section>
          <p>This is a preview of subscription content, access via your institution</p>
          <section><h2>Access options</h2><p>Access Nature and other journals.</p></section>
          <section><h2>Data availability</h2><p>Data are available from the corresponding author.</p></section>
          <section><h2>References</h2>
            <p>Reference 1. A long citation-like paragraph that inflates the page text.</p>
            <p>Reference 2. Another long citation-like paragraph that is not the article body.</p>
          </section>
          <section><h2>Extended data figures and tables</h2>
            <p>Extended Data Fig. 1. This caption is long but still not main article text.</p>
          </section>
        </article>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=120).render(
        raw_html,
        source_url="https://www.nature.com/articles/example",
        doi="10.1038/example",
    )

    assert document.has_fulltext is False
    assert document.access_status == "no_access"
    assert any("preview" in warning for warning in document.warnings)


def test_cleaner_does_not_treat_domain_as_main_heading():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Subscription Preview With Domain Heading</h1>
          <section><h2>Abstract</h2>
            <p>This page has an abstract and back matter but no article body.</p>
          </section>
          <p>This is a preview of subscription content, access via your institution</p>
          <section><h2>Protein domains in extended data</h2>
            <p>A long caption-like paragraph mentions domains but is not Main text.</p>
          </section>
          <section><h2>References</h2>
            <p>Reference text that makes the page longer than a tiny landing page.</p>
          </section>
        </article>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=80).render(
        raw_html,
        source_url="https://www.nature.com/articles/domain-example",
        doi="10.1038/domain-example",
    )

    assert document.has_fulltext is False
    assert document.access_status == "no_access"


def test_cleaner_allows_fulltext_when_access_links_are_present():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Accessible Article With Sign-In Link</h1>
          <p>Access through your institution is available in the page header.</p>
          <section><h2>Abstract</h2><p>This is a substantial abstract for a full article.</p></section>
          <section><h2>Introduction</h2><p>The full text is present and readable in this document.</p></section>
          <section><h2>Results</h2><p>Multiple complete sections provide enough article text to preserve.</p></section>
          <section><h2>Discussion</h2><p>The discussion confirms this is not merely a locked landing page.</p></section>
        </article>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=120).render(
        raw_html,
        source_url="https://publisher.example/article",
        doi="10.1234/accessible",
    )

    assert document.has_fulltext is True
    assert document.access_status == "fulltext"
    assert any("access marker" in warning for warning in document.warnings)


def test_cleaner_promotes_lazy_image_data_src_over_placeholder():
    html = """
    <main>
      <h1>Lazy Image Article</h1>
      <section>
        <h2>Results</h2>
        <p>The full text body is visible and long enough for saving.</p>
        <figure>
          <img
            src="data:image/png;base64,placeholder"
            data-src="/figures/result-1.png"
            alt="Result figure">
          <figcaption>Figure 1. Result figure.</figcaption>
        </figure>
      </section>
    </main>
    """

    document = CleanHtmlRenderer(min_text_length=20).render(
        html,
        source_url="https://publisher.example/article",
        doi="10.1234/lazy-image",
    )

    assert 'src="https://publisher.example/figures/result-1.png"' in document.html
    assert "data-src" not in document.html


def test_cleaner_allows_science_fulltext_with_access_widget_text():
    raw_html = """
    <html>
      <body>
        <main class="article__body">
          <h1>Science Article With Access Widget</h1>
          <p>Get Access through your institution</p>
          <div class="section-label">Abstract</div>
          <p>This complete abstract introduces a long research article.</p>
          <div class="section-label">Introduction</div>
          <p>The introduction is visible and contains full article content.</p>
          <div class="section-label">Results</div>
          <p>The results are visible and not merely a landing-page summary.</p>
          <div class="section-label">Discussion</div>
          <p>The discussion is visible with enough text to be a full article.</p>
          <div class="section-label">References and Notes</div>
          <p>Reference 1. A normal Science reference section is present.</p>
        </main>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=160).render(
        raw_html,
        source_url="https://www.science.org/doi/10.1126/science.example",
        doi="10.1126/science.example",
    )

    assert document.has_fulltext is True
    assert document.access_status == "fulltext"
    assert any("access marker" in warning for warning in document.warnings)


def test_cleaner_rejects_science_preview_with_access_full_article_gate():
    raw_html = """
    <html>
      <body>
        <main class="article__body">
          <h1>Science Preview Article</h1>
          <h2>Editor’s summary</h2>
          <p>A public editor summary is visible.</p>
          <h2>Structured Abstract</h2>
          <h3>INTRODUCTION</h3><p>Structured abstract introduction.</p>
          <h3>RATIONALE</h3><p>Structured abstract rationale.</p>
          <h3>RESULTS</h3><p>Structured abstract results.</p>
          <h3>CONCLUSION</h3><p>Structured abstract conclusion.</p>
          <h2>Abstract</h2>
          <p>The normal abstract is visible.</p>
          <h2>Access the full article</h2>
          <p>Check Access through your institution.</p>
          <h2>Supplementary Materials</h2>
          <h2>References and Notes</h2>
          <p>Reference 1. A reference list can be visible even without the full body.</p>
        </main>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=120).render(
        raw_html,
        source_url="https://www.science.org/doi/10.1126/science.preview",
        doi="10.1126/science.preview",
    )

    assert document.has_fulltext is False
    assert document.access_status == "no_access"
    assert any("science full article access gate" in warning for warning in document.warnings)


def test_cleaner_skips_descendants_after_noise_parent_is_removed():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Robust Article</h1>
          <p>The article body remains available after removing noisy page chrome.</p>
          <p>Enough text is present for the clean HTML renderer to keep this document.</p>
        </article>
        <div class="share-tools">
          <span data-noisy-child="1">Share</span>
        </div>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=40).render(
        raw_html,
        source_url="https://publisher.example/article",
        doi="10.1234/robust",
    )

    assert document.has_fulltext is True
    assert "data-noisy-child" not in document.html
    assert "Robust Article" in document.html


def test_cleaner_skips_descendants_after_noise_inside_article_is_removed():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Article With Internal Noise</h1>
          <p>The article body remains readable after internal sharing tools are removed.</p>
          <div class="share-tools">
            <span data-noisy-child="1">Share this paragraph</span>
          </div>
          <p>Enough content remains for a clean standalone HTML output.</p>
        </article>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=40).render(
        raw_html,
        source_url="https://publisher.example/article",
        doi="10.1234/internal-noise",
    )

    assert document.has_fulltext is True
    assert "Share this paragraph" not in document.html
    assert "Article With Internal Noise" in document.html


def test_cleaner_preserves_media_inside_textless_wrappers():
    raw_html = """
    <html>
      <body>
        <article>
          <h1>Article With Wrapped Figure</h1>
          <p>The article has enough text before the wrapped figure.</p>
          <div class="media-wrapper">
            <img src="/figures/one.png" alt="Wrapped figure">
          </div>
          <p>More content follows the wrapped figure so the page remains full text.</p>
        </article>
      </body>
    </html>
    """

    document = CleanHtmlRenderer(min_text_length=40).render(
        raw_html,
        source_url="https://publisher.example/articles/example",
        doi="10.1234/wrapped-figure",
    )

    assert document.has_fulltext is True
    assert "Wrapped figure" in document.html
    assert 'src="https://publisher.example/figures/one.png"' in document.html
