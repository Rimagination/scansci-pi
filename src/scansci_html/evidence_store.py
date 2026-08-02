from __future__ import annotations

from dataclasses import replace
from hashlib import blake2b
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from .evidence_spans import (
    EvidenceSpan,
    _inherited_section_kind,
    _is_non_evidence_section,
    _section_metadata,
    _section_kind,
    _sentence_offsets,
    _source_locator,
    _year_from_text,
    evidence_html_path_for,
    extract_evidence_spans,
    write_evidence_html,
)
from .resolver import safe_identifier_part
from .source_filters import is_ignored_library_path


SPAN_COLUMNS = (
    "evidence_id",
    "doc_id",
    "title",
    "doi",
    "source_url",
    "publication_year",
    "html_path",
    "html_anchor",
    "section",
    "section_kind",
    "block_id",
    "block_type",
    "sentence_index",
    "char_start",
    "char_end",
    "text",
    "section_id",
    "parent_section_id",
    "section_path",
    "section_level",
    "source_locator",
)


def index_evidence_library(
    library_dir: str | Path,
    *,
    db_path: str | Path,
    inject_evidence_html: bool = False,
    min_sentence_length: int = 40,
    incremental: bool = False,
) -> dict[str, object]:
    library_path = Path(library_dir)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)

    documents = 0
    span_count = 0
    evidence_html_files = 0
    duplicate_documents_skipped = 0
    reused_documents = 0
    changed_documents = 0
    removed_documents = 0
    seen_doc_ids: set[str] = set()
    with sqlite3.connect(db) as connection:
        _initialize_schema(connection)
        existing_doc_ids = _existing_document_ids(connection) if incremental else set()
        if not incremental:
            _clear_index(connection)
        for html_file in _iter_source_html_files(library_path):
            extracted_spans = extract_evidence_spans(
                html_file.read_text(encoding="utf-8"),
                html_path=html_file,
                min_sentence_length=min_sentence_length,
            )
            document_span = extracted_spans[0] if extracted_spans else None
            if document_span is None:
                continue
            if document_span.doc_id in seen_doc_ids:
                duplicate_documents_skipped += 1
                continue
            seen_doc_ids.add(document_span.doc_id)

            if inject_evidence_html:
                output_path = evidence_html_path_for(html_file)
                spans = write_evidence_html(
                    html_file,
                    output_path=output_path,
                    min_sentence_length=min_sentence_length,
                )
                document_span = spans[0] if spans else None
                spans = _spans_with_html_path(spans, output_path)
                if spans:
                    evidence_html_files += 1
            else:
                output_path = None
                spans = extracted_spans
            if not spans:
                continue
            documents += 1
            span_count += len(spans)
            document = document_span or spans[0]
            fingerprint = _document_source_fingerprint(document, spans)
            if incremental and _document_fingerprint_matches(connection, document.doc_id, fingerprint):
                reused_documents += 1
                continue
            if incremental and document.doc_id in existing_doc_ids:
                _delete_document_index_rows(connection, document.doc_id)
            if incremental:
                changed_documents += 1
            _insert_document(connection, document, output_path)
            _insert_spans(connection, spans)
            _record_document_fingerprint(connection, document.doc_id, fingerprint)
        if incremental:
            for removed_doc_id in existing_doc_ids - seen_doc_ids:
                _delete_document_index_rows(connection, removed_doc_id)
                removed_documents += 1
            if changed_documents or removed_documents:
                _mark_vector_generations_stale(connection)
        connection.commit()
    connection.close()

    result: dict[str, object] = {
        "documents": documents,
        "spans": span_count,
        "db_path": str(db),
        "evidence_html_files": evidence_html_files,
        "duplicate_documents_skipped": duplicate_documents_skipped,
    }
    if incremental:
        result.update(
            {
                "reused_documents": reused_documents,
                "changed_documents": changed_documents,
                "removed_documents": removed_documents,
                "index_mode": "incremental",
            }
        )
    return result


def index_markdown_library(
    library_dir: str | Path,
    *,
    db_path: str | Path,
    min_sentence_length: int = 40,
    include_support_directories: bool = False,
    include_title_only_notes: bool = False,
    incremental: bool = False,
) -> dict[str, object]:
    library_path = Path(library_dir)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)

    documents = 0
    span_count = 0
    duplicate_documents_skipped = 0
    reused_documents = 0
    changed_documents = 0
    removed_documents = 0
    seen_doc_ids: set[str] = set()
    with sqlite3.connect(db) as connection:
        _initialize_schema(connection)
        existing_doc_ids = _existing_document_ids(connection) if incremental else set()
        if not incremental:
            _clear_index(connection)
        for markdown_file in _iter_source_markdown_files(
            library_path,
            include_support_directories=include_support_directories,
        ):
            markdown_text = markdown_file.read_text(encoding="utf-8-sig")
            spans = extract_markdown_evidence_spans(
                markdown_text,
                markdown_path=markdown_file,
                min_sentence_length=min_sentence_length,
            )
            if not spans and include_title_only_notes:
                spans = extract_markdown_evidence_spans(
                    markdown_text,
                    markdown_path=markdown_file,
                    min_sentence_length=1,
                )
            if not spans and include_title_only_notes:
                fallback_title = _markdown_title(_split_markdown_front_matter(markdown_text)[1]) or markdown_file.stem
                spans = extract_markdown_evidence_spans(
                    f"---\ntitle: {fallback_title}\n---\n\n{fallback_title}",
                    markdown_path=markdown_file,
                    min_sentence_length=1,
                )
            document_span = spans[0] if spans else None
            if document_span is None:
                continue
            if document_span.doc_id in seen_doc_ids:
                duplicate_documents_skipped += 1
                continue
            seen_doc_ids.add(document_span.doc_id)
            documents += 1
            span_count += len(spans)
            fingerprint = _document_source_fingerprint(document_span, spans)
            if incremental and _document_fingerprint_matches(connection, document_span.doc_id, fingerprint):
                reused_documents += 1
                continue
            if incremental and document_span.doc_id in existing_doc_ids:
                _delete_document_index_rows(connection, document_span.doc_id)
            if incremental:
                changed_documents += 1
            _insert_document(connection, document_span, None)
            _insert_spans(connection, spans)
            _record_document_fingerprint(connection, document_span.doc_id, fingerprint)
        if incremental:
            for removed_doc_id in existing_doc_ids - seen_doc_ids:
                _delete_document_index_rows(connection, removed_doc_id)
                removed_documents += 1
            if changed_documents or removed_documents:
                _mark_vector_generations_stale(connection)
        connection.commit()
    connection.close()

    result: dict[str, object] = {
        "documents": documents,
        "spans": span_count,
        "db_path": str(db),
        "duplicate_documents_skipped": duplicate_documents_skipped,
    }
    if incremental:
        result.update(
            {
                "reused_documents": reused_documents,
                "changed_documents": changed_documents,
                "removed_documents": removed_documents,
                "index_mode": "incremental",
            }
        )
    return result


