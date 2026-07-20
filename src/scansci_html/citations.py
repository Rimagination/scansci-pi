from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+", re.I)


@dataclass(frozen=True)
class ReferenceCandidate:
    doi: str
    source_html_path: str
    source_anchor: str
    source_text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_reference_candidates(html_text: str, *, html_path: str | Path) -> list[ReferenceCandidate]:
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    normalized_path = Path(html_path).as_posix()
    references = _reference_blocks(soup)
    candidates: list[ReferenceCandidate] = []
    seen: set[str] = set()
    for index, tag in enumerate(references, start=1):
        source_text = _normalized_text(tag)
        anchor = _attr(tag, "id") or f"reference-{index:04d}"
        for doi in _dois_from_tag(tag):
            normalized = _normalize_doi(doi)
            if normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            candidates.append(
                ReferenceCandidate(
                    doi=normalized,
                    source_html_path=normalized_path,
                    source_anchor=anchor,
                    source_text=source_text,
                )
            )
    return candidates


def _reference_blocks(soup: BeautifulSoup) -> list[Tag]:
    heading = _reference_heading(soup)
    if heading is None:
        return []
    blocks: list[Tag] = []
    for sibling in heading.find_all_next():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name and re.fullmatch(r"h[1-6]", sibling.name):
            break
        if sibling.name in {"li", "p"} and DOI_RE.search(str(sibling)):
            blocks.append(sibling)
    return blocks


def _reference_heading(soup: BeautifulSoup) -> Tag | None:
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        text = _normalized_text(heading).lower()
        if "reference" in text or "bibliography" in text:
            return heading
    return None


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


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name, "")
    return str(value).strip() if value else ""


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
