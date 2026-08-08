"""Native Zotero integration for ScanSci.

The adapter deliberately owns its protocol surface instead of depending on a
Codex installation.  Reads prefer Zotero's loopback Web API when available and
fall back to the local SQLite database and full-text cache in read-only mode.
Connector writes are available only through an explicit confirmation flag.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib import error, parse, request
import uuid

from .library_manager import discover_local_zotero


ZOTERO_BASE_URL = "http://127.0.0.1:23119"
ZOTERO_USER_PATH = "/api/users/0"
_API_HEADERS = {"Zotero-API-Version": "3"}
_CONNECTOR_HEADERS = {"X-Zotero-Connector-API-Version": "3"}
_BROAD_QUERY_MARKERS = (
    "核心主题",
    "主要主题",
    "主题总结",
    "总结",
    "概览",
    "overview",
    "core theme",
    "main theme",
)
_BROAD_QUERY_TOKENS = {"*", "all", "inventory", "library", "overview"}


def _is_broad_query(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    return (
        not normalized
        or normalized in _BROAD_QUERY_TOKENS
        or any(marker in normalized for marker in _BROAD_QUERY_MARKERS)
    )


class ZoteroIntegrationError(RuntimeError):
    """A user-facing Zotero protocol or availability failure."""


def zotero_status(
    *,
    timeout: float = 1.5,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return truthful local-database, API, and connector readiness."""

    try:
        discovered = discover_local_zotero(data_dir)
    except FileNotFoundError:
        discovered = {}
    database_error = ""
    database_readable = False
    if discovered:
        try:
            database = Path(discovered["database_path"])
            connection = sqlite3.connect(
                f"{database.as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=max(0.2, min(2.0, float(timeout))),
            )
            try:
                connection.execute("SELECT 1").fetchone()
            finally:
                connection.close()
            database_readable = True
        except (OSError, sqlite3.Error, ValueError) as error:
            database_error = f"{type(error).__name__}: {error}"[:300]
    api = _http("/api/", timeout=timeout)
    connector = _http("/connector/ping", timeout=timeout)
    explicit_data_dir = bool(str(data_dir or "").strip() or str(os.environ.get("ZOTERO_DATA_DIR", "")).strip())
    api_running = bool(api[0])
    return {
        "installed": bool(discovered),
        "data_dir": discovered.get("data_dir", ""),
        "database_path": discovered.get("database_path", ""),
        "database_readable": database_readable,
        "database_error": database_error,
        "api_running": api_running,
        "api_status": api[1],
        "connector_running": connector[0],
        "connector_status": connector[1],
        "read_mode": "local-database" if database_readable and (explicit_data_dir or not api_running) else (
            "local-api" if api_running else "unavailable"
        ),
    }


def search_zotero_library(
    query: str,
    *,
    limit: int = 12,
    collection_key: str = "",
    include_fulltext: bool = True,
) -> dict[str, Any]:
    """Search real Zotero metadata and cached attachment text without writes."""

    readiness = zotero_status(timeout=0.6)
    if readiness.get("api_running") and not str(os.environ.get("ZOTERO_DATA_DIR", "")).strip():
        return _search_zotero_api(
            query,
            limit=limit,
            collection_key=collection_key,
            include_fulltext=include_fulltext,
        )
    discovered = discover_local_zotero()
    data_dir = Path(discovered["data_dir"])
    database = Path(discovered["database_path"])
    bounded_limit = max(1, min(50, int(limit)))
    normalized_query = str(query or "").strip()
    broad = _is_broad_query(normalized_query)
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        counts = _library_counts(connection)
        collections = _top_collections(connection, limit=16)
        item_ids = _candidate_item_ids(
            connection,
            query=normalized_query,
            limit=bounded_limit,
            collection_key=collection_key,
            broad=broad,
        )
        items = _item_details(connection, item_ids=item_ids, data_dir=data_dir)
        if include_fulltext:
            for item in items:
                attachment = next((row for row in item["attachments"] if row.get("exists")), None)
                if not attachment:
                    continue
                excerpt = _cached_fulltext_excerpt(
                    data_dir,
                    str(attachment.get("attachment_key", "")),
                    normalized_query,
                )
                if excerpt:
                    item["fulltext_excerpt"] = excerpt
                    item["evidence_kind"] = "zotero-indexed-fulltext"
        return {
            "ok": True,
            "tool": "zotero_search",
            "query": normalized_query,
            "mode": "inventory" if broad else "search",
            "connection": "local-database",
            "read_only": True,
            "library": {
                **counts,
                "collection_count": len(_all_collection_keys(connection)),
                "data_dir": str(data_dir),
            },
            "collections": collections,
            "count": len(items),
            "items": items,
        }
    finally:
        connection.close()