def ensure_library_overview(db_path: str | Path) -> dict[str, int]:
    """Return the durable document-level overview for an evidence library.

    The evidence store is deliberately split into two retrieval resolutions:
    a small catalogue (one card per source document) for orientation, and
    sentence-level evidence for verification.  A library that predates this
    schema is upgraded lazily the first time its overview is requested.
    """

    db = Path(db_path)
    if not db.is_file():
        return _empty_library_overview()
    try:
        with sqlite3.connect(db) as connection:
            _initialize_schema(connection)
            document_count = int(connection.execute("select count(*) from source_documents").fetchone()[0] or 0)
            card_count = int(connection.execute("select count(*) from document_cards").fetchone()[0] or 0)
            node_count = int(connection.execute("select count(*) from knowledge_graph_nodes").fetchone()[0] or 0)
            revision_row = connection.execute(
                "select card_schema_version from library_catalog_revisions where singleton = 1"
            ).fetchone()
            card_schema_version = int(revision_row[0] or 0) if revision_row else 0
            if document_count == 0:
                return _library_overview_stats(connection)
            # Version 2 changes card cache keys from generated summaries to
            # source-document fingerprints.  Older cards must be rebuilt once
            # so only an actual source edit invalidates their compact vectors.
            if card_count == document_count and node_count > 0 and card_schema_version >= 2:
                return _library_overview_stats(connection)
    except sqlite3.Error:
        return _empty_library_overview()
    return build_library_overview(db)


