from __future__ import annotations

from collections.abc import Iterable
from html import escape
from pathlib import Path
import re
from typing import Any

from .article_structure import extract_article_structure
from .models import FetchResponse


PAPER_FETCH_ARTIFACT_MODES = {"none", "markdown-assets", "all"}
PAPER_FETCH_ASSET_PROFILES = {"none", "body", "all"}


class PaperFetchSourceUnavailable(RuntimeError):
    """Raised when the paper-fetch provider route has no usable full text."""


class PaperFetchProviderFetcher:
    """Use paper-fetch's provider route as one native ScanSci structured source."""

    source_name = "paper-fetch-provider"

    def __init__(
        self,
        *,
        artifact_mode: str = "none",
        asset_profile: str = "none",
        preferred_providers: Iterable[str] | None = None,
        timeout: float = 20.0,
        min_text_length: int = 500,
        fetch_paper_fn: object | None = None,
    ) -> None:
        if artifact_mode not in PAPER_FETCH_ARTIFACT_MODES:
            raise ValueError(f"artifact_mode must be one of: {', '.join(sorted(PAPER_FETCH_ARTIFACT_MODES))}")
        if asset_profile not in PAPER_FETCH_ASSET_PROFILES:
            raise ValueError(f"asset_profile must be one of: {', '.join(sorted(PAPER_FETCH_ASSET_PROFILES))}")
        self.artifact_mode = artifact_mode
        self.asset_profile = asset_profile
        self.preferred_providers = list(preferred_providers or [])
        self.timeout = float(timeout)
        self.min_text_length = int(min_text_length)
        self.fetch_paper_fn = fetch_paper_fn

    def fetch(self, url: str) -> FetchResponse:
        try:
            envelope = self._fetch_envelope(url)
        except PaperFetchSourceUnavailable:
            raise
        except Exception as exc:
            raise PaperFetchSourceUnavailable(f"paper-fetch provider failed: {type(exc).__name__}: {exc}") from exc

        article = _getattr(envelope, "article")
        if article is None:
            raise PaperFetchSourceUnavailable("paper-fetch returned no ArticleModel payload")
        metadata = _metadata_from_envelope(envelope, article)
        doi = _first_text(_getattr(article, "doi"), _getattr(envelope, "doi"))
        source_url = _first_text(
            _getattr(metadata, "landing_page_url"),
            _getattr(envelope, "source_url"),
            url,
        )
        html_text = render_paper_fetch_article_html(article, envelope=envelope)
        structure = extract_article_structure(html_text, source_url=source_url, doi=doi)
        content_kind = _content_kind(envelope, article)
        if not (
            _has_fulltext(envelope, article)
            or (content_kind not in {"abstract_only", "metadata_only"} and structure.text_length >= self.min_text_length)
        ):
            raise PaperFetchSourceUnavailable(f"paper-fetch returned {content_kind or 'non-fulltext'} content")
        warnings = _combined_warnings(
            _as_string_list(_getattr(envelope, "warnings")),
            _as_string_list(_getattr(_getattr(article, "quality"), "warnings")),
            [f"paper-fetch provider source: {_first_text(_getattr(article, 'source'), _getattr(envelope, 'source'))}"],
        )
        return FetchResponse(
            url=url,
            final_url=source_url,
            html=html_text,
            status_code=None,
            source=self.source_name,
            warnings=warnings,
        )

    def _fetch_envelope(self, url: str) -> object:
        if self.fetch_paper_fn is not None:
            return self.fetch_paper_fn(url)  # type: ignore[operator]
        return _call_paper_fetch(
            url,
            artifact_mode=self.artifact_mode,
            asset_profile=self.asset_profile,
            preferred_providers=self.preferred_providers,
        )


