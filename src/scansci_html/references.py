from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+", re.I)
DATASET_TERMS = re.compile(
    r"\b(dataset|database|data set|data descriptor|scientific data|earth system science data)\b",
    re.I,
)
REVIEW_TERMS = re.compile(r"\b(review|meta-analysis|synthesis)\b", re.I)
METHOD_TERMS = re.compile(r"\b(method|algorithm|software|model|protocol)\b", re.I)


@dataclass(frozen=True)
class ReferenceRecord:
    reference_id: str
    source_doc_id: str
    source_html_path: str
    source_anchor: str
    raw_text: str
    doi: str = ""
    title: str = ""
    authors: str = ""
    year: int | None = None
    venue: str = ""
    language: str = "unknown"
    record_type: str = "unknown"
    confidence: float = 0.0
    review_state: str = "unreviewed"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["year"] = self.year if self.year is not None else ""
        return payload


def extract_reference_records(
    html_text: str,
    *,
    html_path: str | Path,
    source_url: str = "",
) -> list[ReferenceRecord]:
    del source_url
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    source_doc_id = _source_doc_id(soup, html_path)
    normalized_path = Path(html_path).as_posix()
    records: list[ReferenceRecord] = []
    for index, tag in enumerate(_reference_blocks(soup), start=1):
        raw_text = _normalized_text(tag)
        if not raw_text:
            continue
        anchor = _attr(tag, "id") or f"reference-{index:04d}"
        doi = _first_doi(tag)
        title, authors, venue = _parse_reference_parts(raw_text)
        year = _parse_year(raw_text)
        language = "zh" if _contains_cjk(raw_text) else "en" if re.search(r"[A-Za-z]", raw_text) else "unknown"
        record_type = _record_type(raw_text)
        records.append(
            ReferenceRecord(
                reference_id=f"{Path(html_path).stem}:{anchor}",
                source_doc_id=source_doc_id,
                source_html_path=normalized_path,
                source_anchor=anchor,
                raw_text=raw_text,
                doi=doi,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                language=language,
                record_type=record_type,
                confidence=_confidence(doi=doi, title=title, year=year, language=language),
            )
        )
    return records


def _source_doc_id(soup: BeautifulSoup, html_path: str | Path) -> str:
    article = soup.select_one("article.paper") or soup.select_one("article")
    if isinstance(article, Tag):
        doi = _attr(article, "data-doi")
        if doi:
            return doi
        source = _attr(article, "data-source-url")
        if source:
            return source
    return Path(html_path).stem


def _reference_blocks(soup: BeautifulSoup) -> list[Tag]:
    heading = _reference_heading(soup)
    if heading is None:
        return []
    container = heading.find_parent("section")
    if isinstance(container, Tag):
        items = _reference_items(container)
        if items:
            return items

    blocks: list[Tag] = []
    for sibling in heading.find_next_siblings():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name and re.fullmatch(r"h[1-6]", sibling.name):
            break
        if sibling.name in {"ol", "ul", "section", "div"}:
            blocks.extend(_reference_items(sibling))
        elif sibling.name in {"li", "p"} and len(_normalized_text(sibling)) >= 8:
            blocks.append(sibling)
    return blocks


def _reference_heading(soup: BeautifulSoup) -> Tag | None:
    labels = {"references", "reference", "bibliography", "literature cited", "references and notes"}
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        text = _normalized_text(heading).lower()
        if text in labels:
            return heading
    return None


def _reference_items(container: Tag) -> list[Tag]:
    selectors = ("li", "[role='doc-biblioentry']", ".references__item", ".ref-list__item", "p")
    items: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        for item in container.select(selector):
            if isinstance(item, Tag) and id(item) not in seen and len(_normalized_text(item)) >= 8:
                seen.add(id(item))
                items.append(item)
    return items


def _first_doi(tag: Tag) -> str:
    for doi in _dois_from_tag(tag):
        return _normalize_doi(doi)
    return ""


def _dois_from_tag(tag: Tag) -> Iterable[str]:
    for link in tag.find_all("a", href=True):
        yield from DOI_RE.findall(str(link.get("href", "")))
    yield from DOI_RE.findall(_normalized_text(tag))


def _normalize_doi(value: str) -> str:
    doi = value.strip().rstrip(".,;")
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
    return doi


def _parse_reference_parts(raw_text: str) -> tuple[str, str, str]:
    text = re.sub(r"https?://doi\.org/\S+|doi:\s*\S+|10\.\d{4,9}/\S+", "", raw_text, flags=re.I).strip()
    if _contains_cjk(text):
        parts = [part.strip(" ,;，。") for part in re.split(r"[.。]\s*", text) if part.strip(" ,;，。")]
        authors = parts[0] if parts else ""
        title = parts[1] if len(parts) > 1 else ""
        venue = parts[2].split(",", 1)[0].strip(" ，,;") if len(parts) > 2 else ""
        return title, authors, venue

    parts = [part.strip(" ,;") for part in re.split(r"\.\s+", text) if part.strip(" ,;")]
    authors = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    venue = parts[2] if len(parts) > 2 else ""
    venue = re.sub(r"\b(?:18|19|20)\d{2}\b.*$", "", venue).strip(" ,;(")
    venue = re.sub(r"\s+\d+.*$", "", venue).strip(" ,;(")
    return title, authors, venue


def _parse_year(raw_text: str) -> int | None:
    matches = re.findall(r"\b(?:18|19|20)\d{2}\b", raw_text)
    return int(matches[-1]) if matches else None


def _record_type(raw_text: str) -> str:
    if DATASET_TERMS.search(raw_text):
        return "dataset_paper"
    if REVIEW_TERMS.search(raw_text):
        return "review"
    if METHOD_TERMS.search(raw_text):
        return "method_paper"
    return "unknown"


def _confidence(*, doi: str, title: str, year: int | None, language: str) -> float:
    score = 0.25
    if doi:
        score += 0.25
    if title:
        score += 0.15
    if year is not None:
        score += 0.1
    if language in {"en", "zh"}:
        score += 0.05
    return round(min(score, 0.9), 2)


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name, "")
    return str(value).strip() if value else ""


def _normalized_text(tag: Tag | str) -> str:
    if isinstance(tag, Tag):
        return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
    return re.sub(r"\s+", " ", str(tag or "")).strip()
