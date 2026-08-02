from pathlib import Path

from scansci_html.models import FetchResponse
from scansci_html.service import batch_save_clean_html, save_clean_html


class StaticFetcher:
    def __init__(
        self,
        html: str,
        final_url: str = "https://publisher.example/article",
        source: str = "static",
        warnings: list[str] | None = None,
    ):
        self.html = html
        self.final_url = final_url
        self.source = source
        self.warnings = warnings or []

    def fetch(self, url: str) -> FetchResponse:
        return FetchResponse(
            url=url,
            final_url=self.final_url,
            html=self.html,
            status_code=200,
            source=self.source,
            warnings=list(self.warnings),
        )


class AssetCapableFetcher(StaticFetcher):
    def __init__(self, html: str, image_bytes_by_url: dict[str, bytes]):
        super().__init__(html)
        self.image_bytes_by_url = image_bytes_by_url
        self.asset_urls: list[str] = []

    def get(self, url: str, *, timeout: float, headers: dict[str, str]):
        self.asset_urls.append(url)
        return FakeAssetResponse(content=self.image_bytes_by_url[url])


class SequenceFetcher:
    def __init__(self, responses: list[tuple[str, str]]):
        self.responses = responses
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchResponse:
        self.urls.append(url)
        source, html = self.responses.pop(0)
        return FetchResponse(
            url=url,
            final_url=url.replace("https://doi.org/", "https://publisher.example/articles/"),
            html=html,
            status_code=200,
            source=source,
        )


class BatchRetryFetcher:
    def __init__(self):
        self.urls: list[str] = []
        self.calls_by_url: dict[str, int] = {}

    def fetch(self, url: str) -> FetchResponse:
        self.urls.append(url)
        self.calls_by_url[url] = self.calls_by_url.get(url, 0) + 1
        if url == "https://doi.org/10.1126/science.aed5051":
            return FetchResponse(
                url=url,
                final_url="https://www.science.org/",
                html="""
                <main>
                  <title>Science | AAAS</title>
                  <h3>Violet seed propulsion inspires robot design</h3>
                  <p>Latest news First release Science Advances Science Robotics.</p>
                </main>
                """,
                source="cloakbrowser",
                warnings=["browser access state: fulltext"],
            )
        doi = "10.1126/science.aed5051" if "aed5051" in url else "10.1126/science.adz4320"
        return FetchResponse(
            url=url,
            final_url=f"https://www.science.org/doi/{doi}",
            html=f"""
            <article class="article__body">
              <h1>Recovered Science Article {doi}</h1>
              <p>DOI: {doi}</p>
              <section><h2>Abstract</h2><p>The abstract is visible after session recovery.</p></section>
              <section><h2>Results</h2><p>The full body is visible in the same browser session.</p></section>
              <section><h2>Discussion</h2><p>The article remains readable after retry.</p></section>
              <section><h2>References and Notes</h2><p>References are visible after retry.</p></section>
            </article>
            """,
            source="cloakbrowser",
            warnings=["browser access state: fulltext"],
        )


class RecordingSnapshotter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def save(
        self,
        response: FetchResponse,
        *,
        output_path: Path,
        identifier: str,
        doi: str | None,
        title: str,
    ) -> Path:
        snapshot_path = output_path.with_suffix(".raw.html")
        snapshot_path.write_text(response.html, encoding="utf-8")
        self.calls.append(
            {
                "response": response,
                "output_path": output_path,
                "identifier": identifier,
                "doi": doi,
                "title": title,
                "snapshot_path": snapshot_path,
            }
        )
        return snapshot_path


class FakeAssetResponse:
    def __init__(self, *, content: bytes = b"image-bytes") -> None:
        self.content = content
        self.headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self) -> None:
        return None


class FakeAssetSession:
    def __init__(self, responses: dict[str, FakeAssetResponse]) -> None:
        self.responses = responses

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> FakeAssetResponse:
        return self.responses[url]


class MappingFetcher:
    def __init__(self, html_by_url: dict[str, str]):
        self.html_by_url = html_by_url
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchResponse:
        self.urls.append(url)
        return FetchResponse(
            url=url,
            final_url=url.replace("https://doi.org/", "https://publisher.example/articles/"),
            html=self.html_by_url[url],
            status_code=200,
            source="http",
        )


