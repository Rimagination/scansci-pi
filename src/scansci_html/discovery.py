from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Protocol

import requests


@dataclass(frozen=True)
class DiscoveredPaper:
    title: str
    doi: str
    year: int | None
    venue: str
    source: str
    url: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DiscoveryProvider(Protocol):
    def search(self, query: str, *, limit: int = 10) -> list[DiscoveredPaper]:
        ...


class OpenAlexDiscoveryProvider:
    source_name = "openalex"

    def __init__(self, *, timeout: float = 30.0, session: Any | None = None) -> None:
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def search(self, query: str, *, limit: int = 10) -> list[DiscoveredPaper]:
        response = self.session.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": int(limit)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return [_openalex_paper(item) for item in response.json().get("results", [])]


class CrossrefDiscoveryProvider:
    source_name = "crossref"

    def __init__(self, *, timeout: float = 30.0, session: Any | None = None) -> None:
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def search(self, query: str, *, limit: int = 10) -> list[DiscoveredPaper]:
        response = self.session.get(
            "https://api.crossref.org/works",
            params={"query": query, "rows": int(limit)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return [_crossref_paper(item) for item in response.json().get("message", {}).get("items", [])]


class SemanticScholarDiscoveryProvider:
    source_name = "semantic-scholar"

    def __init__(self, *, timeout: float = 30.0, session: Any | None = None) -> None:
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def search(self, query: str, *, limit: int = 10) -> list[DiscoveredPaper]:
        response = self.session.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "limit": int(limit),
                "fields": "title,year,venue,url,externalIds",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return [_semantic_scholar_paper(item) for item in response.json().get("data", [])]


class PubMedDiscoveryProvider:
    source_name = "pubmed"

    def __init__(self, *, timeout: float = 30.0, session: Any | None = None) -> None:
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def search(self, query: str, *, limit: int = 10) -> list[DiscoveredPaper]:
        search_response = self.session.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmode": "json", "retmax": int(limit)},
            timeout=self.timeout,
        )
        search_response.raise_for_status()
        ids = search_response.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        summary_response = self.session.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout=self.timeout,
        )
        summary_response.raise_for_status()
        result = summary_response.json().get("result", {})
        return [_pubmed_paper(result[pmid]) for pmid in ids if pmid in result]


def build_discovery_provider(provider: str) -> DiscoveryProvider:
    name = (provider or "openalex").strip().lower()
    if name == "openalex":
        return OpenAlexDiscoveryProvider()
    if name == "crossref":
        return CrossrefDiscoveryProvider()
    if name in {"semantic-scholar", "semanticscholar", "s2"}:
        return SemanticScholarDiscoveryProvider()
    if name == "pubmed":
        return PubMedDiscoveryProvider()
    raise ValueError(f"Unsupported discovery provider: {provider}")


def _openalex_paper(item: dict[str, Any]) -> DiscoveredPaper:
    source = item.get("primary_location", {}).get("source", {}) or {}
    return DiscoveredPaper(
        title=str(item.get("title", "")),
        doi=_normalize_doi(str(item.get("doi", ""))),
        year=_int_or_none(item.get("publication_year")),
        venue=str(source.get("display_name", "")),
        source="openalex",
        url=str(item.get("id", "")),
    )


def _crossref_paper(item: dict[str, Any]) -> DiscoveredPaper:
    return DiscoveredPaper(
        title=_first(item.get("title", [])),
        doi=_normalize_doi(str(item.get("DOI", ""))),
        year=_crossref_year(item),
        venue=_first(item.get("container-title", [])),
        source="crossref",
        url=str(item.get("URL", "")),
    )


def _semantic_scholar_paper(item: dict[str, Any]) -> DiscoveredPaper:
    external_ids = item.get("externalIds", {}) or {}
    return DiscoveredPaper(
        title=str(item.get("title", "")),
        doi=_normalize_doi(str(external_ids.get("DOI", ""))),
        year=_int_or_none(item.get("year")),
        venue=str(item.get("venue", "")),
        source="semantic-scholar",
        url=str(item.get("url", "")),
    )


def _pubmed_paper(item: dict[str, Any]) -> DiscoveredPaper:
    pmid = str(item.get("uid", ""))
    return DiscoveredPaper(
        title=str(item.get("title", "")),
        doi=_pubmed_doi(str(item.get("elocationid", ""))),
        year=_year_from_pubdate(str(item.get("pubdate", ""))),
        venue=str(item.get("fulljournalname", "")),
        source="pubmed",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    )


def _pubmed_doi(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("doi:"):
        cleaned = cleaned[4:].strip()
    return _normalize_doi(cleaned)


def _year_from_pubdate(value: str) -> int | None:
    match = re.search(r"\b(\d{4})\b", value)
    if not match:
        return None
    return _int_or_none(match.group(1))


def _normalize_doi(value: str) -> str:
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            return doi[len(prefix) :]
    return doi


def _first(values: Any) -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    return str(values or "")


def _crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published"):
        date_parts = item.get(key, {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            return _int_or_none(date_parts[0][0])
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
