from __future__ import annotations

from collections.abc import Iterable
import csv
from html import escape
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .annotation_layers import load_annotation_layers


REVIEW_MATRIX_FIELDS = [
    "question",
    "question_type",
    "layer_id",
    "layer_name",
    "layer_question",
    "query_plan",
    "retrieval_filters",
    "retrieval_queries",
    "evidence_sufficient",
    "adequacy_profile",
    "adequacy_quote_count",
    "adequacy_min_quotes",
    "adequacy_document_count",
    "adequacy_min_documents",
    "adequacy_followup_reason",
    "claim_id",
    "segment_id",
    "item_id",
    "review_state",
    "topic",
    "claim_text",
    "support_status",
    "verification_score",
    "quote_id",
    "stance",
    "exact_quote",
    "paper",
    "section",
    "section_kind",
    "doi",
    "doc_id",
    "publication_year",
    "evidence_id",
    "html_path",
    "html_anchor",
    "source_href",
    "confidence",
]

DISPLAYABLE_REVIEW_SUPPORT_STATUSES = {"supported", "partial_support"}
CONFIRMED_REVIEW_STATES = {"confirmed", "approved", "verified"}
REVIEW_TRANSFORMATION_TEMPLATES = {"glossary", "timeline", "methods", "report"}


def build_review_matrix(report_payload: dict[str, Any]) -> list[dict[str, Any]]:
    question = str(report_payload.get("question", ""))
    evidence_rows = list(report_payload.get("evidence_table", []) or [])
    claim_by_quote_id = _claim_by_quote_id(report_payload)
    retrieval_context = _retrieval_context(report_payload)
    rows: list[dict[str, Any]] = []
    for evidence in evidence_rows:
        quote_id = str(evidence.get("quote_id", ""))
        claim = claim_by_quote_id.get(quote_id, {})
        rows.append(
            {
                "question": question,
                **retrieval_context,
                "claim_id": str(claim.get("claim_id", "")),
                "claim_text": str(claim.get("text", evidence.get("claim_target", ""))),
                "support_status": str(claim.get("support_status", "")),
                "verification_score": claim.get("verification_score", ""),
                "quote_id": quote_id,
                "stance": str(evidence.get("stance", "")),
                "exact_quote": str(evidence.get("exact_quote", "")),
                "paper": str(evidence.get("paper", "")),
                "section": str(evidence.get("section", "")),
                "section_kind": str(evidence.get("section_kind", "")),
                "doi": str(evidence.get("doi", "")),
                "evidence_id": str(evidence.get("evidence_id", "")),
                "html_path": str(evidence.get("html_path", "")),
                "html_anchor": str(evidence.get("html_anchor", "")),
                "confidence": evidence.get("confidence", ""),
            }
        )
    return rows