def test_save_clean_html_writes_only_html(tmp_path: Path):
    html = """
    <html>
      <body>
        <article>
          <h1>Only HTML Please</h1>
          <section><h2>Abstract</h2><p>This abstract starts the article.</p></section>
          <section><h2>Methods</h2><p>Enough full text content appears here to pass the access gate.</p></section>
          <section><h2>Results</h2><p>The saved result should be a clean standalone HTML file.</p></section>
        </article>
      </body>
    </html>
    """

    result = save_clean_html(
        "10.1234/html-only",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html),
        min_text_length=80,
    )

    assert result.status == "success"
    assert result.output_path is not None
    assert result.output_path.suffix == ".html"
    assert result.output_path.exists()
    assert "Only HTML Please" in result.output_path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.pdf"))
    assert not list(tmp_path.glob("*.md"))
    assert not list(tmp_path.glob("*.markdown"))


def test_save_clean_html_localizes_images_when_requested(tmp_path: Path):
    image_url = "https://publisher.example/images/figure-1.jpg"
    html = f"""
    <html>
      <body>
        <article>
          <h1>Illustrated Article</h1>
          <section><h2>Abstract</h2><p>This abstract starts the article.</p></section>
          <section><h2>Results</h2>
            <p>The full text is available and has a figure.</p>
            <figure><img src="{image_url}" alt="Figure 1"></figure>
          </section>
        </article>
      </body>
    </html>
    """
    asset_session = FakeAssetSession({image_url: FakeAssetResponse(content=b"figure-jpeg")})

    result = save_clean_html(
        "10.1234/illustrated",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html),
        min_text_length=80,
        download_assets=True,
        asset_session=asset_session,
    )

    assert result.status == "success"
    assert result.output_path is not None
    saved_html = result.output_path.read_text(encoding="utf-8")
    assert image_url not in saved_html
    assert '_assets/' in saved_html
    assets = list(result.output_path.with_name(f"{result.output_path.stem}_assets").iterdir())
    assert len(assets) == 1
    assert assets[0].read_bytes() == b"figure-jpeg"


def test_save_clean_html_result_includes_article_structure(tmp_path: Path):
    html = """
    <html>
      <body>
        <article>
          <h1>Structured Result Article</h1>
          <section><h2>Abstract</h2><p>The abstract is available.</p></section>
          <section><h2>Results</h2><p>The full result body is available.</p></section>
          <figure><img src="https://publisher.example/figure.jpg" alt="Figure"></figure>
          <section><h2>References</h2><ol><li>Reference one.</li><li>Reference two.</li></ol></section>
        </article>
      </body>
    </html>
    """

    result = save_clean_html(
        "10.1234/structured-result",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html),
        min_text_length=80,
    )

    assert result.status == "success"
    assert result.structure["has_body"] is True
    assert result.structure["has_endmatter"] is True
    assert result.structure["figure_count"] == 1
    assert result.structure["image_count"] == 1
    assert result.structure["reference_count"] == 2


def test_save_clean_html_rejects_collapsed_references_before_writing(tmp_path: Path):
    html = """
    <article>
      <h1>Collapsed References Article</h1>
      <section><h2>Abstract</h2><p>The abstract is visible.</p></section>
      <section><h2>Results</h2><p>The full result body is visible.</p></section>
      <section><h2>Discussion</h2><p>The discussion body is visible.</p></section>
      <section><h2>References and Notes</h2>
        <ol><li>Reference one.</li><li>Reference two.</li></ol>
        <button>SHOW ALL REFERENCES</button>
      </section>
    </article>
    """

    result = save_clean_html(
        "10.1126/science.collapsed",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://www.science.org/doi/10.1126/science.collapsed",
            source="cloakbrowser",
        ),
        min_text_length=80,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert any("collapsed references" in warning for warning in result.warnings)
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_uses_success_fetcher_for_asset_downloads(tmp_path: Path):
    image_url = "https://publisher.example/images/protected-figure.png"
    html = f"""
    <article>
      <h1>Session Bound Images</h1>
      <section><h2>Abstract</h2><p>This article has protected image assets.</p></section>
      <section><h2>Results</h2>
        <p>The same fetcher session should download the image.</p>
        <img src="{image_url}" alt="Protected figure">
      </section>
    </article>
    """
    fetcher = AssetCapableFetcher(html, {image_url: b"protected-image"})

    result = save_clean_html(
        "10.1234/session-image",
        output_dir=tmp_path,
        fetcher=fetcher,
        min_text_length=80,
        download_assets=True,
    )

    assert result.status == "success"
    assert fetcher.asset_urls == [image_url]
    assert result.output_path is not None
    saved_html = result.output_path.read_text(encoding="utf-8")
    assert image_url not in saved_html
    assets = list(result.output_path.with_name(f"{result.output_path.stem}_assets").iterdir())
    assert assets[0].read_bytes() == b"protected-image"