def build_library_overview(
    db_path: str | Path,
    *,
    summary_character_limit: int = 720,
    max_keywords_per_document: int = 8,
) -> dict[str, int]:
    """Build a compact document / section / concept map for one library.

    This intentionally does *not* summarize every evidence span or construct
    an entity graph over every span.  It creates exactly one extractive card
    for each document, reuses the already materialized section hierarchy, and
    adds a lightweight cross-document concept layer.  All semantic edges keep
    their source document-card evidence anchors so a later answer can descend
    to original evidence instead of citing a generated summary.
    """

    db = Path(db_path)
    if not db.is_file():
        return _empty_library_overview()
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        _initialize_schema(connection)
        documents = list(
            connection.execute(
                """
                select doc_id, title, doi, source_url, publication_year, html_path
                from source_documents
                order by title collate nocase, doc_id
                """
            )
        )
        # Pre-versioned libraries already contain parsed evidence but no source
        # fingerprints.  Backfill them once from the durable evidence rows;
        # future incremental imports do not need this full-library pass.
        for document in documents:
            doc_id = str(document["doc_id"])
            known_fingerprint = connection.execute(
                "select 1 from document_index_revisions where doc_id = ?",
                (doc_id,),
            ).fetchone()
            if not known_fingerprint:
                _record_document_fingerprint(
                    connection,
                    doc_id,
                    _stored_document_fingerprint(connection, doc_id),
                )
        sections_by_doc: dict[str, list[sqlite3.Row]] = {}
        first_evidence_by_section: dict[str, str] = {}
        for row in connection.execute(
            """
            select section_id, doc_id, parent_section_id, section_title, section_path,
                   section_kind, section_level, source_locator
            from document_sections
            order by doc_id, section_level, section_path
            """
        ):
            sections_by_doc.setdefault(str(row["doc_id"]), []).append(row)
        for row in connection.execute(
            """
            select section_id, min(evidence_id) as evidence_id
            from evidence_spans
            where section_id <> ''
            group by section_id
            """
        ):
            if str(row["section_id"] or "").strip() and str(row["evidence_id"] or "").strip():
                first_evidence_by_section[str(row["section_id"])] = str(row["evidence_id"])

        # A rebuilt source index invalidates cards and graph edges, while
        # retaining the underlying document/section/evidence store.
        connection.execute("delete from knowledge_graph_edges")
        connection.execute("delete from knowledge_graph_nodes")
        connection.execute("delete from document_cards")

        document_keywords: dict[str, list[str]] = {}
        document_anchors: dict[str, list[str]] = {}
        for document in documents:
            doc_id = str(document["doc_id"])
            candidate_spans = list(
                connection.execute(
                    """
                    select evidence_id, text, section_id, section, section_kind, sentence_index
                    from evidence_spans
                    where doc_id = ? and trim(text) <> ''
                    order by
                        case lower(section_kind)
                            when 'abstract' then 0
                            when 'introduction' then 1
                            when 'conclusion' then 2
                            when 'results' then 3
                            else 4
                        end,
                        sentence_index
                    limit 12
                    """,
                    (doc_id,),
                )
            )
            summary, anchors = _extractive_document_summary(
                candidate_spans,
                character_limit=summary_character_limit,
            )
            section_rows = sections_by_doc.get(doc_id, [])
            headings = [str(row["section_title"] or "") for row in section_rows[:16]]
            keywords = _document_card_keywords(
                str(document["title"] or ""),
                headings,
                summary,
                max_keywords=max_keywords_per_document,
            )
            evidence_count = int(
                connection.execute("select count(*) from evidence_spans where doc_id = ?", (doc_id,)).fetchone()[0] or 0
            )
            fingerprint_row = connection.execute(
                "select source_fingerprint from document_index_revisions where doc_id = ?",
                (doc_id,),
            ).fetchone()
            # Card embeddings are keyed to the parsed source fingerprint, not
            # a generated card. A source edit therefore invalidates only that
            # document's compact vector, while unchanged cards remain reusable.
            source_digest = str(fingerprint_row[0] or "") if fingerprint_row else ""
            if not source_digest:
                source_digest = blake2b(
                    "\n".join((str(document["title"] or ""), summary, "|".join(anchors))).encode("utf-8"),
                    digest_size=20,
                ).hexdigest()
            connection.execute(
                """
                insert into document_cards (
                    doc_id, title, summary, keywords_json, anchor_evidence_ids_json,
                    section_count, evidence_count, summary_method, source_digest
                ) values (?, ?, ?, ?, ?, ?, ?, 'extractive-evidence', ?)
                """,
                (
                    doc_id,
                    str(document["title"] or "").strip() or doc_id,
                    summary,
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(anchors, ensure_ascii=False),
                    len(section_rows),
                    evidence_count,
                    source_digest,
                ),
            )
            document_keywords[doc_id] = keywords
            document_anchors[doc_id] = anchors

            document_node_id = f"document:{doc_id}"
            connection.execute(
                """
                insert into knowledge_graph_nodes (node_id, node_type, label, metadata_json)
                values (?, 'document', ?, ?)
                """,
                (
                    document_node_id,
                    str(document["title"] or "").strip() or doc_id,
                    json.dumps(
                        {
                            "doc_id": doc_id,
                            "doi": str(document["doi"] or ""),
                            "source_url": str(document["source_url"] or ""),
                            "publication_year": document["publication_year"],
                            "summary_method": "extractive-evidence",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

            for section in _overview_sections(section_rows):
                section_id = str(section["section_id"])
                section_node_id = f"section:{section_id}"
                section_anchor = first_evidence_by_section.get(section_id, "")
                edge_anchors = [section_anchor] if section_anchor else list(anchors[:1])
                connection.execute(
                    """
                    insert into knowledge_graph_nodes (node_id, node_type, label, metadata_json)
                    values (?, 'section', ?, ?)
                    """,
                    (
                        section_node_id,
                        str(section["section_title"] or "").strip() or "正文",
                        json.dumps(
                            {
                                "doc_id": doc_id,
                                "section_id": section_id,
                                "section_path": str(section["section_path"] or ""),
                                "source_locator": str(section["source_locator"] or ""),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                connection.execute(
                    """
                    insert into knowledge_graph_edges (
                        edge_id, source_node_id, target_node_id, edge_type, weight,
                        anchor_evidence_ids_json, metadata_json
                    ) values (?, ?, ?, 'contains', 1.0, ?, ?)
                    """,
                    (
                        _overview_edge_id(document_node_id, section_node_id, "contains"),
                        document_node_id,
                        section_node_id,
                        json.dumps(edge_anchors, ensure_ascii=False),
                        json.dumps({"provenance": "document-section-parser"}, ensure_ascii=False),
                    ),
                )

        concept_documents: dict[str, list[str]] = {}
        concept_labels: dict[str, str] = {}
        for doc_id, keywords in document_keywords.items():
            for keyword in keywords:
                normalized = _normalized_overview_keyword(keyword)
                if not normalized:
                    continue
                concept_documents.setdefault(normalized, []).append(doc_id)
                concept_labels.setdefault(normalized, keyword)
        document_total = len(documents)
        max_concept_documents = max(8, document_total // 3)
        for normalized, doc_ids in concept_documents.items():
            unique_doc_ids = list(dict.fromkeys(doc_ids))
            if len(unique_doc_ids) < 2 or len(unique_doc_ids) > max_concept_documents:
                continue
            concept_node_id = f"concept:{blake2b(normalized.encode('utf-8'), digest_size=10).hexdigest()}"
            connection.execute(
                """
                insert into knowledge_graph_nodes (node_id, node_type, label, metadata_json)
                values (?, 'concept', ?, ?)
                """,
                (
                    concept_node_id,
                    concept_labels[normalized],
                    json.dumps({"document_count": len(unique_doc_ids)}, ensure_ascii=False),
                ),
            )
            for doc_id in unique_doc_ids:
                document_node_id = f"document:{doc_id}"
                connection.execute(
                    """
                    insert into knowledge_graph_edges (
                        edge_id, source_node_id, target_node_id, edge_type, weight,
                        anchor_evidence_ids_json, metadata_json
                    ) values (?, ?, ?, 'mentions', 1.0, ?, ?)
                    """,
                    (
                        _overview_edge_id(document_node_id, concept_node_id, "mentions"),
                        document_node_id,
                        concept_node_id,
                        json.dumps(document_anchors.get(doc_id, [])[:3], ensure_ascii=False),
                        json.dumps({"provenance": "document-card-keywords"}, ensure_ascii=False),
                    ),
                )
        _record_catalog_revision(connection)
        connection.commit()
        return _library_overview_stats(connection)


def _empty_library_overview() -> dict[str, int]:
    return {
        "documents": 0,
        "document_cards": 0,
        "sections": 0,
        "graph_nodes": 0,
        "graph_edges": 0,
        "evidence_spans": 0,
        "catalog_revision": 0,
    }


def _library_overview_stats(connection: sqlite3.Connection) -> dict[str, int]:
    revision_row = connection.execute(
        "select catalog_revision from library_catalog_revisions where singleton = 1"
    ).fetchone()
    return {
        "documents": int(connection.execute("select count(*) from source_documents").fetchone()[0] or 0),
        "document_cards": int(connection.execute("select count(*) from document_cards").fetchone()[0] or 0),
        "sections": int(connection.execute("select count(*) from document_sections").fetchone()[0] or 0),
        "graph_nodes": int(connection.execute("select count(*) from knowledge_graph_nodes").fetchone()[0] or 0),
        "graph_edges": int(connection.execute("select count(*) from knowledge_graph_edges").fetchone()[0] or 0),
        "evidence_spans": int(connection.execute("select count(*) from evidence_spans").fetchone()[0] or 0),
        "catalog_revision": int(revision_row[0] or 0) if revision_row else 0,
    }


def _record_catalog_revision(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        update library_catalog_revisions
        set catalog_revision = catalog_revision + 1,
            card_schema_version = 2,
            updated_at = current_timestamp
        where singleton = 1
        """
    )


def _extractive_document_summary(
    rows: list[sqlite3.Row],
    *,
    character_limit: int,
) -> tuple[str, list[str]]:
    selected: list[str] = []
    anchors: list[str] = []
    seen_sections: set[str] = set()
    used = 0
    for row in rows:
        text = re.sub(r"\s+", " ", str(row["text"] or "")).strip()
        evidence_id = str(row["evidence_id"] or "").strip()
        section_id = str(row["section_id"] or row["section"] or "").strip()
        if not text or not evidence_id:
            continue
        # Keep the card representative across sections instead of copying an
        # abstract's first twelve sentences.
        if section_id in seen_sections and len(selected) >= 2:
            continue
        remaining = max(0, int(character_limit) - used)
        if remaining <= 0:
            break
        excerpt = text[:remaining].rstrip()
        if len(excerpt) < 24 and selected:
            continue
        selected.append(excerpt)
        anchors.append(evidence_id)
        seen_sections.add(section_id)
        used += len(excerpt) + 1
        if len(selected) >= 4:
            break
    if not selected:
        return "", []
    return " ".join(selected), list(dict.fromkeys(anchors))


def _overview_sections(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    roots = [row for row in rows if not str(row["parent_section_id"] or "").strip()]
    selected = roots or rows
    # A catalogue map should remain legible; detail remains available through
    # document_sections and evidence_spans.
    return selected[:12]


def _document_card_keywords(
    title: str,
    headings: list[str],
    summary: str,
    *,
    max_keywords: int,
) -> list[str]:
    candidates: list[str] = []
    for raw in [title, *headings, summary]:
        for part in re.split(r"[，,;；:：|/\\\\()（）\[\]【】\n]+", str(raw or "")):
            value = re.sub(r"\s+", " ", part).strip(" -—–·•.")
            if not value:
                continue
            # Chinese headings often carry a meaningful phrase without a
            # whitespace tokenizer.  Keep a bounded phrase, while English
            # sentences are handled as technical token groups below.
            if re.search(r"[\u4e00-\u9fff]", value) and 2 <= len(value) <= 32:
                candidates.append(value)
            for term in re.findall(r"[A-Za-z][A-Za-z0-9+/#._-]*(?:\s+[A-Za-z][A-Za-z0-9+/#._-]*){0,3}", value):
                normalized = re.sub(r"\s+", " ", term).strip()
                if len(normalized) >= 3:
                    candidates.append(normalized)
    ignored = {"abstract", "introduction", "conclusion", "results", "discussion", "references", "正文"}
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalized_overview_keyword(candidate)
        if not normalized or normalized in ignored or normalized in seen:
            continue
        seen.add(normalized)
        output.append(candidate)
        if len(output) >= max(1, int(max_keywords)):
            break
    return output


def _normalized_overview_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _overview_edge_id(source: str, target: str, edge_type: str) -> str:
    material = "\x1f".join((source, target, edge_type))
    return f"edge:{blake2b(material.encode('utf-8'), digest_size=12).hexdigest()}"


def extract_markdown_evidence_spans(
    markdown_text: str,
    *,
    markdown_path: str | Path,
    min_sentence_length: int = 40,
) -> list[EvidenceSpan]:
    metadata, body = _split_markdown_front_matter(str(markdown_text or ""))
    title = _markdown_title(body) or str(metadata.get("title") or "").strip() or Path(markdown_path).stem
    doi = str(metadata.get("doi") or "").strip() or None
    source_url = str(metadata.get("source_url") or metadata.get("url") or "").strip()
    normalized_path = Path(markdown_path).as_posix()
    if not source_url:
        source_url = normalized_path
    publication_year = _metadata_year(metadata)
    remote_source = source_url if re.match(r"^https?://", source_url, flags=re.IGNORECASE) else ""
    if doi or remote_source:
        doc_id = safe_identifier_part(doi or remote_source)
    else:
        digest = blake2b(normalized_path.encode("utf-8"), digest_size=10).hexdigest()
        readable = safe_identifier_part(f"{title}-{Path(markdown_path).stem}")
        doc_id = f"{readable}-{digest}" if readable != "paper" else f"local-{digest}"

    spans: list[EvidenceSpan] = []
    current_section = ""
    current_section_kind = ""
    section_stack: list[tuple[int, str, str]] = []
    block_ordinal = 0

    for block_type, level, text in _iter_markdown_blocks(body):
        if block_type == "heading":
            heading_text = text.strip()
            if not heading_text:
                continue
            continue_non_evidence = (
                current_section_kind
                if _is_page_heading(heading_text) and _is_non_evidence_section(current_section_kind)
                else ""
            )
            while section_stack and section_stack[-1][0] >= int(level or 1):
                section_stack.pop()
            direct_kind = continue_non_evidence or _section_kind(heading_text)
            current_section_kind = _inherited_section_kind(direct_kind, section_stack)
            section_stack.append((int(level or 1), heading_text, current_section_kind))
            current_section = heading_text
            continue

        block_text = re.sub(r"\s+", " ", text).strip()
        if not block_text:
            continue
        section_kind = current_section_kind or _section_kind(current_section)
        if _is_non_evidence_section(section_kind):
            continue
        block_ordinal += 1
        block_anchor = f"md-block-{block_ordinal:04d}"
        section, section_path, section_level, section_id, parent_section_id = _section_metadata(
            doc_id,
            section_stack,
            fallback=current_section,
        )
        sentence_offsets = (
            ((block_text, 0, len(block_text)),)
            if block_type in {"list_item", "table_row"}
            else tuple(_sentence_offsets(block_text))
        )
        for local_sentence_index, (sentence_text, char_start, char_end) in enumerate(sentence_offsets, start=1):
            if len(sentence_text) < int(min_sentence_length):
                continue
            sentence_index = len(spans) + 1
            html_anchor = (
                block_anchor if block_type in {"list_item", "table_row"} else f"{block_anchor}-s{local_sentence_index:04d}"
            )
            spans.append(
                EvidenceSpan(
                    doc_id=doc_id,
                    evidence_id=f"{doc_id}.s{sentence_index:04d}",
                    title=title,
                    doi=doi,
                    source_url=source_url,
                    publication_year=publication_year,
                    html_path=normalized_path,
                    html_anchor=html_anchor,
                    section=section,
                    section_kind=section_kind,
                    block_id=f"{doc_id}:{block_anchor}",
                    block_type=block_type,
                    sentence_index=sentence_index,
                    char_start=char_start,
                    char_end=char_end,
                    text=sentence_text,
                    section_id=section_id,
                    parent_section_id=parent_section_id,
                    section_path=section_path,
                    section_level=section_level,
                    source_locator=_source_locator(section_path, html_anchor=block_anchor),
                )
            )
    return spans


def export_spans_jsonl(db_path: str | Path, output_path: str | Path) -> dict[str, object]:
    db = Path(db_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = list(_span_rows(db))
    with output.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"spans": len(rows), "output_path": str(output)}


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists source_documents (
            doc_id text primary key,
            title text not null,
            doi text,
            source_url text not null,
            publication_year integer,
            html_path text not null,
            evidence_html_path text not null
        )
        """
    )
    connection.execute(
        """
        create table if not exists evidence_spans (
            evidence_id text primary key,
            doc_id text not null,
            title text not null,
            doi text,
            source_url text not null,
            publication_year integer,
            html_path text not null,
            html_anchor text not null,
            section text not null,
            section_kind text not null,
            block_id text not null,
            block_type text not null,
            sentence_index integer not null,
            char_start integer not null,
            char_end integer not null,
            text text not null,
            section_id text not null default '',
            parent_section_id text not null default '',
            section_path text not null default '',
            section_level integer not null default 0,
            source_locator text not null default ''
        )
        """
    )
    _ensure_column(connection, "source_documents", "publication_year", "integer")
    _ensure_column(connection, "evidence_spans", "publication_year", "integer")
    _ensure_column(connection, "evidence_spans", "section_id", "text not null default ''")
    _ensure_column(connection, "evidence_spans", "parent_section_id", "text not null default ''")
    _ensure_column(connection, "evidence_spans", "section_path", "text not null default ''")
    _ensure_column(connection, "evidence_spans", "section_level", "integer not null default 0")
    _ensure_column(connection, "evidence_spans", "source_locator", "text not null default ''")
    connection.execute(
        """
        create table if not exists document_sections (
            section_id text primary key,
            doc_id text not null,
            parent_section_id text not null,
            section_title text not null,
            section_path text not null,
            section_kind text not null,
            section_level integer not null,
            source_locator text not null
        )
        """
    )
    connection.execute(
        """
        create table if not exists document_cards (
            doc_id text primary key,
            title text not null,
            summary text not null,
            keywords_json text not null default '[]',
            anchor_evidence_ids_json text not null default '[]',
            section_count integer not null default 0,
            evidence_count integer not null default 0,
            summary_method text not null default 'extractive-evidence',
            source_digest text not null default ''
        )
        """
    )
    connection.execute(
        """
        create table if not exists document_index_revisions (
            doc_id text primary key,
            source_fingerprint text not null,
            indexed_at text not null default current_timestamp
        )
        """
    )
    connection.execute(
        """
        create table if not exists library_catalog_revisions (
            singleton integer primary key check(singleton = 1),
            catalog_revision integer not null default 0,
            card_schema_version integer not null default 0,
            updated_at text not null default current_timestamp
        )
        """
    )
    connection.execute(
        "insert or ignore into library_catalog_revisions(singleton, catalog_revision, card_schema_version) values (1, 0, 0)"
    )
    connection.execute(
        """
        create table if not exists document_card_embeddings (
            doc_id text not null,
            provider text not null,
            dimensions integer not null,
            source_digest text not null,
            embedding_json text not null,
            updated_at text not null default current_timestamp,
            primary key (doc_id, provider, dimensions)
        )
        """
    )
    connection.execute(
        """
        create table if not exists knowledge_graph_nodes (
            node_id text primary key,
            node_type text not null,
            label text not null,
            metadata_json text not null default '{}'
        )
        """
    )
    connection.execute(
        """
        create table if not exists knowledge_graph_edges (
            edge_id text primary key,
            source_node_id text not null,
            target_node_id text not null,
            edge_type text not null,
            weight real not null default 1.0,
            anchor_evidence_ids_json text not null default '[]',
            metadata_json text not null default '{}'
        )
        """
    )
    connection.execute("create index if not exists idx_evidence_spans_doc_id on evidence_spans (doc_id)")
    connection.execute("create index if not exists idx_evidence_spans_section_id on evidence_spans (section_id)")
    connection.execute("create index if not exists idx_document_sections_doc_id on document_sections (doc_id)")
    connection.execute("create index if not exists idx_document_cards_title on document_cards (title)")
    connection.execute("create index if not exists idx_document_card_embeddings_provider on document_card_embeddings (provider, dimensions)")
    connection.execute("create index if not exists idx_knowledge_graph_nodes_type on knowledge_graph_nodes (node_type)")
    connection.execute("create index if not exists idx_knowledge_graph_edges_source on knowledge_graph_edges (source_node_id)")
    connection.execute("create index if not exists idx_knowledge_graph_edges_target on knowledge_graph_edges (target_node_id)")
    connection.execute(
        """
        create virtual table if not exists evidence_spans_fts using fts5(
            evidence_id unindexed,
            doc_id unindexed,
            title,
            section,
            text
        )
        """
    )


def _clear_index(connection: sqlite3.Connection) -> None:
    connection.execute("delete from knowledge_graph_edges")
    connection.execute("delete from knowledge_graph_nodes")
    connection.execute("delete from document_cards")
    connection.execute("delete from document_index_revisions")
    connection.execute("delete from evidence_spans_fts")
    connection.execute("delete from evidence_spans")
    connection.execute("delete from document_sections")
    connection.execute("delete from source_documents")


def _existing_document_ids(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("select doc_id from source_documents")
        if str(row[0] or "").strip()
    }


def _document_source_fingerprint(first_span: EvidenceSpan, spans: list[EvidenceSpan]) -> str:
    """Fingerprint original parsed structure, not a generated summary.

    The value lets a repeated import keep every unchanged source document and
    its existing vector rows.  It intentionally includes section placement and
    exact evidence text so an edited document cannot silently reuse an old
    card or vector generation.
    """

    digest = blake2b(digest_size=20)
    digest.update(
        "\x1f".join(
            (
                str(first_span.doc_id),
                str(first_span.title),
                str(first_span.doi or ""),
                str(first_span.source_url),
                str(first_span.publication_year or ""),
            )
        ).encode("utf-8")
    )
    for span in spans:
        digest.update(
            "\x1e".join(
                (
                    str(span.evidence_id),
                    str(span.section_id),
                    str(span.section_path),
                    str(span.block_id),
                    str(span.sentence_index),
                    str(span.text),
                )
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _stored_document_fingerprint(connection: sqlite3.Connection, doc_id: str) -> str:
    row = connection.execute(
        "select source_fingerprint from document_index_revisions where doc_id = ?",
        (doc_id,),
    ).fetchone()
    if row and str(row[0] or "").strip():
        return str(row[0])
    document = connection.execute(
        """
        select doc_id, title, doi, source_url, publication_year, html_path
        from source_documents where doc_id = ?
        """,
        (doc_id,),
    ).fetchone()
    if document is None:
        return ""
    spans = connection.execute(
        """
        select evidence_id, section_id, section_path, block_id, sentence_index, text
        from evidence_spans where doc_id = ? order by evidence_id
        """,
        (doc_id,),
    ).fetchall()
    digest = blake2b(digest_size=20)
    digest.update(
        "\x1f".join(str(value or "") for value in document[:5]).encode("utf-8")
    )
    for span in spans:
        digest.update("\x1e".join(str(value or "") for value in span).encode("utf-8"))
    return digest.hexdigest()


def _document_fingerprint_matches(connection: sqlite3.Connection, doc_id: str, fingerprint: str) -> bool:
    if doc_id not in _existing_document_ids(connection):
        return False
    existing = _stored_document_fingerprint(connection, doc_id)
    if not existing:
        return False
    if existing == fingerprint:
        _record_document_fingerprint(connection, doc_id, fingerprint)
        return True
    return False


def _record_document_fingerprint(connection: sqlite3.Connection, doc_id: str, fingerprint: str) -> None:
    connection.execute(
        """
        insert into document_index_revisions(doc_id, source_fingerprint, indexed_at)
        values (?, ?, current_timestamp)
        on conflict(doc_id) do update set
          source_fingerprint = excluded.source_fingerprint,
          indexed_at = current_timestamp
        """,
        (doc_id, fingerprint),
    )


def _delete_document_index_rows(connection: sqlite3.Connection, doc_id: str) -> None:
    """Remove only one source document; untouched rows and vectors survive."""

    connection.execute("delete from evidence_spans_fts where doc_id = ?", (doc_id,))
    connection.execute("delete from evidence_spans where doc_id = ?", (doc_id,))
    connection.execute("delete from document_sections where doc_id = ?", (doc_id,))
    connection.execute("delete from document_cards where doc_id = ?", (doc_id,))
    connection.execute("delete from document_index_revisions where doc_id = ?", (doc_id,))
    connection.execute("delete from source_documents where doc_id = ?", (doc_id,))


def _mark_vector_generations_stale(connection: sqlite3.Connection) -> None:
    """Keep old vectors on disk but never serve them after a source edit.

    The next background vector pass can reuse unchanged row digests. Until it
    activates a complete generation, retrieval uses the document catalogue and
    SQLite full-text route instead of mixing fresh text with a stale vector.
    """

    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'scansci_vector_index_generations'"
    ).fetchone()
    if row:
        connection.execute(
            "update scansci_vector_index_generations set state = 'stale' where state = 'active'"
        )


def _insert_document(connection: sqlite3.Connection, first_span: EvidenceSpan, evidence_html_path: Path | None) -> None:
    connection.execute(
        """
        insert into source_documents (
            doc_id, title, doi, source_url, publication_year, html_path, evidence_html_path
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            first_span.doc_id,
            first_span.title,
            first_span.doi,
            first_span.source_url,
            first_span.publication_year,
            first_span.html_path,
            evidence_html_path.as_posix() if evidence_html_path else "",
        ),
    )


def _insert_spans(connection: sqlite3.Connection, spans: list[EvidenceSpan]) -> None:
    rows = [tuple(span.to_dict()[column] for column in SPAN_COLUMNS) for span in spans]
    placeholders = ", ".join("?" for _ in SPAN_COLUMNS)
    connection.executemany(
        f"insert into evidence_spans ({', '.join(SPAN_COLUMNS)}) values ({placeholders})",
        rows,
    )
    connection.executemany(
        """
        insert into evidence_spans_fts (evidence_id, doc_id, title, section, text)
        values (?, ?, ?, ?, ?)
        """,
        ((span.evidence_id, span.doc_id, span.title, span.section, span.text) for span in spans),
    )
    _insert_sections(connection, spans)


def _insert_sections(connection: sqlite3.Connection, spans: list[EvidenceSpan]) -> None:
    """Materialize document → section nodes alongside sentence evidence.

    Storing these nodes separately is the missing middle of the document /
    section / evidence chain.  It also lets graph retrieval use structure
    later without reparsing every source file.
    """

    rows: dict[str, tuple[str, str, str, str, str, int, str]] = {}
    for span in spans:
        path_parts = [part.strip() for part in str(span.section_path or span.section or "正文").split(" / ") if part.strip()]
        if not path_parts:
            path_parts = ["正文"]
        for index, title in enumerate(path_parts, start=1):
            path = " / ".join(path_parts[:index])
            section_id = _section_id_for_path(span.doc_id, path)
            parent_path = " / ".join(path_parts[: index - 1])
            parent_section_id = _section_id_for_path(span.doc_id, parent_path) if parent_path else ""
            is_leaf = index == len(path_parts)
            rows.setdefault(
                section_id,
                (
                    section_id,
                    span.doc_id,
                    parent_section_id,
                    title,
                    path,
                    span.section_kind if is_leaf else "other",
                    max(0, int(span.section_level or 0) - (len(path_parts) - index)),
                    span.source_locator if is_leaf else "",
                ),
            )
    connection.executemany(
        """
        insert into document_sections (
            section_id, doc_id, parent_section_id, section_title, section_path,
            section_kind, section_level, source_locator
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows.values(),
    )


def _section_id_for_path(doc_id: str, section_path: str) -> str:
    # Keep the same derivation as evidence_spans._section_id without importing
    # another private helper into public index consumers.
    readable = re.sub(r"[^a-z0-9]+", "-", str(section_path).lower()).strip("-")[:56] or "root"
    digest = blake2b(str(section_path).encode("utf-8"), digest_size=5).hexdigest()
    return f"{doc_id}.sec.{readable}-{digest}"


def _spans_with_html_path(spans: list[EvidenceSpan], html_path: Path) -> list[EvidenceSpan]:
    normalized_path = html_path.as_posix()
    return [replace(span, html_path=normalized_path) for span in spans]


def _span_rows(db_path: Path) -> Iterable[dict[str, object]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute(
            f"select {', '.join(SPAN_COLUMNS)} from evidence_spans order by evidence_id"
        ):
            yield dict(row)


def _split_markdown_front_matter(markdown_text: str) -> tuple[dict[str, str], str]:
    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown_text
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return metadata, "\n".join(lines[index + 1 :])
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key:
            metadata[normalized_key] = value.strip().strip('"').strip("'")
    return {}, markdown_text


def _markdown_title(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return _strip_markdown_inline(match.group(1))
    return ""


def _metadata_year(metadata: dict[str, str]) -> int | None:
    for key in ("publication_year", "published_year", "year", "date", "publication_date"):
        year = _year_from_text(str(metadata.get(key, "")))
        if year is not None:
            return year
    return None


def _iter_markdown_blocks(markdown_text: str) -> Iterable[tuple[str, int, str]]:
    paragraph_lines: list[str] = []
    in_fence = False

    def flush_paragraph() -> tuple[str, int, str] | None:
        if not paragraph_lines:
            return None
        source_lines = _without_pdf_running_header(list(paragraph_lines))
        text = " ".join(_strip_markdown_inline(line) for line in source_lines).strip()
        paragraph_lines.clear()
        return ("paragraph", 0, text) if text else None

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            continue
        implicit_heading = _implicit_markdown_heading(stripped)
        if implicit_heading:
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            yield ("heading", 2, implicit_heading)
            continue
        heading_match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading_match:
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            yield ("heading", len(heading_match.group(1)), _strip_markdown_inline(heading_match.group(2)))
            continue
        list_match = re.match(r"^\s*(?:[-*+]\s+|\d+[\).]\s+)(.+?)\s*$", line)
        if list_match:
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            yield ("list_item", 0, _strip_markdown_inline(list_match.group(1)))
            continue
        if _is_markdown_table_row(stripped):
            pending = flush_paragraph()
            if pending is not None:
                yield pending
            if not _is_markdown_table_separator(stripped):
                yield ("table_row", 0, _markdown_table_row_text(stripped))
            continue
        paragraph_lines.append(stripped)
    pending = flush_paragraph()
    if pending is not None:
        yield pending


def _implicit_markdown_heading(line: str) -> str:
    """Recognize high-confidence headings emitted by plain-text PDF extractors.

    PDF text often preserves a standalone ``References`` line but loses the
    Markdown marker.  Treating only a small, explicit vocabulary as headings
    keeps this high precision and prevents bibliography rows from becoming
    retrievable evidence.
    """

    candidate = re.sub(r"\s+", " ", str(line or "")).strip()
    if not candidate or len(candidate) > 90 or candidate.endswith(("。", ".", "！", "!", "？", "?", "；", ";")):
        return ""
    normalized = re.sub(r"^[\d.()\-\s]+", "", candidate).strip().lower()
    known = {
        "abstract",
        "摘要",
        "introduction",
        "intro",
        "引言",
        "前言",
        "materials and methods",
        "materials & methods",
        "methods",
        "methodology",
        "材料与方法",
        "材料與方法",
        "研究方法",
        "实验方法",
        "實驗方法",
        "results",
        "result",
        "结果",
        "結果",
        "discussion",
        "讨论",
        "討論",
        "conclusion",
        "conclusions",
        "结论",
        "結論",
        "references",
        "references and notes",
        "bibliography",
        "参考文献",
        "參考文獻",
        "acknowledgements",
        "acknowledgments",
        "致谢",
        "致謝",
    }
    return candidate if normalized in known else ""


def _is_page_heading(value: str) -> bool:
    return bool(re.fullmatch(r"(?:第\s*)?\d+\s*页|page\s*\d+", str(value or "").strip(), flags=re.IGNORECASE))


def _without_pdf_running_header(lines: list[str]) -> list[str]:
    """Drop only the explicit `[Highlight]` running header emitted by PDFs.

    Some journal PDFs start each page with a highlight marker, URL, journal
    name, DOI, title and affiliation before the first prose line.  Those are
    useful document metadata but bad retrieval evidence.  We trim them only
    when the marker is explicit and stop at the first sentence-like prose line
    so normal Markdown notes are never altered.
    """

    if not lines or not lines[0].strip().lower().startswith("[highlight]"):
        return lines
    for index, line in enumerate(lines[1:], start=1):
        candidate = line.strip()
        if len(candidate) < 24:
            continue
        if candidate.endswith(("。", "！", "？", ".", "!", "?")) and not re.search(r"\bdoi\s*:", candidate, re.I):
            return lines[index:]
    return []


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2 and (stripped.startswith("|") or stripped.endswith("|"))


def _is_markdown_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _markdown_table_row_text(line: str) -> str:
    cells = [_strip_markdown_inline(cell.strip()) for cell in line.strip("|").split("|")]
    return " | ".join(cell for cell in cells if cell)


def _strip_markdown_inline(text: str) -> str:
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    # Do not strip every `*`, `_` or `~`: those characters are meaningful in
    # formulas, identifiers and extracted PDF text (for example `~0.3 eV`).
    # Remove only paired Markdown emphasis delimiters.
    for marker in ("***", "___", "**", "__", "~~", "*", "_"):
        escaped = re.escape(marker)
        value = re.sub(rf"(?<!\w){escaped}(?=\S)(.*?\S){escaped}(?!\w)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _iter_source_html_files(library_path: Path) -> Iterable[Path]:
    return sorted(
        path
        for path in library_path.rglob("*.html")
        if _is_source_html_file(path, library_path)
    )


def _is_source_html_file(path: Path, library_path: Path) -> bool:
    if not path.is_file():
        return False
    if is_ignored_library_path(path, library_path):
        return False
    if path.name.endswith(".evidence.html") or path.name.endswith(".raw.html"):
        return False
    try:
        relative_parts = path.relative_to(library_path).parts
    except ValueError:
        relative_parts = path.parts
    normalized_parts = {part.lower() for part in relative_parts}
    if "_rejected_preview" in normalized_parts or "raw-snapshots" in normalized_parts:
        return False
    return not any(part.lower().endswith("_files") for part in relative_parts)


def _iter_source_markdown_files(
    library_path: Path,
    *,
    include_support_directories: bool = False,
) -> Iterable[Path]:
    return sorted(
        path
        for extension in ("*.md", "*.markdown")
        for path in library_path.rglob(extension)
        if _is_source_markdown_file(
            path,
            library_path,
            include_support_directories=include_support_directories,
        )
    )


def _is_source_markdown_file(
    path: Path,
    library_path: Path,
    *,
    include_support_directories: bool = False,
) -> bool:
    if not path.is_file():
        return False
    if is_ignored_library_path(path, library_path):
        return False
    try:
        relative_parts = path.relative_to(library_path).parts
    except ValueError:
        relative_parts = path.parts
    if any(part.startswith(".") for part in relative_parts):
        return False
    normalized_parts = {part.lower() for part in relative_parts}
    if not include_support_directories and (
        "assets" in normalized_parts or "json" in normalized_parts or "raw" in normalized_parts
    ):
        return False
    if "_rejected_preview" in normalized_parts or "raw-snapshots" in normalized_parts:
        return False
    return True


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {str(row[1]) for row in connection.execute(f"pragma table_info({table_name})")}
    if column_name not in columns:
        connection.execute(f"alter table {table_name} add column {column_name} {column_type}")
