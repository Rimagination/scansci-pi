"""Read-only operations for user-linked Obsidian vaults.

Obsidian vaults remain in place.  ScanSci receives the vault root from a
notebook connection and resolves every requested note beneath that root, so a
model tool cannot use ``..`` or an absolute path to escape the linked vault.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable


_MAX_VAULT_FILES = 20_000
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


def obsidian_status(vault_path: str | Path) -> dict[str, Any]:
    """Inspect a linked vault without changing it."""

    root = _vault_root(vault_path)
    notes = list(_note_files(root))
    return {
        "ok": True,
        "connection": "local-folder",
        "read_only": True,
        "vault_path": str(root),
        "vault_name": root.name,
        "note_count": len(notes),
        "has_obsidian_config": (root / ".obsidian").is_dir(),
        "capabilities": ["status", "search", "read_note", "backlinks"],
    }


def search_obsidian_vault(
    vault_path: str | Path,
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Search note names and Markdown bodies in one linked vault."""

    root = _vault_root(vault_path)
    terms = _query_terms(query)
    if not terms:
        raise ValueError("Obsidian search query cannot be empty")
    rows: list[dict[str, Any]] = []
    for note in _note_files(root):
        relative = note.relative_to(root).as_posix()
        text = note.read_text(encoding="utf-8", errors="replace")
        haystack = f"{relative}\n{text}".lower()
        positions = [haystack.find(term) for term in terms]
        matched = sum(position >= 0 for position in positions)
        if not matched:
            continue
        first = min(position for position in positions if position >= 0)
        body_start = max(0, first - len(relative) - 240)
        excerpt = re.sub(r"\s+", " ", text[body_start : body_start + 900]).strip()
        rows.append(
            {
                "note_path": relative,
                "title": _note_title(text, note.stem),
                "excerpt": excerpt,
                "matched_terms": matched,
                "wikilinks": _wikilinks(text)[:20],
                "modified_at": note.stat().st_mtime,
            }
        )
    rows.sort(key=lambda row: (int(row["matched_terms"]), float(row["modified_at"])), reverse=True)
    bounded = max(1, min(50, int(limit)))
    return {
        "ok": True,
        "connection": "local-folder",
        "read_only": True,
        "vault_path": str(root),
        "query": str(query),
        "count": min(len(rows), bounded),
        "results": rows[:bounded],
    }


def read_obsidian_note(
    vault_path: str | Path,
    note_path: str,
    *,
    max_chars: int = 40_000,
) -> dict[str, Any]:
    """Read one Markdown note from a linked vault."""

    root = _vault_root(vault_path)
    note = _note_path(root, note_path)
    text = note.read_text(encoding="utf-8", errors="replace")
    bounded = max(1_000, min(100_000, int(max_chars)))
    content = text[:bounded]
    return {
        "ok": True,
        "connection": "local-folder",
        "read_only": True,
        "vault_path": str(root),
        "note_path": note.relative_to(root).as_posix(),
        "title": _note_title(text, note.stem),
        "content": content,
        "chars": len(content),
        "truncated": len(text) > len(content),
        "wikilinks": _wikilinks(text),
    }


def obsidian_backlinks(
    vault_path: str | Path,
    note_path: str,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    """Find notes that link to a selected note using Obsidian wikilinks."""

    root = _vault_root(vault_path)
    target = _note_path(root, note_path)
    relative = target.relative_to(root).with_suffix("").as_posix()
    candidates = {relative.lower(), target.stem.lower()}
    rows: list[dict[str, Any]] = []
    for note in _note_files(root):
        if note == target:
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        links = _wikilinks(text)
        matched = [link for link in links if _link_target(link).lower() in candidates]
        if not matched:
            continue
        rows.append(
            {
                "note_path": note.relative_to(root).as_posix(),
                "title": _note_title(text, note.stem),
                "matched_links": matched,
            }
        )
    bounded = max(1, min(100, int(limit)))
    return {
        "ok": True,
        "connection": "local-folder",
        "read_only": True,
        "vault_path": str(root),
        "target_note": target.relative_to(root).as_posix(),
        "count": min(len(rows), bounded),
        "backlinks": rows[:bounded],
    }


def _vault_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Obsidian vault does not exist: {root}")
    return root


def _note_path(root: Path, value: str) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("note_path cannot be empty")
    relative = Path(raw)
    if relative.is_absolute():
        raise ValueError("note_path must be relative to the linked Obsidian vault")
    candidates = [relative]
    if relative.suffix.lower() not in _MARKDOWN_SUFFIXES:
        candidates.extend([relative.with_suffix(".md"), relative.with_suffix(".markdown")])
    for candidate_relative in candidates:
        candidate = (root / candidate_relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("note_path escapes the linked Obsidian vault")
        if candidate.is_file() and candidate.suffix.lower() in _MARKDOWN_SUFFIXES:
            return candidate
    raise FileNotFoundError(f"Obsidian note does not exist: {raw}")


def _note_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _MARKDOWN_SUFFIXES:
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        yield path
        count += 1
        if count >= _MAX_VAULT_FILES:
            return


def _query_terms(value: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[\w\u3400-\u9fff-]{2,}", str(value or "").lower())))[:12]


def _note_title(text: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return match.group(1).strip() if match else fallback


def _wikilinks(text: str) -> list[str]:
    return list(dict.fromkeys(match.strip() for match in re.findall(r"\[\[([^\]]+)\]\]", text) if match.strip()))


def _link_target(value: str) -> str:
    return value.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/").removesuffix(".md")
