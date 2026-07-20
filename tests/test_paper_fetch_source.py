from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scansci_html.evidence_spans import extract_evidence_spans
from scansci_html.official_sources import OfficialSourceRegistry
from scansci_html.paper_fetch_source import (
    PaperFetchProviderFetcher,
    PaperFetchSourceUnavailable,
    render_paper_fetch_article_html,
)
from scansci_html.service import save_clean_html


@dataclass
class FakeMetadata:
    title: str = "Provider Converted Paper"
    authors: list[str] = field(default_factory=lambda: ["Ada Example", "Lin Example"])
    abstract: str = "This abstract describes a provider conversion path."
    journal: str = "Journal of Provider Tests"
    published: str = "2026-03-15"
    keywords: list[str] = field(default_factory=lambda: ["retrieval", "conversion"])
    landing_page_url: str = "https://publisher.example/articles/10.1234/provider"


@dataclass
class FakeSection:
    heading: str
    level: int
    kind: str
    text: str


@dataclass
class FakeReference:
    raw: str


@dataclass
class FakeAsset:
    kind: str
    heading: str
    caption: str


@dataclass
class FakeQuality:
    has_fulltext: bool = True
    content_kind: str = "fulltext"
    warnings: list[str] = field(default_factory=lambda: ["provider xml normalized"])


@dataclass
class FakeArticle:
    doi: str = "10.1234/provider"
    source: str = "springer_html"
    metadata: FakeMetadata = field(default_factory=FakeMetadata)
    sections: list[FakeSection] = field(
        default_factory=lambda: [
            FakeSection(
                heading="Introduction",
                level=1,
                kind="introduction",
                text=(
                    "Provider extraction preserves a complete introductory sentence for retrieval. "
                    "The second sentence checks sentence-level indexing."
                ),
            ),
            FakeSection(
                heading="Results",
                level=1,
                kind="results",
                text=(
                    "Treatment increased root biomass in drought plots. "
                    "Control plots stayed unchanged across repeated measurements."
                ),
            ),
        ]
    )
    references: list[FakeReference] = field(default_factory=lambda: [FakeReference("Example et al. 2026.")])
    assets: list[FakeAsset] = field(
        default_factory=lambda: [FakeAsset("figure", "Figure 1", "Figure caption reports treatment response.")]
    )
    quality: FakeQuality = field(default_factory=FakeQuality)


@dataclass
class FakeEnvelope:
    doi: str = "10.1234/provider"
    source: str = "springer_html"
    has_fulltext: bool = True
    content_kind: str = "fulltext"
    warnings: list[str] = field(default_factory=lambda: ["provider route: springer"])
    source_trail: list[str] = field(default_factory=lambda: ["crossref", "springer_html"])
    article: FakeArticle = field(default_factory=FakeArticle)
    markdown: str = "# Provider Converted Paper\n\nMarkdown sidecar.\n"


def test_paper_fetch_article_renders_as_scansci_evidence_html(tmp_path: Path):
    html = render_paper_fetch_article_html(FakeArticle(), envelope=FakeEnvelope())

    assert '<article class="paper"' in html
    assert 'data-doi="10.1234/provider"' in html
    assert 'data-paper-fetch-source="springer_html"' in html
    assert "<h2>Results</h2>" in html

    spans = extract_evidence_spans(html, html_path=tmp_path / "provider.html", min_sentence_length=20)
    assert any(span.section == "Results" for span in spans)
    assert any("Treatment increased root biomass" in span.text for span in spans)


def test_paper_fetch_provider_fetcher_returns_fetch_response():
    fetcher = PaperFetchProviderFetcher(
        min_text_length=20,
        fetch_paper_fn=lambda query: FakeEnvelope(),
    )

    response = fetcher.fetch("https://doi.org/10.1234/provider")

    assert response.source == "paper-fetch-provider"
    assert response.final_url == "https://publisher.example/articles/10.1234/provider"
    assert "<h1>Provider Converted Paper</h1>" in response.html
    assert "paper-fetch provider source: springer_html" in response.warnings


def test_paper_fetch_provider_fetcher_skips_abstract_only_payload():
    envelope = FakeEnvelope(
        has_fulltext=False,
        content_kind="abstract_only",
        article=FakeArticle(sections=[], quality=FakeQuality(has_fulltext=False, content_kind="abstract_only")),
    )
    fetcher = PaperFetchProviderFetcher(
        min_text_length=500,
        fetch_paper_fn=lambda query: envelope,
    )

    try:
        fetcher.fetch("https://doi.org/10.1234/abstract-only")
    except PaperFetchSourceUnavailable as exc:
        assert "abstract_only" in str(exc)
    else:
        raise AssertionError("abstract-only provider payload should be skipped")


def test_save_clean_html_uses_paper_fetch_provider_as_native_structured_source(tmp_path: Path):
    source_fetcher = PaperFetchProviderFetcher(
        min_text_length=20,
        fetch_paper_fn=lambda query: FakeEnvelope(),
    )

    result = save_clean_html(
        "10.1234/provider",
        output_dir=tmp_path,
        source_fetchers=[source_fetcher],
        fetcher=FailingFetcher(),
        min_text_length=20,
    )

    assert result.status == "success"
    assert result.output_path is not None
    saved_html = result.output_path.read_text(encoding="utf-8")
    assert "Provider Converted Paper" in saved_html
    assert "Treatment increased root biomass" in saved_html
    assert result.source_url == "https://publisher.example/articles/10.1234/provider"


def test_official_source_registry_continues_after_paper_fetch_unavailable():
    class MissingPaperFetch:
        def fetch(self, _url):
            raise PaperFetchSourceUnavailable("paper-fetch runtime is not installed")

    class HitSource:
        def fetch(self, url):
            return PaperFetchProviderFetcher(
                min_text_length=20,
                fetch_paper_fn=lambda query: FakeEnvelope(),
            ).fetch(url)

    responses = list(OfficialSourceRegistry([MissingPaperFetch(), HitSource()]).fetch_candidates("10.1234/provider"))

    assert len(responses) == 1
    assert responses[0].source == "paper-fetch-provider"


class FailingFetcher:
    def fetch(self, _url):
        raise AssertionError("generic fetcher should not run when paper-fetch source succeeds")
