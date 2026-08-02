from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag


SENSITIVE_QUERY_KEYS = {
    "token",
    "nonce",
    "invoice",
    "idenid",
    "auth",
    "signature",
    "sig",
    "key",
    "access_token",
}
ARTIFACT_LABEL_RE = re.compile(
    r"supplement|supplementary|supporting information|source data|data availability|dataset|"
    r"figshare|zenodo|dryad|sciencedb|xlsx|xls|csv|zip|appendix",
    re.I,
)


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    source_doc_id: str
    source_html_path: str
    source_anchor: str
    label: str
    url: str
    doi: str = ""
    repository: str = "unknown"
    artifact_type: str = "unknown"
    content_type: str = ""
    size_bytes: int | str = ""
    license: str = ""
    access_status: str = "unknown"
    downloaded_path: str = ""
    checked_at: str = ""
    review_state: str = "unreviewed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_artifact_records(
    html_text: str,
    *,
    html_path: str | Path,
    source_url: str = "",
) -> list[ArtifactRecord]:
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    source_doc_id = _source_doc_id(soup, html_path)
    normalized_path = Path(html_path).as_posix()
    records: list[ArtifactRecord] = []
    seen_urls: set[str] = set()
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        label = _normalized_text(link)
        href = str(link.get("href") or "").strip()
        absolute = _sanitize_url(urljoin(source_url, href) if source_url else href)
        if not absolute or absolute in seen_urls:
            continue
        if not _looks_like_artifact(label, absolute):
            continue
        seen_urls.add(absolute)
        ordinal = len(records) + 1
        records.append(
            ArtifactRecord(
                artifact_id=f"{Path(html_path).stem}:artifact-{ordinal:04d}",
                source_doc_id=source_doc_id,
                source_html_path=normalized_path,
                source_anchor=_nearest_anchor(link) or f"artifact-{ordinal:04d}",
                label=label or absolute,
                url=absolute,
                repository=_repository(absolute),
                artifact_type=_artifact_type(label, absolute),
                access_status=_access_status(absolute),
            )
        )
    return records


def _source_doc_id(soup: BeautifulSoup, html_path: str | Path) -> str:
    article = soup.select_one("article.paper") or soup.select_one("article")
    if isinstance(article, Tag):
        for name in ("data-doi", "data-source-url"):
            value = str(article.get(name) or "").strip()
            if value:
                return value
    return Path(html_path).stem


def _sanitize_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    safe_query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY_KEYS
        ]
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, safe_query, ""))


def _looks_like_artifact(label: str, url: str) -> bool:
    target = f"{label} {url}"
    return bool(
        ARTIFACT_LABEL_RE.search(target)
        or re.search(r"\.(xlsx?|csv|zip|pdf|docx?|txt|nc|hdf5?)(?:$|\?)", url, re.I)
    )


def _repository(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "figshare" in host:
        return "figshare"
    if "zenodo" in host:
        return "zenodo"
    if "dryad" in host:
        return "dryad"
    if "osf.io" in host:
        return "osf"
    if "sciencedb" in host:
        return "sciencedb"
    if host:
        return "publisher"
    return "unknown"


def _artifact_type(label: str, url: str) -> str:
    target = f"{label} {url}".lower()
    if "source data" in target:
        return "source_data"
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if suffix in {"xlsx", "xls", "csv", "zip", "pdf", "doc", "docx", "txt", "nc", "hdf", "hdf5"}:
        return "xlsx" if suffix in {"xlsx", "xls"} else suffix
    if any(name in target for name in ("figshare", "zenodo", "dryad", "sciencedb", "dataset")):
        return "dataset_record"
    if "supplement" in target or "supporting information" in target:
        return "supplementary"
    return "unknown"


def _access_status(url: str) -> str:
    return "metadata_only" if _repository(url) in {"figshare", "zenodo", "dryad", "osf", "sciencedb"} else "unknown"


def _nearest_anchor(tag: Tag) -> str:
    current: Tag | None = tag
    while isinstance(current, Tag):
        value = str(current.get("id") or "").strip()
        if value:
            return value
        current = current.parent if isinstance(current.parent, Tag) else None
    return ""


def _normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
