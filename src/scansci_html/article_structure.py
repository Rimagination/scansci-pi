from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


BODY_HEADINGS = {
    "introduction",
    "background",
    "main",
    "results",
    "result",
    "discussion",
    "methods",
    "materials and methods",
    "materials & methods",
    "method",
    "conclusion",
    "conclusions",
}
ABSTRACT_HEADINGS = {
    "abstract",
    "structured abstract",
    "editor's summary",
    "editor's summaries",
    "editor's summary",
}
REFERENCE_HEADINGS = {
    "references",
    "references and notes",
    "literature cited",
}
ENDMATTER_HEADINGS = {
    *REFERENCE_HEADINGS,
    "acknowledgments",
    "acknowledgements",
    "funding",
    "data availability",
    "supplementary materials",
    "supporting information",
}

ACCESS_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("check-access", re.compile(r"\bcheck\s+access\b", re.I)),
    ("institutional-login", re.compile(r"\b(access|sign in|log in)\s+(content\s+)?through\s+your\s+institution\b", re.I)),
    ("institutional-login", re.compile(r"\binstitutional\s+login\b", re.I)),
    ("institutional-login", re.compile(r"\bfind\s+your\s+institution\b", re.I)),
    ("read-full-text", re.compile(r"\bread\s+the\s+full\s+text\b", re.I)),
    ("purchase-access", re.compile(r"\bpurchase\s+(instant\s+)?access\b", re.I)),
    ("purchase-access", re.compile(r"\brent\s+or\s+purchase\b", re.I)),
    ("subscription-preview", re.compile(r"\bpreview\s+of\s+subscription\s+content\b", re.I)),
)
COLLAPSED_REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("show-all-references", re.compile(r"\bshow\s+all\s+references\b", re.I)),
    ("show-all-references", re.compile(r"\bsee\s+all\s+references\b", re.I)),
)


@dataclass(frozen=True)
class ArticleSection:
    heading: str
    level: int
    kind: str
    text_length: int = 0

    def to_summary(self) -> dict[str, object]:
        return {
            "heading": self.heading,
            "level": self.level,
            "kind": self.kind,
            "text_length": self.text_length,
        }


@dataclass(frozen=True)
class ArticleStructure:
    title: str = ""
    source_url: str = ""
    doi: str | None = None
    text_length: int = 0
    sections: list[ArticleSection] = field(default_factory=list)
    figure_count: int = 0
    image_count: int = 0
    table_count: int = 0
    reference_count: int = 0
    access_markers: list[str] = field(default_factory=list)
    collapsed_reference_markers: list[str] = field(default_factory=list)

    @property
    def body_section_count(self) -> int:
        return sum(1 for section in self.sections if section.kind == "body")

    @property
    def endmatter_section_count(self) -> int:
        return sum(1 for section in self.sections if section.kind in {"references", "endmatter"})

    @property
    def has_body(self) -> bool:
        return self.body_section_count > 0

    @property
    def has_endmatter(self) -> bool:
        return self.reference_count > 0 or self.endmatter_section_count > 0

    def blocking_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.access_markers and not self.has_body:
            warnings.append("article structure shows access gate without body sections")
        if self.collapsed_reference_markers:
            warnings.append("article structure indicates collapsed references; expand references before saving")
        return warnings

    def to_summary(self) -> dict[str, object]:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "doi": self.doi,
            "text_length": self.text_length,
            "section_count": len(self.sections),
            "body_section_count": self.body_section_count,
            "endmatter_section_count": self.endmatter_section_count,
            "has_body": self.has_body,
            "has_endmatter": self.has_endmatter,
            "figure_count": self.figure_count,
            "image_count": self.image_count,
            "table_count": self.table_count,
            "reference_count": self.reference_count,
            "access_markers": list(self.access_markers),
            "collapsed_reference_markers": list(self.collapsed_reference_markers),
            "sections": [section.to_summary() for section in self.sections],
        }


def extract_article_structure(
    html: str,
    *,
    source_url: str = "",
    doi: str | None = None,
) -> ArticleStructure:
    soup = BeautifulSoup(str(html or ""), "lxml")
    root = _select_article_root(soup)
    text = _normalized_text(root)
    headings = _collect_sections(root)
    title = _extract_title(root, soup, headings)
    return ArticleStructure(
        title=title,
        source_url=source_url or _article_attr(root, "data-source-url"),
        doi=doi or _article_attr(root, "data-doi") or None,
        text_length=len(text),
        sections=headings,
        figure_count=len(root.find_all("figure")),
        image_count=len(root.find_all("img")),
        table_count=len(root.find_all("table")),
        reference_count=_count_references(root),
        access_markers=_dedupe_markers(text, ACCESS_MARKER_PATTERNS),
        collapsed_reference_markers=_dedupe_markers(text, COLLAPSED_REFERENCE_PATTERNS),
    )


def _select_article_root(soup: BeautifulSoup) -> Tag:
    for selector in ("article.paper", "article", "main", "[role='main']", "body"):
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return soup