def build_review_matrix_from_annotation_layers(
    layer_db_path: str | Path,
    *,
    layer_ids: Iterable[str] | None = None,
    support_statuses: Iterable[str] | None = None,
    review_states: Iterable[str] | None = None,
    confirmed_only: bool = False,
) -> list[dict[str, Any]]:
    status_set = (
        _normalized_filter_set(support_statuses)
        if support_statuses is not None
        else set(DISPLAYABLE_REVIEW_SUPPORT_STATUSES)
    )
    review_state_set = set(CONFIRMED_REVIEW_STATES) if confirmed_only else _normalized_filter_set(review_states)
    layers = load_annotation_layers(
        layer_db_path,
        layer_ids=[str(layer_id) for layer_id in layer_ids] if layer_ids else None,
    )
    rows: list[dict[str, Any]] = []
    for layer in layers:
        layer_payload = _dict_or_empty(layer.get("payload"))
        evidence_cards = {
            str(card.get("citation_id", "")): dict(card)
            for card in list(layer_payload.get("evidence_cards", []) or [])
            if isinstance(card, dict)
        }
        for raw_item in layer.get("items", []) or []:
            item = dict(raw_item or {})
            support_status = str(item.get("support_status", "") or "")
            if status_set and _normalized_value(support_status) not in status_set:
                continue
            review_state = str(item.get("review_state", "") or "")
            if review_state_set and _normalized_value(review_state) not in review_state_set:
                continue
            payload = _dict_or_empty(item.get("payload"))
            segment = _dict_or_empty(payload.get("segment"))
            evidence = _dict_or_empty(payload.get("evidence"))
            card = evidence_cards.get(str(item.get("citation_id", "") or ""), {})
            evidence_view = {**card, **evidence}
            claim_text = str(item.get("claim_text") or segment.get("text") or "")
            quote = str(item.get("quote") or evidence_view.get("exact_quote") or "")
            row = {
                "question": str(layer.get("question") or layer.get("source_text") or ""),
                "question_type": "grounded_annotation",
                "layer_id": str(layer.get("layer_id", "") or ""),
                "layer_name": str(layer.get("name", "") or ""),
                "layer_question": str(layer.get("question", "") or ""),
                "query_plan": "",
                "retrieval_filters": "",
                "retrieval_queries": _annotation_retrieval_queries_summary(evidence_view),
                "evidence_sufficient": "",
                "adequacy_profile": "",
                "adequacy_quote_count": "",
                "adequacy_min_quotes": "",
                "adequacy_document_count": "",
                "adequacy_min_documents": "",
                "adequacy_followup_reason": "",
                "claim_id": str(item.get("segment_id") or segment.get("segment_id") or ""),
                "segment_id": str(item.get("segment_id") or segment.get("segment_id") or ""),
                "item_id": str(item.get("item_id", "") or ""),
                "review_state": review_state,
                "topic": _topic_from_claim(claim_text),
                "claim_text": claim_text,
                "support_status": support_status,
                "verification_score": item.get("support_score", ""),
                "quote_id": str(item.get("citation_id") or evidence_view.get("citation_id") or ""),
                "stance": _stance_from_support_status(support_status),
                "exact_quote": quote,
                "paper": str(evidence_view.get("title", "") or ""),
                "section": str(evidence_view.get("section", "") or ""),
                "section_kind": str(evidence_view.get("section_kind", "") or ""),
                "doi": str(evidence_view.get("doi", "") or ""),
                "doc_id": str(item.get("doc_id") or evidence_view.get("doc_id") or ""),
                "publication_year": evidence_view.get("publication_year", ""),
                "evidence_id": str(item.get("evidence_id") or evidence_view.get("evidence_id") or ""),
                "html_path": str(item.get("html_path") or evidence_view.get("html_path") or ""),
                "html_anchor": str(item.get("html_anchor") or evidence_view.get("html_anchor") or ""),
                "source_href": str(item.get("source_href") or evidence_view.get("source_href") or ""),
                "confidence": item.get("support_score", ""),
            }
            rows.append(row)
    return rows


def filter_review_matrix_rows(
    rows: Iterable[dict[str, Any]],
    *,
    support_statuses: Iterable[str] | None = None,
    question_types: Iterable[str] | None = None,
    section_kinds: Iterable[str] | None = None,
    review_states: Iterable[str] | None = None,
    evidence_sufficient: bool | None = None,
) -> list[dict[str, Any]]:
    support_status_set = _normalized_filter_set(support_statuses)
    question_type_set = _normalized_filter_set(question_types)
    section_kind_set = _normalized_filter_set(section_kinds)
    review_state_set = _normalized_filter_set(review_states)
    result: list[dict[str, Any]] = []
    for row in rows:
        if support_status_set and _normalized_value(row.get("support_status")) not in support_status_set:
            continue
        if question_type_set and _normalized_value(row.get("question_type")) not in question_type_set:
            continue
        if section_kind_set and _normalized_value(row.get("section_kind")) not in section_kind_set:
            continue
        if review_state_set and _normalized_value(row.get("review_state")) not in review_state_set:
            continue
        if evidence_sufficient is not None:
            row_evidence_sufficient = _optional_bool_value(row.get("evidence_sufficient"))
            if row_evidence_sufficient is not evidence_sufficient:
                continue
        result.append(dict(row))
    return result


def review_matrix_fields(fields: Iterable[str] | None = None) -> list[str]:
    if fields is None:
        return list(REVIEW_MATRIX_FIELDS)
    selected = [str(field).strip() for field in fields if str(field).strip()]
    if not selected:
        return list(REVIEW_MATRIX_FIELDS)
    unknown = [field for field in selected if field not in REVIEW_MATRIX_FIELDS]
    if unknown:
        raise ValueError(f"Unknown review matrix columns: {', '.join(unknown)}")
    return selected