def render_paper_fetch_article_html(article: object, *, envelope: object | None = None) -> str:
    metadata = _metadata_from_envelope(envelope, article)
    doi = _first_text(_getattr(article, "doi"), _getattr(envelope, "doi"))
    title = _first_text(_getattr(metadata, "title"), "Untitled article")
    source_url = _first_text(_getattr(metadata, "landing_page_url"), _getattr(envelope, "source_url"))
    published = _first_text(_getattr(metadata, "published"))
    source = _first_text(_getattr(article, "source"), _getattr(envelope, "source"))
    content_kind = _content_kind(envelope, article)
    publication_year = _year_from_text(published)

    article_attrs = {
        "class": "paper",
        "data-doi": doi,
        "data-source-url": source_url,
        "data-publication-year": str(publication_year or ""),
        "data-paper-fetch-source": source,
        "data-paper-fetch-content-kind": content_kind,
    }
    head_parts = [
        '<meta charset="utf-8">',
        f"<title>{escape(title)}</title>",
        f'<meta name="citation_title" content="{escape(title, quote=True)}">',
    ]
    if doi:
        head_parts.append(f'<meta name="citation_doi" content="{escape(doi, quote=True)}">')
    if published:
        head_parts.append(f'<meta name="citation_publication_date" content="{escape(published, quote=True)}">')

    body_parts: list[str] = [
        "<!doctype html>",
        "<html>",
        "<head>",
        *head_parts,
        "</head>",
        "<body>",
        f"<article{_html_attrs(article_attrs)}>",
        f"<h1>{escape(title)}</h1>",
    ]
    body_parts.extend(_render_metadata_section(metadata))

    abstract = _first_text(_getattr(metadata, "abstract"))
    sections = list(_getattr(article, "sections") or [])
    if abstract and not _sections_include_abstract(sections):
        body_parts.extend(
            [
                '<section data-section-kind="abstract">',
                "<h2>Abstract</h2>",
                f'<p id="paper-fetch-abstract-p1">{escape(abstract)}</p>',
                "</section>",
            ]
        )

    for index, section in enumerate(sections, start=1):
        rendered_section = _render_section(section, index=index)
        if rendered_section:
            body_parts.extend(rendered_section)

    asset_section = _render_assets(_getattr(article, "assets") or [])
    if asset_section:
        body_parts.extend(asset_section)

    reference_section = _render_references(_getattr(article, "references") or [])
    if reference_section:
        body_parts.extend(reference_section)

    body_parts.extend(["</article>", "</body>", "</html>"])
    return "\n".join(body_parts) + "\n"


def _call_paper_fetch(
    identifier: str,
    *,
    artifact_mode: str,
    asset_profile: str,
    preferred_providers: Iterable[str] | None,
) -> object:
    fetch_paper, FetchStrategy, RenderOptions, RuntimeContext = _import_paper_fetch_runtime()
    artifact_dir = Path("html-papers") / "_paper_fetch_artifacts" if artifact_mode != "none" else None
    context = RuntimeContext(
        download_dir=artifact_dir,
        artifact_mode=artifact_mode,
        asset_profile=asset_profile,
    )
    try:
        return fetch_paper(
            identifier,
            modes={"article"},
            strategy=FetchStrategy(
                preferred_providers=list(preferred_providers or []) or None,
                asset_profile=asset_profile,
            ),
            render=RenderOptions(
                include_refs="all",
                asset_profile=asset_profile,
                max_tokens="full_text",
            ),
            context=context,
        )
    finally:
        context.close()


def _import_paper_fetch_runtime() -> tuple[object, object, object, object]:
    try:
        from paper_fetch.models import RenderOptions
        from paper_fetch.runtime import RuntimeContext
        from paper_fetch.service import FetchStrategy, fetch_paper
    except ModuleNotFoundError as exc:
        raise PaperFetchSourceUnavailable("paper-fetch runtime is not installed") from exc
    return fetch_paper, FetchStrategy, RenderOptions, RuntimeContext


def _metadata_from_envelope(envelope: object | None, article: object | None) -> object | None:
    article_metadata = _getattr(article, "metadata")
    return article_metadata or _getattr(envelope, "metadata")


def _render_metadata_section(metadata: object | None) -> list[str]:
    if metadata is None:
        return []
    rows: list[str] = []
    authors = _as_string_list(_getattr(metadata, "authors"))
    journal = _first_text(_getattr(metadata, "journal"))
    published = _first_text(_getattr(metadata, "published"))
    keywords = _as_string_list(_getattr(metadata, "keywords"))
    if authors:
        rows.append(f"<p><strong>Authors.</strong> {escape('; '.join(authors))}</p>")
    if journal:
        rows.append(f"<p><strong>Journal.</strong> {escape(journal)}</p>")
    if published:
        rows.append(f"<p><strong>Published.</strong> {escape(published)}</p>")
    if keywords:
        rows.append(f"<p><strong>Keywords.</strong> {escape('; '.join(keywords))}</p>")
    if not rows:
        return []
    return [
        '<section data-section-kind="article_metadata">',
        "<h2>About this article</h2>",
        *rows,
        "</section>",
    ]


def _render_section(section: object, *, index: int) -> list[str]:
    heading = _first_text(_getattr(section, "heading"), _title_from_kind(_getattr(section, "kind")))
    text = _first_text(_getattr(section, "text"))
    if not heading and not text:
        return []
    try:
        raw_level = int(_getattr(section, "level") or 1)
    except (TypeError, ValueError):
        raw_level = 1
    level = min(6, max(2, raw_level + 1))
    kind = _first_text(_getattr(section, "kind"), "body")
    block_prefix = f"paper-fetch-section-{index:04d}"
    parts = [
        f'<section data-section-kind="{escape(kind, quote=True)}">',
        f"<h{level}>{escape(heading or 'Section')}</h{level}>",
    ]
    parts.extend(_render_text_blocks(text, block_prefix=block_prefix))
    parts.append("</section>")
    return parts