def _collect_sections(root: Tag) -> list[ArticleSection]:
    sections: list[ArticleSection] = []
    seen: set[int] = set()
    for node in root.find_all(True):
        if not isinstance(node, Tag):
            continue
        level = _heading_level(node)
        if level is None or id(node) in seen:
            continue
        seen.add(id(node))
        heading = _normalized_text(node)
        if not heading:
            continue
        sections.append(
            ArticleSection(
                heading=heading,
                level=level,
                kind=_section_kind(heading, level=level),
                text_length=_section_text_length(node),
            )
        )
    return sections


def _heading_level(node: Tag) -> int | None:
    name = _normalize(node.name)
    if len(name) == 2 and name.startswith("h") and name[1].isdigit():
        return int(name[1])
    role = _normalize(node.get("role"))
    if role == "heading":
        try:
            return int(node.get("aria-level") or 2)
        except (TypeError, ValueError):
            return 2
    classes = _class_tokens(node)
    if "section-label" in classes or "section-title" in classes:
        return 2
    return None


def _section_kind(heading: str, *, level: int) -> str:
    normalized = _normalize_heading(heading)
    if level == 1:
        return "title"
    if _heading_in(normalized, ABSTRACT_HEADINGS):
        return "abstract"
    if _heading_in(normalized, REFERENCE_HEADINGS):
        return "references"
    if _heading_in(normalized, BODY_HEADINGS) or _looks_like_numbered_body_heading(normalized):
        return "body"
    if _heading_in(normalized, ENDMATTER_HEADINGS):
        return "endmatter"
    return "unknown"


def _heading_in(normalized_heading: str, expected_values: set[str]) -> bool:
    return any(
        normalized_heading == expected
        or normalized_heading.startswith(expected + " ")
        or normalized_heading.startswith(expected + ":")
        for expected in expected_values
    )


def _looks_like_numbered_body_heading(normalized_heading: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+\S", normalized_heading))


def _section_text_length(node: Tag) -> int:
    container = node.find_parent("section")
    if isinstance(container, Tag):
        return len(_normalized_text(container))
    return len(_normalized_text(node))


def _extract_title(root: Tag, soup: BeautifulSoup, sections: list[ArticleSection]) -> str:
    for section in sections:
        if section.kind == "title" and section.heading:
            return section.heading
    for selector in ("meta[name='citation_title']", "meta[property='og:title']", "meta[name='dc.title']"):
        meta = soup.select_one(selector)
        if isinstance(meta, Tag) and meta.get("content"):
            return _normalized_text(str(meta["content"]))
    if soup.title and soup.title.string:
        return _normalized_text(soup.title.string)
    return ""


def _count_references(root: Tag) -> int:
    total = 0
    for heading in root.find_all(True):
        if not isinstance(heading, Tag):
            continue
        level = _heading_level(heading)
        if level is None:
            continue
        if _section_kind(_normalized_text(heading), level=level) != "references":
            continue
        total += _count_references_near_heading(heading, level=level)
    return total


def _count_references_near_heading(heading: Tag, *, level: int) -> int:
    container = heading.find_parent("section")
    if isinstance(container, Tag):
        count = _count_reference_items(container)
        if count:
            return count

    fragments: list[Tag] = []
    for sibling in heading.find_next_siblings():
        if not isinstance(sibling, Tag):
            continue
        sibling_level = _heading_level(sibling)
        if sibling_level is not None and sibling_level <= level:
            break
        fragments.append(sibling)
    if not fragments:
        return 0
    soup = BeautifulSoup("", "lxml")
    wrapper = soup.new_tag("section")
    for fragment in fragments:
        wrapper.append(BeautifulSoup(str(fragment), "lxml"))
    return _count_reference_items(wrapper)


def _count_reference_items(container: Tag) -> int:
    item_selectors = (
        "li",
        "[role='doc-biblioentry']",
        "[role='listitem']",
        ".references__item",
        ".ref-list__item",
        ".citation",
    )
    items: list[Tag] = []
    seen: set[int] = set()
    for selector in item_selectors:
        for item in container.select(selector):
            if isinstance(item, Tag) and id(item) not in seen and len(_normalized_text(item)) >= 5:
                seen.add(id(item))
                items.append(item)
    if items:
        return len(items)
    paragraphs = [
        paragraph
        for paragraph in container.find_all("p")
        if isinstance(paragraph, Tag) and len(_normalized_text(paragraph)) >= 12
    ]
    return len(paragraphs)


def _dedupe_markers(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()
    for marker, pattern in patterns:
        if marker in seen:
            continue
        if pattern.search(text):
            markers.append(marker)
            seen.add(marker)
    return markers


def _article_attr(root: Tag, name: str) -> str:
    return str(root.get(name) or "").strip()


def _class_tokens(node: Tag) -> set[str]:
    classes = node.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    return {_normalize(value) for value in classes}


def _normalized_text(value: Any) -> str:
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: Any) -> str:
    return _normalized_text(value).lower()


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip(" .:;-")
