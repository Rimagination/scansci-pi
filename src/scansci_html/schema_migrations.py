"""Small, transaction-friendly SQLite schema migration helpers.

The application owns several SQLite files.  This module deliberately keeps
the registry independent from any one feature so a future desktop rollback
can inspect and downgrade a database without rebuilding user data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sqlite3
from typing import Callable, Iterable


MigrationOperation = Callable[[sqlite3.Connection], None]


def _noop(_connection: sqlite3.Connection) -> None:
    """An additive migration can be rolled back in metadata only."""


@dataclass(frozen=True)
class Migration:
    """One numbered migration.

    ``rollback`` is intentionally explicit.  Additive migrations may use the
    default metadata-only rollback so an older binary never destroys data it
    does not understand.
    """

    version: int
    name: str
    apply: MigrationOperation
    rollback: MigrationOperation = _noop

    def checksum(self, schema_name: str) -> str:
        value = f"{schema_name}:{int(self.version)}:{self.name}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_schema_registry(connection: sqlite3.Connection) -> None:
    """Create the registry tables without committing the caller's transaction."""

    connection.execute(
        """
        create table if not exists schema_meta (
            schema_name text primary key,
            schema_version integer not null default 0,
            updated_at text not null
        )
        """
    )
    connection.execute(
        """
        create table if not exists schema_migrations (
            schema_name text not null,
            version integer not null,
            name text not null,
            checksum text not null,
            applied_at text not null,
            primary key (schema_name, version)
        )
        """
    )


def current_schema_version(connection: sqlite3.Connection, schema_name: str) -> int:
    ensure_schema_registry(connection)
    row = connection.execute(
        "select schema_version from schema_meta where schema_name = ?",
        (str(schema_name),),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def applied_migrations(connection: sqlite3.Connection, schema_name: str) -> list[dict[str, object]]:
    ensure_schema_registry(connection)
    rows = connection.execute(
        """
        select schema_name, version, name, checksum, applied_at
        from schema_migrations where schema_name = ? order by version
        """,
        (str(schema_name),),
    ).fetchall()
    return [dict(row) for row in rows]


def apply_migrations(
    connection: sqlite3.Connection,
    schema_name: str,
    migrations: Iterable[Migration],
    *,
    target_version: int | None = None,
) -> int:
    """Apply missing migrations idempotently inside the caller's transaction.

    A savepoint makes a partially applied migration recoverable even when the
    caller has other work in the same transaction.  The function never calls
    ``commit``; state changes and their event can therefore share one commit.
    """

    ordered = sorted(migrations, key=lambda item: int(item.version))
    if len({int(item.version) for item in ordered}) != len(ordered):
        raise ValueError(f"Duplicate migration version for {schema_name}")
    if any(int(item.version) <= 0 for item in ordered):
        raise ValueError(f"Migration versions must be positive for {schema_name}")
    ensure_schema_registry(connection)
    name = str(schema_name)
    current = current_schema_version(connection, name)
    highest = max((int(item.version) for item in ordered), default=current)
    target = highest if target_version is None else int(target_version)
    if target < current:
        raise ValueError(f"Cannot apply schema version {target} below current version {current}")
    by_version = {int(item.version): item for item in ordered}
    missing = [version for version in range(current + 1, target + 1) if version not in by_version]
    if missing:
        raise ValueError(f"Missing migrations for {name}: {missing}")
    for version in range(current + 1, target + 1):
        migration = by_version[version]
        savepoint = f"schema_migration_{version}"
        connection.execute(f"savepoint {savepoint}")
        try:
            migration.apply(connection)
            connection.execute(
                """
                insert into schema_migrations(schema_name, version, name, checksum, applied_at)
                values (?, ?, ?, ?, ?)
                """,
                (name, version, migration.name, migration.checksum(name), _utc_now()),
            )
            connection.execute(
                """
                insert into schema_meta(schema_name, schema_version, updated_at)
                values (?, ?, ?)
                on conflict(schema_name) do update set
                  schema_version = excluded.schema_version,
                  updated_at = excluded.updated_at
                """,
                (name, version, _utc_now()),
            )
            connection.execute(f"release savepoint {savepoint}")
        except Exception:
            connection.execute(f"rollback to savepoint {savepoint}")
            connection.execute(f"release savepoint {savepoint}")
            raise
        current = version
    return current


def rollback_migration(
    connection: sqlite3.Connection,
    schema_name: str,
    migrations: Iterable[Migration],
    *,
    version: int | None = None,
) -> int:
    """Roll back the newest applied migration, or the requested newest version.

    Rollback is deliberately one step at a time.  The additive migrations in
    ScanSci keep their columns/tables when rolling metadata back, which lets an
    older binary reopen the database without data loss.
    """

    ordered = {int(item.version): item for item in migrations}
    ensure_schema_registry(connection)
    current = current_schema_version(connection, schema_name)
    if current == 0:
        return 0
    requested = current if version is None else int(version)
    if requested != current:
        raise ValueError(f"Only the newest schema version can be rolled back: {current}")
    migration = ordered.get(current)
    if migration is None:
        raise ValueError(f"Migration {schema_name}@{current} is not registered")
    savepoint = f"schema_rollback_{current}"
    connection.execute(f"savepoint {savepoint}")
    try:
        migration.rollback(connection)
        connection.execute(
            "delete from schema_migrations where schema_name = ? and version = ?",
            (str(schema_name), current),
        )
        previous = current - 1
        connection.execute(
            "update schema_meta set schema_version = ?, updated_at = ? where schema_name = ?",
            (previous, _utc_now(), str(schema_name)),
        )
        connection.execute(f"release savepoint {savepoint}")
    except Exception:
        connection.execute(f"rollback to savepoint {savepoint}")
        connection.execute(f"release savepoint {savepoint}")
        raise
    return previous


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