def test_save_clean_html_marks_current_route_auth_required_when_access_missing(tmp_path: Path):
    html = """
    <html>
      <body>
        <article>
          <h1>Locked Article</h1>
          <p>Abstract only.</p>
          <p>Access through your institution to read this article.</p>
        </article>
      </body>
    </html>
    """

    result = save_clean_html(
        "10.1234/locked",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html),
        min_text_length=80,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_marks_browser_access_gate_auth_required(tmp_path: Path):
    html = """
    <html>
      <body>
        <article>
          <h1>Science Preview</h1>
          <p>Abstract only.</p>
          <button>Check Access</button>
        </article>
      </body>
    </html>
    """

    result = save_clean_html(
        "10.1126/science.aed5051",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://www.science.org/doi/10.1126/science.aed5051",
            source="cloakbrowser",
            warnings=["browser access state: access_entry"],
        ),
        min_text_length=80,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_rejects_browser_human_login_even_if_page_is_long(tmp_path: Path):
    html = """
    <article>
      <h1>Login Shell With Long Text</h1>
      <section><h2>Introduction</h2>
        <p>This long page-shaped text should not override the browser access state.</p>
      </section>
      <section><h2>Results</h2>
        <p>The renderer may see body-like sections, but the browser detected a login page.</p>
      </section>
      <section><h2>References</h2><p>Reference text makes the page long.</p></section>
    </article>
    """

    result = save_clean_html(
        "10.1234/login-shell",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://publisher.example/login",
            source="cloakbrowser",
            warnings=["browser access state: human_login"],
        ),
        min_text_length=80,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert any("browser access state: human_login" in warning for warning in result.warnings)
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_rejects_science_home_redirect_without_requested_doi(tmp_path: Path):
    html = """
    <main>
      <h1>Science | AAAS</h1>
      <section><h2>Latest News</h2><p>Science channel content is not the requested paper.</p></section>
      <section><h2>First Release</h2><p>More channel content with enough text to look article-like.</p></section>
      <section><h2>References</h2><p>This is still not the DOI article.</p></section>
    </main>
    """

    result = save_clean_html(
        "10.1126/science.aed5051",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://www.science.org/",
            source="cloakbrowser",
        ),
        min_text_length=40,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert any("does not contain the requested DOI" in warning for warning in result.warnings)
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_rejects_science_home_html_even_when_final_url_has_doi(tmp_path: Path):
    html = """
    <main>
      <h1>Science | AAAS</h1>
      <section><h2>Latest News</h2><p>Science channel content is not the requested paper.</p></section>
      <section><h2>First Release</h2><p>More channel content with enough text to look article-like.</p></section>
      <section><h2>References</h2><p>This is still not the DOI article.</p></section>
    </main>
    """

    result = save_clean_html(
        "10.1126/science.aed5051",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://www.science.org/doi/10.1126/science.aed5051",
            source="cloakbrowser",
        ),
        min_text_length=40,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert any("does not contain the requested DOI" in warning for warning in result.warnings)
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_rejects_wiley_abstract_page_even_when_text_is_long(tmp_path: Path):
    html = """
    <article>
      <h1>Utilizing palm oil mill effluent for biodiesel synthesis</h1>
      <p>Author affiliation text repeated across the abstract landing page.</p>
      <section><h2>Supporting Information</h2>
        <p>Supporting information text is visible but this is not the article body.</p>
      </section>
      <section><h2>References</h2>
        <p>Reference text mentions Materials, immobilization, lipase, and biodiesel.</p>
        <p>More reference text makes the page long enough to resemble full text.</p>
      </section>
      <section><h2>Citing Literature</h2><p>Backmatter continues here.</p></section>
    </article>
    """

    result = save_clean_html(
        "10.1002/bbb.2202",
        output_dir=tmp_path,
        fetcher=StaticFetcher(
            html,
            final_url="https://scijournals.onlinelibrary.wiley.com/doi/abs/10.1002/bbb.2202",
            source="cloakbrowser",
            warnings=["browser access state: subscription_preview"],
        ),
        min_text_length=80,
    )

    assert result.status == "auth_required"
    assert result.output_path is None
    assert any("wiley abstract page" in warning for warning in result.warnings)
    assert list(tmp_path.iterdir()) == []