def _retrieval_context(report_payload: dict[str, Any]) -> dict[str, Any]:
    query_plan = _dict_or_empty(report_payload.get("query_plan", {}))
    adequacy = _dict_or_empty(report_payload.get("adequacy", {}))
    retrieval_queries = [
        str(query)
        for query in list(report_payload.get("retrieval_queries", []) or [])
        if str(query).strip()
    ]
    filters = _dict_or_empty(query_plan.get("filters", {}))
    return {
        "question_type": str(query_plan.get("question_type", "")),
        "query_plan": _json_summary(query_plan),
        "retrieval_filters": _json_summary(filters),
        "retrieval_queries": " | ".join(retrieval_queries),
        "evidence_sufficient": adequacy.get("is_sufficient", ""),
        "adequacy_profile": str(adequacy.get("profile", "")),
        "adequacy_quote_count": adequacy.get("quote_count", ""),
        "adequacy_min_quotes": adequacy.get("min_quotes", ""),
        "adequacy_document_count": adequacy.get("document_count", ""),
        "adequacy_min_documents": adequacy.get("min_documents", ""),
        "adequacy_followup_reason": str(adequacy.get("followup_reason", "")),
    }


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _json_summary(value: Any) -> str:
    if value in ({}, [], None, ""):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_review_matrix(
    rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    output_format: str = "csv",
    fields: Iterable[str] | None = None,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    format_name = output_format.strip().lower()
    fieldnames = review_matrix_fields(fields)
    if format_name == "csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return
    if format_name == "json":
        projected_rows = [{field: row.get(field, "") for field in fieldnames} for row in rows]
        path.write_text(json.dumps(projected_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if format_name == "html":
        path.write_text(_render_review_matrix_html(rows, fieldnames), encoding="utf-8")
        return
    raise ValueError(f"Unsupported review matrix format: {output_format}")


def read_review_matrix_rows(input_path: str | Path, *, input_format: str = "") -> list[dict[str, Any]]:
    path = Path(input_path)
    format_name = (input_format or path.suffix.lstrip(".") or "csv").strip().lower()
    if format_name == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else payload.get("records", [])
        return [dict(row) for row in list(payload or []) if isinstance(row, dict)]
    if format_name == "csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    raise ValueError(f"Unsupported review matrix input format: {input_format or path.suffix}")


def apply_review_matrix_to_annotation_layers(
    layer_db_path: str | Path,
    review_rows: Iterable[dict[str, Any]],
    *,
    state_column: str = "review_state",
) -> dict[str, int]:
    rows = [dict(row) for row in review_rows]
    updated = 0
    skipped = 0
    with sqlite3.connect(Path(layer_db_path)) as connection:
        for row in rows:
            review_state = str(row.get(state_column, "") or "").strip()
            if not review_state:
                skipped += 1
                continue
            item_id = str(row.get("item_id", "") or "").strip()
            if item_id:
                cursor = connection.execute(
                    "update annotation_items set review_state = ? where item_id = ?",
                    (review_state, item_id),
                )
            else:
                layer_id = str(row.get("layer_id", "") or "").strip()
                segment_id = str(row.get("segment_id") or row.get("claim_id") or "").strip()
                evidence_id = str(row.get("evidence_id", "") or "").strip()
                if not layer_id or not segment_id or not evidence_id:
                    skipped += 1
                    continue
                cursor = connection.execute(
                    """
                    update annotation_items
                    set review_state = ?
                    where layer_id = ? and segment_id = ? and evidence_id = ?
                    """,
                    (review_state, layer_id, segment_id, evidence_id),
                )
            if int(cursor.rowcount or 0) > 0:
                updated += int(cursor.rowcount or 0)
            else:
                skipped += 1
        connection.commit()
    return {"rows": len(rows), "updated": updated, "skipped": skipped}


def confirmed_review_rows(
    rows: Iterable[dict[str, Any]],
    *,
    review_states: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    materialized = [dict(row) for row in rows]
    selected_states = _normalized_filter_set(review_states) or set(CONFIRMED_REVIEW_STATES)
    has_review_state = any(str(row.get("review_state", "") or "").strip() for row in materialized)
    if not has_review_state:
        return materialized
    return [row for row in materialized if _normalized_value(row.get("review_state")) in selected_states]


def write_review_transformation(
    rows: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    template: str,
    output_format: str = "md",
) -> None:
    template_name = template.strip().lower()
    if template_name not in REVIEW_TRANSFORMATION_TEMPLATES:
        raise ValueError(f"Unsupported review transformation template: {template}")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = confirmed_review_rows(rows)
    records = build_review_transformation_records(materialized, template=template_name)
    format_name = output_format.strip().lower()
    if format_name == "json":
        path.write_text(
            json.dumps(
                {
                    "template": template_name,
                    "rows": len(materialized),
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    markdown = render_review_transformation_markdown(records, template=template_name)
    if format_name in {"md", "markdown"}:
        path.write_text(markdown, encoding="utf-8")
        return
    if format_name == "html":
        path.write_text(_render_markdown_pre_html(markdown, title=_template_title(template_name)), encoding="utf-8")
        return
    raise ValueError(f"Unsupported review transformation format: {output_format}")


def build_review_transformation_records(
    rows: Iterable[dict[str, Any]],
    *,
    template: str,
) -> list[dict[str, Any]]:
    materialized = [dict(row) for row in rows]
    if template == "timeline":
        materialized.sort(key=lambda row: (_year_sort_key(row), _source_label(row), str(row.get("evidence_id", ""))))
    else:
        materialized.sort(key=lambda row: (_topic_from_review_row(row), _source_label(row), str(row.get("evidence_id", ""))))
    records: list[dict[str, Any]] = []
    for row in materialized:
        source = _source_label(row)
        href = _source_href_from_row(row)
        records.append(
            {
                "topic": _topic_from_review_row(row),
                "claim": str(row.get("claim_text", "") or ""),
                "quote": str(row.get("exact_quote", "") or ""),
                "source": source,
                "source_href": href,
                "paper": str(row.get("paper", "") or ""),
                "doi": str(row.get("doi", "") or ""),
                "year": _year_text(row),
                "section": str(row.get("section", "") or ""),
                "section_kind": str(row.get("section_kind", "") or ""),
                "evidence_id": str(row.get("evidence_id", "") or ""),
                "review_state": str(row.get("review_state", "") or ""),
                "support_status": str(row.get("support_status", "") or ""),
            }
        )
    return records


def render_review_transformation_markdown(records: list[dict[str, Any]], *, template: str) -> str:
    if template == "glossary":
        return _render_glossary_markdown(records)
    if template == "timeline":
        return _render_timeline_markdown(records)
    if template == "methods":
        return _render_methods_markdown(records)
    if template == "report":
        return _render_report_draft_markdown(records)
    raise ValueError(f"Unsupported review transformation template: {template}")


def _normalized_filter_set(values: Iterable[str] | None) -> set[str]:
    if not values:
        return set()
    return {_normalized_value(value) for value in values if _normalized_value(value)}


def _normalized_value(value: Any) -> str:
    return str(value or "").strip().lower()


def _optional_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return normalized in {"1", "true", "yes", "y"}


def _annotation_retrieval_queries_summary(evidence: dict[str, Any]) -> str:
    queries: list[str] = []
    for raw_query in list(evidence.get("retrieval_queries", []) or []):
        if isinstance(raw_query, dict):
            query = str(raw_query.get("query", "") or "").strip()
        else:
            query = str(raw_query or "").strip()
        if query and query not in queries:
            queries.append(query)
    return " | ".join(queries)


def _stance_from_support_status(value: str) -> str:
    status = _normalized_value(value)
    if status == "supported":
        return "supports"
    if status == "partial_support":
        return "partially_supports"
    if status == "unsupported":
        return "does_not_support"
    return status


def _topic_from_claim(value: str) -> str:
    text = _single_line(value)
    text = re.sub(r"^[\s\-\*\d\.\)\uff08\uff09]+", "", text).strip()
    if not text:
        return "未命名主题"
    first_clause = re.split(r"[。；;:：，,]", text, maxsplit=1)[0].strip()
    if first_clause:
        text = first_clause
    return _short_text(text, 42) or "未命名主题"


def _topic_from_review_row(row: dict[str, Any]) -> str:
    for key in ("topic", "term", "entity", "method"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return _short_text(value, 42)
    return _topic_from_claim(str(row.get("claim_text", "") or row.get("exact_quote", "") or ""))


def _year_text(row: dict[str, Any]) -> str:
    value = row.get("publication_year", "")
    if value not in ("", None):
        match = re.search(r"(?:19|20)\d{2}", str(value))
        if match:
            return match.group(0)
    for key in ("paper", "claim_text", "exact_quote"):
        match = re.search(r"(?:19|20)\d{2}", str(row.get(key, "") or ""))
        if match:
            return match.group(0)
    return ""


def _year_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    year = _year_text(row)
    return (int(year) if year else 9999, str(row.get("evidence_id", "") or ""))


def _source_href_from_row(row: dict[str, Any]) -> str:
    source_href = str(row.get("source_href", "") or "").strip()
    if source_href:
        return source_href
    html_path = str(row.get("html_path", "") or "").strip()
    html_anchor = str(row.get("html_anchor", "") or "").strip()
    if not html_path:
        return ""
    if not html_anchor:
        return html_path
    return f"{html_path}#{html_anchor}"


def _source_label(row: dict[str, Any]) -> str:
    return (
        str(row.get("paper", "") or "").strip()
        or str(row.get("doi", "") or "").strip()
        or str(row.get("evidence_id", "") or "").strip()
        or "source"
    )


def _source_markdown(record: dict[str, Any]) -> str:
    label = _escape_markdown_link_label(_short_text(str(record.get("source", "") or "source"), 80))
    href = str(record.get("source_href", "") or "").strip()
    evidence_id = str(record.get("evidence_id", "") or "").strip()
    suffix = f" `{evidence_id}`" if evidence_id else ""
    if href:
        return f"[{label}]({href}){suffix}"
    return f"{label}{suffix}"


def _render_glossary_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# 术语表",
        "",
        "| 术语/主题 | 证据结论 | 原文证据 | 来源 |",
        "|---|---|---|---|",
    ]
    if not records:
        lines.append("| 暂无已确认证据 |  |  |  |")
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(str(record.get("topic", "") or "")),
                    _md_cell(_short_text(str(record.get("claim", "") or ""), 160)),
                    _md_cell(_short_text(str(record.get("quote", "") or ""), 220)),
                    _md_cell(_source_markdown(record)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _render_timeline_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# 时间线",
        "",
        "| 年份 | 主题 | 证据结论 | 原文证据 | 来源 |",
        "|---|---|---|---|---|",
    ]
    if not records:
        lines.append("| 暂无已确认证据 |  |  |  |  |")
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(str(record.get("year", "") or "未标年")),
                    _md_cell(str(record.get("topic", "") or "")),
                    _md_cell(_short_text(str(record.get("claim", "") or ""), 150)),
                    _md_cell(_short_text(str(record.get("quote", "") or ""), 200)),
                    _md_cell(_source_markdown(record)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _render_methods_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# 方法对比表",
        "",
        "| 方法/主题 | 研究场景 | 证据结论 | 原文证据 | 来源 |",
        "|---|---|---|---|---|",
    ]
    if not records:
        lines.append("| 暂无已确认证据 |  |  |  |  |")
    for record in records:
        context = " / ".join(
            part
            for part in [
                str(record.get("paper", "") or ""),
                str(record.get("section", "") or record.get("section_kind", "") or ""),
            ]
            if part
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(str(record.get("topic", "") or "")),
                    _md_cell(_short_text(context, 120)),
                    _md_cell(_short_text(str(record.get("claim", "") or ""), 150)),
                    _md_cell(_short_text(str(record.get("quote", "") or ""), 200)),
                    _md_cell(_source_markdown(record)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _render_report_draft_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# 证据综述草稿",
        "",
        "> 本草稿只使用已确认的证据行生成；每条结论都保留原文证据和来源链接。",
        "",
    ]
    if not records:
        lines.extend(["暂无已确认证据。", ""])
        return "\n".join(lines)
    current_topic = ""
    for record in records:
        topic = str(record.get("topic", "") or "未命名主题")
        if topic != current_topic:
            if current_topic:
                lines.append("")
            lines.append(f"## {topic}")
            current_topic = topic
        claim = _single_line(str(record.get("claim", "") or ""))
        quote = _single_line(str(record.get("quote", "") or ""))
        source = _source_markdown(record)
        if quote:
            lines.append(f"- {claim} 证据：\"{quote}\"。来源：{source}。")
        else:
            lines.append(f"- {claim} 来源：{source}。")
    return "\n".join(lines) + "\n"


def _render_markdown_pre_html(markdown: str, *, title: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.55; margin: 2rem; color: #17202a; }",
            "    main { max-width: 960px; margin: 0 auto; }",
            "    pre { white-space: pre-wrap; word-break: break-word; background: #f8fafc; padding: 1rem; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            f"  <pre>{escape(markdown)}</pre>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _template_title(template: str) -> str:
    return {
        "glossary": "术语表",
        "timeline": "时间线",
        "methods": "方法对比表",
        "report": "证据综述草稿",
    }.get(template, template)


def _md_cell(value: str) -> str:
    return _single_line(value).replace("|", "\\|")


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _short_text(value: str, limit: int) -> str:
    text = _single_line(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _escape_markdown_link_label(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]")


def _claim_by_quote_id(report_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    answer = dict(report_payload.get("answer", {}) or {})
    claims = list(answer.get("answer", []) or [])
    result: dict[str, dict[str, Any]] = {}
    for claim in claims:
        for quote_id in claim.get("quote_ids", []) or []:
            result[str(quote_id)] = dict(claim)
    return result


def _render_review_matrix_html(rows: list[dict[str, Any]], fields: list[str]) -> str:
    body_rows = "\n".join(_render_review_matrix_row(row, fields) for row in rows)
    if not body_rows:
        body_rows = f'        <tr><td colspan="{len(fields)}">No evidence rows.</td></tr>'
    headers = "".join(f"<th>{escape(field)}</th>" for field in fields)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            "  <title>ScanSci Review Matrix</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.45; margin: 2rem; color: #17202a; }",
            "    main { max-width: 1280px; margin: 0 auto; }",
            "    table { border-collapse: collapse; width: 100%; }",
            "    th, td { border-top: 1px solid #d7dee8; padding: .45rem; text-align: left; vertical-align: top; }",
            "    th { position: sticky; top: 0; background: #f8fafc; }",
            "    .quote { min-width: 18rem; }",
            "    .claim { min-width: 16rem; }",
            "    .audit { min-width: 14rem; }",
            "    .source { min-width: 12rem; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            "  <h1>ScanSci Review Matrix</h1>",
            f"  <p>{len(rows)} evidence rows</p>",
            "  <table>",
            f"      <thead><tr>{headers}</tr></thead>",
            "      <tbody>",
            body_rows,
            "      </tbody>",
            "  </table>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_review_matrix_row(row: dict[str, Any], fields: list[str]) -> str:
    cells = [_review_matrix_cell(row, field) for field in fields]
    claim_id = escape(str(row.get("claim_id", "")))
    support_status = escape(str(row.get("support_status", "")))
    evidence_id = escape(str(row.get("evidence_id", "")))
    return (
        f'        <tr data-claim-id="{claim_id}" data-support-status="{support_status}" '
        f'data-evidence-id="{evidence_id}">'
        + "".join(cells)
        + "</tr>"
    )


def _review_matrix_cell(row: dict[str, Any], field: str) -> str:
    value = str(row.get(field, ""))
    class_name = ""
    if field == "exact_quote":
        class_name = ' class="quote"'
    elif field == "claim_text":
        class_name = ' class="claim"'
    elif field in {"query_plan", "retrieval_filters", "retrieval_queries"}:
        class_name = ' class="audit"'
    elif field == "evidence_id":
        class_name = ' class="source"'
        value = _source_link(row)
        return f"<td{class_name}>{value}</td>"
    return f"<td{class_name}>{escape(value)}</td>"


def _source_link(row: dict[str, Any]) -> str:
    evidence_id = str(row.get("evidence_id", ""))
    html_path = str(row.get("html_path", ""))
    html_anchor = str(row.get("html_anchor", ""))
    if not evidence_id:
        return ""
    if not html_path or not html_anchor:
        return escape(evidence_id)
    href = f"{html_path}#{html_anchor}"
    return (
        f'<a href="{escape(href)}" data-evidence-id="{escape(evidence_id)}">'
        f"{escape(evidence_id)}</a>"
    )
