"""Optional sqlite-vec cache for deterministic local evidence embeddings."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


VECTOR_CACHE_SCHEMA = 1


def cached_hashing_candidates(
    db_path: str | Path,
    rows: dict[str, dict[str, Any]],
    *,
    provider: Any,
    query_vector: list[float],
    limit: int,
) -> tuple[list[tuple[str, float]], dict[str, Any]] | None:
    """Return approximate cosine candidates, or ``None`` when unavailable.

    Only deterministic local hashing embeddings are cached.  Remote and model
    embeddings retain the existing provider path so a model upgrade can never
    silently reuse vectors from a different embedding space.
    """

    dimensions = int(getattr(provider, "dimensions", 0) or 0)
    if dimensions <= 0 or dimensions > 4_096 or len(query_vector) != dimensions:
        return None
    if not any(abs(float(value)) > 1e-12 for value in query_vector):
        return None
    try:
        import sqlite_vec
    except ImportError:
        return None

    table = _vector_table(dimensions)
    embedded = 0
    with sqlite3.connect(Path(db_path)) as connection:
        try:
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
                    ("hashing-v1", dimensions),
                )
            }
            current_ids = set(rows)
            stale_ids = set(existing) - current_ids
            for evidence_id in stale_ids:
                connection.execute(f"delete from {table} where evidence_id = ?", (evidence_id,))
                connection.execute(
                    "delete from scansci_vector_cache_meta where evidence_id = ? and provider = ? and dimensions = ?",
                    (evidence_id, "hashing-v1", dimensions),
                )

            pending: list[tuple[str, str, str]] = []
            for evidence_id, row in rows.items():
                text = str(row.get("text", ""))
                digest = sha256(text.encode("utf-8")).hexdigest()
                if existing.get(evidence_id) != digest:
                    pending.append((evidence_id, text, digest))
            if pending:
                vectors = provider.embed_texts([item[1] for item in pending])
                for (evidence_id, _text, digest), vector in zip(pending, vectors):
                    if len(vector) != dimensions:
                        raise ValueError("Embedding dimension changed while building vector cache")
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
                        (evidence_id, "hashing-v1", dimensions, digest, VECTOR_CACHE_SCHEMA),
                    )
                    embedded += 1
            connection.commit()

            requested = max(1, min(len(rows), int(limit)))
            matches = connection.execute(
                f"select evidence_id, distance from {table} where embedding match ? and k = ? order by distance",
                (json.dumps([float(value) for value in query_vector], separators=(",", ":")), requested),
            ).fetchall()
            candidates = []
            for evidence_id, raw_distance in matches:
                distance = float(raw_distance)
                cosine = max(-1.0, min(1.0, 1.0 - (distance * distance / 2.0)))
                candidates.append((str(evidence_id), cosine))
            version = str(connection.execute("select vec_version()").fetchone()[0])
            return candidates, {
                "backend": "sqlite-vec",
                "version": version,
                "dimensions": dimensions,
                "embedded": embedded,
                "cached": max(0, len(rows) - embedded),
                "requested": requested,
            }
        except (sqlite3.Error, ValueError, OSError):
            return None


def vector_cache_status(db_path: str | Path) -> dict[str, Any]:
    db = Path(db_path)
    if not db.is_file():
        return {"available": False, "reason": "evidence_store_missing"}
    try:
        import sqlite_vec

        with sqlite3.connect(db) as connection:
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            version = str(connection.execute("select vec_version()").fetchone()[0])
            tables = [
                str(row[0])
                for row in connection.execute(
                    "select name from sqlite_master where type = 'table' and name like 'scansci_vec_hashing_%'"
                )
            ]
            cached = 0
            if _table_exists(connection, "scansci_vector_cache_meta"):
                cached = int(connection.execute("select count(*) from scansci_vector_cache_meta").fetchone()[0])
            return {"available": True, "version": version, "cached_vectors": cached, "tables": tables}
    except (ImportError, sqlite3.Error, OSError) as error:
        return {"available": False, "reason": type(error).__name__}


def _vector_table(dimensions: int) -> str:
    value = f"scansci_vec_hashing_{int(dimensions)}"
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError("Unsafe vector table name")
    return value


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone() is not None
