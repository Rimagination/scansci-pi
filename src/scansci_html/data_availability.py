from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .artifacts import _repository, _sanitize_url


@dataclass(frozen=True)
class DataAvailabilityRecord:
    availability_id: str
    source_doc_id: str
    statement_text: str
    source_html_path: str
    source_anchor: str
    availability_status: str
    repository: str = "unknown"
    url: str = ""
    doi: str = ""
    license: str = ""
    files_available: bool = False
    evidence_level: str = "statement_only"
    confidence: float = 0.0
    review_state: str = "unreviewed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_data_availability_records(
    html_text: str,
    *,
    html_path: str | Path,
    source_url: str = "",
) -> list[DataAvailabilityRecord]:
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    source_doc_id = _source_doc_id(soup, html_path)
    normalized_path = Path(html_path).as_posix()
    records: list[DataAvailabilityRecord] = []
    for index, block in enumerate(_availability_blocks(soup), start=1):
        statement = _normalized_text(block)
        if not statement:
            continue
        url = _first_link_url(block, source_url=source_url)
        repository = _repository(url) if url else "unknown"
        status = _availability_status(statement, has_url=bool(url))
        records.append(
            DataAvailabilityRecord(
                availability_id=f"{Path(html_path).stem}:data-availability-{index:04d}",
                source_doc_id=source_doc_id,
                statement_text=statement,
                source_html_path=normalized_path,
                source_anchor=_attr(block, "id") or f"data-availability-{index:04d}",
                availability_status=status,
                repository=repository,
                url=url,
                license=_license(statement),
                files_available=False,
                evidence_level="metadata_page" if url and repository != "publisher" else "statement_only",
                confidence=_confidence(status=status, has_url=bool(url), repository=repository),
            )
        )
    return records


def _availability_blocks(soup: BeautifulSoup) -> list[Tag]:
    blocks: list[Tag] = []
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        if not isinstance(heading, Tag):
            continue
        heading_text = _normalized_text(heading).lower()
        if "data availability" not in heading_text and "availability of data" not in heading_text:
            continue
        container = heading.find_parent("section")
        if isinstance(container, Tag):
            paragraphs = [node for node in container.find_all("p") if isinstance(node, Tag) and _normalized_text(node)]
            if paragraphs:
                blocks.extend(paragraphs)
                continue
        for sibling in heading.find_next_siblings():
            if not isinstance(sibling, Tag):
                continue
            if sibling.name and re.fullmatch(r"h[1-6]", sibling.name):
                break
            if sibling.name in {"p", "div"} and _normalized_text(sibling):
                blocks.append(sibling)
    return blocks


def _availability_status(statement: str, *, has_url: bool) -> str:
    lower = statement.lower()
    if "no datasets were generated" in lower or "no data were generated" in lower:
        return "not_applicable"
    if "not publicly available" in lower or "restricted" in lower:
        return "no"
    if "embargo" in lower:
        return "embargoed"
    if (
        "upon reasonable request" in lower
        or "corresponding author" in lower
        or "available from the author" in lower
    ):
        return "by_request"
    if has_url or "available at" in lower or "deposited" in lower:
        return "yes"
    return "unknown"


def _license(statement: str) -> str:
    match = re.search(r"\b(CC\s+BY(?:[-\s]\d(?:\.\d)?)?|Creative Commons[^.;,]*)", statement, re.I)
    return match.group(1).replace("  ", " ").strip() if match else ""


def _first_link_url(block: Tag, *, source_url: str) -> str:
    link = block.find("a", href=True)
    if not isinstance(link, Tag):
        return ""
    href = str(link.get("href") or "").strip()
    return _sanitize_url(urljoin(source_url, href) if source_url else href)


def _confidence(*, status: str, has_url: bool, repository: str) -> float:
    score = 0.45
    if status != "unknown":
        score += 0.15
    if has_url:
        score += 0.1
    if repository not in {"unknown", "publisher"}:
        score += 0.1
    return round(min(score, 0.85), 2)


def _source_doc_id(soup: BeautifulSoup, html_path: str | Path) -> str:
    article = soup.select_one("article.paper") or soup.select_one("article")
    if isinstance(article, Tag):
        for name in ("data-doi", "data-source-url"):
            value = str(article.get(name) or "").strip()
            if value:
                return value
    return Path(html_path).stem


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name, "")
    return str(value).strip() if value else ""


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
