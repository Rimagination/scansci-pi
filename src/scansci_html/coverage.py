from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import sqlite3
from typing import Any


def build_corpus_coverage(db_path: str | Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        documents = [dict(row) for row in connection.execute("select * from source_documents order by doc_id")]
        spans = [
            dict(row)
            for row in connection.execute(
                """
                select doc_id, section_kind, block_type
                from evidence_spans
                order by doc_id, evidence_id
                """
            )
        ]

    global_section_counts = Counter(str(span.get("section_kind", "")) for span in spans)
    global_block_counts = Counter(str(span.get("block_type", "")) for span in spans)
    spans_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in spans:
        spans_by_doc[str(span.get("doc_id", ""))].append(span)

    document_summaries = []
    for document in documents:
        doc_id = str(document.get("doc_id", ""))
        doc_spans = spans_by_doc.get(doc_id, [])
        document_summaries.append(
            {
                "doc_id": doc_id,
                "title": str(document.get("title", "")),
                "doi": str(document.get("doi", "")),
                "evidence_spans": len(doc_spans),
                "section_kind_counts": _sorted_counts(
                    Counter(str(span.get("section_kind", "")) for span in doc_spans)
                ),
                "block_type_counts": _sorted_counts(
                    Counter(str(span.get("block_type", "")) for span in doc_spans)
                ),
            }
        )

    return {
        "documents": len(documents),
        "evidence_spans": len(spans),
        "section_kind_counts": _sorted_counts(global_section_counts),
        "block_type_counts": _sorted_counts(global_block_counts),
        "document_summaries": document_summaries,
    }


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter) if key}