def test_save_clean_html_uses_authorization_browser_when_preflight_needs_auth(tmp_path: Path):
    locked_html = """
    <article>
      <h1>Locked Then Authorized</h1>
      <p>This is a preview of subscription content, access via your institution.</p>
    </article>
    """
    full_html = """
    <article>
      <h1>Locked Then Authorized</h1>
      <section><h2>Abstract</h2><p>The authorized page has readable article text.</p></section>
      <section><h2>Results</h2><p>The browser session exposes the full HTML body.</p></section>
    </article>
    """
    preflight = SequenceFetcher([("http", locked_html)])
    auth_browser = SequenceFetcher([("cloakbrowser", full_html)])

    result = save_clean_html(
        "10.1234/authorized",
        output_dir=tmp_path,
        fetcher=preflight,
        auth_fetcher=auth_browser,
        min_text_length=60,
    )

    assert result.status == "success"
    assert preflight.urls == ["https://doi.org/10.1234/authorized"]
    assert auth_browser.urls == ["https://doi.org/10.1234/authorized"]
    assert result.output_path is not None
    assert result.output_path.exists()


def test_batch_save_clean_html_preserves_exact_input_list_without_substitution(tmp_path: Path):
    full_html = """
    <article>
      <h1>Accessible Batch Article</h1>
      <section><h2>Abstract</h2><p>This is the article abstract.</p></section>
      <section><h2>Results</h2><p>The full text is available and should be saved.</p></section>
    </article>
    """
    locked_html = """
    <article>
      <h1>Locked Batch Article</h1>
      <p>This is a preview of subscription content, access via your institution.</p>
    </article>
    """
    identifiers = ["10.1234/first", "10.1234/second"]
    fetcher = MappingFetcher(
        {
            "https://doi.org/10.1234/first": full_html,
            "https://doi.org/10.1234/second": locked_html,
        }
    )

    results = batch_save_clean_html(
        identifiers,
        output_dir=tmp_path,
        fetcher=fetcher,
        min_text_length=50,
    )

    assert [result.identifier for result in results] == identifiers
    assert [result.status for result in results] == ["success", "auth_required"]
    assert fetcher.urls == [
        "https://doi.org/10.1234/first",
        "https://doi.org/10.1234/second",
    ]
    assert len(list(tmp_path.glob("*.html"))) == 1
    assert not list(tmp_path.glob("*.pdf"))
    assert not list(tmp_path.glob("*.md"))


def test_batch_save_clean_html_retries_incomplete_science_items_in_same_session(tmp_path: Path):
    identifiers = ["10.1126/science.aed5051", "10.1126/science.adz4320"]
    fetcher = BatchRetryFetcher()

    results = batch_save_clean_html(
        identifiers,
        output_dir=tmp_path,
        fetcher=fetcher,
        min_text_length=50,
        retry_incomplete_rounds=1,
    )

    assert [result.identifier for result in results] == identifiers
    assert [result.status for result in results] == ["success", "success"]
    assert fetcher.urls == [
        "https://doi.org/10.1126/science.aed5051",
        "https://doi.org/10.1126/science.adz4320",
        "https://www.science.org/doi/10.1126/science.aed5051",
    ]
    assert results[0].source_url == "https://www.science.org/doi/10.1126/science.aed5051"
    assert len(list(tmp_path.glob("*.html"))) == 2


