from __future__ import annotations

from copy import copy
import re
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import CleanHtmlDocument


NOISE_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
    "button",
    "input",
    "select",
    "textarea",
}

NOISE_TOKENS = {
    "advert",
    "ads",
    "banner",
    "breadcrumb",
    "cookie",
    "footer",
    "header",
    "login",
    "menu",
    "metrics",
    "modal",
    "navbar",
    "newsletter",
    "popup",
    "recommend",
    "related",
    "share",
    "sidebar",
    "signin",
    "social",
    "toolbar",
}

CONTAINER_SELECTORS = (
    "main article",
    "[role='main'] article",
    "article",
    "#html_fulltext",
    "#itemFullTextId",
    "#Fulltext",
    "#article-body",
    "#article",
    "#main-content",
    "#content",
    ".article__body",
    ".article-body",
    ".article-content",
    ".articleContent",
    ".c-article-body",
    ".fulltext",
    ".full-text",
    ".entry-content",
    "[role='main']",
    "main",
    "body",
)

PAYWALL_MARKERS = (
    "access through your institution",
    "access through your organization",
    "access this article",
    "authorization required",
    "get access",
    "log in via your institution",
    "purchase this article",
    "purchase pdf",
    "rent or purchase",
    "sign in through your institution",
    "sign in to continue reading",
    "subscribe to unlock",
    "this is a preview of subscription content",
    "you do not have access",
)

ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "table": {"summary"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "ol": {"start"},
}

GLOBAL_ATTRS = {"id", "lang"}


class CleanHtmlRenderer:
    def __init__(self, *, min_text_length: int = 500) -> None:
        self.min_text_length = max(0, int(min_text_length))

    def render(
        self,
        html_text: str,
        *,
        source_url: str,
        doi: str | None = None,
    ) -> CleanHtmlDocument:
        soup = BeautifulSoup(str(html_text or ""), "lxml")
        _remove_noise(soup)
        root = _select_best_container(soup)
        if root is None:
            root = soup.body or soup
        root_copy = _clone_tag(root)
        _sanitize_tree(root_copy, source_url=source_url)
        article = _as_article(root_copy, source_url=source_url, doi=doi)
        title = _extract_title(article, soup)
        text = _normalized_text(article)
        warnings, blocking_warnings = _access_warnings(
            article,
            text,
            min_text_length=self.min_text_length,
            source_url=source_url,
        )
        has_fulltext = not blocking_warnings
        access_status = "fulltext" if has_fulltext else "no_access"
        return CleanHtmlDocument(
            title=title,
            html=_standalone_html(article, title=title),
            text_length=len(text),
            has_fulltext=has_fulltext,
            access_status=access_status,
            source_url=source_url,
            doi=doi,
            warnings=warnings,
        )


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        if tag.attrs is None or tag.parent is None:
            continue
        if tag.has_attr("hidden") or str(tag.get("aria-hidden", "")).lower() == "true":
            tag.decompose()
            continue
        identity = " ".join(
            str(value)
            for value in [
                tag.get("id", ""),
                " ".join(tag.get("class", [])),
                tag.get("role", ""),
                tag.get("aria-label", ""),
            ]
        ).lower()
        if any(token in identity for token in NOISE_TOKENS):
            tag.decompose()


def _select_best_container(soup: BeautifulSoup) -> Tag | None:
    candidates: list[Tag] = []
    seen: set[int] = set()
    for selector in CONTAINER_SELECTORS:
        for tag in soup.select(selector):
            if isinstance(tag, Tag) and id(tag) not in seen:
                seen.add(id(tag))
                candidates.append(tag)
    if not candidates:
        return soup.body if isinstance(soup.body, Tag) else None
    return max(candidates, key=_container_score)


def _container_score(tag: Tag) -> float:
    text = _normalized_text(tag)
    text_len = len(text)
    if text_len == 0:
        return 0
    link_text = " ".join(link.get_text(" ", strip=True) for link in tag.find_all("a"))
    link_density = len(link_text) / max(text_len, 1)
    structure_bonus = (
        len(tag.find_all(re.compile(r"^h[1-6]$"))) * 120
        + len(tag.find_all("p")) * 12
        + len(tag.find_all(["figure", "table"])) * 80
        + len(tag.find_all(["section"])) * 40
    )
    return text_len + structure_bonus - (link_density * 250)


