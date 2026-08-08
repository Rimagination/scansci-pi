"""Resolve optional Zotero tag scopes against an evidence-store catalogue."""

from __future__ import annotations

from functools import lru_cache
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable


_AUTO_TAG_STOPWORDS = {
    "about", "across", "after", "among", "based", "from", "have", "into", "more",
    "over", "than", "that", "their", "there", "these", "this", "through", "using",
    "with", "without", "and", "the", "for", "of", "on", "in", "as", "a", "an",
    "to", "is", "are", "does", "what", "how", "研究", "影响", "基于", "一个", "一种",
}


def normalize_zotero_tag(value: Any) -> str:
    """Return a stable comparison key without changing the displayed tag."""

    return " ".join(str(value or "").strip().split()).casefold()


def _display_tags(values: Any) -> list[str]:
    display: dict[str, str] = {}
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    for value in raw_values:
        if isinstance(value, dict):
            value = value.get("tag", "")
        label = " ".join(str(value or "").strip().split())
        normalized = normalize_zotero_tag(label)
        if normalized and normalized not in display:
            display[normalized] = label
    return list(display.values())


def zotero_item_tags(item: dict[str, Any]) -> list[str]:
    """Read tags from both the local database and Zotero Web API shapes."""

    return _display_tags(item.get("tags", []))


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").strip().casefold())


def _auto_tag_terms(value: Any) -> set[str]:
    """Tokenize English and Chinese text for lightweight tag-profile matching."""

    text = str(value or "").strip().casefold()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{3,}|[\u4e00-\u9fff]{2,}", text)
        if token not in _AUTO_TAG_STOPWORDS
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.update(chunk[index:index + 2] for index in range(max(0, len(chunk) - 1)))
    return terms


@lru_cache(maxsize=4)
def _read_live_zotero_items(
    data_dir: str,
    database_path: str,
    database_signature: str,
) -> tuple[dict[str, Any], ...]:
    """Read tags lazily when an older notebook snapshot has no tag metadata."""

    try:
        # Import lazily to keep this pure helper free of an import cycle during
        # library-manager startup.
        from .library_manager import _read_local_zotero_database

        state = _read_local_zotero_database(
            limit=10_000,
            data_dir=data_dir or str(Path(database_path).parent),
        )
        return tuple(dict(item) for item in list(state.get("items", []) or []) if isinstance(item, dict))
    except (OSError, sqlite3.Error, ValueError):
        return ()


