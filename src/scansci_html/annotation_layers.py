from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


def write_annotation_layer(
    layer_db_path: str | Path,
    annotation_payload: dict[str, Any],
    *,
    layer_id: str = "",
    name: str = "",
    question: str = "",
    replace: bool = False,
) -> dict[str, object]:
    layer_db = Path(layer_db_path)
    layer_db.parent.mkdir(parents=True, exist_ok=True)
    normalized_layer_id = _safe_layer_id(layer_id) or _generated_layer_id(annotation_payload, name=name, question=question)
    created_at = _utc_now()
    metadata = _layer_metadata(
        normalized_layer_id,
        annotation_payload,
        name=name,
        question=question,
        created_at=created_at,
    )
    items = _layer_items(normalized_layer_id, annotation_payload)

    with sqlite3.connect(layer_db) as connection:
        _initialize_schema(connection)
        existing = connection.execute(
            "select 1 from annotation_layers where layer_id = ?",
            (normalized_layer_id,),
        ).fetchone()
        if existing and not replace:
            raise ValueError(f"Annotation layer already exists: {normalized_layer_id}")
        connection.execute("delete from annotation_items where layer_id = ?", (normalized_layer_id,))
        connection.execute("delete from annotation_layers where layer_id = ?", (normalized_layer_id,))
        connection.execute(
            """
            insert into annotation_layers (
              layer_id,
              name,
              question,
              source_text,
              evidence_db_path,
              schema_version,
              created_at,
              summary_json,
              payload_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata["layer_id"],
                metadata["name"],
                metadata["question"],
                metadata["source_text"],
                metadata["evidence_db_path"],
                metadata["schema_version"],
                metadata["created_at"],
                json.dumps(metadata["summary"], ensure_ascii=False, sort_keys=True),
                json.dumps(annotation_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.executemany(
            """
            insert into annotation_items (
              item_id,
              layer_id,
              segment_id,
              evidence_id,
              citation_id,
              doc_id,
              support_status,
              support_score,
              review_state,
              claim_text,
              quote,
              source_href,
              html_path,
              html_anchor,
              payload_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["item_id"],
                    item["layer_id"],
                    item["segment_id"],
                    item["evidence_id"],
                    item["citation_id"],
                    item["doc_id"],
                    item["support_status"],
                    item["support_score"],
                    item["review_state"],
                    item["claim_text"],
                    item["quote"],
                    item["source_href"],
                    item["html_path"],
                    item["html_anchor"],
                    json.dumps(item["payload"], ensure_ascii=False, sort_keys=True),
                )
                for item in items
            ],
        )
        connection.commit()

    return {
        "layer_db_path": str(layer_db),
        "layer_id": normalized_layer_id,
        "name": metadata["name"],
        "question": metadata["question"],
        "items": len(items),
        "segments": int(dict(metadata["summary"]).get("segments", 0) or 0),
    }


def load_annotation_layers(
    layer_db_path: str | Path,
    *,
    layer_ids: list[str] | None = None,
) -> list[dict[str, object]]:
    layer_db = Path(layer_db_path)
    if not layer_db.exists():
        return []
    with sqlite3.connect(layer_db) as connection:
        connection.row_factory = sqlite3.Row
        _initialize_schema(connection)
        params: list[object] = []
        where = ""
        if layer_ids:
            placeholders = ", ".join("?" for _ in layer_ids)
            where = f"where layer_id in ({placeholders})"
            params.extend(layer_ids)
        layer_rows = connection.execute(
            f"""
            select
              layer_id,
              name,
              question,
              source_text,
              evidence_db_path,
              schema_version,
              created_at,
              summary_json,
              payload_json
            from annotation_layers
            {where}
            order by created_at desc, layer_id
            """,
            params,
        ).fetchall()
        item_rows = connection.execute(
            f"""
            select
              item_id,
              layer_id,
              segment_id,
              evidence_id,
              citation_id,
              doc_id,
              support_status,
              support_score,
              review_state,
              claim_text,
              quote,
              source_href,
              html_path,
              html_anchor,
              payload_json
            from annotation_items
            {where}
            order by layer_id, segment_id, citation_id, item_id
            """,
            params,
        ).fetchall()

    items_by_layer: dict[str, list[dict[str, object]]] = {}
    for row in item_rows:
        layer_id = str(row["layer_id"])
        item = dict(row)
        item["payload"] = _json_loads_object(str(item.pop("payload_json") or "{}"))
        items_by_layer.setdefault(layer_id, []).append(item)

    layers: list[dict[str, object]] = []
    for row in layer_rows:
        layer = dict(row)
        layer["summary"] = _json_loads_object(str(layer.pop("summary_json") or "{}"))
        layer["payload"] = _json_loads_object(str(layer.pop("payload_json") or "{}"))
        layer["items"] = items_by_layer.get(str(layer["layer_id"]), [])
        layers.append(layer)
    return layers