def test_output_filename_is_stable_and_safe(tmp_path: Path):
    html = """
    <article>
      <h1>Forest/Climate Feedbacks: A Test?</h1>
      <p>This article has a long enough body to be saved as clean HTML.</p>
      <p>Additional scientific full text gives the cleaner enough content.</p>
    </article>
    """

    result = save_clean_html(
        "10.5555/Sci.Adv:ABC/123",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html),
        min_text_length=40,
    )

    assert result.status == "success"
    assert result.output_path is not None
    assert result.output_path.name == "10.5555_Sci.Adv_ABC_123_forest_climate_feedbacks_a_test.html"


def test_save_clean_html_uses_structured_source_before_http_or_browser(tmp_path: Path):
    official_full_html = """
    <article>
      <h1>Official Structured Full Text</h1>
      <section><h2>Abstract</h2><p>The official source has a real abstract.</p></section>
      <section><h2>Results</h2><p>The official source has enough full text to save.</p></section>
      <section><h2>References</h2><p>Reference one.</p></section>
    </article>
    """
    locked_html = """
    <article><h1>Locked</h1><p>Access through your institution.</p></article>
    """
    browser_full_html = """
    <article><h1>Browser Full Text</h1><p>This browser body should not be needed.</p></article>
    """
    official_source = SequenceFetcher([("pmc-jats", official_full_html)])
    http_fetcher = SequenceFetcher([("http", locked_html)])
    auth_browser = SequenceFetcher([("cloakbrowser", browser_full_html)])

    result = save_clean_html(
        "10.1234/official",
        output_dir=tmp_path,
        source_fetchers=[official_source],
        fetcher=http_fetcher,
        auth_fetcher=auth_browser,
        min_text_length=80,
    )

    assert result.status == "success"
    assert "Official Structured Full Text" in result.output_path.read_text(encoding="utf-8")
    assert official_source.urls == ["https://doi.org/10.1234/official"]
    assert http_fetcher.urls == []
    assert auth_browser.urls == []


def test_save_clean_html_falls_back_to_browser_when_structured_source_is_not_fulltext(
    tmp_path: Path,
):
    official_preview_html = """
    <article><h1>Official Preview</h1><p>Abstract only.</p></article>
    """
    locked_html = """
    <article><h1>Publisher Preview</h1><p>Access through your institution.</p></article>
    """
    browser_full_html = """
    <article>
      <h1>Authorized Browser Full Text</h1>
      <section><h2>Abstract</h2><p>The browser page has an abstract.</p></section>
      <section><h2>Discussion</h2><p>The browser page has the authorized body.</p></section>
    </article>
    """
    official_source = SequenceFetcher([("pmc-jats", official_preview_html)])
    http_fetcher = SequenceFetcher([("http", locked_html)])
    auth_browser = SequenceFetcher([("cloakbrowser", browser_full_html)])

    result = save_clean_html(
        "10.1234/fallback",
        output_dir=tmp_path,
        source_fetchers=[official_source],
        fetcher=http_fetcher,
        auth_fetcher=auth_browser,
        min_text_length=80,
    )

    assert result.status == "success"
    assert "Authorized Browser Full Text" in result.output_path.read_text(encoding="utf-8")
    assert official_source.urls == ["https://doi.org/10.1234/fallback"]
    assert http_fetcher.urls == ["https://doi.org/10.1234/fallback"]
    assert auth_browser.urls == ["https://doi.org/10.1234/fallback"]


def test_save_clean_html_writes_optional_raw_snapshot_for_success(tmp_path: Path):
    html = """
    <html>
      <body>
        <article>
          <h1>Snapshot Article</h1>
          <section><h2>Abstract</h2><p>This article can be captured cleanly.</p></section>
          <section><h2>Results</h2><p>The raw HTML should be saved separately as evidence.</p></section>
        </article>
      </body>
    </html>
    """
    snapshotter = RecordingSnapshotter()

    result = save_clean_html(
        "10.1234/snapshot",
        output_dir=tmp_path,
        fetcher=StaticFetcher(html, source="cloakbrowser"),
        snapshotter=snapshotter,
        min_text_length=80,
    )

    assert result.status == "success"
    assert result.snapshot_path is not None
    assert result.snapshot_path.exists()
    assert result.snapshot_path.suffixes[-2:] == [".raw", ".html"]
    assert "Snapshot Article" in result.snapshot_path.read_text(encoding="utf-8")
    assert snapshotter.calls[0]["doi"] == "10.1234/snapshot"
