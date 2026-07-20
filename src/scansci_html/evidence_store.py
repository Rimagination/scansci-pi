from __future__ import annotations

from dataclasses import replace
from hashlib import blake2b
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable

from .evidence_spans import (
    EvidenceSpan,
    _inherited_section_kind,
    _is_non_evidence_section,
    _section_kind,
    _sentence_offsets,
    _year_from_text,
    evidence_html_path_for,
    extract_evidence_spans,
    write_evidence_html,
)
from .resolver import safe_identifier_part


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
)


def index_evidence_library(
    library_dir: str | Path,
    *,
    db_path: str | Path,
    inject_evidence_html: bool = False,
    min_sentence_length: int = 40,
) -> dict[str, object]:
    library_path = Path(library_dir)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)

    documents = 0
    span_count = 0
    evidence_html_files = 0
    duplicate_documents_skipped = 0
    seen_doc_ids: set[str] = set()
    with sqlite3.connect(db) as connection:
        _initialize_schema(connection)
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
            _insert_document(connection, document_span or spans[0], output_path)
            _insert_spans(connection, spans)
        connection.commit()
    connection.close()

    return {
        "documents": documents,
        "spans": span_count,
        "db_path": str(db),
        "evidence_html_files": evidence_html_files,
        "duplicate_documents_skipped": duplicate_documents_skipped,
    }


def index_markdown_library(
    library_dir: str | Path,
    *,
    db_path: str | Path,
    min_sentence_length: int = 40,
) -> dict[str, object]:
    library_path = Path(library_dir)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)

    documents = 0
    span_count = 0
    duplicate_documents_skipped = 0
    seen_doc_ids: set[str] = set()
    with sqlite3.connect(db) as connection:
        _initialize_schema(connection)
        _clear_index(connection)
        for markdown_file in _iter_source_markdown_files(library_path):
            spans = extract_markdown_evidence_spans(
                markdown_file.read_text(encoding="utf-8-sig"),
                markdown_path=markdown_file,
                min_sentence_length=min_sentence_length,
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
            _insert_document(connection, document_span, None)
            _insert_spans(connection, spans)
        connection.commit()
    connection.close()

    return {
        "documents": documents,
        "spans": span_count,
        "db_path": str(db),
        "duplicate_documents_skipped": duplicate_documents_skipped,
    }


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
    local_identity = f"{title}-{Path(markdown_path).stem}".strip("-")
    raw_identity = doi or remote_source or local_identity or normalized_path
    doc_id = safe_identifier_part(raw_identity)
    if doc_id == "paper":
        digest = blake2b(raw_identity.encode("utf-8"), digest_size=10).hexdigest()
        doc_id = f"local-{digest}"

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
            while section_stack and section_stack[-1][0] >= int(level or 1):
                section_stack.pop()
            direct_kind = _section_kind(heading_text)
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
                    section=current_section,
                    section_kind=section_kind,
                    block_id=f"{doc_id}:{block_anchor}",
                    block_type=block_type,
                    sentence_index=sentence_index,
                    char_start=char_start,
                    char_end=char_end,
                    text=sentence_text,
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
            text text not null
        )
        """
    )
    _ensure_column(connection, "source_documents", "publication_year", "integer")
    _ensure_column(connection, "evidence_spans", "publication_year", "integer")
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
    connection.execute("delete from evidence_spans_fts")
    connection.execute("delete from evidence_spans")
    connection.execute("delete from source_documents")


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
        text = " ".join(_strip_markdown_inline(line) for line in paragraph_lines).strip()
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
    value = re.sub(r"[*_~]+", "", value)
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


def _iter_source_markdown_files(library_path: Path) -> Iterable[Path]:
    return sorted(
        path
        for extension in ("*.md", "*.markdown")
        for path in library_path.rglob(extension)
        if _is_source_markdown_file(path, library_path)
    )


def _is_source_markdown_file(path: Path, library_path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        relative_parts = path.relative_to(library_path).parts
    except ValueError:
        relative_parts = path.parts
    normalized_parts = {part.lower() for part in relative_parts}
    if "assets" in normalized_parts or "json" in normalized_parts or "raw" in normalized_parts:
        return False
    if "_rejected_preview" in normalized_parts or "raw-snapshots" in normalized_parts:
        return False
    return True


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {str(row[1]) for row in connection.execute(f"pragma table_info({table_name})")}
    if column_name not in columns:
        connection.execute(f"alter table {table_name} add column {column_name} {column_type}")