def build_overlay_viewer_payload(
    evidence_db_path: str | Path,
    layer_db_path: str | Path,
    *,
    layer_ids: list[str] | None = None,
    doc_id: str = "",
) -> dict[str, object]:
    layers = load_annotation_layers(layer_db_path, layer_ids=layer_ids)
    documents = _load_documents(Path(evidence_db_path))
    used_doc_ids = _used_doc_ids(layers)
    if doc_id:
        selected_doc_ids = {doc_id}
    elif used_doc_ids:
        selected_doc_ids = used_doc_ids
    else:
        selected_doc_ids = {str(document.get("doc_id", "")) for document in documents[:1]}
    selected_documents = [
        document
        for document in documents
        if str(document.get("doc_id", "")) in selected_doc_ids
    ]
    if not selected_documents and documents:
        selected_documents = documents[:1]
    return {
        "schema_version": "annotation_overlay_viewer.v1",
        "evidence_db_path": str(Path(evidence_db_path)),
        "layer_db_path": str(Path(layer_db_path)),
        "documents": selected_documents,
        "layers": layers,
        "summary": {
            "documents": len(selected_documents),
            "layers": len(layers),
            "items": sum(len(layer.get("items", []) or []) for layer in layers),
        },
    }


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists annotation_layers (
            layer_id text primary key,
            name text not null,
            question text not null,
            source_text text not null,
            evidence_db_path text not null,
            schema_version text not null,
            created_at text not null,
            summary_json text not null,
            payload_json text not null
        )
        """
    )
    connection.execute(
        """
        create table if not exists annotation_items (
            item_id text primary key,
            layer_id text not null,
            segment_id text not null,
            evidence_id text not null,
            citation_id text not null,
            doc_id text not null,
            support_status text not null,
            support_score real not null,
            review_state text not null,
            claim_text text not null,
            quote text not null,
            source_href text not null,
            html_path text not null,
            html_anchor text not null,
            payload_json text not null,
            foreign key(layer_id) references annotation_layers(layer_id)
        )
        """
    )
    connection.execute("create index if not exists idx_annotation_items_layer on annotation_items(layer_id)")
    connection.execute("create index if not exists idx_annotation_items_evidence on annotation_items(evidence_id)")
    connection.execute("create index if not exists idx_annotation_items_doc on annotation_items(doc_id)")


def _layer_metadata(
    layer_id: str,
    payload: dict[str, Any],
    *,
    name: str,
    question: str,
    created_at: str,
) -> dict[str, object]:
    source_text = str(payload.get("source_text", "") or "")
    layer_name = str(name or question or _first_line(source_text) or layer_id).strip()
    return {
        "layer_id": layer_id,
        "name": layer_name,
        "question": str(question or source_text).strip(),
        "source_text": source_text,
        "evidence_db_path": str(payload.get("db_path", "") or ""),
        "schema_version": str(payload.get("schema_version", "") or "grounded_annotation"),
        "created_at": created_at,
        "summary": dict(payload.get("summary", {}) or {}),
    }


def _layer_items(layer_id: str, payload: dict[str, Any]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for segment in payload.get("segments", []) or []:
        segment_payload = dict(segment or {})
        segment_id = str(segment_payload.get("segment_id", ""))
        claim_text = str(segment_payload.get("text", ""))
        for evidence in segment_payload.get("evidence", []) or []:
            evidence_payload = dict(evidence or {})
            evidence_id = str(evidence_payload.get("evidence_id", ""))
            citation_id = str(evidence_payload.get("citation_id", ""))
            if not evidence_id:
                continue
            item_id = f"{layer_id}:{segment_id}:{evidence_id}:{citation_id}"
            doc_id = str(evidence_payload.get("doc_id", ""))
            if not doc_id:
                doc_id = _doc_id_from_evidence_id(evidence_id)
            item_payload = {
                "segment": segment_payload,
                "evidence": evidence_payload,
            }
            items.append(
                {
                    "item_id": item_id,
                    "layer_id": layer_id,
                    "segment_id": segment_id,
                    "evidence_id": evidence_id,
                    "citation_id": citation_id,
                    "doc_id": doc_id,
                    "support_status": str(evidence_payload.get("support_status", "weak_candidate")),
                    "support_score": _float_or_zero(evidence_payload.get("support_score")),
                    "review_state": "unreviewed",
                    "claim_text": claim_text,
                    "quote": str(evidence_payload.get("exact_quote", "")),
                    "source_href": str(evidence_payload.get("source_href", "")),
                    "html_path": str(evidence_payload.get("html_path", "")),
                    "html_anchor": str(evidence_payload.get("html_anchor", "")),
                    "payload": item_payload,
                }
            )
    return items


def _load_documents(evidence_db_path: Path) -> list[dict[str, object]]:
    if not evidence_db_path.exists():
        return []
    with sqlite3.connect(evidence_db_path) as connection:
        connection.row_factory = sqlite3.Row
        evidence_html_expr = (
            "evidence_html_path"
            if _has_column(connection, "source_documents", "evidence_html_path")
            else "html_path as evidence_html_path"
        )
        rows = connection.execute(
            f"""
            select
              doc_id,
              title,
              doi,
              source_url,
              publication_year,
              html_path,
              {evidence_html_expr}
            from source_documents
            order by title, doc_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _has_column(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return column_name in {str(row[1]) for row in connection.execute(f"pragma table_info({table_name})")}


def _used_doc_ids(layers: list[dict[str, object]]) -> set[str]:
    doc_ids: set[str] = set()
    for layer in layers:
        for item in layer.get("items", []) or []:
            doc_id_value = str(dict(item).get("doc_id", "")).strip()
            if doc_id_value:
                doc_ids.add(doc_id_value)
    return doc_ids


def _generated_layer_id(payload: dict[str, Any], *, name: str, question: str) -> str:
    seed = "|".join(
        [
            str(name or ""),
            str(question or ""),
            str(payload.get("source_text", "") or ""),
            str(_utc_now()),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"layer_{stamp}_{digest}"


def _safe_layer_id(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value or "").strip())
    return normalized.strip("_")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _first_line(value: str) -> str:
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return ""


def _doc_id_from_evidence_id(evidence_id: str) -> str:
    if ".s" in evidence_id:
        return evidence_id.rsplit(".s", 1)[0]
    return evidence_id.rsplit(".", 1)[0]


def _float_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json_loads_object(value: str) -> dict[str, object]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}