def _search_zotero_api(
    query: str,
    *,
    limit: int,
    collection_key: str,
    include_fulltext: bool,
) -> dict[str, Any]:
    bounded_limit = max(1, min(50, int(limit)))
    normalized_query = str(query or "").strip()
    broad = _is_broad_query(normalized_query)
    base_path = (
        f"{ZOTERO_USER_PATH}/collections/{parse.quote(collection_key)}/items/top"
        if collection_key
        else f"{ZOTERO_USER_PATH}/items/top"
    )
    params: dict[str, Any] = {
        "limit": bounded_limit,
        "sort": "dateModified",
        "direction": "desc",
    }
    if normalized_query and not broad:
        params["q"] = normalized_query
    ok, status, body, item_headers = _http_json(
        f"{base_path}?{parse.urlencode(params)}",
        timeout=6,
    )
    if not ok or not isinstance(body, list):
        raise ZoteroIntegrationError(f"Zotero 本机 API 检索失败（HTTP {status or '无响应'}）")

    collections_ok, _collections_status, collection_body, _collection_headers = _http_json(
        f"{ZOTERO_USER_PATH}/collections?{parse.urlencode({'limit': 100})}",
        timeout=6,
    )
    collections = []
    if collections_ok and isinstance(collection_body, list):
        for row in collection_body:
            data = dict(row.get("data", {}) or {}) if isinstance(row, dict) else {}
            meta = dict(row.get("meta", {}) or {}) if isinstance(row, dict) else {}
            collections.append({
                "key": str(row.get("key", data.get("key", ""))),
                "name": str(data.get("name", "")),
                "parent": str(data.get("parentCollection", "")),
                "item_count": int(meta.get("numItems", 0) or 0),
            })
        collections.sort(key=lambda row: (-int(row["item_count"]), str(row["name"]).lower()))

    items = []
    for row in body:
        if not isinstance(row, dict):
            continue
        data = dict(row.get("data", {}) or {})
        item_key = str(row.get("key", data.get("key", "")))
        title = str(data.get("title") or data.get("caseName") or data.get("nameOfAct") or "").strip()
        if not item_key or not title:
            continue
        creators = []
        for creator in list(data.get("creators", []) or []):
            if not isinstance(creator, dict):
                continue
            name = str(creator.get("name", "")).strip() or " ".join(
                part for part in [str(creator.get("firstName", "")).strip(), str(creator.get("lastName", "")).strip()] if part
            )
            if name:
                creators.append(name)
        tags: list[str] = []
        for raw_tag in list(data.get("tags", []) or []):
            tag = str(raw_tag.get("tag", "") if isinstance(raw_tag, dict) else raw_tag).strip()
            if tag and tag not in tags:
                tags.append(tag)
        collection_keys = [str(key) for key in list(data.get("collections", []) or []) if key]
        collection_map = {str(collection["key"]): str(collection["name"]) for collection in collections}
        attachments = _api_pdf_children(item_key, include_fulltext=include_fulltext, query=normalized_query)
        date = str(data.get("date", ""))
        year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", date)
        item = {
            "item_key": item_key,
            "item_type": str(data.get("itemType", "")),
            "title": title,
            "creators": creators[:8],
            "year": year_match.group(1) if year_match else "",
            "date": date,
            "doi": str(data.get("DOI", "")),
            "publication": str(data.get("publicationTitle") or data.get("bookTitle") or data.get("websiteTitle") or ""),
            "abstract": str(data.get("abstractNote", ""))[:1_200],
            "url": str(data.get("url", "")),
            "collections": [{"key": key, "name": collection_map.get(key, key)} for key in collection_keys],
            "tags": tags,
            "attachments": [{key: value for key, value in attachment.items() if key != "fulltext_excerpt"} for attachment in attachments],
            "evidence_kind": "zotero-metadata",
        }
        excerpt = next((str(attachment.get("fulltext_excerpt", "")) for attachment in attachments if attachment.get("fulltext_excerpt")), "")
        if excerpt:
            item["fulltext_excerpt"] = excerpt
            item["evidence_kind"] = "zotero-indexed-fulltext"
        items.append(item)
    total_header = item_headers.get("Total-Results", "")
    return {
        "ok": True,
        "tool": "zotero_search",
        "query": normalized_query,
        "mode": "inventory" if broad else "search",
        "connection": "local-api",
        "read_only": True,
        "library": {
            "item_count": int(total_header) if str(total_header).isdigit() else len(items),
            "pdf_count": sum(bool(item["attachments"]) for item in items),
            "collection_count": len(collections),
            "data_dir": discover_local_zotero().get("data_dir", ""),
        },
        "collections": collections[:16],
        "count": len(items),
        "items": items,
    }


