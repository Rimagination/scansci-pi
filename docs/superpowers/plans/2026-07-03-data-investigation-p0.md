# Data Investigation P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable `scansci investigate` P0 workflow: extract structured references, artifact links, and data availability records from clean HTML, then export CSV/JSONL without leaking private task details or credentials.

**Architecture:** Add three focused extraction modules that operate on clean HTML and return dataclasses with `to_dict()` methods. Keep existing `citations.py` compatible by letting it remain the DOI-only adapter, while new `references.py` provides richer `ReferenceRecord` output. Wire the modules into a new layered CLI namespace `investigate references|artifacts|availability`.

**Tech Stack:** Python 3.11, BeautifulSoup/lxml, dataclasses, argparse, csv/jsonl file writers, pytest.

---

## File Structure

- Create `src/scansci_html/references.py`: structured reference extraction from one clean HTML document.
- Create `src/scansci_html/artifacts.py`: supplementary/source-data/repository/file-link discovery from one clean HTML document.
- Create `src/scansci_html/data_availability.py`: data availability statement extraction and status classification.
- Modify `src/scansci_html/cli.py`: add `investigate` layered command aliases, parsers, handlers, CSV/JSONL helpers.
- Modify `README.md`: add a short P0 usage section.
- Create `tests/test_data_investigation.py`: focused tests for the new modules and CLI.

Do not add private-task fixtures, specific private dataset names, site lists, or benchmark references.

---

### Task 1: Structured Reference Records

**Files:**
- Create: `src/scansci_html/references.py`
- Test: `tests/test_data_investigation.py`

- [ ] **Step 1: Write the failing reference extraction tests**

Add this to `tests/test_data_investigation.py`:

```python
import csv
import json
from pathlib import Path

from scansci_html.references import extract_reference_records


def test_extract_reference_records_keeps_doi_and_no_doi_entries():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <h2>Results</h2>
      <p>Body DOI 10.9999/not-a-reference should not be used.</p>
      <h2>References</h2>
      <ol>
        <li id="ref-1">Smith J, Doe A. Dataset paper title. Nature Data 12, 1-4 (2020). https://doi.org/10.1000/alpha</li>
        <li id="ref-2">李四, 王五. 中文参考文献题名. 生态学报, 2021, 41(1): 1-9.</li>
      </ol>
    </article>
    """

    records = extract_reference_records(html, html_path=Path("paper.html"))

    assert [record.to_dict() for record in records] == [
        {
            "reference_id": "paper:ref-1",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "ref-1",
            "raw_text": "Smith J, Doe A. Dataset paper title. Nature Data 12, 1-4 (2020). https://doi.org/10.1000/alpha",
            "doi": "10.1000/alpha",
            "title": "Dataset paper title",
            "authors": "Smith J, Doe A",
            "year": 2020,
            "venue": "Nature Data",
            "language": "en",
            "record_type": "dataset_paper",
            "confidence": 0.8,
            "review_state": "unreviewed",
        },
        {
            "reference_id": "paper:ref-2",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "ref-2",
            "raw_text": "李四, 王五. 中文参考文献题名. 生态学报, 2021, 41(1): 1-9.",
            "doi": "",
            "title": "中文参考文献题名",
            "authors": "李四, 王五",
            "year": 2021,
            "venue": "生态学报",
            "language": "zh",
            "record_type": "unknown",
            "confidence": 0.55,
            "review_state": "unreviewed",
        },
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_extract_reference_records_keeps_doi_and_no_doi_entries -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scansci_html.references'`.

- [ ] **Step 3: Implement `references.py`**

Create `src/scansci_html/references.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+", re.I)
YEAR_RE = re.compile(r"(?:\(|,|\s)(18|19|20)\d{2}(?:\)|,|\.|\s)")
DATASET_TERMS = re.compile(r"\b(dataset|database|data set|data descriptor|scientific data|earth system science data)\b", re.I)
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


def extract_reference_records(html_text: str, *, html_path: str | Path) -> list[ReferenceRecord]:
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
```

Also implement the helpers in the same file:

```python
def _source_doc_id(soup: BeautifulSoup, html_path: str | Path) -> str:
    article = soup.select_one("article.paper") or soup.select_one("article")
    if isinstance(article, Tag):
        doi = _attr(article, "data-doi")
        if doi:
            return doi
        source_url = _attr(article, "data-source-url")
        if source_url:
            return source_url
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
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        text = _normalized_text(heading).lower()
        if text in {"references", "reference", "bibliography", "literature cited", "references and notes"}:
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
```

