"""Small, deterministic metadata extraction helpers for research PDFs.

Metadata is deliberately collected before any expensive document conversion.
The importer can therefore repair a weak filename-derived title without making
an extra network request.  User-supplied records (for example Zotero) remain
authoritative; embedded PDF metadata is a useful second source and the file
name is the final fallback.
"""

from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_GENERIC_TITLES = {
    "untitled",
    "untitled document",
    "microsoft word",
    "adobe acrobat",
    "document",
    "paper",
    "article",
}
_GENERIC_AUTHORS = {
    "cnki",
    "知网",
    "unknown",
    "anonymous",
    "adobe acrobat",
    "microsoft word",
}


def extract_pdf_metadata(
    path: str | Path,
    *,
    supplied: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return conservative title/author/DOI/date fields for *path*.

    This function is intentionally local and bounded.  It reads the PDF
    document information dictionary only, so importing a large collection does
    not require opening or rasterising every page.  A later provider such as
    Crossref can enrich a DOI record, but it should not be needed to identify a
    document reliably.
    """

    source = dict(supplied or {})
    embedded: dict[str, str] = {}
    resolved = Path(path).expanduser().resolve()
    if resolved.is_file() and resolved.suffix.lower() == ".pdf":
        embedded = _read_embedded_metadata(resolved)

    filename_title, filename_author = _filename_fields(resolved.stem)
    title = _first_meaningful(
        source.get("title"),
        source.get("shortTitle"),
        embedded.get("title"),
        filename_title,
    )
    author = _first_meaningful(
        _author_value(source.get("author")),
        _author_value(source.get("authors")),
        _author_value(source.get("creators")),
        _author_value(embedded.get("author")),
        filename_author,
    )
    doi = _normalize_doi(
        _first_meaningful(source.get("doi"), source.get("DOI"), embedded.get("doi"), embedded.get("subject"), embedded.get("keywords"))
    )
    date = _first_meaningful(
        source.get("date"),
        source.get("year"),
        embedded.get("date"),
    )
    year = _year_from(date)
    if not year:
        year = _year_from(_first_meaningful(embedded.get("subject"), embedded.get("keywords"), resolved.name))

    result: dict[str, str] = {}
    if title:
        result["title"] = title
    if author:
        result["author"] = author
    if doi:
        result["doi"] = doi
    if date:
        result["date"] = date
    if year:
        result["year"] = year

    sources: list[str] = []
    if any(_has_value(source.get(key)) for key in ("title", "author", "authors", "creators", "doi", "DOI", "date", "year")):
        sources.append("supplied")
    if embedded:
        sources.append("pdf-embedded")
    sources.append("filename")
    result["metadata_source"] = "+".join(sources)
    result["metadata_confidence"] = _confidence(result, supplied=source, embedded=embedded)
    return result


def _has_value(value: Any) -> bool:
    return bool(str(value or "").strip())


def _read_embedded_metadata(path: Path) -> dict[str, str]:
    """Read the info dictionary without making noisy parser warnings normal."""

    try:
        import fitz  # type: ignore[import-not-found]

        document = fitz.open(str(path))
        try:
            raw = document.metadata or {}
        finally:
            document.close()
    except Exception:
        try:
            reader = PdfReader(str(path), strict=False)
            raw = reader.metadata or {}
        except Exception:
            # A damaged/encrypted information dictionary must not prevent the
            # normal PDF text parser from importing the source.
            return {}
    result: dict[str, str] = {}
    for key, value in dict(raw).items():
        normalized_key = str(key).removeprefix("/").strip().lower()
        normalized_value = _clean_value(value)
        if normalized_key and normalized_value:
            result[normalized_key] = normalized_value
    return result


def _clean_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_clean_value(item) for item in value if _has_value(item))
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def _first_meaningful(*values: Any) -> str:
    for value in values:
        text = _clean_value(value)
        if text and text.casefold() not in _GENERIC_TITLES:
            return text
    return ""


def _author_value(value: Any) -> str:
    text = _clean_value(value)
    if text.casefold() in _GENERIC_AUTHORS:
        return ""
    return text


def _filename_fields(stem: str) -> tuple[str, str]:
    """Split the common ``标题_作者`` export convention conservatively."""

    value = _clean_value(stem)
    if "_" not in value:
        return value, ""
    title, author = value.rsplit("_", 1)
    author = author.strip()
    # A trailing short Chinese name or an ASCII surname is a useful author
    # hint; long underscore-heavy titles are left intact.
    if title.strip() and 2 <= len(author) <= 32 and re.search(r"[\u3400-\u9fffA-Za-z]", author):
        return title.strip(), author
    return value, ""


def _normalize_doi(value: Any) -> str:
    text = _clean_value(value)
    if not text:
        return ""
    match = _DOI_RE.search(text)
    if not match:
        return ""
    doi = match.group(0).rstrip(".,;:)]}>")
    return doi.lower()


def _year_from(value: Any) -> str:
    match = _YEAR_RE.search(_clean_value(value))
    return match.group(0) if match else ""


def _confidence(result: Mapping[str, str], *, supplied: Mapping[str, Any], embedded: Mapping[str, str]) -> str:
    if _has_value(supplied.get("title")) and (_has_value(supplied.get("doi")) or _has_value(supplied.get("DOI"))):
        return "high"
    if _has_value(supplied.get("title")) or _has_value(embedded.get("title")):
        return "medium"
    if result.get("doi"):
        return "medium"
    return "low"