def _api_pdf_children(item_key: str, *, include_fulltext: bool, query: str) -> list[dict[str, Any]]:
    ok, _status, body, _headers = _http_json(
        f"{ZOTERO_USER_PATH}/items/{parse.quote(item_key)}/children",
        timeout=4,
    )
    if not ok or not isinstance(body, list):
        return []
    attachments = []
    for row in body:
        data = dict(row.get("data", {}) or {}) if isinstance(row, dict) else {}
        if str(data.get("itemType", "")) != "attachment" or str(data.get("contentType", "")).lower() != "application/pdf":
            continue
        key = str(row.get("key", data.get("key", "")))
        attachment: dict[str, Any] = {"attachment_key": key, "exists": True, "link_mode": data.get("linkMode")}
        if include_fulltext and key:
            fulltext_ok, _fulltext_status, fulltext_body, _fulltext_headers = _http_json(
                f"{ZOTERO_USER_PATH}/items/{parse.quote(key)}/fulltext",
                timeout=4,
            )
            if fulltext_ok and isinstance(fulltext_body, dict):
                text = re.sub(r"\s+", " ", str(fulltext_body.get("content", ""))).strip()
                if text:
                    terms = _query_terms(query)
                    lowered = text.lower()
                    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
                    start = max(0, min(positions) - 300) if positions else 0
                    attachment["fulltext_excerpt"] = text[start : start + 1_200]
        attachments.append(attachment)
    return attachments


def zotero_fulltext(attachment_key: str, *, max_chars: int = 40_000) -> dict[str, Any]:
    """Read Zotero-indexed attachment text through API or its local cache."""

    key = _safe_key(attachment_key)
    ok, status, body, _headers = _http_json(f"{ZOTERO_USER_PATH}/items/{key}/fulltext", timeout=4)
    if ok and isinstance(body, dict):
        content = str(body.get("content", ""))[: max(1, int(max_chars))]
        return {
            "ok": True,
            "attachment_key": key,
            "connection": "local-api",
            "content": content,
            "chars": len(content),
            "indexed_pages": body.get("indexedPages"),
            "total_pages": body.get("totalPages"),
        }

    data_dir = Path(discover_local_zotero()["data_dir"])
    cache_path = data_dir / "storage" / key / ".zotero-ft-cache"
    if not cache_path.is_file():
        raise ZoteroIntegrationError(
            f"Zotero 没有为附件 {key} 建立可读全文缓存（本机 API 状态：{status or '未启动'}）"
        )
    content = cache_path.read_text(encoding="utf-8", errors="replace")[: max(1, int(max_chars))]
    return {
        "ok": True,
        "attachment_key": key,
        "connection": "local-fulltext-cache",
        "content": content,
        "chars": len(content),
        "cache_path": str(cache_path),
    }