And parsing helpers:

```python
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
    parts = [part.strip(" ,;") for part in re.split(r"\.\s+", text) if part.strip(" ,;")]
    authors = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    venue = parts[2] if len(parts) > 2 else ""
    venue = re.sub(r"\b(?:18|19|20)\d{2}\b.*$", "", venue).strip(" ,;")
    if _contains_cjk(text):
        cjk_parts = [part.strip(" ,;，。") for part in re.split(r"[.。]\s*", text) if part.strip(" ,;，。")]
        authors = cjk_parts[0] if cjk_parts else authors
        title = cjk_parts[1] if len(cjk_parts) > 1 else title
        venue = cjk_parts[2].split(",", 1)[0].strip(" ，,;") if len(cjk_parts) > 2 else venue
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
    score = 0.35
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
```

- [ ] **Step 4: Run reference test to verify it passes**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_extract_reference_records_keeps_doi_and_no_doi_entries -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/scansci_html/references.py tests/test_data_investigation.py
git commit -m "feat: add structured reference extraction"
```

If the repository has no identity configured, skip the commit and record the `git status --short` output in the final report.

---

### Task 2: Artifact Discovery

**Files:**
- Create: `src/scansci_html/artifacts.py`
- Modify: `tests/test_data_investigation.py`

- [ ] **Step 1: Write failing artifact tests**

Append:

```python
from scansci_html.artifacts import discover_artifact_records