def _zotero_items(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    zotero = dict(dict(notebook.get("metadata", {}) or {}).get("zotero", {}) or {})
    stored_items = [
        dict(item)
        for item in list(zotero.get("items", []) or [])
        if isinstance(item, dict)
    ]
    if any(zotero_item_tags(item) for item in stored_items):
        return stored_items
    data_dir = str(zotero.get("data_dir", "") or "").strip()
    database_path = str(zotero.get("database_path", "") or "").strip()
    candidate = Path(database_path) if database_path else Path(data_dir) / "zotero.sqlite"
    try:
        stat = candidate.stat()
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return stored_items
    live_items = _read_live_zotero_items(data_dir, str(candidate), signature)
    return [dict(item) for item in live_items] or stored_items


def zotero_item_matches_scope(item: dict[str, Any], scope: dict[str, Any] | None) -> bool:
    requested = dict(scope or {})
    if str(requested.get("type", "")).strip() != "zotero-tag":
        return True
    tags = {normalize_zotero_tag(tag) for tag in _display_tags(requested.get("tags", []))}
    if not tags:
        return True
    item_tags = {normalize_zotero_tag(tag) for tag in zotero_item_tags(item)}
    if str(requested.get("match", "any")).strip().casefold() == "all":
        return tags.issubset(item_tags)
    return bool(tags & item_tags)


def filter_zotero_result(result: dict[str, Any], scope: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the same opt-in tag rule to metadata-only Zotero tool results."""

    requested = dict(scope or {})
    if str(requested.get("type", "")).strip() != "zotero-tag":
        return result
    items = [
        dict(item)
        for item in list(result.get("items", []) or [])
        if isinstance(item, dict) and zotero_item_matches_scope(item, requested)
    ]
    filtered = dict(result)
    filtered["items"] = items
    filtered["count"] = len(items)
    library = dict(filtered.get("library", {}) or {})
    library["item_count"] = len(items)
    library["pdf_count"] = sum(bool(item.get("attachments")) for item in items)
    filtered["library"] = library
    filtered["tag_scope_applied"] = True
    return filtered


def _normalize_doi(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    return normalized.rstrip(".,;)]}")


def _normalize_title(value: Any) -> str:
    return re.sub(r"[^\w]+", "", str(value or "").strip().casefold())


def _normalize_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or re.match(r"^https?://", raw, flags=re.IGNORECASE):
        return ""
    if raw.casefold().startswith("file://"):
        raw = raw[7:]
    try:
        candidate = Path(raw).expanduser().resolve()
    except OSError:
        candidate = Path(raw).expanduser()
    return os.path.normcase(os.path.normpath(str(candidate)))


def _path_keys(value: Any) -> set[str]:
    normalized = _normalize_path(value)
    if not normalized:
        return set()
    return {normalized, os.path.normcase(os.path.basename(normalized))}


def _item_paths(item: dict[str, Any]) -> set[str]:
    values = [item.get("pdf_path"), item.get("path")]
    for attachment in list(item.get("attachments", []) or []):
        if isinstance(attachment, dict):
            values.extend([attachment.get("path"), attachment.get("original_path")])
    paths: set[str] = set()
    for value in values:
        paths.update(_path_keys(value))
    return paths


def _source_rows(evidence_db: str | Path) -> list[dict[str, Any]]:
    path = Path(evidence_db)
    if not path.is_file():
        return []
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                select doc_id, title, doi, source_url, html_path
                from source_documents
                order by doc_id
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _source_indexes(sources: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    indexes: dict[str, dict[str, set[str]]] = {
        "doi": {},
        "title": {},
        "path": {},
    }
    for source in sources:
        doc_id = str(source.get("doc_id", "") or "").strip()
        if not doc_id:
            continue
        doi = _normalize_doi(source.get("doi"))
        if doi:
            indexes["doi"].setdefault(doi, set()).add(doc_id)
        title = _normalize_title(source.get("title"))
        if len(title) >= 8:
            indexes["title"].setdefault(title, set()).add(doc_id)
        for path_key in _path_keys(source.get("source_url")) | _path_keys(source.get("html_path")):
            indexes["path"].setdefault(path_key, set()).add(doc_id)
    return indexes


def _matching_doc_ids_fast(item: dict[str, Any], indexes: dict[str, dict[str, set[str]]]) -> set[str]:
    matches: set[str] = set()
    doi = _normalize_doi(item.get("doi"))
    if doi:
        matches.update(indexes["doi"].get(doi, set()))
    for path_key in _item_paths(item):
        matches.update(indexes["path"].get(path_key, set()))
    title = _normalize_title(item.get("title"))
    if len(title) >= 8:
        matches.update(indexes["title"].get(title, set()))
    return matches


def _matching_doc_ids(item: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    item_doi = _normalize_doi(item.get("doi"))
    item_title = _normalize_title(item.get("title"))
    item_paths = _item_paths(item)
    matches: list[str] = []
    for source in sources:
        doc_id = str(source.get("doc_id", "") or "").strip()
        if not doc_id:
            continue
        source_doi = _normalize_doi(source.get("doi"))
        source_paths = _path_keys(source.get("source_url")) | _path_keys(source.get("html_path"))
        source_title = _normalize_title(source.get("title"))
        matched = bool(item_doi and source_doi and item_doi == source_doi)
        matched = matched or bool(item_paths and source_paths and item_paths & source_paths)
        # Title matching is deliberately exact and used only as a last resort;
        # a fuzzy title match can silently widen a tag experiment.
        matched = matched or bool(item_title and len(item_title) >= 8 and item_title == source_title)
        if matched:
            matches.append(doc_id)
    return list(dict.fromkeys(matches))


def sync_zotero_document_tags(
    evidence_db: str | Path,
    items: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Refresh the document-to-tag sidecar used by hybrid retrieval.

    Zotero remains the source of truth.  Matching uses DOI, attachment path,
    and exact title as fallbacks, the same identity rules as the legacy scope
    experiment.  The operation only changes the metadata sidecar; it never
    touches source files, evidence spans, or vector rows.
    """

    database = Path(evidence_db)
    if not database.is_file():
        return {"status": "missing_database", "matched_items": 0, "documents": 0, "tags": 0}
    sources = _source_rows(database)
    if not sources:
        return {"status": "empty_catalogue", "matched_items": 0, "documents": 0, "tags": 0}
    indexes = _source_indexes(sources)
    tags_by_document: dict[str, dict[str, str]] = {}
    matched_items = 0
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        document_ids = _matching_doc_ids_fast(item, indexes)
        display_tags = _display_tags(item.get("tags", []))
        if not document_ids or not display_tags:
            continue
        matched_items += 1
        for doc_id in document_ids:
            per_document = tags_by_document.setdefault(str(doc_id), {})
            for tag in display_tags:
                per_document.setdefault(normalize_zotero_tag(tag), tag)

    try:
        with sqlite3.connect(database, timeout=5.0) as connection:
            connection.execute(
                """
                create table if not exists document_tags (
                    doc_id text not null,
                    tag text not null,
                    normalized_tag text not null,
                    source text not null default 'zotero',
                    primary key (doc_id, normalized_tag, source)
                )
                """
            )
            connection.execute(
                "create index if not exists idx_document_tags_normalized on document_tags(normalized_tag)"
            )
            connection.execute("create index if not exists idx_document_tags_doc on document_tags(doc_id)")
            connection.execute("delete from document_tags where source = 'zotero'")
            connection.executemany(
                """
                insert into document_tags(doc_id, tag, normalized_tag, source)
                values (?, ?, ?, 'zotero')
                """,
                [
                    (doc_id, display, normalized)
                    for doc_id, values in sorted(tags_by_document.items())
                    for normalized, display in sorted(values.items())
                    if normalized and display
                ],
            )
            connection.commit()
    except sqlite3.Error as error:
        return {
            "status": "failed",
            "reason": f"{type(error).__name__}: {error}"[:300],
            "matched_items": matched_items,
            "documents": len(tags_by_document),
            "tags": sum(len(value) for value in tags_by_document.values()),
        }
    return {
        "status": "ready",
        "matched_items": matched_items,
        "documents": len(tags_by_document),
        "tags": sum(len(value) for value in tags_by_document.values()),
    }


def resolve_zotero_tag_scope(
    notebook: dict[str, Any],
    evidence_db: str | Path,
    scope: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a UI tag selection into document IDs for retrieval.

    This function never changes the default search. An empty or non-Zotero
    scope returns ``active=False``; an active scope with no mapped PDFs returns
    an empty document list so the UI can honestly show that the experiment has
    no searchable matches instead of silently falling back to the whole shelf.
    """

    requested = dict(scope or {})
    if str(requested.get("type", "")).strip() != "zotero-tag":
        return {"active": False, "type": str(requested.get("type", "") or "")}
    tags = _display_tags(requested.get("tags", []))
    match_mode = "all" if str(requested.get("match", "any")).strip().casefold() == "all" else "any"
    base: dict[str, Any] = {
        "active": bool(tags),
        "type": "zotero-tag",
        "tags": tags,
        "match": match_mode,
        "doc_ids": [],
        "matched_item_count": 0,
        "matched_document_count": 0,
        "unmatched_item_count": 0,
        "status": "inactive" if not tags else "empty",
    }
    if not tags:
        return base

    normalized_tags = {normalize_zotero_tag(tag) for tag in tags}
    zotero_items = _zotero_items(notebook)
    selected_items: list[dict[str, Any]] = []
    for item in zotero_items:
        if not isinstance(item, dict):
            continue
        item_tags = {normalize_zotero_tag(tag) for tag in zotero_item_tags(item)}
        has_scope = (
            normalized_tags.issubset(item_tags)
            if match_mode == "all"
            else bool(normalized_tags & item_tags)
        )
        if has_scope:
            selected_items.append(item)

    sources = _source_rows(evidence_db)
    indexes = _source_indexes(sources)
    doc_ids: list[str] = []
    matched_item_count = 0
    for item in selected_items:
        item_doc_ids = _matching_doc_ids_fast(item, indexes)
        if item_doc_ids:
            matched_item_count += 1
            doc_ids.extend(item_doc_ids)

    base.update(
        {
            "matched_item_count": len(selected_items),
            "matched_document_count": len(set(doc_ids)),
            "unmatched_item_count": max(0, len(selected_items) - matched_item_count),
            "doc_ids": list(dict.fromkeys(doc_ids)),
            "status": "applied" if doc_ids else "empty",
        }
    )
    return base


def infer_zotero_tag_scope(
    notebook: dict[str, Any],
    evidence_db: str | Path,
    query: str,
    *,
    max_tags: int = 5,
    min_documents_per_tag: int = 2,
    max_documents_per_tag: int = 30,
    max_scope_fraction: float = 0.75,
) -> dict[str, Any]:
    """Infer a safe tag-backed document scope from a knowledge question.

    The matcher profiles each tag with the titles of its mapped Zotero items.
    This lets a question such as ``plant diversity and ecosystem stability``
    reach tags like ``functional diversity`` even when the exact tag label is
    not present in the question.  It is deliberately conservative: tags with
    no mapped full text, very broad tag groups, and empty/ambiguous matches
    fall back to ordinary full-library retrieval.
    """

    clean_query = str(query or "").strip()
    base: dict[str, Any] = {
        "active": False,
        "type": "zotero-tag",
        "mode": "auto",
        "query": clean_query,
        "tags": [],
        "match": "any",
        "doc_ids": [],
        "matched_item_count": 0,
        "matched_document_count": 0,
        "unmatched_item_count": 0,
        "status": "no-query" if not clean_query else "no-match",
    }
    if not clean_query:
        return base

    sources = _source_rows(evidence_db)
    if not sources:
        base["status"] = "no-index"
        return base
    indexes = _source_indexes(sources)
    tag_profiles: dict[str, dict[str, Any]] = {}
    for item in _zotero_items(notebook):
        doc_ids = _matching_doc_ids_fast(item, indexes)
        if not doc_ids:
            continue
        title_terms = _auto_tag_terms(item.get("title", ""))
        for display_tag in zotero_item_tags(item):
            normalized_tag = normalize_zotero_tag(display_tag)
            if not normalized_tag:
                continue
            record = tag_profiles.setdefault(
                normalized_tag,
                {"display": display_tag, "doc_ids": set(), "item_keys": set(), "titles": []},
            )
            record["doc_ids"].update(doc_ids)
            record["item_keys"].add(str(item.get("key", "") or ""))
            if title_terms:
                record["titles"].append(title_terms)
    if not tag_profiles:
        base["status"] = "no-tags"
        return base

    query_terms = _auto_tag_terms(clean_query)
    compact_query = _compact_text(clean_query)
    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    for normalized_tag, record in tag_profiles.items():
        doc_ids = set(record["doc_ids"])
        if normalized_tag.startswith("/") or not (
            min_documents_per_tag <= len(doc_ids) <= max_documents_per_tag
        ):
            continue
        exact_label = 1.0 if _compact_text(normalized_tag) in compact_query else 0.0
        profile_overlap = 0.0
        for title_terms in list(record["titles"]):
            if query_terms and title_terms:
                profile_overlap = max(profile_overlap, len(query_terms & title_terms) / len(query_terms))
        score = exact_label * 3.0 + profile_overlap / math.sqrt(max(1, len(doc_ids)))
        if score >= 0.1:
            candidates.append((score, profile_overlap, normalized_tag, record))
    candidates.sort(key=lambda item: (-item[0], -item[1], len(item[3]["doc_ids"]), item[2]))
    chosen = candidates[: max(1, int(max_tags))]
    scope_doc_ids: set[str] = set()
    selected_tags: list[str] = []
    selected_item_keys: set[str] = set()
    candidate_details: list[dict[str, Any]] = []
    for score, profile_overlap, normalized_tag, record in chosen:
        scope_doc_ids.update(record["doc_ids"])
        selected_item_keys.update(record["item_keys"])
        selected_tags.append(str(record["display"]))
        candidate_details.append(
            {
                "tag": str(record["display"]),
                "score": round(float(score), 6),
                "profile_overlap": round(float(profile_overlap), 6),
                "document_count": len(record["doc_ids"]),
            }
        )
    if not scope_doc_ids:
        base["status"] = "no-mapped-documents"
        base["candidate_tags"] = candidate_details
        return base
    if len(scope_doc_ids) > max(1, int(len(sources) * max_scope_fraction)):
        base["status"] = "too-broad"
        base["candidate_tags"] = candidate_details
        return base
    base.update(
        {
            "active": True,
            "tags": selected_tags,
            "doc_ids": sorted(scope_doc_ids),
            "matched_item_count": len(selected_item_keys),
            "matched_document_count": len(scope_doc_ids),
            "candidate_tags": candidate_details,
            "status": "applied",
        }
    )
    return base
