"""Optional sqlite-vec cache for local evidence embeddings.

The evidence store is queried repeatedly while a review is planned section by
section.  Persisting only the tiny hashing fallback meant a real local neural
model had to re-embed the complete library for every query.  Providers that
declare a stable ``cache_key`` can now share the same content-addressed cache.
Remote providers intentionally remain uncached here.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from contextlib import AbstractContextManager, closing
from typing import Any, Callable


VECTOR_CACHE_SCHEMA = 1
VECTOR_GENERATION_SCHEMA = 1


class VectorCacheBusy(RuntimeError):
    """Another ScanSci process is already building this cache."""


_CACHE_LOCKS: dict[str, threading.RLock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


class _VectorCacheLock(AbstractContextManager["_VectorCacheLock"]):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.path = self.db_path.with_name(f".{self.db_path.name}.scansci-vec.lock")
        key = str(self.db_path)
        with _CACHE_LOCKS_GUARD:
            self._thread_lock = _CACHE_LOCKS.setdefault(key, threading.RLock())
        self._handle: Any | None = None

    def __enter__(self) -> "_VectorCacheLock":
        self._thread_lock.acquire()
        try:
            try:
                descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if not _remove_stale_vector_cache_lock(self.path):
                    raise VectorCacheBusy(f"向量缓存正在被另一个任务构建：{self.path.name}")
                descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            self._handle = os.fdopen(descriptor, "w", encoding="utf-8")
            self._handle.write(f"pid={os.getpid()}\ncreated={time.time():.3f}\n")
            self._handle.flush()
        except Exception:
            self._thread_lock.release()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            if self._handle is not None:
                self._handle.close()
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        finally:
            self._thread_lock.release()


def _remove_stale_vector_cache_lock(path: Path) -> bool:
    """Remove a lock left by a dead process, never interrupting a live build."""

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^pid=(\d+)", content, flags=re.MULTILINE)
        pid = int(match.group(1)) if match else 0
        if pid:
            try:
                os.kill(pid, 0)
                return False
            except (OSError, SystemError):
                # Windows can raise ``SystemError`` rather than ``OSError``
                # for os.kill(dead_pid, 0). A lock with a confirmed dead owner
                # is stale immediately; retaining it for an arbitrary hour
                # prevents a normal retry after a cancelled indexing task.
                path.unlink()
                return True
        if time.time() - path.stat().st_mtime < 3600:
            return False
        path.unlink()
        return True
    except (OSError, ValueError):
        return False


def load_embedding_cache_rows(db_path: str | Path) -> dict[str, dict[str, str]]:
    """Load the minimal immutable inputs required for vector-cache building."""

    with sqlite3.connect(Path(db_path)) as connection:
        return {
            str(evidence_id): {"evidence_id": str(evidence_id), "text": str(value)}
            for evidence_id, value in connection.execute(
                "select evidence_id, text from evidence_spans order by evidence_id"
            )
        }


def _row_digests(rows: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        str(evidence_id): sha256(str(row.get("text", "")).encode("utf-8")).hexdigest()
        for evidence_id, row in rows.items()
    }


def _corpus_fingerprint(
    row_digests: dict[str, str],
    *,
    provider: str,
    dimensions: int,
) -> str:
    digest = sha256()
    digest.update(f"{VECTOR_GENERATION_SCHEMA}\0{provider}\0{int(dimensions)}\0".encode("utf-8"))
    for evidence_id in sorted(row_digests):
        digest.update(evidence_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row_digests[evidence_id].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _ensure_generation_schema(connection: sqlite3.Connection) -> None:
    _ensure_evidence_revision_schema(connection)
    connection.execute(
        """
        create table if not exists scansci_vector_index_generations (
            generation_id text primary key,
            logical_provider text not null,
            storage_provider text not null unique,
            dimensions integer not null,
            corpus_sha256 text not null,
            state text not null,
            completed integer not null default 0,
            total integer not null default 0,
            reused integer not null default 0,
            created_at real not null,
            updated_at real not null,
            validated_at real,
            error text not null default '',
            source_revision integer not null default 0,
            unique(logical_provider, dimensions, corpus_sha256)
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("pragma table_info(scansci_vector_index_generations)")
    }
    if "source_revision" not in columns:
        connection.execute(
            "alter table scansci_vector_index_generations "
            "add column source_revision integer not null default 0"
        )
    connection.execute(
        """
        create index if not exists scansci_vector_index_generation_lookup
        on scansci_vector_index_generations(logical_provider, dimensions, state, updated_at)
        """
    )