def _render_text_blocks(text: str, *, block_prefix: str) -> list[str]:
    parts: list[str] = []
    for index, block in enumerate(_paragraph_blocks(text), start=1):
        if _looks_like_markdown_table(block):
            parts.append(_render_markdown_table(block, table_id=f"{block_prefix}-table-{index:02d}"))
        else:
            parts.append(f'<p id="{block_prefix}-p{index:02d}">{escape(block)}</p>')
    return parts


def _render_markdown_table(block: str, *, table_id: str) -> str:
    rows = [_split_markdown_table_row(line) for line in block.splitlines() if line.strip()]
    rows = [row for row in rows if row]
    if len(rows) < 2:
        return f'<p id="{table_id}">{escape(block)}</p>'
    header = rows[0]
    body = [row for row in rows[2:] if not _is_markdown_separator_row(row)]
    head_html = "".join(f"<th>{escape(cell)}</th>" for cell in header)
    body_rows = []
    for row in body:
        cells = "".join(f"<td>{escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        f'<table id="{table_id}">'
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_assets(assets: Iterable[object]) -> list[str]:
    captions: list[str] = []
    for index, asset in enumerate(assets, start=1):
        caption = _first_text(_getattr(asset, "caption"), _getattr(asset, "heading"))
        if not caption:
            continue
        kind = _first_text(_getattr(asset, "kind"), "asset")
        captions.append(
            "<figure "
            f'data-paper-fetch-asset-kind="{escape(kind, quote=True)}" '
            f'id="paper-fetch-asset-{index:04d}">'
            f"<figcaption>{escape(caption)}</figcaption>"
            "</figure>"
        )
    if not captions:
        return []
    return ["<section>", "<h2>Figures and tables</h2>", *captions, "</section>"]


def _render_references(references: Iterable[object]) -> list[str]:
    items: list[str] = []
    for reference in references:
        raw = _first_text(_getattr(reference, "raw"), _getattr(reference, "title"))
        if raw:
            items.append(f"<li>{escape(raw)}</li>")
    if not items:
        return []
    return ["<section>", "<h2>References</h2>", "<ol>", *items, "</ol>", "</section>"]


def _sections_include_abstract(sections: Iterable[object]) -> bool:
    for section in sections:
        heading = _first_text(_getattr(section, "heading")).lower()
        kind = _first_text(_getattr(section, "kind")).lower()
        if "abstract" in heading or kind == "abstract":
            return True
    return False


def _paragraph_blocks(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]
    return blocks or [normalized]


def _looks_like_markdown_table(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return (
        len(lines) >= 2
        and "|" in lines[0]
        and "|" in lines[1]
        and _is_markdown_separator_row(_split_markdown_table_row(lines[1]))
    )


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_separator_row(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _title_from_kind(kind: object) -> str:
    text = _first_text(kind)
    if not text:
        return ""
    return text.replace("_", " ").title()


def _content_kind(envelope: object | None, article: object | None) -> str:
    quality = _getattr(article, "quality")
    return _first_text(
        _getattr(envelope, "content_kind"),
        _getattr(quality, "content_kind"),
    )


def _has_fulltext(envelope: object | None, article: object | None) -> bool:
    quality = _getattr(article, "quality")
    return bool(
        _getattr(envelope, "has_fulltext")
        or _getattr(quality, "has_fulltext")
        or _content_kind(envelope, article) == "fulltext"
    )


def _html_attrs(attrs: dict[str, str]) -> str:
    rendered = [
        f'{name}="{escape(str(value), quote=True)}"'
        for name, value in attrs.items()
        if str(value or "").strip()
    ]
    return " " + " ".join(rendered) if rendered else ""


def _getattr(value: object | None, name: str, default: object | None = None) -> object | None:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_text(*values: object | None) -> str:
    for value in values:
        if value is None:
            continue
        text = re.sub(r"\s+", " ", str(value)).strip()
        if text:
            return text
    return ""


def _as_string_list(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return [_first_text(item) for item in value if _first_text(item)]  # type: ignore[union-attr]
    except TypeError:
        text = _first_text(value)
        return [text] if text else []


def _combined_warnings(*warning_lists: list[str]) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for warnings in warning_lists:
        for warning in warnings:
            if warning and warning not in seen:
                combined.append(warning)
                seen.add(warning)
    return combined


def _year_from_text(value: str) -> int | None:
    match = re.search(r"\b(1[6-9]\d{2}|20\d{2}|21\d{2}|22\d{2})\b", value)
    return int(match.group(1)) if match else None


__all__ = [
    "PAPER_FETCH_ARTIFACT_MODES",
    "PAPER_FETCH_ASSET_PROFILES",
    "PaperFetchProviderFetcher",
    "PaperFetchSourceUnavailable",
    "render_paper_fetch_article_html",
]