def test_discover_artifact_records_sanitizes_urls_and_classifies_repositories():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <h2>Data availability</h2>
      <p id="data-availability">Source data are available at
        <a href="https://figshare.com/articles/dataset/example/123?token=REDACTED">Figshare dataset</a>.
      </p>
      <h2>Supplementary information</h2>
      <p><a id="supp-1" href="/articles/supplementary.xlsx?nonce=REDACTED">Supplementary Table 1</a></p>
    </article>
    """

    records = discover_artifact_records(
        html,
        html_path=Path("paper.html"),
        source_url="https://example.org/paper",
    )

    assert [record.to_dict() for record in records] == [
        {
            "artifact_id": "paper:artifact-0001",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "data-availability",
            "label": "Figshare dataset",
            "url": "https://figshare.com/articles/dataset/example/123",
            "doi": "",
            "repository": "figshare",
            "artifact_type": "dataset_record",
            "content_type": "",
            "size_bytes": "",
            "license": "",
            "access_status": "metadata_only",
            "downloaded_path": "",
            "checked_at": "",
            "review_state": "unreviewed",
        },
        {
            "artifact_id": "paper:artifact-0002",
            "source_doc_id": "10.1234/source",
            "source_html_path": "paper.html",
            "source_anchor": "supp-1",
            "label": "Supplementary Table 1",
            "url": "https://example.org/articles/supplementary.xlsx",
            "doi": "",
            "repository": "publisher",
            "artifact_type": "xlsx",
            "content_type": "",
            "size_bytes": "",
            "license": "",
            "access_status": "unknown",
            "downloaded_path": "",
            "checked_at": "",
            "review_state": "unreviewed",
        },
    ]
```

- [ ] **Step 2: Run artifact test to verify it fails**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_discover_artifact_records_sanitizes_urls_and_classifies_repositories -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `artifacts.py`**

Create `src/scansci_html/artifacts.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag


SENSITIVE_QUERY_KEYS = {"token", "nonce", "invoice", "idenid", "auth", "signature", "sig", "key", "access_token"}
ARTIFACT_LABEL_RE = re.compile(r"supplement|supplementary|supporting information|source data|data availability|dataset|figshare|zenodo|dryad|scienceDB|xlsx|xls|csv|zip|appendix", re.I)


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
```

Add discovery helpers:

```python
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
```

Add parsing helpers:

```python
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
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in SENSITIVE_QUERY_KEYS]
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, safe_query, ""))


def _looks_like_artifact(label: str, url: str) -> bool:
    target = f"{label} {url}"
    return bool(ARTIFACT_LABEL_RE.search(target) or re.search(r"\.(xlsx?|csv|zip|pdf|docx?|txt|nc|hdf5?)(?:$|\?)", url, re.I))


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
```

- [ ] **Step 4: Run artifact test to verify it passes**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_discover_artifact_records_sanitizes_urls_and_classifies_repositories -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/scansci_html/artifacts.py tests/test_data_investigation.py
git commit -m "feat: discover data investigation artifacts"
```

---

### Task 3: Data Availability Parser

**Files:**
- Create: `src/scansci_html/data_availability.py`
- Modify: `tests/test_data_investigation.py`

- [ ] **Step 1: Write failing data availability tests**

Append:

```python
from scansci_html.data_availability import extract_data_availability_records


def test_extract_data_availability_records_classifies_statement_and_links_artifacts():
    html = """
    <article class="paper" data-doi="10.1234/source">
      <h1>Source Paper</h1>
      <section>
        <h2>Data availability</h2>
        <p id="availability-p1">The source data are available at
          <a href="https://zenodo.org/records/12345">Zenodo</a> under a CC BY license.
        </p>
      </section>
    </article>
    """

    records = extract_data_availability_records(html, html_path=Path("paper.html"), source_url="https://example.org/paper")

    assert [record.to_dict() for record in records] == [
        {
            "availability_id": "paper:data-availability-0001",
            "source_doc_id": "10.1234/source",
            "statement_text": "The source data are available at Zenodo under a CC BY license.",
            "source_html_path": "paper.html",
            "source_anchor": "availability-p1",
            "availability_status": "yes",
            "repository": "zenodo",
            "url": "https://zenodo.org/records/12345",
            "doi": "",
            "license": "CC BY",
            "files_available": False,
            "evidence_level": "metadata_page",
            "confidence": 0.8,
            "review_state": "unreviewed",
        }
    ]


def test_extract_data_availability_records_detects_by_request():
    html = """
    <article class="paper">
      <h2>Data availability</h2>
      <p id="availability-p1">Data are available from the corresponding author upon reasonable request.</p>
    </article>
    """

    records = extract_data_availability_records(html, html_path=Path("paper.html"))

    assert records[0].availability_status == "by_request"
    assert records[0].evidence_level == "statement_only"
```

- [ ] **Step 2: Run availability tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_extract_data_availability_records_classifies_statement_and_links_artifacts tests/test_data_investigation.py::test_extract_data_availability_records_detects_by_request -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `data_availability.py`**

Create `src/scansci_html/data_availability.py`:

```python
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
```

Add extraction:

```python
def extract_data_availability_records(
    html_text: str,
    *,
    html_path: str | Path,
    source_url: str = "",
) -> list[DataAvailabilityRecord]:
    soup = BeautifulSoup(str(html_text or ""), "lxml")
    source_doc_id = _source_doc_id(soup, html_path)
    normalized_path = Path(html_path).as_posix()
    blocks = _availability_blocks(soup)
    records: list[DataAvailabilityRecord] = []
    for index, block in enumerate(blocks, start=1):
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
```

Add helpers:

```python
def _availability_blocks(soup: BeautifulSoup) -> list[Tag]:
    blocks: list[Tag] = []
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        if not isinstance(heading, Tag):
            continue
        if "data availability" not in _normalized_text(heading).lower() and "availability of data" not in _normalized_text(heading).lower():
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
    if "upon reasonable request" in lower or "corresponding author" in lower or "available from the author" in lower:
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
```

- [ ] **Step 4: Run availability tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_extract_data_availability_records_classifies_statement_and_links_artifacts tests/test_data_investigation.py::test_extract_data_availability_records_detects_by_request -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/scansci_html/data_availability.py tests/test_data_investigation.py
git commit -m "feat: parse data availability statements"
```

---

### Task 4: CLI Wiring And Exports

**Files:**
- Modify: `src/scansci_html/cli.py`
- Modify: `tests/test_data_investigation.py`

- [ ] **Step 1: Write failing CLI tests**

Append:

```python
from scansci_html import cli


def test_cli_investigate_references_writes_csv_and_jsonl(tmp_path: Path, capsys):
    html_path = tmp_path / "paper.html"
    csv_path = tmp_path / "references.csv"
    jsonl_path = tmp_path / "references.jsonl"
    html_path.write_text(
        """
        <article class="paper" data-doi="10.1234/source">
          <h2>References</h2>
          <ol><li id="ref-1">Smith J. Dataset paper title. Data Journal (2020). doi:10.1000/example</li></ol>
        </article>
        """,
        encoding="utf-8",
    )

    exit_code = cli.main([
        "investigate",
        "references",
        "--html",
        str(html_path),
        "--output",
        str(csv_path),
        "--jsonl-output",
        str(jsonl_path),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["output_path"] == str(csv_path)
    assert payload["jsonl_output_path"] == str(jsonl_path)
    assert "reference_id,source_doc_id,source_html_path" in csv_path.read_text(encoding="utf-8")
    assert json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])["doi"] == "10.1000/example"
```

- [ ] **Step 2: Run CLI test to verify it fails**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_cli_investigate_references_writes_csv_and_jsonl -q
```

Expected: FAIL because `investigate references` is not defined.

- [ ] **Step 3: Modify imports and command aliases**

In `src/scansci_html/cli.py`, add imports:

```python
from .artifacts import ArtifactRecord, discover_artifact_records
from .data_availability import DataAvailabilityRecord, extract_data_availability_records
from .references import ReferenceRecord, extract_reference_records
```

Add aliases to `_LAYERED_COMMAND_ALIASES`:

```python
    ("investigate", "references"): "investigate-references",
    ("investigate", "artifacts"): "investigate-artifacts",
    ("investigate", "availability"): "investigate-availability",
```

Add to `_LAYERED_COMMAND_EPILOG`:

```text
  investigate references|artifacts|availability
```

Add layer parser in `_add_layered_entry_parsers`:

```python
        (
            "investigate",
            "Application layer: research data availability investigation exports.",
            ["references", "artifacts", "availability"],
        ),
```

- [ ] **Step 4: Add CLI parsers**

In `build_parser`, near existing `references` parser, add:

```python
    investigate_references = subparsers.add_parser(
        "investigate-references",
        help="Extract structured reference records from clean HTML.",
    )
    _add_investigation_input_options(investigate_references)
    _add_investigation_output_options(investigate_references)

    investigate_artifacts = subparsers.add_parser(
        "investigate-artifacts",
        help="Discover supplementary/source-data artifact records from clean HTML.",
    )
    _add_investigation_input_options(investigate_artifacts)
    _add_investigation_output_options(investigate_artifacts)

    investigate_availability = subparsers.add_parser(
        "investigate-availability",
        help="Parse data availability statements from clean HTML.",
    )
    _add_investigation_input_options(investigate_availability)
    _add_investigation_output_options(investigate_availability)
```

Add helper parser functions near `_add_workspace_options`:

```python
def _add_investigation_input_options(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", default="", help="Single clean HTML file to inspect.")
    source.add_argument("--library-dir", default="", help="Directory of clean HTML files to inspect recursively.")


def _add_investigation_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", required=True, help="CSV output path.")
    parser.add_argument("--jsonl-output", default="", help="Optional JSONL output path.")
```

- [ ] **Step 5: Add CLI handlers and writers**

Before the existing `if args.command == "references":` handler, add:

```python
    if args.command == "investigate-references":
        rows = _collect_investigation_rows(args, extractor=extract_reference_records)
        _write_dict_csv(Path(args.output), [row.to_dict() for row in rows], fieldnames=list(ReferenceRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), [row.to_dict() for row in rows])
        _emit_json(_investigation_payload(args, rows))
        return 0

    if args.command == "investigate-artifacts":
        rows = _collect_investigation_rows(args, extractor=discover_artifact_records)
        _write_dict_csv(Path(args.output), [row.to_dict() for row in rows], fieldnames=list(ArtifactRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), [row.to_dict() for row in rows])
        _emit_json(_investigation_payload(args, rows))
        return 0

    if args.command == "investigate-availability":
        rows = _collect_investigation_rows(args, extractor=extract_data_availability_records)
        _write_dict_csv(Path(args.output), [row.to_dict() for row in rows], fieldnames=list(DataAvailabilityRecord.__dataclass_fields__))
        if args.jsonl_output:
            _write_jsonl(Path(args.jsonl_output), [row.to_dict() for row in rows])
        _emit_json(_investigation_payload(args, rows))
        return 0
```

Add helper functions near `_write_csv`:

```python
def _collect_investigation_rows(args: argparse.Namespace, *, extractor: object) -> list[object]:
    paths = [Path(args.html)] if args.html else sorted(Path(args.library_dir).rglob("*.html"))
    rows: list[object] = []
    for html_path in paths:
        html_text = html_path.read_text(encoding="utf-8")
        rows.extend(extractor(html_text, html_path=html_path, source_url=_source_url_from_html(html_text)))
    return rows


def _source_url_from_html(html_text: str) -> str:
    match = re.search(r'data-source-url=["\\']([^"\\']+)["\\']', html_text)
    return match.group(1) if match else ""


def _write_dict_csv(path: Path, rows: list[dict[str, object]], *, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _investigation_payload(args: argparse.Namespace, rows: list[object]) -> dict[str, object]:
    return {
        "command": args.command,
        "count": len(rows),
        "output_path": str(Path(args.output)),
        "jsonl_output_path": str(Path(args.jsonl_output)) if args.jsonl_output else "",
    }
```

Make sure `re` is imported at the top of `cli.py`.

- [ ] **Step 6: Run CLI test to verify it passes**

Run:

```powershell
python -m pytest tests/test_data_investigation.py::test_cli_investigate_references_writes_csv_and_jsonl -q
```

Expected: PASS.

- [ ] **Step 7: Run all data investigation tests**

Run:

```powershell
python -m pytest tests/test_data_investigation.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```powershell
git add src/scansci_html/cli.py tests/test_data_investigation.py
git commit -m "feat: add investigate export commands"
```

---

### Task 5: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_cli.py`, `tests/test_data_investigation.py`, `tests/test_citations.py`

- [ ] **Step 1: Add README usage section**

Add a short section after the references section:

```markdown
## Research data availability investigation

The `investigate` commands build evidence-chain tables for data reproducibility work. They operate on clean HTML that you already have lawful access to, and they do not bypass paywalls or store credentials.

```powershell
scansci investigate references --library-dir .\html-papers --output .\outputs\references.csv --jsonl-output .\outputs\references.jsonl
scansci investigate artifacts --library-dir .\html-papers --output .\outputs\artifacts.csv --jsonl-output .\outputs\artifacts.jsonl
scansci investigate availability --library-dir .\html-papers --output .\outputs\data_availability.csv --jsonl-output .\outputs\data_availability.jsonl
```

The first P0 outputs are review tables. Rows default to `review_state=unreviewed`, preserve source HTML paths and anchors, and sanitize credential-like query parameters such as `token`, `nonce`, and `invoice`.
```

- [ ] **Step 2: Run focused regression tests**

Run:

```powershell
python -m pytest tests/test_data_investigation.py tests/test_citations.py tests/test_cli.py::test_cli_help_lists_layered_commands -q
```

Expected: PASS.

- [ ] **Step 3: Scan for private-task leakage and credential-like URL fields**

Run:

```powershell
rg -n "PRIVATE_TASK_NAME|token=REDACTED|nonce=REDACTED|invoice=REDACTED" docs src tests README.md
```

Expected: no private task names. Test fixtures may include `token=REDACTED` or `nonce=REDACTED` only in tests that assert sanitization.

- [ ] **Step 4: Check git status**

Run:

```powershell
git status --short
```

Expected: only intentional source, test, README, spec, and plan files are modified/untracked.

- [ ] **Step 5: Commit docs**

Run:

```powershell
git add README.md docs/superpowers/specs/2026-07-03-data-availability-investigation-design.md docs/superpowers/plans/2026-07-03-data-investigation-p0.md
git commit -m "docs: plan data availability investigation layer"
```

If commits are skipped because the repository has no configured identity or because the user wants to manage initial repo history, report that clearly.

---

## Self-Review

Spec coverage:

- Structured references: Task 1 and Task 4.
- `artifacts.csv/jsonl`: Task 2 and Task 4.
- `data_availability.csv/jsonl`: Task 3 and Task 4.
- Privacy/compliance: Task 2 URL sanitizer, Task 5 leakage scan, README text.
- Project/workspace, entity schema, matrix, SQLite, Web UI: explicitly deferred to P1/P2 in the approved spec and not implemented in P0.

Placeholder scan:

- No `TBD`, `TODO`, or open-ended implementation instructions are used as required plan content.

Type consistency:

- Dataclass names are `ReferenceRecord`, `ArtifactRecord`, `DataAvailabilityRecord`.
- CLI commands are normalized to `investigate-references`, `investigate-artifacts`, `investigate-availability`.
- Layered aliases are `scansci investigate references|artifacts|availability`.