def _clone_tag(tag: Tag) -> Tag:
    fragment = BeautifulSoup(str(tag), "lxml")
    cloned = fragment.find(tag.name)
    if isinstance(cloned, Tag):
        return cloned
    if isinstance(fragment.body, Tag):
        return fragment.body
    return copy(tag)


def _sanitize_tree(root: Tag, *, source_url: str) -> None:
    _remove_noise(root)
    for tag in list(root.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        if tag.attrs is None or tag.parent is None:
            continue
        if tag.name in {"div", "span"} and not tag.get_text(" ", strip=True) and not _has_non_text_content(tag):
            tag.decompose()
            continue
        if tag.name == "img":
            _promote_lazy_image_src(tag)
        allowed = set(GLOBAL_ATTRS)
        allowed.update(ALLOWED_ATTRS.get(tag.name, set()))
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr not in allowed:
                del tag.attrs[attr]
        if tag.name == "a" and tag.get("href"):
            tag["href"] = urljoin(source_url, str(tag["href"]))
        if tag.name == "img" and tag.get("src"):
            tag["src"] = urljoin(source_url, str(tag["src"]))


def _has_non_text_content(tag: Tag) -> bool:
    return tag.find(["img", "picture", "source", "figure", "table", "math", "svg"]) is not None


def _promote_lazy_image_src(tag: Tag) -> None:
    src = str(tag.get("src") or "").strip()
    if src and not _is_placeholder_image_src(src):
        return
    for attr in (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-hires",
        "data-url",
    ):
        candidate = str(tag.get(attr) or "").strip()
        if candidate:
            tag["src"] = candidate
            return


def _is_placeholder_image_src(src: str) -> bool:
    normalized = src.strip().lower()
    if not normalized:
        return True
    if normalized.startswith("data:image"):
        return True
    return any(token in normalized for token in ("placeholder", "spacer", "transparent"))


def _as_article(root: Tag, *, source_url: str, doi: str | None) -> Tag:
    soup = BeautifulSoup("", "lxml")
    if root.name == "article":
        article = root
    else:
        article = soup.new_tag("article")
        for child in list(root.contents):
            article.append(child.extract() if hasattr(child, "extract") else child)
    article["class"] = "paper"
    article["data-source-url"] = source_url
    if doi:
        article["data-doi"] = doi
    return article


def _extract_title(article: Tag, soup: BeautifulSoup) -> str:
    h1 = article.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        if title:
            return title
    for selector in (
        "meta[name='citation_title']",
        "meta[property='og:title']",
        "meta[name='dc.title']",
    ):
        meta = soup.select_one(selector)
        if meta and meta.get("content"):
            return str(meta["content"]).strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return "Untitled article"


def _access_warnings(
    article: Tag,
    text: str,
    *,
    min_text_length: int,
    source_url: str,
) -> tuple[list[str], list[str]]:
    lower = text.lower()
    warnings: list[str] = []
    blocking: list[str] = []
    has_access_marker = any(marker in lower for marker in PAYWALL_MARKERS)
    science_access_gate_without_body = (
        _is_science_url(source_url)
        and _has_science_full_article_access_gate(lower)
        and not _science_body_headings_after_abstract(article)
    )
    short_text_warning = ""
    if len(text) < min_text_length:
        short_text_warning = (
            f"article body is shorter than the fulltext threshold ({len(text)} < {min_text_length})"
        )
        warnings.append(short_text_warning)
        blocking.append(short_text_warning)
    if science_access_gate_without_body:
        marker_warning = "science full article access gate detected without full body"
        warnings.append(marker_warning)
        blocking.append(marker_warning)
    if has_access_marker:
        has_fulltext_shape = _has_fulltext_shape(article, text, min_text_length=min_text_length)
        if "preview of subscription content" in lower:
            marker_warning = "subscription preview marker detected"
            blocking.append(marker_warning)
        else:
            marker_warning = (
                "paywall or institutional access marker detected"
                if short_text_warning or not has_fulltext_shape
                else "institutional access marker detected, but article text passed the fulltext threshold"
            )
        warnings.append(marker_warning)
        if "preview of subscription content" not in lower and (short_text_warning or not has_fulltext_shape):
            blocking.append(marker_warning)
    return warnings, blocking


def _has_fulltext_shape(article: Tag, text: str, *, min_text_length: int) -> bool:
    if len(text) < min_text_length:
        return False
    headings = [
        _normalize_heading(heading.get_text(" ", strip=True))
        for heading in article.find_all(["h2", "h3"])
    ]
    scientific_headings = {
        "introduction",
        "results",
        "discussion",
        "main",
        "methods",
        "references",
        "data availability",
        "materials and methods",
    }
    body_headings = {
        "main",
        "introduction",
        "results",
        "discussion",
        "methods",
        "materials and methods",
    }
    if any(_heading_matches(candidate, heading) for candidate in headings for heading in body_headings):
        return True
    if sum(
        1
        for heading in scientific_headings
        if any(_heading_matches(candidate, heading) for candidate in headings)
    ) >= 3:
        return True

    lower = text.lower()
    text_body_markers = {
        "introduction",
        "results",
        "discussion",
        "materials and methods",
    }
    text_end_markers = {
        "references and notes",
        "references",
        "acknowledgments",
        "supplementary materials",
        "data and materials availability",
    }
    has_text_body = any(marker in lower for marker in text_body_markers)
    has_text_endmatter = any(marker in lower for marker in text_end_markers)
    has_multiple_science_markers = sum(
        1
        for marker in {"abstract", *text_body_markers, *text_end_markers}
        if marker in lower
    ) >= 3
    return has_text_body and has_text_endmatter and has_multiple_science_markers


def _is_science_url(source_url: str) -> bool:
    return "science.org" in source_url.lower()


def _has_science_full_article_access_gate(text: str) -> bool:
    return "access the full article" in text or "check access" in text


def _science_body_headings_after_abstract(article: Tag) -> tuple[str, ...]:
    headings = [
        _normalize_heading(heading.get_text(" ", strip=True))
        for heading in article.find_all(["h2", "h3"])
    ]
    abstract_indexes = [index for index, heading in enumerate(headings) if heading == "abstract"]
    start = abstract_indexes[-1] + 1 if abstract_indexes else 0
    body: list[str] = []
    for heading in headings[start:]:
        if not heading:
            continue
        if _is_science_gate_or_backmatter_heading(heading):
            break
        if heading in {"editor's summary", "editor’s summary", "structured abstract"}:
            continue
        body.append(heading)
    return tuple(body)


def _is_science_gate_or_backmatter_heading(heading: str) -> bool:
    markers = (
        "access the full article",
        "check access",
        "supplementary materials",
        "references and notes",
        "references",
        "eletters",
        "recommended articles",
        "information",
        "authors",
    )
    return any(heading == marker or heading.startswith(marker + " ") for marker in markers)


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip(" .:;-")


def _heading_matches(candidate: str, expected: str) -> bool:
    if candidate == expected:
        return True
    return candidate.startswith(expected + " ") or candidate.startswith(expected + ":")


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def _standalone_html(article: Tag, *, title: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            CSS,
            "  </style>",
            "</head>",
            "<body>",
            str(article),
            "</body>",
            "</html>",
            "",
        ]
    )