def zotero_file_url(attachment_key: str) -> dict[str, Any]:
    """Resolve a Zotero attachment to a local file path or API file URL."""

    key = _safe_key(attachment_key)
    ok, _status, body, _headers = _http_json(f"{ZOTERO_USER_PATH}/items/{key}/file/view/url", timeout=3)
    if ok:
        return {"ok": True, "attachment_key": key, "connection": "local-api", "url": body}

    discovered = discover_local_zotero()
    database = Path(discovered["database_path"])
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        row = connection.execute(
            """
            SELECT ia.path
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE i.key = ?
            """,
            (key,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        raise ZoteroIntegrationError(f"找不到 Zotero 附件：{key}")
    raw_path = str(row[0] or "")
    if raw_path.startswith("storage:"):
        path = Path(discovered["storage_path"]) / key / raw_path.removeprefix("storage:")
    else:
        path = Path(raw_path).expanduser()
    return {
        "ok": path.is_file(),
        "attachment_key": key,
        "connection": "local-database",
        "path": str(path.resolve()),
        "exists": path.is_file(),
    }


def zotero_export_bibtex(*, item_key: str = "", limit: int = 100) -> dict[str, Any]:
    """Export BibTeX through Zotero's canonical local API formatter."""

    key = _safe_key(item_key) if item_key else ""
    params: dict[str, Any] = {"format": "bibtex", "limit": max(1, min(100, int(limit)))}
    if key:
        params["itemKey"] = key
    path = f"{ZOTERO_USER_PATH}/items/top?{parse.urlencode(params)}"
    ok, status, text, _headers = _http(path, timeout=8)
    if not ok:
        raise ZoteroIntegrationError(
            "BibTeX 导出需要 Zotero 本机 API。请启动 Zotero 后重试"
            + (f"（HTTP {status}）" if status else "")
        )
    return {
        "ok": True,
        "connection": "local-api",
        "item_key": key,
        "bibtex": text,
        "entry_count": len(re.findall(r"@\w+\s*\{", text)),
    }


def zotero_formatted_citations(*, style: str = "apa", limit: int = 50) -> dict[str, Any]:
    """Return Zotero-rendered citations for the current library."""

    params = parse.urlencode({"include": "data,citation", "style": style, "limit": max(1, min(100, int(limit)))})
    ok, status, body, _headers = _http_json(f"{ZOTERO_USER_PATH}/items/top?{params}", timeout=8)
    if not ok or not isinstance(body, list):
        raise ZoteroIntegrationError(
            "格式化引用需要正在运行的 Zotero 本机 API"
            + (f"（HTTP {status}）" if status else "")
        )
    rows = []
    for item in body:
        data = dict(item.get("data", {}) or {}) if isinstance(item, dict) else {}
        rows.append({
            "item_key": str(item.get("key", data.get("key", ""))),
            "title": str(data.get("title", "")),
            "citation": item.get("citation"),
        })
    return {"ok": True, "connection": "local-api", "style": style, "count": len(rows), "items": rows}


def zotero_import_records(text: str, *, record_format: str, confirmed: bool) -> dict[str, Any]:
    """Import BibTeX/RIS through Zotero Connector after explicit confirmation."""

    if not confirmed:
        raise ZoteroIntegrationError("写入 Zotero 需要用户明确确认")
    kind = str(record_format or "").strip().lower()
    if kind not in {"bibtex", "ris"}:
        raise ValueError("record_format must be 'bibtex' or 'ris'")
    payload = str(text or "").strip()
    if not payload:
        raise ValueError("导入内容不能为空")
    session = f"scansci-{uuid.uuid4().hex}"
    path = f"/connector/import?{parse.urlencode({'session': session})}"
    ok, status, body, _headers = _http(
        path,
        method="POST",
        data=payload.encode("utf-8"),
        headers={**_CONNECTOR_HEADERS, "Content-Type": "text/plain"},
        timeout=10,
    )
    if not ok:
        raise ZoteroIntegrationError(
            "无法写入 Zotero；请启动 Zotero 并确认 Connector 服务可用"
            + (f"（HTTP {status}）" if status else "")
        )
    return {"ok": True, "connection": "connector", "session": session, "response": body[:2_000]}


def _library_counts(connection: sqlite3.Connection) -> dict[str, int]:
    item_count = int(connection.execute(
        """
        SELECT COUNT(*) FROM items i
        JOIN itemTypes t ON t.itemTypeID=i.itemTypeID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE d.itemID IS NULL AND t.typeName NOT IN ('attachment','note','annotation')
        """
    ).fetchone()[0] or 0)
    pdf_count = int(connection.execute(
        "SELECT COUNT(*) FROM itemAttachments WHERE lower(coalesce(contentType,''))='application/pdf'"
    ).fetchone()[0] or 0)
    return {"item_count": item_count, "pdf_count": pdf_count}


def _all_collection_keys(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute("SELECT key FROM collections WHERE key IS NOT NULL")]


def _top_collections(connection: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT c.key, c.collectionName, parent.key, COUNT(DISTINCT ci.itemID) AS itemCount
        FROM collections c
        LEFT JOIN collections parent ON parent.collectionID=c.parentCollectionID
        LEFT JOIN collectionItems ci ON ci.collectionID=c.collectionID
        GROUP BY c.collectionID, c.key, c.collectionName, parent.key
        ORDER BY itemCount DESC, lower(c.collectionName)
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [
        {"key": str(row[0] or ""), "name": str(row[1] or ""), "parent": str(row[2] or ""), "item_count": int(row[3] or 0)}
        for row in rows
    ]


def _candidate_item_ids(
    connection: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    collection_key: str,
    broad: bool,
) -> list[int]:
    clauses = ["d.itemID IS NULL", "t.typeName NOT IN ('attachment','note','annotation')"]
    params: list[Any] = []
    if collection_key:
        clauses.append(
            "EXISTS (SELECT 1 FROM collectionItems ci JOIN collections c ON c.collectionID=ci.collectionID "
            "WHERE ci.itemID=i.itemID AND c.key=?)"
        )
        params.append(collection_key)
    terms = _query_terms(query)
    if terms and not broad:
        matches = []
        for term in terms[:6]:
            matches.append(
                "(EXISTS (SELECT 1 FROM itemData id JOIN itemDataValues v ON v.valueID=id.valueID "
                "WHERE id.itemID=i.itemID AND lower(v.value) LIKE ?) OR "
                "EXISTS (SELECT 1 FROM itemCreators ic JOIN creators cr ON cr.creatorID=ic.creatorID "
                "WHERE ic.itemID=i.itemID AND lower(coalesce(cr.firstName,'') || ' ' || coalesce(cr.lastName,'')) LIKE ?))"
            )
            params.extend([f"%{term}%", f"%{term}%"])
        clauses.append("(" + " OR ".join(matches) + ")")
    params.append(max(1, int(limit)))
    rows = connection.execute(
        f"""
        SELECT i.itemID
        FROM items i
        JOIN itemTypes t ON t.itemTypeID=i.itemTypeID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE {' AND '.join(clauses)}
        ORDER BY i.dateModified DESC, i.itemID DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [int(row[0]) for row in rows]


def _item_details(connection: sqlite3.Connection, *, item_ids: list[int], data_dir: Path) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    placeholders = ",".join("?" for _ in item_ids)
    item_rows = connection.execute(
        f"""
        SELECT i.itemID, i.key, t.typeName, i.dateModified
        FROM items i JOIN itemTypes t ON t.itemTypeID=i.itemTypeID
        WHERE i.itemID IN ({placeholders})
        """,
        item_ids,
    ).fetchall()
    base = {int(row[0]): row for row in item_rows}
    fields: dict[int, dict[str, str]] = {item_id: {} for item_id in item_ids}
    creators: dict[int, list[str]] = {item_id: [] for item_id in item_ids}
    collections: dict[int, list[dict[str, str]]] = {item_id: [] for item_id in item_ids}
    tags: dict[int, list[str]] = {item_id: [] for item_id in item_ids}
    attachments: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids}
    for row in connection.execute(
        f"""
        SELECT id.itemID, f.fieldName, v.value
        FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
        JOIN itemDataValues v ON v.valueID=id.valueID
        WHERE id.itemID IN ({placeholders})
        """,
        item_ids,
    ):
        fields[int(row[0])][str(row[1])] = str(row[2] or "")
    for row in connection.execute(
        f"""
        SELECT ic.itemID, cr.firstName, cr.lastName
        FROM itemCreators ic JOIN creators cr ON cr.creatorID=ic.creatorID
        WHERE ic.itemID IN ({placeholders}) ORDER BY ic.itemID, ic.orderIndex
        """,
        item_ids,
    ):
        name = " ".join(part for part in [str(row[1] or "").strip(), str(row[2] or "").strip()] if part)
        if name and len(creators[int(row[0])]) < 8:
            creators[int(row[0])].append(name)
    for row in connection.execute(
        f"""
        SELECT ci.itemID, c.key, c.collectionName
        FROM collectionItems ci JOIN collections c ON c.collectionID=ci.collectionID
        WHERE ci.itemID IN ({placeholders})
        """,
        item_ids,
    ):
        collections[int(row[0])].append({"key": str(row[1] or ""), "name": str(row[2] or "")})
    try:
        for row in connection.execute(
            f"""
            SELECT it.itemID, t.name
            FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            WHERE it.itemID IN ({placeholders})
            ORDER BY it.itemID, lower(t.name), t.tagID
            """,
            item_ids,
        ):
            tag = str(row[1] or "").strip()
            if tag and tag not in tags[int(row[0])]:
                tags[int(row[0])].append(tag)
    except sqlite3.Error:
        pass
    for row in connection.execute(
        f"""
        SELECT ia.parentItemID, child.key, ia.path, ia.linkMode
        FROM itemAttachments ia JOIN items child ON child.itemID=ia.itemID
        WHERE ia.parentItemID IN ({placeholders})
          AND lower(coalesce(ia.contentType,''))='application/pdf'
        """,
        item_ids,
    ):
        raw_path = str(row[2] or "")
        key = str(row[1] or "")
        path = data_dir / "storage" / key / raw_path.removeprefix("storage:") if raw_path.startswith("storage:") else Path(raw_path).expanduser()
        attachments[int(row[0])].append({
            "attachment_key": key,
            "path": str(path.resolve()),
            "exists": path.is_file(),
            "link_mode": int(row[3] or 0),
        })
    output = []
    for item_id in item_ids:
        row = base.get(item_id)
        if row is None:
            continue
        values = fields[item_id]
        title = str(values.get("title") or values.get("caseName") or values.get("nameOfAct") or "").strip()
        if not title:
            continue
        date = str(values.get("date", ""))
        year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", date)
        output.append({
            "item_key": str(row[1] or ""),
            "item_type": str(row[2] or ""),
            "title": title,
            "creators": creators[item_id],
            "year": year_match.group(1) if year_match else "",
            "date": date,
            "doi": str(values.get("DOI", "")),
            "publication": str(values.get("publicationTitle") or values.get("bookTitle") or values.get("websiteTitle") or ""),
            "abstract": str(values.get("abstractNote", ""))[:1_200],
            "url": str(values.get("url", "")),
            "collections": collections[item_id],
            "tags": tags[item_id],
            "attachments": attachments[item_id],
            "evidence_kind": "zotero-metadata",
        })
    return output


def _cached_fulltext_excerpt(data_dir: Path, attachment_key: str, query: str, *, width: int = 1_200) -> str:
    if not attachment_key:
        return ""
    cache = data_dir / "storage" / attachment_key / ".zotero-ft-cache"
    if not cache.is_file():
        return ""
    text = re.sub(r"\s+", " ", cache.read_text(encoding="utf-8", errors="replace")).strip()
    if not text:
        return ""
    lowered = text.lower()
    positions = [lowered.find(term) for term in _query_terms(query) if lowered.find(term) >= 0]
    start = max(0, min(positions) - width // 4) if positions else 0
    return text[start : start + width]


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[0-9A-Za-z][0-9A-Za-z._-]{2,}|[\u4e00-\u9fff]{2,}", str(query or "").lower())
    stop = {"zotero", "文献库", "中的", "进行", "请问", "帮我", "总结", "核心主题", "主要主题"}
    return list(dict.fromkeys(term for term in terms if term not in stop))


def _safe_key(value: str) -> str:
    key = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{8}", key):
        raise ValueError("Zotero item/attachment key must contain exactly 8 letters or digits")
    return key


def _http_json(
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[bool, int | None, Any, dict[str, str]]:
    ok, status, text, response_headers = _http(path, method=method, data=data, headers=headers, timeout=timeout)
    try:
        body: Any = json.loads(text) if text else None
    except json.JSONDecodeError:
        body = text
    return ok, status, body, response_headers


def _http(
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[bool, int | None, str, dict[str, str]]:
    request_headers = dict(headers or {})
    if path.startswith("/api"):
        request_headers.update({key: value for key, value in _API_HEADERS.items() if key not in request_headers})
    req = request.Request(ZOTERO_BASE_URL + path, data=data, method=method, headers=request_headers)
    try:
        # Loopback traffic must never inherit a corporate/system HTTP proxy.
        # A proxy can make a healthy Zotero server look like a timeout.
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as response:
            return True, int(response.status), response.read().decode("utf-8", errors="replace"), dict(response.headers.items())
    except error.HTTPError as exc:
        return False, int(exc.code), exc.read().decode("utf-8", errors="replace"), dict(exc.headers.items())
    except (OSError, ValueError):
        return False, None, "", {}
