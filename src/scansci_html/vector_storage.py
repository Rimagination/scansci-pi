"""Location and safe migration helpers for knowledge-base vector indexes.

Vector data is stored in the same SQLite evidence store as the parsed
document/evidence rows.  This module only owns the *directory policy* for
isolated notebook stores; the evidence schema and vector implementation stay
in their existing modules.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


_configured_root: Path | None = None
_UNSET = object()


def _normalise_root(value: str | Path | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("vector index directory must be an absolute path")
    return path.resolve()


def configure_vector_index_root(value: str | Path | None) -> Path | None:
    """Set the process-local vector index directory override.

    ``None`` restores the legacy location next to the configured evidence
    database.  The directory is not created until an index is written.
    """

    global _configured_root
    _configured_root = _normalise_root(value)
    return _configured_root


def configured_vector_index_root() -> Path | None:
    """Return the currently active override, if any."""

    return _configured_root


def vector_library_root(
    evidence_db: str | Path,
    *,
    vector_index_root: str | Path | None | object = _UNSET,
) -> Path:
    """Return the directory containing isolated notebook evidence stores.

    The optional argument is intentionally tri-state: omitting it uses the
    process setting, while passing ``None`` explicitly requests the legacy
    location.  A private sentinel keeps that distinction without exposing a
    second public API.
    """

    base = Path(evidence_db).expanduser().resolve()
    root = _configured_root if vector_index_root is _UNSET else _normalise_root(vector_index_root)  # type: ignore[arg-type]
    parent = root if root is not None else base.parent
    # Preview/CLI callers may pass an already-isolated ``.../*.libraries/kb_*.sqlite``
    # file instead of the application-level ``evidence.sqlite`` root.  Keep
    # that collection name stable so changing the directory still migrates the
    # existing notebook database rather than nesting ``kb_*.libraries``.
    collection_name = base.parent.name if base.parent.name.endswith(".libraries") else f"{base.stem}.libraries"
    return parent / collection_name

def _backup_sqlite(source: Path, target: Path) -> None:
    """Create a consistent SQLite snapshot and validate it before publishing."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.migrating")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(temporary)
        try:
            source_connection.backup(target_connection)
            check = str(target_connection.execute("pragma integrity_check").fetchone()[0] or "").lower()
            if check != "ok":
                raise ValueError(f"vector index integrity check failed: {source}")
            target_connection.commit()
        finally:
            target_connection.close()
            source_connection.close()
            target_connection = None
            source_connection = None
        temporary.replace(target)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def migrate_vector_indexes(
    *,
    workspace: str | Path,
    evidence_db: str | Path,
    old_root: str | Path | None,
    new_root: str | Path | None,
) -> dict[str, Any]:
    """Copy isolated knowledge-base stores and update workspace references.

    Existing files are retained in the source directory as a recoverable
    rollback copy.  Every destination is created from SQLite's backup API and
    integrity-checked before workspace paths are changed.  If any copy or
    workspace update fails, newly-created destinations are removed and the
    source remains authoritative.
    """

    source_root = vector_library_root(evidence_db, vector_index_root=old_root)
    destination_root = vector_library_root(evidence_db, vector_index_root=new_root)
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    if source_root == destination_root or not source_root.is_dir():
        return {
            "migrated": 0,
            "source_root": str(source_root),
            "destination_root": str(destination_root),
            "updated_workspace_paths": 0,
        }

    source_files = sorted(
        path for path in source_root.glob("*.sqlite")
        if path.is_file() and not path.name.startswith(".")
    )
    if not source_files:
        return {
            "migrated": 0,
            "source_root": str(source_root),
            "destination_root": str(destination_root),
            "updated_workspace_paths": 0,
        }

    # Refuse an accidentally nested destination.  It would make a future
    # migration enumerate its own output and is almost certainly a typo.
    if destination_root == source_root or source_root in destination_root.parents:
        raise ValueError("vector index directory cannot be inside the current vector index directory")

    mappings: dict[str, str] = {}
    created: list[Path] = []
    try:
        for source in source_files:
            destination = destination_root / source.name
            if destination.exists():
                raise FileExistsError(f"vector index destination already exists: {destination}")
            _backup_sqlite(source, destination)
            created.append(destination)
            mappings[str(source.resolve())] = str(destination.resolve())

        from .workspace import update_evidence_db_paths

        updated = update_evidence_db_paths(workspace, mappings)
    except Exception:
        for destination in created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return {
        "migrated": len(mappings),
        "source_root": str(source_root),
        "destination_root": str(destination_root),
        "updated_workspace_paths": int(updated),
        "mapping": mappings,
    }
