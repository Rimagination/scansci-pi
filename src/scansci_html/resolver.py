from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .models import ResolvedIdentifier


DOI_PREFIX_RE = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


def normalize_doi(value: str) -> str | None:
    cleaned = DOI_PREFIX_RE.sub("", value.strip()).strip()
    if not cleaned:
        return None
    match = DOI_RE.search(cleaned)
    if not match:
        return None
    doi = match.group(0).strip().rstrip(".,);]")
    return doi or None


def resolve_identifier(identifier: str) -> ResolvedIdentifier:
    original = identifier.strip()
    if not original:
        raise ValueError("identifier cannot be empty")

    parsed = urlparse(original)
    doi = normalize_doi(original)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return ResolvedIdentifier(original=original, url=original, doi=doi)

    if doi:
        return ResolvedIdentifier(
            original=original,
            url=f"https://doi.org/{quote(doi, safe='/')}",
            doi=doi,
        )

    raise ValueError("identifier must be a DOI, DOI URL, or article URL")


def safe_identifier_part(identifier: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", identifier.strip())
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or "paper"


def title_slug(title: str, *, max_length: int = 80) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", title.lower())
    value = re.sub(r"_+", "_", value).strip("_")
    if len(value) <= max_length:
        return value or "article"
    return value[:max_length].rstrip("_") or "article"
