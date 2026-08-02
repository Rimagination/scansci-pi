"""Conservative, verifiable migration from ScanSci + ScanSciPi to one data root."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any
from uuid import uuid4


_WORKSPACE_TABLE_ORDER = (
    "notebooks",
    "sources",
    "notes",
    "layers",
    "layer_sources",
    "research_runs",
    "research_stages",
    "research_tool_calls",
    "research_artifacts",
    "research_evidence_links",
    "research_run_messages",
    "citation_records",
    "citation_audits",
)


class DataMigrationError(RuntimeError):
    """Raised when migration cannot prove that the resulting data is safe."""


def inspect_data_roots(canonical_root: str | Path, pi_root: str | Path) -> dict[str, Any]:
    """Return a read-only migration plan without exposing settings or message content."""

    canonical, pi = _validated_roots(canonical_root, pi_root)
    return {
        "canonical_root": str(canonical),
        "pi_root": str(pi),
        "canonical_exists": canonical.is_dir(),
        "pi_exists": pi.is_dir(),
        "canonical_files": _file_count(canonical),
        "pi_files": _file_count(pi),
        "canonical_workspace": _workspace_summary(canonical / "workspace.sqlite"),
        "pi_workspace": _workspace_summary(pi / "workspace.sqlite"),
        "shared_relative_files": len(_relative_files(canonical).keys() & _relative_files(pi).keys()),
    }


def migrate_data_roots(
    canonical_root: str | Path,
    pi_root: str | Path,
    *,
    backup_parent: str | Path | None = None,
) -> dict[str, Any]:
    """Merge two live roots and atomically switch the canonical ScanSci directory.

    Both inputs are copied to a verified backup set before the switch. The
    original Pi root is never moved or deleted. The previous canonical root is
    retained as a sibling ``*.pre-unification-*`` directory for quick rollback.
    """

    canonical, pi = _validated_roots(canonical_root, pi_root)
    if not canonical.is_dir() or not pi.is_dir():
        raise DataMigrationError("Both ScanSci and ScanSciPi data roots must exist")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_base = Path(backup_parent).expanduser().resolve() if backup_parent else canonical.parent / "ScanSci-merge-backups"
    backup_set = (backup_base / stamp).resolve()
    staging = (canonical.parent / f".ScanSci-unified-{uuid4().hex}").resolve()
    preserved = (canonical.parent / f"ScanSci.pre-unification-{stamp}").resolve()
    _assert_child(backup_set, backup_base)
    _assert_child(staging, canonical.parent)
    _assert_child(preserved, canonical.parent)
    if backup_set.exists() or staging.exists() or preserved.exists():
        raise DataMigrationError("Migration output path already exists; retry with a new timestamp")

    switched = False
    try:
        backup_set.mkdir(parents=True)
        canonical_backup = backup_set / "ScanSci"
        pi_backup = backup_set / "ScanSciPi"
        _copy_tree_consistent(canonical, canonical_backup)
        _copy_tree_consistent(pi, pi_backup)
        backup_checks = {
            "ScanSci": _verify_tree_copy(canonical, canonical_backup),
            "ScanSciPi": _verify_tree_copy(pi, pi_backup),
        }

        _copy_tree_consistent(pi, staging)
        file_merge = _merge_files(canonical, staging)
        settings_merge = _merge_settings(canonical / ".scansci-notebook.json", staging / ".scansci-notebook.json")
        workspace_merge = _merge_workspace(
            staging / "workspace.sqlite",
            canonical / "workspace.sqlite",
            old_root=pi,
            new_root=canonical,
        )
        _rewrite_text_paths(staging, old_root=pi, new_root=canonical)

        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "verified",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "canonical_root": str(canonical),
            "pi_root": str(pi),
            "backup_set": str(backup_set),
            "preserved_previous_root": str(preserved),
            "backup_checks": backup_checks,
            "file_merge": file_merge,
            "settings_merge": settings_merge,
            "workspace_merge": workspace_merge,
        }
        migration_dir = staging / ".scansci-migration"
        migration_dir.mkdir(parents=True, exist_ok=True)
        _write_json(migration_dir / "manifest.json", report)
        _verify_workspace(staging / "workspace.sqlite")

        canonical.rename(preserved)
        try:
            staging.rename(canonical)
            switched = True
        except Exception:
            preserved.rename(canonical)
            raise

        report["status"] = "complete"
        report["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        _write_json(canonical / ".scansci-migration" / "manifest.json", report)
        _write_json(backup_set / "migration-report.json", report)
        return report
    except Exception as error:
        if not switched and staging.exists():
            _safe_remove_tree(staging, canonical.parent)
        if isinstance(error, DataMigrationError):
            raise
        raise DataMigrationError(str(error)) from error


def _validated_roots(canonical_root: str | Path, pi_root: str | Path) -> tuple[Path, Path]:
    canonical = Path(canonical_root).expanduser().resolve()
    pi = Path(pi_root).expanduser().resolve()
    if canonical == pi or canonical.parent != pi.parent:
        raise DataMigrationError("Data roots must be distinct sibling directories")
    return canonical, pi


def _assert_child(path: Path, parent: Path) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as error:
        raise DataMigrationError(f"Unsafe migration path outside {parent}: {path}") from error


def _safe_remove_tree(path: Path, parent: Path) -> None:
    _assert_child(path, parent)
    if path == parent.resolve():
        raise DataMigrationError("Refusing to remove the migration parent")
    shutil.rmtree(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}


def _file_count(root: Path) -> int:
    return len(_relative_files(root))


def _is_sqlite(path: Path) -> bool:
    return path.suffix.casefold() == ".sqlite" and path.stat().st_size > 0


def _sqlite_backup(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".copying")
    temporary.unlink(missing_ok=True)
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    temporary.replace(destination)


def _copy_tree_consistent(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("*.sqlite-wal", "*.sqlite-shm"))
    for sqlite_source in source.rglob("*.sqlite"):
        if not _is_sqlite(sqlite_source):
            continue
        sqlite_destination = destination / sqlite_source.relative_to(source)
        sqlite_destination.parent.mkdir(parents=True, exist_ok=True)
        _sqlite_backup(sqlite_source, sqlite_destination)


def _verify_tree_copy(source: Path, destination: Path) -> dict[str, Any]:
    source_files = _relative_files(source)
    destination_files = _relative_files(destination)
    expected = {rel for rel in source_files if not rel.endswith((".sqlite-wal", ".sqlite-shm"))}
    if expected != set(destination_files):
        raise DataMigrationError(f"Backup inventory mismatch for {source}")
    checked_files = 0
    checked_databases = 0
    for rel in sorted(expected):
        source_file, destination_file = source_files[rel], destination_files[rel]
        if _is_sqlite(source_file):
            if _workspace_summary(source_file) != _workspace_summary(destination_file):
                raise DataMigrationError(f"SQLite backup mismatch: {rel}")
            if source_file.name == "workspace.sqlite":
                _verify_workspace(destination_file)
            checked_databases += 1
        elif _sha256(source_file) != _sha256(destination_file):
            raise DataMigrationError(f"Backup hash mismatch: {rel}")
        else:
            checked_files += 1
    return {"verified_files": checked_files, "verified_databases": checked_databases}


def _merge_files(original: Path, staging: Path) -> dict[str, int]:
    copied = identical = conflicts = 0
    conflict_root = staging / ".scansci-migration" / "original-conflicts"
    for rel, source in sorted(_relative_files(original).items()):
        if rel in {"workspace.sqlite", ".scansci-notebook.json"} or rel.endswith((".sqlite-wal", ".sqlite-shm")):
            continue
        destination = staging / rel
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1
        elif _sha256(source) == _sha256(destination):
            identical += 1
        else:
            archived = conflict_root / rel
            archived.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, archived)
            conflicts += 1
    return {"copied_original_only": copied, "identical": identical, "archived_conflicts": conflicts}


def _merge_settings(original_path: Path, pi_path: Path) -> dict[str, Any]:
    if not original_path.is_file():
        return {"merged": False, "reason": "original settings missing"}
    original = json.loads(original_path.read_text(encoding="utf-8-sig"))
    pi = json.loads(pi_path.read_text(encoding="utf-8-sig")) if pi_path.is_file() else {}
    merged = _merge_value(original, pi)
    _write_json(pi_path, merged)
    return {"merged": True, "top_level_keys": sorted(merged), "pi_values_preferred": True}


def _merge_value(original: Any, pi: Any) -> Any:
    if isinstance(original, dict) and isinstance(pi, dict):
        return {key: _merge_value(original.get(key), pi[key]) if key in original and key in pi else pi.get(key, original.get(key)) for key in original.keys() | pi.keys()}
    if isinstance(original, list) and isinstance(pi, list) and all(isinstance(item, dict) and item.get("id") for item in original + pi):
        by_id = {str(item["id"]): item for item in original}
        by_id.update({str(item["id"]): item for item in pi})
        return list(by_id.values())
    return pi


def _table_names(connection: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {row[0] for row in connection.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _merge_workspace(destination: Path, original: Path, *, old_root: Path, new_root: Path) -> dict[str, Any]:
    if not destination.is_file() or not original.is_file():
        raise DataMigrationError("Both workspace.sqlite files are required")
    connection = sqlite3.connect(destination)
    inserted: dict[str, int] = {}
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ATTACH DATABASE ? AS original", (str(original),))
        main_tables = _table_names(connection)
        original_tables = _table_names(connection, "original")
        for table in _WORKSPACE_TABLE_ORDER:
            if table not in main_tables or table not in original_tables:
                continue
            main_columns = {row[1] for row in connection.execute(f'PRAGMA main.table_info("{table}")')}
            original_columns = [row[1] for row in connection.execute(f'PRAGMA original.table_info("{table}")')]
            columns = [column for column in original_columns if column in main_columns]
            quoted = ", ".join(f'"{column}"' for column in columns)
            before = connection.total_changes
            connection.execute(f'INSERT OR IGNORE INTO main."{table}" ({quoted}) SELECT {quoted} FROM original."{table}"')
            inserted[table] = connection.total_changes - before
        connection.commit()
        connection.execute("DETACH DATABASE original")
        _rewrite_database_paths(connection, old_root=old_root, new_root=new_root)
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        if violations:
            raise DataMigrationError(f"Merged workspace has {len(violations)} foreign-key violation(s)")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise DataMigrationError(f"Merged workspace integrity check failed: {integrity}")
    finally:
        connection.close()
    return {"inserted_rows": inserted, "integrity_check": "ok", "foreign_key_violations": 0}


def _rewrite_database_paths(connection: sqlite3.Connection, *, old_root: Path, new_root: Path) -> None:
    replacements = ((str(old_root), str(new_root)), (old_root.as_posix(), new_root.as_posix()))
    for table in _table_names(connection):
        for row in connection.execute(f'PRAGMA table_info("{table}")'):
            column, column_type = str(row[1]), str(row[2]).upper()
            if "TEXT" not in column_type:
                continue
            for old, new in replacements:
                connection.execute(
                    f'UPDATE "{table}" SET "{column}" = replace("{column}", ?, ?) WHERE instr("{column}", ?) > 0',
                    (old, new, old),
                )
    connection.commit()


def _rewrite_text_paths(root: Path, *, old_root: Path, new_root: Path) -> None:
    replacements = ((str(old_root), str(new_root)), (old_root.as_posix(), new_root.as_posix()))
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".json", ".jsonl", ".md", ".txt"}:
            continue
        if ".scansci-migration" in path.relative_to(root).parts:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        updated = text
        for old, new in replacements:
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def _workspace_summary(path: Path) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        summary: dict[str, int] = {}
        for table in sorted(_table_names(connection)):
            try:
                summary[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.OperationalError:
                # Extension-backed virtual tables (for example sqlite-vec)
                # may be unreadable until the packaged extension is loaded.
                summary[table] = -1
        return summary
    finally:
        connection.close()


def _verify_workspace(path: Path) -> None:
    if not _is_sqlite(path):
        return
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    if result != "ok":
        raise DataMigrationError(f"SQLite integrity check failed for {path}: {result}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