CSS = """\
    :root { color-scheme: light; }
    body {
      margin: 0;
      background: #f6f7f8;
      color: #182026;
      font: 17px/1.65 Georgia, "Times New Roman", serif;
    }
    .paper {
      box-sizing: border-box;
      width: min(920px, calc(100% - 32px));
      margin: 32px auto;
      padding: 40px;
      background: #fff;
      border: 1px solid #d9dee3;
    }
    h1, h2, h3, h4, h5, h6 {
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.25;
      margin: 1.8em 0 0.55em;
    }
    h1 { font-size: 2rem; margin-top: 0; }
    h2 { font-size: 1.45rem; border-bottom: 1px solid #e4e7eb; padding-bottom: 0.25em; }
    p, ul, ol, table, figure { margin: 1em 0; }
    a { color: #0b5cad; }
    img { max-width: 100%; height: auto; }
    figure { break-inside: avoid; }
    figcaption, caption { color: #4c5963; font-size: 0.95rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    th, td { border: 1px solid #d9dee3; padding: 0.45rem 0.55rem; vertical-align: top; }
    th { background: #f0f3f5; }
    pre, code { font-family: Consolas, "Liberation Mono", monospace; }
    @media (max-width: 640px) {
      body { font-size: 16px; }
      .paper { width: 100%; margin: 0; padding: 24px 18px; border-width: 0; }
    }"""