def _generation_record(row: sqlite3.Row | tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    values = list(row)
    return {
        "generation_id": str(values[0]),
        "logical_provider": str(values[1]),
        "storage_provider": str(values[2]),
        "dimensions": int(values[3]),
        "corpus_sha256": str(values[4]),
        "state": str(values[5]),
        "completed": int(values[6]),
        "total": int(values[7]),
        "reused": int(values[8]),
        "created_at": float(values[9]),
        "updated_at": float(values[10]),
        "validated_at": float(values[11]) if values[11] is not None else None,
        "error": str(values[12] or ""),
        "source_revision": int(values[13]) if len(values) > 13 else 0,
    }


def _generation_select_sql() -> str:
    return """
        select generation_id, logical_provider, storage_provider, dimensions,
               corpus_sha256, state, completed, total, reused, created_at,
               updated_at, validated_at, error
               , source_revision
        from scansci_vector_index_generations
    """


def _ensure_evidence_revision_schema(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "evidence_spans"):
        return
    connection.execute(
        """
        create table if not exists scansci_evidence_revision (
            singleton integer primary key check(singleton = 1),
            revision integer not null
        )
        """
    )
    connection.execute(
        "insert or ignore into scansci_evidence_revision(singleton, revision) values (1, 0)"
    )
    for event, suffix in (("insert", "insert"), ("update", "update"), ("delete", "delete")):
        connection.execute(
            f"""
            create trigger if not exists scansci_evidence_revision_{suffix}
            after {event} on evidence_spans
            begin
                update scansci_evidence_revision
                set revision = revision + 1
                where singleton = 1;
            end
            """
        )


def _evidence_revision(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "scansci_evidence_revision"):
        return 0
    row = connection.execute(
        "select revision from scansci_evidence_revision where singleton = 1"
    ).fetchone()
    return int(row[0]) if row else 0


def _active_generation(
    connection: sqlite3.Connection,
    *,
    provider: str,
    dimensions: int,
) -> dict[str, Any] | None:
    if not _table_exists(connection, "scansci_vector_index_generations"):
        return None
    row = connection.execute(
        _generation_select_sql()
        + """
          where logical_provider = ? and dimensions = ? and state = 'active'
          order by updated_at desc limit 1
        """,
        (provider, int(dimensions)),
    ).fetchone()
    return _generation_record(row)


def _current_generation(
    connection: sqlite3.Connection,
    *,
    provider: str,
    dimensions: int,
    corpus_sha256: str,
) -> dict[str, Any] | None:
    if not _table_exists(connection, "scansci_vector_index_generations"):
        return None
    row = connection.execute(
        _generation_select_sql()
        + """
          where logical_provider = ? and dimensions = ? and corpus_sha256 = ?
          limit 1
        """,
        (provider, int(dimensions), corpus_sha256),
    ).fetchone()
    return _generation_record(row)


def _matching_cached_count(
    connection: sqlite3.Connection,
    *,
    storage_provider: str,
    dimensions: int,
    row_digests: dict[str, str],
) -> int:
    if not row_digests or not _table_exists(connection, "scansci_vector_cache_meta"):
        return 0
    existing = {
        str(evidence_id): str(text_digest)
        for evidence_id, text_digest in connection.execute(
            """
            select evidence_id, text_sha256
            from scansci_vector_cache_meta
            where provider = ? and dimensions = ?
            """,
            (storage_provider, int(dimensions)),
        )
    }
    return sum(existing.get(evidence_id) == digest for evidence_id, digest in row_digests.items())


def _resolve_storage_provider(
    db_path: str | Path,
    *,
    logical_provider: str,
    dimensions: int,
) -> tuple[str, bool]:
    """Return the immutable serving generation, falling back to legacy storage."""

    try:
        with sqlite3.connect(Path(db_path)) as connection:
            active = _active_generation(
                connection,
                provider=logical_provider,
                dimensions=dimensions,
            )
            if active is not None:
                return str(active["storage_provider"]), True
            if _table_exists(connection, "scansci_vector_index_generations"):
                row = connection.execute(
                    _generation_select_sql()
                    + """
                      where logical_provider = ? and dimensions = ? and state = 'building'
                      order by updated_at desc limit 1
                    """,
                    (logical_provider, int(dimensions)),
                ).fetchone()
                building = _generation_record(row)
                if building is not None:
                    return str(building["storage_provider"]), False
    except sqlite3.Error:
        pass
    return logical_provider, False


def cached_hashing_candidates(
    db_path: str | Path,
    rows: dict[str, dict[str, Any]],
    *,
    provider: Any,
    query_vector: list[float],
    limit: int,
) -> tuple[list[tuple[str, float]], dict[str, Any]] | None:
    """Backward-compatible wrapper for the default hashing provider."""

    return cached_embedding_candidates(
        db_path,
        rows,
        provider=provider,
        query_vector=query_vector,
        limit=limit,
    )


def cached_embedding_candidates(
    db_path: str | Path,
    rows: dict[str, dict[str, Any]],
    *,
    provider: Any,
    query_vector: list[float],
    limit: int,
    cache_batch_size: int = 512,
    build_missing: bool = True,
    prune_stale: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    error_sink: list[str] | None = None,
    storage_provider_key: str = "",
) -> tuple[list[tuple[str, float]], dict[str, Any]] | None:
    """Return cached cosine candidates for a stable local embedding provider."""

    dimensions = int(getattr(provider, "dimensions", 0) or 0)
    logical_provider = str(getattr(provider, "cache_key", "") or "").strip()
    if not logical_provider or dimensions <= 0 or dimensions > 4_096 or len(query_vector) != dimensions:
        if error_sink is not None:
            error_sink.append(
                "Invalid embedding cache contract: "
                f"provider={logical_provider or '<missing>'}, dimensions={dimensions}, "
                f"query_dimensions={len(query_vector)}"
            )
        return None
    if not _valid_vector(query_vector, dimensions):
        if error_sink is not None:
            error_sink.append(
                f"Embedding provider returned an invalid query vector: {logical_provider}"
            )
        return None
    serving_active = False
    provider_key = str(storage_provider_key or "").strip()
    if not provider_key:
        provider_key, serving_active = _resolve_storage_provider(
            db_path,
            logical_provider=logical_provider,
            dimensions=dimensions,
        )
    try:
        import sqlite_vec
    except ImportError as error:
        if error_sink is not None:
            error_sink.append(f"ImportError: {error}")
        return None

    table = _vector_table(dimensions, provider_key=provider_key)
    embedded = 0
    try:
        with _VectorCacheLock(db_path):
            with sqlite3.connect(Path(db_path), timeout=30.0) as connection:
                connection.execute("pragma busy_timeout = 30000")
                connection.enable_load_extension(True)
                sqlite_vec.load(connection)
                connection.enable_load_extension(False)
                connection.execute(
                    """
                    create table if not exists scansci_vector_cache_meta (
                        evidence_id text not null,
                        provider text not null,
                        dimensions integer not null,
                        text_sha256 text not null,
                        schema_version integer not null,
                        primary key (evidence_id, provider, dimensions)
                    )
                    """
                )
                connection.execute(
                    f"create virtual table if not exists {table} using vec0(evidence_id text primary key, embedding float[{dimensions}])"
                )
                existing = {
                    str(row[0]): str(row[1])
                    for row in connection.execute(
                        "select evidence_id, text_sha256 from scansci_vector_cache_meta where provider = ? and dimensions = ?",
                        (provider_key, dimensions),
                    )
                }
                current_digests = _row_digests(rows)
                current_ids = set(current_digests)
                immutable_serving_generation = serving_active
                if prune_stale and not immutable_serving_generation:
                    for evidence_id in set(existing) - current_ids:
                        connection.execute(f"delete from {table} where evidence_id = ?", (evidence_id,))
                        connection.execute(
                            "delete from scansci_vector_cache_meta where evidence_id = ? and provider = ? and dimensions = ?",
                            (evidence_id, provider_key, dimensions),
                        )

                pending: list[tuple[str, str, str]] = []
                for evidence_id, row in rows.items():
                    text = str(row.get("text", ""))
                    digest = current_digests[evidence_id]
                    if existing.get(evidence_id) != digest:
                        pending.append((evidence_id, text, digest))
                cached_before = max(0, len(rows) - len(pending))
                cancelled = False
                if progress_callback is not None:
                    progress_callback(cached_before, len(rows))
                effective_build_missing = bool(build_missing and not immutable_serving_generation)
                if pending and effective_build_missing:
                    batch_size = max(1, int(cache_batch_size))
                    for offset in range(0, len(pending), batch_size):
                        if cancel_requested is not None and cancel_requested():
                            cancelled = True
                            break
                        batch = pending[offset : offset + batch_size]
                        vectors = provider.embed_texts([item[1] for item in batch])
                        if len(vectors) != len(batch):
                            raise ValueError("Embedding provider returned a different number of vectors")
                        for (evidence_id, _text, digest), vector in zip(batch, vectors):
                            if not _valid_vector(vector, dimensions):
                                raise ValueError("Embedding provider returned a non-finite, zero, or wrong-sized vector")
                            connection.execute(f"delete from {table} where evidence_id = ?", (evidence_id,))
                            connection.execute(
                                f"insert into {table} (evidence_id, embedding) values (?, ?)",
                                (evidence_id, json.dumps([float(value) for value in vector], separators=(",", ":"))),
                            )
                            connection.execute(
                                """
                                insert into scansci_vector_cache_meta (
                                    evidence_id, provider, dimensions, text_sha256, schema_version
                                ) values (?, ?, ?, ?, ?)
                                on conflict(evidence_id, provider, dimensions) do update set
                                    text_sha256 = excluded.text_sha256,
                                    schema_version = excluded.schema_version
                                """,
                                (evidence_id, provider_key, dimensions, digest, VECTOR_CACHE_SCHEMA),
                            )
                            existing[evidence_id] = digest
                            embedded += 1
                        connection.commit()
                        if progress_callback is not None:
                            progress_callback(cached_before + embedded, len(rows))
                        if cancel_requested is not None and cancel_requested():
                            cancelled = True
                            break
                connection.commit()

                table_size = int(connection.execute(f"select count(*) from {table}").fetchone()[0])
                requested = (
                    max(1, min(table_size, int(limit)))
                    if prune_stale and table_size
                    else max(1, table_size)
                    if table_size
                    else 0
                )
                matches = (
                    connection.execute(
                        f"select evidence_id, distance from {table} where embedding match ? and k = ? order by distance",
                        (
                            json.dumps(
                                [float(value) for value in query_vector],
                                separators=(",", ":"),
                            ),
                            requested,
                        ),
                    ).fetchall()
                    if requested
                    else []
                )
                candidates = []
                for evidence_id, raw_distance in matches:
                    distance = float(raw_distance)
                    cosine = max(-1.0, min(1.0, 1.0 - (distance * distance / 2.0)))
                    evidence_id = str(evidence_id)
                    if (
                        evidence_id in current_ids
                        and existing.get(evidence_id) == current_digests.get(evidence_id)
                    ):
                        candidates.append((evidence_id, cosine))
                    if len(candidates) >= max(1, int(limit)):
                        break
                version = str(connection.execute("select vec_version()").fetchone()[0])
                return candidates, {
                    "backend": "sqlite-vec",
                    "version": version,
                    "provider": logical_provider,
                    "storage_provider": provider_key,
                    "dimensions": dimensions,
                    "embedded": embedded,
                    "cached": cached_before,
                    "completed": cached_before + embedded,
                    "total": len(rows),
                    "pending": max(0, len(pending) - embedded),
                    "ready": cached_before + embedded >= len(rows),
                    "cancelled": cancelled,
                    "requested": requested,
                }
    except (VectorCacheBusy, sqlite3.Error, ValueError, OSError) as error:
        if error_sink is not None:
            error_sink.append(f"{type(error).__name__}: {error}")
        return None


def query_cached_embedding_candidates(
    db_path: str | Path,
    *,
    provider: Any,
    query_vector: list[float],
    limit: int,
    error_sink: list[str] | None = None,
) -> tuple[list[tuple[str, float]], dict[str, Any]] | None:
    """Read candidates from an already active sqlite-vec generation.

    This is the serving counterpart to :func:`prewarm_embedding_cache`.  It
    deliberately does not receive evidence text or validate every cached row:
    doing either would force a 190k-span library back into memory for every
    question.  A serving generation is activated only after its full digest
    validation during indexing, so query-time retrieval can remain read-only
    and bounded.
    """

    dimensions = int(getattr(provider, "dimensions", 0) or 0)
    logical_provider = str(getattr(provider, "cache_key", "") or "").strip()
    if not logical_provider or dimensions <= 0 or dimensions > 4_096 or len(query_vector) != dimensions:
        return None
    if not _valid_vector(query_vector, dimensions):
        return None
    provider_key, serving_active = _resolve_storage_provider(
        db_path,
        logical_provider=logical_provider,
        dimensions=dimensions,
    )
    # A partial generation must never become a query-time source.  The old
    # complete generation remains active while a new one is built.
    if not serving_active:
        return None
    table = _vector_table(dimensions, provider_key=provider_key)
    try:
        import sqlite_vec
    except ImportError as error:
        if error_sink is not None:
            error_sink.append(f"ImportError: {error}")
        return None
    try:
        with sqlite3.connect(Path(db_path), timeout=5.0) as connection:
            connection.execute("pragma busy_timeout = 5000")
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            if not _table_exists(connection, table):
                return None
            table_size = int(connection.execute(f"select count(*) from {table}").fetchone()[0] or 0)
            requested = min(table_size, max(1, int(limit)))
            if requested <= 0:
                return [], {
                    "backend": "sqlite-vec",
                    "provider": logical_provider,
                    "storage_provider": provider_key,
                    "dimensions": dimensions,
                    "ready": True,
                    "requested": 0,
                }
            matches = connection.execute(
                f"select evidence_id, distance from {table} where embedding match ? and k = ? order by distance",
                (
                    json.dumps([float(value) for value in query_vector], separators=(",", ":")),
                    requested,
                ),
            ).fetchall()
            candidates: list[tuple[str, float]] = []
            for evidence_id, raw_distance in matches:
                distance = float(raw_distance)
                cosine = max(-1.0, min(1.0, 1.0 - (distance * distance / 2.0)))
                candidates.append((str(evidence_id), cosine))
            version = str(connection.execute("select vec_version()").fetchone()[0])
            return candidates, {
                "backend": "sqlite-vec",
                "version": version,
                "provider": logical_provider,
                "storage_provider": provider_key,
                "dimensions": dimensions,
                "ready": True,
                "requested": requested,
            }
    except (sqlite3.Error, ValueError, OSError) as error:
        if error_sink is not None:
            error_sink.append(f"{type(error).__name__}: {error}")
        return None


def _ensure_cache_meta_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists scansci_vector_cache_meta (
            evidence_id text not null,
            provider text not null,
            dimensions integer not null,
            text_sha256 text not null,
            schema_version integer not null,
            primary key (evidence_id, provider, dimensions)
        )
        """
    )
    # Earlier versions of this table were created without the schema_version
    # column when the DDL did not yet include it.  Add the column in-place
    # so the status report and future generations can track their baseline.
    existing = {row[1] for row in connection.execute("pragma table_info('scansci_vector_cache_meta')")}
    if "schema_version" not in existing:
        connection.execute(
            "alter table scansci_vector_cache_meta add column schema_version integer not null default 0"
        )


def migrate_embedding_caches(
    destination_db: str | Path,
    *,
    source_dbs: list[str | Path],
    provider: str = "",
    dimensions: int = 0,
) -> dict[str, Any]:
    """Copy verified embeddings from older evidence stores into a new one.

    Evidence libraries are rebuilt transactionally: a fresh SQLite store is
    prepared and then swapped into place.  The source text may be unchanged,
    but that swap used to discard the content-addressed vector cache with the
    old database.  This routine transfers only vectors whose SHA-256 digest is
    present in the destination evidence store.  It therefore works both for a
    legacy shared ``evidence.sqlite`` and for a previous per-library store,
    while never letting vectors leak from another knowledge library.

    Vector IDs are deliberately *not* used as the migration key.  Re-parsing a
    document can alter a local evidence ID even when the underlying text is
    unchanged; the digest is the stable safety boundary.  Active generations
    are preferred over building generations, and retired generations are not
    copied.
    """

    destination = Path(destination_db).resolve()
    requested_provider = str(provider or "").strip()
    requested_dimensions = max(0, int(dimensions or 0))
    report: dict[str, Any] = {
        "available": False,
        "destination": destination.name,
        "sources_checked": 0,
        "sources_used": [],
        "migrated_vectors": 0,
        "matched_evidence": 0,
        "providers": [],
        "errors": [],
    }
    if not destination.is_file():
        report["reason"] = "destination_missing"
        return report

    candidates: list[Path] = []
    seen: set[Path] = {destination}
    for raw_path in source_dbs:
        try:
            source = Path(raw_path).resolve()
        except (TypeError, OSError):
            continue
        if source in seen or not source.is_file():
            continue
        seen.add(source)
        candidates.append(source)
    report["sources_checked"] = len(candidates)
    if not candidates:
        report["reason"] = "no_legacy_cache"
        return report

    try:
        import sqlite_vec
    except ImportError as error:
        report["reason"] = "sqlite_vec_missing"
        report["errors"].append(f"ImportError: {error}")
        return report

    try:
        with _VectorCacheLock(destination):
            with closing(sqlite3.connect(destination, timeout=30.0)) as target_connection:
                target_connection.execute("pragma busy_timeout = 30000")
                target_connection.enable_load_extension(True)
                sqlite_vec.load(target_connection)
                target_connection.enable_load_extension(False)
                if not _table_exists(target_connection, "evidence_spans"):
                    report["reason"] = "destination_evidence_missing"
                    return report
                target_rows = {
                    str(evidence_id): {"text": str(text)}
                    for evidence_id, text in target_connection.execute(
                        "select evidence_id, text from evidence_spans order by evidence_id"
                    )
                }
                if not target_rows:
                    report["reason"] = "destination_empty"
                    return report
                target_digests = _row_digests(target_rows)
                target_ids_by_digest: dict[str, list[str]] = {}
                for evidence_id, digest in target_digests.items():
                    target_ids_by_digest.setdefault(digest, []).append(evidence_id)
                _ensure_cache_meta_schema(target_connection)
                _ensure_generation_schema(target_connection)

                for source in candidates:
                    try:
                        migrated = _migrate_embedding_cache_from_source(
                            source_connection_path=source,
                            target_connection=target_connection,
                            target_ids_by_digest=target_ids_by_digest,
                            provider=requested_provider,
                            dimensions=requested_dimensions,
                            sqlite_vec_module=sqlite_vec,
                        )
                    except (sqlite3.Error, OSError, ValueError) as error:
                        report["errors"].append(f"{source.name}: {type(error).__name__}: {error}"[:500])
                        continue
                    if not migrated["providers"]:
                        continue
                    report["sources_used"].append(source.name)
                    report["migrated_vectors"] += int(migrated["migrated_vectors"])
                    report["matched_evidence"] += int(migrated["matched_evidence"])
                    report["providers"].extend(migrated["providers"])
                target_connection.commit()
    except (VectorCacheBusy, sqlite3.Error, OSError) as error:
        report["reason"] = type(error).__name__
        report["errors"].append(f"{type(error).__name__}: {error}"[:500])
        return report

    report["available"] = True
    report["providers"] = sorted(
        report["providers"],
        key=lambda item: (str(item.get("provider", "")), int(item.get("dimensions", 0))),
    )
    report["reason"] = "migrated" if report["migrated_vectors"] else "no_matching_vectors"
    return report


def _migrate_embedding_cache_from_source(
    *,
    source_connection_path: Path,
    target_connection: sqlite3.Connection,
    target_ids_by_digest: dict[str, list[str]],
    provider: str,
    dimensions: int,
    sqlite_vec_module: Any,
) -> dict[str, Any]:
    """Transfer matching cache entries from one source database.

    The caller owns the destination transaction.  A source is only read, so a
    live background index can keep committing batches while its already
    committed vectors are safely reused by an import operation.
    """

    report: dict[str, Any] = {"migrated_vectors": 0, "matched_evidence": 0, "providers": []}
    with closing(sqlite3.connect(source_connection_path, timeout=30.0)) as source_connection:
        source_connection.execute("pragma busy_timeout = 30000")
        source_connection.enable_load_extension(True)
        sqlite_vec_module.load(source_connection)
        source_connection.enable_load_extension(False)
        if not _table_exists(source_connection, "scansci_vector_cache_meta"):
            return report
        candidates = _legacy_storage_candidates(
            source_connection,
            provider=provider,
            dimensions=dimensions,
        )
        for source_provider, logical_provider, vector_dimensions in candidates:
            source_table = _vector_table(vector_dimensions, provider_key=source_provider)
            if not _table_exists(source_connection, source_table):
                continue
            target_table = _vector_table(vector_dimensions, provider_key=logical_provider)
            target_connection.execute(
                f"create virtual table if not exists {target_table} "
                f"using vec0(evidence_id text primary key, embedding float[{vector_dimensions}])"
            )
            existing_target = {
                str(evidence_id): str(text_digest)
                for evidence_id, text_digest in target_connection.execute(
                    """
                    select evidence_id, text_sha256
                    from scansci_vector_cache_meta
                    where provider = ? and dimensions = ?
                    """,
                    (logical_provider, vector_dimensions),
                )
            }
            source_ids_by_digest: dict[str, str] = {}
            for evidence_id, digest in source_connection.execute(
                """
                select evidence_id, text_sha256
                from scansci_vector_cache_meta
                where provider = ? and dimensions = ?
                """,
                (source_provider, vector_dimensions),
            ):
                digest = str(digest)
                if digest in target_ids_by_digest:
                    source_ids_by_digest.setdefault(digest, str(evidence_id))
            if not source_ids_by_digest:
                continue
            source_digest_by_id = {source_id: digest for digest, source_id in source_ids_by_digest.items()}
            candidate_ids = list(source_digest_by_id)
            migrated_for_provider = 0
            matched_for_provider = sum(len(target_ids_by_digest[digest]) for digest in source_ids_by_digest)
            for offset in range(0, len(candidate_ids), 500):
                batch_ids = candidate_ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in batch_ids)
                for source_id, embedding in source_connection.execute(
                    f"select evidence_id, embedding from {source_table} where evidence_id in ({placeholders})",
                    batch_ids,
                ):
                    digest = source_digest_by_id.get(str(source_id))
                    if not digest:
                        continue
                    for target_id in target_ids_by_digest[digest]:
                        if existing_target.get(target_id) == digest:
                            continue
                        target_connection.execute(f"delete from {target_table} where evidence_id = ?", (target_id,))
                        target_connection.execute(
                            f"insert into {target_table} (evidence_id, embedding) values (?, ?)",
                            (target_id, embedding),
                        )
                        target_connection.execute(
                            """
                            insert into scansci_vector_cache_meta (
                                evidence_id, provider, dimensions, text_sha256, schema_version
                            ) values (?, ?, ?, ?, ?)
                            on conflict(evidence_id, provider, dimensions) do update set
                                text_sha256 = excluded.text_sha256,
                                schema_version = excluded.schema_version
                            """,
                            (target_id, logical_provider, vector_dimensions, digest, VECTOR_CACHE_SCHEMA),
                        )
                        existing_target[target_id] = digest
                        migrated_for_provider += 1
                target_connection.commit()
            if migrated_for_provider:
                report["providers"].append(
                    {
                        "provider": logical_provider,
                        "dimensions": vector_dimensions,
                        "migrated_vectors": migrated_for_provider,
                    }
                )
            report["migrated_vectors"] += migrated_for_provider
            report["matched_evidence"] += matched_for_provider
    return report


def _legacy_storage_candidates(
    connection: sqlite3.Connection,
    *,
    provider: str,
    dimensions: int,
) -> list[tuple[str, str, int]]:
    """Return safe ``(storage, logical, dimensions)`` legacy cache sources."""

    available = {
        (str(storage_provider), int(vector_dimensions))
        for storage_provider, vector_dimensions in connection.execute(
            "select distinct provider, dimensions from scansci_vector_cache_meta"
        )
    }
    generated_storage: set[tuple[str, int]] = set()
    selected: dict[tuple[str, int], tuple[tuple[int, float], str]] = {}
    if _table_exists(connection, "scansci_vector_index_generations"):
        for logical, storage, vector_dimensions, state, updated_at in connection.execute(
            """
            select logical_provider, storage_provider, dimensions, state, updated_at
            from scansci_vector_index_generations
            """
        ):
            logical = str(logical)
            storage = str(storage)
            vector_dimensions = int(vector_dimensions)
            generated_storage.add((storage, vector_dimensions))
            if (storage, vector_dimensions) not in available:
                continue
            if str(state) == "active":
                priority = 2
            elif str(state) == "building":
                priority = 1
            else:
                continue
            key = (logical, vector_dimensions)
            rank = (priority, float(updated_at or 0.0))
            if key not in selected or rank > selected[key][0]:
                selected[key] = (rank, storage)

    candidates: list[tuple[str, str, int]] = []
    for (logical, vector_dimensions), (_rank, storage) in selected.items():
        if provider and logical != provider:
            continue
        if dimensions and vector_dimensions != dimensions:
            continue
        candidates.append((storage, logical, vector_dimensions))
    for storage, vector_dimensions in available:
        if (storage, vector_dimensions) in generated_storage:
            continue
        if provider and storage != provider:
            continue
        if dimensions and vector_dimensions != dimensions:
            continue
        candidates.append((storage, storage, vector_dimensions))
    return sorted(set(candidates), key=lambda item: (item[1], item[2], item[0]))


def _prepare_generation(
    db_path: str | Path,
    *,
    logical_provider: str,
    dimensions: int,
    row_digests: dict[str, str],
    corpus_sha256: str,
) -> dict[str, Any]:
    """Create or resume a building generation and reuse unchanged active vectors."""

    import sqlite_vec

    now = time.time()
    with _VectorCacheLock(db_path):
        with sqlite3.connect(Path(db_path), timeout=30.0) as connection:
            connection.execute("pragma busy_timeout = 30000")
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            _ensure_cache_meta_schema(connection)
            _ensure_generation_schema(connection)
            source_revision = _evidence_revision(connection)
            current = _current_generation(
                connection,
                provider=logical_provider,
                dimensions=dimensions,
                corpus_sha256=corpus_sha256,
            )
            if current is not None:
                return current

            active = _active_generation(
                connection,
                provider=logical_provider,
                dimensions=dimensions,
            )
            generation_count = int(
                connection.execute(
                    """
                    select count(*) from scansci_vector_index_generations
                    where logical_provider = ? and dimensions = ?
                    """,
                    (logical_provider, int(dimensions)),
                ).fetchone()[0]
            )
            storage_provider = (
                logical_provider
                if generation_count == 0 and active is None
                else f"{logical_provider}#generation:{corpus_sha256[:20]}"
            )
            generation_id = "g_" + sha256(
                f"{logical_provider}\0{dimensions}\0{corpus_sha256}".encode("utf-8")
            ).hexdigest()[:24]
            connection.execute(
                """
                insert into scansci_vector_index_generations (
                    generation_id, logical_provider, storage_provider, dimensions,
                    corpus_sha256, state, completed, total, reused,
                    created_at, updated_at, error, source_revision
                ) values (?, ?, ?, ?, ?, 'building', 0, ?, 0, ?, ?, '', ?)
                """,
                (
                    generation_id,
                    logical_provider,
                    storage_provider,
                    int(dimensions),
                    corpus_sha256,
                    len(row_digests),
                    now,
                    now,
                    source_revision,
                ),
            )

            reused = 0
            if active is None:
                # ``migrate_embedding_caches`` deliberately writes matching
                # legacy vectors under the logical provider.  Treat those
                # validated cache rows as reused when the first generation is
                # created, rather than presenting a full rebuild to the user.
                reused = _matching_cached_count(
                    connection,
                    storage_provider=storage_provider,
                    dimensions=dimensions,
                    row_digests=row_digests,
                )
            if active is not None and str(active["storage_provider"]) != storage_provider:
                source_provider = str(active["storage_provider"])
                source_table = _vector_table(dimensions, provider_key=source_provider)
                target_table = _vector_table(dimensions, provider_key=storage_provider)
                if _table_exists(connection, source_table):
                    connection.execute(
                        f"create virtual table if not exists {target_table} "
                        f"using vec0(evidence_id text primary key, embedding float[{dimensions}])"
                    )
                    source_digests = {
                        str(evidence_id): str(text_digest)
                        for evidence_id, text_digest in connection.execute(
                            """
                            select evidence_id, text_sha256
                            from scansci_vector_cache_meta
                            where provider = ? and dimensions = ?
                            """,
                            (source_provider, int(dimensions)),
                        )
                    }
                    reusable_ids = [
                        evidence_id
                        for evidence_id, digest in row_digests.items()
                        if source_digests.get(evidence_id) == digest
                    ]
                    for offset in range(0, len(reusable_ids), 500):
                        batch_ids = reusable_ids[offset : offset + 500]
                        if not batch_ids:
                            continue
                        placeholders = ",".join("?" for _ in batch_ids)
                        for evidence_id, embedding in connection.execute(
                            f"select evidence_id, embedding from {source_table} "
                            f"where evidence_id in ({placeholders})",
                            batch_ids,
                        ):
                            evidence_id = str(evidence_id)
                            connection.execute(
                                f"insert into {target_table} (evidence_id, embedding) values (?, ?)",
                                (evidence_id, embedding),
                            )
                            connection.execute(
                                """
                                insert into scansci_vector_cache_meta (
                                    evidence_id, provider, dimensions, text_sha256, schema_version
                                ) values (?, ?, ?, ?, ?)
                                """,
                                (
                                    evidence_id,
                                    storage_provider,
                                    int(dimensions),
                                    row_digests[evidence_id],
                                    VECTOR_CACHE_SCHEMA,
                                ),
                            )
                            reused += 1
            connection.execute(
                """
                update scansci_vector_index_generations
                set completed = ?, reused = ?, updated_at = ?
                where generation_id = ?
                """,
                (reused, reused, time.time(), generation_id),
            )
            connection.commit()
            prepared = _current_generation(
                connection,
                provider=logical_provider,
                dimensions=dimensions,
                corpus_sha256=corpus_sha256,
            )
            if prepared is None:
                raise RuntimeError("Unable to create vector index generation")
            return prepared


def _update_generation_progress(
    db_path: str | Path,
    *,
    generation_id: str,
    completed: int,
    total: int,
    error: str = "",
) -> None:
    try:
        with sqlite3.connect(Path(db_path), timeout=30.0) as connection:
            connection.execute("pragma busy_timeout = 30000")
            connection.execute(
                """
                update scansci_vector_index_generations
                set completed = ?, total = ?, updated_at = ?, error = ?
                where generation_id = ?
                """,
                (max(0, int(completed)), max(0, int(total)), time.time(), error, generation_id),
            )
            connection.commit()
    except sqlite3.Error:
        pass


def _activate_generation(
    db_path: str | Path,
    *,
    generation: dict[str, Any],
    row_digests: dict[str, str],
) -> None:
    import sqlite_vec

    storage_provider = str(generation["storage_provider"])
    dimensions = int(generation["dimensions"])
    with sqlite3.connect(Path(db_path), timeout=30.0) as connection:
        connection.execute("pragma busy_timeout = 30000")
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        matching = _matching_cached_count(
            connection,
            storage_provider=storage_provider,
            dimensions=dimensions,
            row_digests=row_digests,
        )
        table = _vector_table(dimensions, provider_key=storage_provider)
        table_size = (
            int(connection.execute(f"select count(*) from {table}").fetchone()[0])
            if _table_exists(connection, table)
            else 0
        )
        if matching != len(row_digests) or table_size < len(row_digests):
            raise ValueError(
                f"Vector generation validation failed: matching={matching}, "
                f"table={table_size}, expected={len(row_digests)}"
            )
        now = time.time()
        connection.execute("begin immediate")
        connection.execute(
            """
            update scansci_vector_index_generations
            set state = 'retired', updated_at = ?
            where logical_provider = ? and dimensions = ? and state = 'active'
              and generation_id <> ?
            """,
            (
                now,
                str(generation["logical_provider"]),
                dimensions,
                str(generation["generation_id"]),
            ),
        )
        connection.execute(
            """
            update scansci_vector_index_generations
            set state = 'active', completed = total, validated_at = ?,
                updated_at = ?, error = ''
            where generation_id = ?
            """,
            (now, now, str(generation["generation_id"])),
        )
        connection.commit()


def prewarm_embedding_cache(
    db_path: str | Path,
    rows: dict[str, dict[str, Any]],
    *,
    provider: Any,
    cache_batch_size: int = 128,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Incrementally build, validate, and atomically activate an index generation."""

    if not rows:
        return {
            "backend": "sqlite-vec",
            "embedded": 0,
            "cached": 0,
            "completed": 0,
            "total": 0,
            "cancelled": False,
            "ready": True,
        }
    logical_provider = str(getattr(provider, "cache_key", "") or "").strip()
    dimensions = int(getattr(provider, "dimensions", 0) or 0)
    if not logical_provider or dimensions <= 0:
        raise RuntimeError("本地嵌入模型未提供稳定的缓存标识或向量维度")
    row_digests = _row_digests(rows)
    corpus_sha256 = _corpus_fingerprint(
        row_digests,
        provider=logical_provider,
        dimensions=dimensions,
    )
    generation = _prepare_generation(
        db_path,
        logical_provider=logical_provider,
        dimensions=dimensions,
        row_digests=row_digests,
        corpus_sha256=corpus_sha256,
    )
    if str(generation.get("state")) == "active":
        completed = int(generation.get("completed", len(rows)))
        if progress_callback is not None:
            progress_callback(completed, len(rows))
        return {
            "backend": "sqlite-vec",
            "provider": logical_provider,
            "storage_provider": str(generation["storage_provider"]),
            "generation_id": str(generation["generation_id"]),
            "embedded": 0,
            "cached": completed,
            "completed": completed,
            "total": len(rows),
            "pending": 0,
            "ready": True,
            "cancelled": False,
            # A copied, already-active generation has no new build event, but
            # every completed vector is still being reused.  Report that
            # truthfully so callers do not mistake a zero for a rebuild.
            "reused": max(int(generation.get("reused", 0)), completed),
        }

    query_embedder = getattr(provider, "embed_query", None)
    if callable(query_embedder):
        query_vector = [float(value) for value in query_embedder("scientific evidence retrieval")]
    else:
        query_vector = [float(value) for value in provider.embed_texts(["scientific evidence retrieval"])[0]]

    generation_id = str(generation["generation_id"])

    def report_progress(completed: int, total: int) -> None:
        _update_generation_progress(
            db_path,
            generation_id=generation_id,
            completed=completed,
            total=total,
        )
        if progress_callback is not None:
            progress_callback(completed, total)

    errors: list[str] = []
    result = cached_embedding_candidates(
        db_path,
        rows,
        provider=provider,
        query_vector=query_vector,
        limit=1,
        cache_batch_size=max(1, int(cache_batch_size)),
        build_missing=True,
        prune_stale=True,
        progress_callback=report_progress,
        cancel_requested=cancel_requested,
        error_sink=errors,
        storage_provider_key=str(generation["storage_provider"]),
    )
    if result is None:
        detail = errors[-1] if errors else "unknown vector cache error"
        _update_generation_progress(
            db_path,
            generation_id=generation_id,
            completed=int(generation.get("completed", 0)),
            total=len(rows),
            error=detail,
        )
        raise RuntimeError(f"本地向量缓存不可用；请检查 sqlite-vec 与嵌入模型（{detail}）")

    metadata = dict(result[1])
    metadata["generation_id"] = generation_id
    metadata["reused"] = int(generation.get("reused", 0))
    if not bool(metadata.get("cancelled")) and int(metadata.get("completed", 0)) >= len(rows):
        try:
            _activate_generation(db_path, generation=generation, row_digests=row_digests)
        except (sqlite3.Error, ValueError, OSError) as error:
            _update_generation_progress(
                db_path,
                generation_id=generation_id,
                completed=int(metadata.get("completed", 0)),
                total=len(rows),
                error=str(error),
            )
            raise RuntimeError(f"索引构建完成但校验失败，上一代索引仍在使用（{error}）") from error
        metadata["ready"] = True
    return metadata


def vector_cache_status(
    db_path: str | Path,
    *,
    provider: str = "",
    dimensions: int = 0,
) -> dict[str, Any]:
    db = Path(db_path)
    if not db.is_file():
        return {
            "available": False,
            "state": "empty",
            "reason": "evidence_store_missing",
            "ready": False,
        }
    try:
        import sqlite_vec

        with sqlite3.connect(db, timeout=30.0) as connection:
            connection.execute("pragma busy_timeout = 30000")
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            version = str(connection.execute("select vec_version()").fetchone()[0])
            _ensure_cache_meta_schema(connection)
            _ensure_generation_schema(connection)
            requested_dimensions = max(0, int(dimensions))
            total_evidence = (
                int(connection.execute("select count(*) from evidence_spans").fetchone()[0])
                if _table_exists(connection, "evidence_spans")
                else 0
            )
            active = (
                _active_generation(
                    connection,
                    provider=provider,
                    dimensions=requested_dimensions,
                )
                if provider and requested_dimensions > 0
                else None
            )
            revision = _evidence_revision(connection)
            fast_ready = bool(
                active
                and str(active.get("state")) == "active"
                and int(active.get("source_revision", -1)) == revision
                and int(active.get("total", -1)) == total_evidence
                and int(active.get("completed", -1)) >= total_evidence
            )
            if fast_ready:
                rows: dict[str, dict[str, Any]] = {}
                row_digests: dict[str, str] = {}
                corpus_sha256 = str(active.get("corpus_sha256", ""))
                current = active
            else:
                rows = {
                    str(evidence_id): {"text": str(text)}
                    for evidence_id, text in connection.execute(
                        "select evidence_id, text from evidence_spans order by evidence_id"
                    )
                } if _table_exists(connection, "evidence_spans") else {}
                row_digests = _row_digests(rows)
                corpus_sha256 = (
                    _corpus_fingerprint(
                        row_digests,
                        provider=provider,
                        dimensions=requested_dimensions,
                    )
                    if provider and requested_dimensions > 0
                    else ""
                )
                current = (
                    _current_generation(
                        connection,
                        provider=provider,
                        dimensions=requested_dimensions,
                        corpus_sha256=corpus_sha256,
                    )
                    if corpus_sha256
                    else None
                )

            # Adopt a complete pre-generation cache without recomputing vectors.
            legacy_matching = (
                _matching_cached_count(
                    connection,
                    storage_provider=provider,
                    dimensions=requested_dimensions,
                    row_digests=row_digests,
                )
                if provider and requested_dimensions > 0 and not fast_ready
                else 0
            )
            if (
                corpus_sha256
                and current is None
                and active is None
                and legacy_matching == total_evidence
                and total_evidence > 0
            ):
                now = time.time()
                generation_id = "g_" + sha256(
                    f"{provider}\0{requested_dimensions}\0{corpus_sha256}".encode("utf-8")
                ).hexdigest()[:24]
                connection.execute(
                    """
                    insert or ignore into scansci_vector_index_generations (
                        generation_id, logical_provider, storage_provider, dimensions,
                        corpus_sha256, state, completed, total, reused,
                        created_at, updated_at, validated_at, error, source_revision
                    ) values (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, '', ?)
                    """,
                    (
                        generation_id,
                        provider,
                        provider,
                        requested_dimensions,
                        corpus_sha256,
                        total_evidence,
                        total_evidence,
                        legacy_matching,
                        now,
                        now,
                        now,
                        _evidence_revision(connection),
                    ),
                )
                connection.commit()
                current = _current_generation(
                    connection,
                    provider=provider,
                    dimensions=requested_dimensions,
                    corpus_sha256=corpus_sha256,
                )
                active = current

            target = current
            target_storage = str(target["storage_provider"]) if target else provider
            completed = total_evidence if fast_ready else (
                _matching_cached_count(
                    connection,
                    storage_provider=target_storage,
                    dimensions=requested_dimensions,
                    row_digests=row_digests,
                )
                if provider and requested_dimensions > 0
                else 0
            )
            active_matching = total_evidence if fast_ready else (
                _matching_cached_count(
                    connection,
                    storage_provider=str(active["storage_provider"]),
                    dimensions=requested_dimensions,
                    row_digests=row_digests,
                )
                if active is not None
                else 0
            )
            ready = bool(
                current
                and str(current.get("state")) == "active"
                and completed >= total_evidence
            )
            error = str(target.get("error", "")) if target else ""
            if total_evidence == 0:
                state = "empty"
            elif ready:
                state = "ready"
            elif target and error:
                state = "degraded" if active_matching else "failed"
            elif target and str(target.get("state")) == "building":
                state = "indexing"
            elif active_matching:
                state = "degraded"
            else:
                state = "pending"
            progress = round((completed / total_evidence) if total_evidence else 1.0, 6)

            providers = [
                {
                    "provider": str(row[0]),
                    "dimensions": int(row[1]),
                    "cached_vectors": int(row[2]),
                }
                for row in connection.execute(
                    """
                    select provider, dimensions, count(*)
                    from scansci_vector_cache_meta
                    group by provider, dimensions
                    order by provider, dimensions
                    """
                )
            ]
            generation_storage = {
                str(row[0])
                for row in connection.execute(
                    """
                    select storage_provider from scansci_vector_index_generations
                    where logical_provider = ? and dimensions = ?
                    """,
                    (provider, requested_dimensions),
                )
            } if provider else set()
            requested_storage = generation_storage | ({provider} if provider else set())
            other_cached = sum(
                int(item["cached_vectors"])
                for item in providers
                if item["provider"] not in requested_storage
                or (
                    requested_dimensions > 0
                    and int(item["dimensions"]) != requested_dimensions
                )
            )
            tables = [
                str(row[0])
                for row in connection.execute(
                    "select name from sqlite_master where type = 'table' and name like 'scansci_vec_%'"
                )
            ]
            return {
                "available": True,
                "state": state,
                "version": version,
                "provider": provider,
                "dimensions": requested_dimensions,
                "cached_vectors": completed,
                "other_cached_vectors": other_cached,
                "completed": completed,
                "total": total_evidence,
                "progress": progress,
                "ready": ready,
                "migration_required": bool(provider) and not ready and total_evidence > 0,
                "serving_stale": bool(active and active_matching and not ready),
                "serving_vectors": active_matching,
                "active_generation_id": str(active["generation_id"]) if active else "",
                "building_generation_id": (
                    str(current["generation_id"])
                    if current and str(current.get("state")) == "building"
                    else ""
                ),
                "reused_vectors": int(current.get("reused", 0)) if current else 0,
                "error": error,
                "providers": providers,
                "tables": tables,
            }
    except (ImportError, sqlite3.Error, OSError) as error:
        return {
            "available": False,
            "state": "failed",
            "reason": type(error).__name__,
            "ready": False,
        }


def _vector_table(dimensions: int, *, provider_key: str = "hashing-v1") -> str:
    if provider_key == "hashing-v1":
        value = f"scansci_vec_hashing_{int(dimensions)}"
    else:
        provider_hash = sha256(provider_key.encode("utf-8")).hexdigest()[:16]
        value = f"scansci_vec_{provider_hash}_{int(dimensions)}"
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError("Unsafe vector table name")
    return value


def _valid_vector(vector: Any, dimensions: int) -> bool:
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError):
        return False
    return (
        len(values) == int(dimensions)
        and all(math.isfinite(value) for value in values)
        and any(abs(value) > 1e-12 for value in values)
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone() is not None
