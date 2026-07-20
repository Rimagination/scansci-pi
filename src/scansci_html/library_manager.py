"""Manage user-selected local literature folders for the desktop workbench."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from .evidence_store import index_evidence_library, index_markdown_library
from .ingestion import SUPPORTED_INGESTION_SUFFIXES, ingest_sources, ingestion_source_text
from .workspace import (
    load_workspace_summary,
    set_notebook_root_path,
    sync_sources_from_evidence_store,
    update_notebook_metadata,
)


_MAX_LIBRARY_DOCUMENTS = 2_000
_HTML_SUFFIXES = {".html"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_SUPPORTED_SUFFIXES = _HTML_SUFFIXES | _MARKDOWN_SUFFIXES
_IMPORTABLE_SUFFIXES = set(SUPPORTED_INGESTION_SUFFIXES)
_LIBRARY_IMPORTABLE_SUFFIXES = {
    ".pdf", ".docx", ".pptx", ".html", ".htm", ".md", ".markdown", ".txt", ".rtf", ".epub",
}


def notebook_evidence_db(evidence_db: str | Path, notebook_id: str) -> Path:
    """Return the isolated evidence index owned by one knowledge library."""

    base = Path(evidence_db).resolve()
    root = base.parent / f"{base.stem}.libraries"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_safe_folder_name(notebook_id)}.sqlite"


def import_library_folder(
    workspace: str | Path,
    evidence_db: str | Path,
    *,
    notebook_id: str,
    folder_path: str | Path,
    library_kind: str = "folder",
) -> dict[str, Any]:
    """Index a selected folder and switch the notebook only after validation."""

    folder = _resolved_directory(folder_path)
    html_files = _candidate_files(folder, _HTML_SUFFIXES)
    markdown_files = _candidate_files(folder, _MARKDOWN_SUFFIXES)
    candidates = html_files or markdown_files
    importable_files = _candidate_files(folder, _LIBRARY_IMPORTABLE_SUFFIXES)
    requires_conversion = bool(importable_files) and (
        not candidates
        or len(importable_files) > len(html_files) + len(markdown_files)
        or bool(html_files and markdown_files)
    )
    if requires_conversion:
        result = import_library_files(
            workspace,
            evidence_db,
            notebook_id=notebook_id,
            file_paths=importable_files,
        )
        update_notebook_metadata(
            workspace,
            notebook_id=notebook_id,
            metadata={"imported_from_folder": str(folder), "library_kind": _library_kind(library_kind)},
        )
        result["workspace"] = load_workspace_summary(workspace)
        result["notebook"] = result["workspace"]["notebooks"][0]
        return result
    if not candidates:
        pdf_count = sum(1 for path in folder.rglob("*.pdf") if path.is_file())
        if pdf_count:
            raise ValueError(
                "所选文件夹只有 PDF。请先用 scansci-html 转换为 HTML，或通过“添加论文文件”导入已转换文献。"
            )
        raise ValueError("所选文件夹没有可索引的 HTML 或 Markdown 文献")
    if len(candidates) > _MAX_LIBRARY_DOCUMENTS:
        raise ValueError(f"资料文件过多（{len(candidates)}），单次最多 {_MAX_LIBRARY_DOCUMENTS} 篇")

    target_db = notebook_evidence_db(evidence_db, notebook_id)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    temporary_db = target_db.with_name(f".{target_db.stem}.{uuid4().hex}.importing.sqlite")
    source_format = "html" if html_files else "markdown"
    try:
        if source_format == "html":
            indexed = index_evidence_library(
                folder,
                db_path=temporary_db,
                inject_evidence_html=True,
                min_sentence_length=10,
            )
        else:
            indexed = index_markdown_library(
                folder,
                db_path=temporary_db,
                min_sentence_length=10,
            )
        if int(indexed.get("documents", 0) or 0) <= 0:
            raise ValueError("所选文件夹中的文献没有可提取正文")
        _replace_evidence_database(temporary_db, target_db)
        indexed["db_path"] = str(target_db)
    finally:
        if temporary_db.exists():
            temporary_db.unlink()

    normalized_kind = _library_kind(library_kind)
    set_notebook_root_path(
        workspace,
        notebook_id=notebook_id,
        root_path=folder,
        metadata={"library_kind": normalized_kind, "library_root": str(folder)},
    )
    synced = sync_sources_from_evidence_store(
        workspace,
        target_db,
        notebook_id=notebook_id,
        metadata={"library_root": str(folder), "source_format": source_format},
        replace=True,
    )
    summary = load_workspace_summary(workspace, notebook_id=notebook_id)
    notebook = next(iter(list(summary.get("notebooks", []) or [])), {})
    return {
        "ok": True,
        "folder_path": str(folder),
        "source_format": source_format,
        "library_kind": normalized_kind,
        "indexed": indexed,
        "synced": synced,
        "notebook": notebook,
        "workspace": load_workspace_summary(workspace),
        "ignored_markdown_files": len(markdown_files) if html_files else 0,
    }


def import_library_files(
    workspace: str | Path,
    evidence_db: str | Path,
    *,
    notebook_id: str,
    file_paths: Iterable[str | Path],
) -> dict[str, Any]:
    """Copy selected source documents into a managed notebook folder and index them."""

    supplied = [_resolved_file(path) for path in file_paths]
    supported = [path for path in supplied if path.suffix.lower() in _IMPORTABLE_SUFFIXES]
    if not supported:
        raise ValueError("请选择 HTML 或 Markdown 文献文件")
    if len(supported) > _MAX_LIBRARY_DOCUMENTS:
        raise ValueError(f"单次最多添加 {_MAX_LIBRARY_DOCUMENTS} 篇文献")

    workspace_path = Path(workspace).resolve()
    managed = (
        workspace_path.parent
        / ".scansci-library"
        / _safe_folder_name(notebook_id)
        / f"generation-{uuid4().hex}"
    )
    managed.mkdir(parents=True, exist_ok=True)
    legacy_sources: list[Path] = []
    for existing in _existing_source_paths(workspace_path, notebook_id=notebook_id):
        if not existing.is_file():
            continue
        if existing.suffix.lower() in _MARKDOWN_SUFFIXES:
            shutil.copy2(existing, _unique_path(managed, _safe_folder_name(existing.stem), existing.suffix or ".md"))
        else:
            legacy_sources.append(existing)

    jobs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    added = 0
    for original, is_new in [*((path, False) for path in legacy_sources), *((path, True) for path in supported)]:
        try:
            job = ingest_sources(
                workspace_path,
                [{"name": original.name, "path": str(original)}],
                max_files=1,
                max_total_bytes=200 * 1024 * 1024,
                max_file_bytes=200 * 1024 * 1024,
            )
            source = dict(list(job.get("sources", []) or [])[0])
            text = ingestion_source_text(workspace_path, str(job["job_id"]), str(source["source_id"]))
            stem = _safe_folder_name(original.stem)
            target = _unique_path(managed, stem, ".md")
            metadata = {
                "title": original.stem,
                "source_file": original.name,
                "source_url": str(original),
                "source_suffix": original.suffix.lower(),
                "parser": str(source.get("parser", "")),
                "ingestion_job": str(job["job_id"]),
            }
            target.write_text(_markdown_document(metadata, text), encoding="utf-8")
            jobs.append(job)
            if is_new:
                added += 1
        except Exception as error:  # one scanned or corrupt PDF must not discard the whole library
            failures.append({"name": original.name, "error": str(error)[:300]})

    if added <= 0 and not any(managed.iterdir()):
        detail = failures[0]["error"] if failures else "没有可提取的文献"
        raise ValueError(f"知识库中没有成功解析的文件：{detail}")
    result = import_library_folder(
        workspace_path,
        evidence_db,
        notebook_id=notebook_id,
        folder_path=managed,
    )
    result["added_files"] = added
    result["skipped_files"] = failures
    result["managed"] = True
    result["ingestion"] = {
        "jobs": jobs,
        "summary": {
            "requested": len(supported),
            "completed": added,
            "skipped": len(failures),
            "characters": sum(int(dict(job.get("summary", {})).get("characters", 0) or 0) for job in jobs),
            "pages": sum(int(dict(job.get("summary", {})).get("pages", 0) or 0) for job in jobs),
        },
    }
    return result


def register_zotero_library(
    workspace: str | Path,
    *,
    notebook_id: str,
    folder_path: str | Path,
) -> dict[str, Any]:
    """Remember a local Zotero PDF store as a read-only literature shelf.

    The evidence engine only indexes extractable HTML and Markdown today, so
    this deliberately does not pretend that raw PDFs have been parsed.  The
    connection is still useful: users see the real local literature shelf and
    can enable document processing before importing searchable full text.
    """

    folder = _resolved_directory(folder_path)
    pdf_files = sorted(path for path in folder.rglob("*.pdf") if path.is_file())
    if not pdf_files:
        raise ValueError("所选 Zotero 文件夹没有找到 PDF 文献")
    preview_titles = [path.stem.replace("_", " ").strip() for path in pdf_files[:18]]
    zotero = {
        "path": str(folder),
        "pdf_count": len(pdf_files),
        "sample_titles": preview_titles,
    }
    update_notebook_metadata(workspace, notebook_id=notebook_id, metadata={"zotero": zotero})
    summary = load_workspace_summary(workspace, notebook_id=notebook_id)
    notebook = next(iter(list(summary.get("notebooks", []) or [])), {})
    return {
        "ok": True,
        "zotero": zotero,
        "notebook": notebook,
        "workspace": load_workspace_summary(workspace),
    }


def connect_local_zotero(
    workspace: str | Path,
    *,
    notebook_id: str,
    client: Any | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    """Read bibliographic metadata from Zotero 7's loopback API.

    No Zotero cloud key is requested or stored.  The user remains in control of
    the local API through Zotero's "Allow other applications" preference.
    """

    if client is None:
        try:
            from pyzotero import zotero

            client = zotero.Zotero("0", "user", local=True)
        except Exception as error:  # optional connector boundary
            raise RuntimeError("本机 Zotero 连接器不可用，请重新安装 ScanSci") from error
    try:
        raw_items = list(client.items(limit=max(1, min(500, int(limit)))))
    except Exception as error:
        raise RuntimeError(
            "无法连接本机 Zotero。请打开 Zotero → 设置 → 高级，启用“允许本机其他应用与 Zotero 通信”后重试。"
        ) from error

    items: list[dict[str, Any]] = []
    attachment_count = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        data = dict(raw.get("data", {}) or {})
        item_type = str(data.get("itemType", ""))
        if item_type in {"attachment", "note", "annotation"}:
            if item_type == "attachment" and str(data.get("contentType", "")) == "application/pdf":
                attachment_count += 1
            continue
        creators = []
        for creator in list(data.get("creators", []) or [])[:4]:
            if not isinstance(creator, dict):
                continue
            name = str(creator.get("name", "")).strip() or " ".join(
                part for part in [str(creator.get("firstName", "")).strip(), str(creator.get("lastName", "")).strip()] if part
            )
            if name:
                creators.append(name)
        title = str(data.get("title", "")).strip() or str(data.get("shortTitle", "")).strip()
        if not title:
            continue
        items.append(
            {
                "key": str(raw.get("key", data.get("key", ""))),
                "title": title,
                "item_type": item_type,
                "doi": str(data.get("DOI", "")),
                "date": str(data.get("date", "")),
                "publication": str(data.get("publicationTitle", data.get("proceedingsTitle", ""))),
                "creators": creators,
                "url": str(data.get("url", "")),
            }
        )

    zotero_state = {
        "connection": "local-api",
        "connected": True,
        "item_count": len(items),
        "pdf_count": attachment_count,
        "items": items[:80],
        "sample_titles": [item["title"] for item in items[:18]],
    }
    update_notebook_metadata(workspace, notebook_id=notebook_id, metadata={"zotero": zotero_state})
    summary = load_workspace_summary(workspace, notebook_id=notebook_id)
    notebook = next(iter(list(summary.get("notebooks", []) or [])), {})
    return {
        "ok": True,
        "zotero": zotero_state,
        "notebook": notebook,
        "workspace": load_workspace_summary(workspace),
    }


def _resolved_directory(value: str | Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("请选择资料文件夹")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("资料文件夹必须使用绝对路径")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"资料文件夹不存在：{resolved}")
    return resolved


def _resolved_file(value: str | Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("文件路径不能为空")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("文件必须使用绝对路径")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"文件不存在：{resolved}")
    return resolved


def _candidate_files(folder: Path, suffixes: set[str]) -> list[Path]:
    return [
        path
        for path in folder.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and not path.name.endswith(".evidence.html")
        and not path.name.endswith(".raw.html")
    ]


def _copy_existing_sources(workspace: Path, *, notebook_id: str, destination: Path) -> None:
    summary = load_workspace_summary(workspace, notebook_id=notebook_id)
    notebooks = list(summary.get("notebooks", []) or [])
    for source in list(dict(notebooks[0]).get("sources", []) or []) if notebooks else []:
        path = Path(str(dict(source).get("html_path", ""))).resolve()
        if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
            _copy_unique(path, destination)


def _existing_source_paths(workspace: Path, *, notebook_id: str) -> list[Path]:
    summary = load_workspace_summary(workspace, notebook_id=notebook_id)
    notebooks = list(summary.get("notebooks", []) or [])
    paths: list[Path] = []
    for source in list(dict(notebooks[0]).get("sources", []) or []) if notebooks else []:
        raw = str(dict(source).get("html_path", ""))
        if not raw:
            continue
        path = Path(raw).resolve()
        if path.is_file() and path.suffix.lower() in _IMPORTABLE_SUFFIXES:
            paths.append(path)
    return paths


def _copy_unique(source: Path, destination: Path) -> Path:
    candidate = destination / source.name
    if candidate.exists() and candidate.read_bytes() == source.read_bytes():
        return candidate
    counter = 2
    while candidate.exists():
        candidate = destination / f"{source.stem}-{counter}{source.suffix.lower()}"
        counter += 1
    shutil.copy2(source, candidate)
    return candidate


def _unique_path(destination: Path, stem: str, suffix: str) -> Path:
    candidate = destination / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = destination / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _markdown_document(metadata: dict[str, str], text: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        normalized = str(value or "").replace("\n", " ").replace('"', '\\"')
        lines.append(f'{key}: "{normalized}"')
    lines.extend(["---", "", str(text or "").strip(), ""])
    return "\n".join(lines)


def _safe_folder_name(value: str) -> str:
    normalized = "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
    return normalized.strip(".-")[:80] or "library"


def _library_kind(value: str) -> str:
    normalized = str(value or "folder").strip().lower()
    return normalized if normalized in {"folder", "obsidian"} else "folder"


def _replace_evidence_database(source: Path, destination: Path) -> None:
    """Replace the evidence store, including when Windows keeps it open for reading."""

    try:
        os.replace(source, destination)
        return
    except PermissionError:
        destination.parent.mkdir(parents=True, exist_ok=True)

    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
