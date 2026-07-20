from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from .resolver import safe_identifier_part


@dataclass(frozen=True)
class EvidenceBlock:
    doc_id: str
    block_id: str
    title: str
    doi: str | None
    source_url: str
    html_path: str
    anchor: str
    section: str
    block_type: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_evidence_blocks(
    html_text: str,
    *,
    html_path: str | Path,
    min_text_length: int = 40,
) -> list[EvidenceBlock]:
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    article = _article_root(soup)
    title = _document_title(article, soup)
    doi = _attr(article, "data-doi")
    source_url = _attr(article, "data-source-url")
    doc_id = safe_identifier_part(doi or source_url or Path(html_path).stem)
    normalized_path = Path(html_path).as_posix()

    blocks: list[EvidenceBlock] = []
    current_section = ""
    for tag in article.descendants:
        if not isinstance(tag, Tag):
            continue
        if tag.name and re.fullmatch(r"h[1-6]", tag.name):
            heading_text = _normalized_text(tag)
            if heading_text:
                current_section = heading_text
            continue
        block_type = _block_type(tag)
        if not block_type:
            continue
        if _inside_same_block(tag):
            continue
        text = _normalized_text(tag)
        if len(text) < min_text_length:
            continue
        ordinal = len(blocks) + 1
        anchor = _attr(tag, "id") or f"evidence-{ordinal:04d}"
        blocks.append(
            EvidenceBlock(
                doc_id=doc_id,
                block_id=f"{doc_id}:{anchor}",
                title=title,
                doi=doi,
                source_url=source_url,
                html_path=normalized_path,
                anchor=anchor,
                section=current_section,
                block_type=block_type,
                text=text,
            )
        )
    return blocks


def index_html_library(
    library_dir: str | Path,
    *,
    output_path: str | Path,
    min_text_length: int = 40,
) -> dict[str, object]:
    library_path = Path(library_dir)
    output = Path(output_path)
    all_blocks: list[EvidenceBlock] = []
    documents = 0
    for html_file in _iter_html_files(library_path):
        blocks = extract_evidence_blocks(
            html_file.read_text(encoding="utf-8"),
            html_path=html_file,
            min_text_length=min_text_length,
        )
        if blocks:
            documents += 1
            all_blocks.extend(blocks)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        for block in all_blocks:
            file.write(json.dumps(block.to_dict(), ensure_ascii=False) + "\n")

    return {
        "documents": documents,
        "blocks": len(all_blocks),
        "output_path": str(output),
    }


def _iter_html_files(library_path: Path) -> Iterable[Path]:
    return sorted(path for path in library_path.rglob("*.html") if path.is_file())


def _article_root(soup: BeautifulSoup) -> Tag:
    for selector in ("article.paper", "article", "body"):
        tag = soup.select_one(selector)
        if isinstance(tag, Tag):
            return tag
    return soup


def _document_title(article: Tag, soup: BeautifulSoup) -> str:
    h1 = article.find("h1")
    if isinstance(h1, Tag):
        text = _normalized_text(h1)
        if text:
            return text
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return "Untitled article"


def _block_type(tag: Tag) -> str:
    if tag.name == "p":
        return "paragraph"
    if tag.name in {"figcaption", "caption"}:
        return "caption"
    return ""


def _inside_same_block(tag: Tag) -> bool:
    parent = tag.parent
    while isinstance(parent, Tag):
        if _block_type(parent):
            return True
        parent = parent.parent
    return False


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name, "")
    return str(value).strip() if value else ""


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
