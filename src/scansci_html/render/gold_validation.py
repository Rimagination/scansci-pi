from __future__ import annotations

from html import escape
from typing import Any


def render_gold_validation_report(
    payload: dict[str, Any],
    *,
    title: str = "ScanSci Gold Validation Report",
) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 2rem; color: #17202a; }",
            "    main { max-width: 1180px; margin: 0 auto; }",
            "    section { margin-block: 1.5rem; }",
            "    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .75rem; }",
            "    .card, .box { border: 1px solid #d7dee8; border-radius: 6px; padding: .65rem .75rem; background: #f8fafc; }",
            "    .card span { display: block; color: #455466; font-size: .86rem; }",
            "    .card strong { font-size: 1.25rem; }",
            "    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: .75rem; }",
            "    .question-issues { border-top: 1px solid #d7dee8; padding-block: .9rem; }",
            "    .question-issues h3 { margin-block: 0 .35rem; }",
            "    .evidence-sources { display: grid; gap: .45rem; margin-top: .5rem; }",
            "    .evidence-source { border-left: 3px solid #64748b; padding: .35rem .55rem; background: #f8fafc; }",
            "    .evidence-source p { margin: .2rem 0 0; }",
            "    .evidence-source .meta { color: #455466; font-size: .9rem; }",
            "    table { width: 100%; border-collapse: collapse; }",
            "    th, td { border-bottom: 1px solid #d7dee8; padding: .45rem; text-align: left; vertical-align: top; }",
            "    th { color: #455466; font-size: .9rem; }",
            "    code { white-space: pre-wrap; overflow-wrap: anywhere; }",
            "    ul { margin: .35rem 0 0; padding-left: 1.15rem; }",
            "    .pass { color: #166534; }",
            "    .fail { color: #991b1b; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            _render_summary(payload),
            _render_coverage(payload),
            _render_issue_sections(payload),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_summary(payload: dict[str, Any]) -> str:
    rows = [
        ("Passed", _bool_text(payload.get("passed", False))),
        ("Questions", str(payload.get("questions", ""))),
        ("Answerable", str(payload.get("answerable_questions", ""))),
        ("Unanswerable", str(payload.get("unanswerable_questions", ""))),
        ("Min per answer type", str(payload.get("min_per_answer_type", ""))),
        ("Evidence store checked", _bool_text(payload.get("checked_evidence_store", False))),
        ("Issue count", str(len(list(payload.get("issues", []) or [])))),
    ]
    cards = "\n".join(
        [
            "      <div class=\"card\">"
            f"<span>{escape(label)}</span>"
            f"<strong class=\"{escape('pass' if value == 'true' else 'fail' if label == 'Passed' else '')}\">{escape(value)}</strong>"
            "</div>"
            for label, value in rows
            if value
        ]
    )
    evidence_store_path = str(payload.get("evidence_store_path", ""))
    return "\n".join(
        [
            '  <section aria-label="Validation summary">',
            "    <h2>Summary</h2>",
            '    <div class="summary">',
            cards,
            "    </div>",
            f"    <p>Evidence store: <code>{escape(evidence_store_path or 'not checked')}</code></p>",
            "  </section>",
        ]
    )


def _render_coverage(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            '  <section aria-label="Coverage">',
            "    <h2>Coverage</h2>",
            '    <div class="grid">',
            _render_dict_box("Answer type counts", payload.get("answer_type_counts", {})),
            _render_annotation_progress(payload.get("annotation_progress", {})),
            _render_gold_evidence_coverage(payload.get("gold_evidence_coverage", {})),
            _render_list_box("Required answer types", payload.get("required_answer_types", [])),
            _render_list_box("Missing answer types", payload.get("missing_answer_types", [])),
            _render_records_box(
                "Underrepresented answer types",
                payload.get("underrepresented_answer_types", []),
                ["answer_type", "count", "minimum"],
                empty="No underrepresented answer types.",
            ),
            "    </div>",
            "  </section>",
        ]
    )


def _render_issue_sections(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            '  <section aria-label="Issues">',
            "    <h2>Issues</h2>",
            '    <div class="grid">',
            _render_list_box("Missing gold evidence IDs", payload.get("missing_gold_evidence_ids", [])),
            _render_records_box(
                "Gold evidence adequacy issues",
                payload.get("gold_evidence_adequacy_issues", []),
                ["line", "question_id", "answer_type", "message"],
                empty="No gold evidence adequacy issues.",
            ),
            _render_records_box(
                "Gold evidence quality warnings",
                payload.get("gold_evidence_quality_warnings", []),
                ["line", "question_id", "answer_type", "evidence_ids", "message"],
                empty="No gold evidence quality warnings.",
            ),
            "    </div>",
            _render_records_table(
                "All validation issues",
                payload.get("issues", []),
                ["line", "question_id", "message"],
                empty="No validation issues.",
            ),
            _render_issues_by_question(
                payload.get("issues", []),
                payload.get("question_summaries", []),
            ),
            "  </section>",
        ]
    )


def _render_dict_box(label: str, value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return f'      <div class="box"><h3>{escape(label)}</h3><p>None.</p></div>'
    items = "".join(f"<li><code>{escape(str(key))}: {escape(str(value[key]))}</code></li>" for key in sorted(value))
    return f'      <div class="box"><h3>{escape(label)}</h3><ul>{items}</ul></div>'


def _render_list_box(label: str, value: Any) -> str:
    items = [str(item) for item in value or []]
    if not items:
        return f'      <div class="box"><h3>{escape(label)}</h3><p>None.</p></div>'
    body = "".join(f"<li><code>{escape(item)}</code></li>" for item in items)
    return f'      <div class="box"><h3>{escape(label)}</h3><ul>{body}</ul></div>'


def _render_annotation_progress(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return '<div class="box"><h3>Annotation progress</h3><p>Not reported.</p></div>'
    rows = [
        ("total_rows", value.get("total_rows", "")),
        ("completed_rows", value.get("completed_rows", "")),
        ("incomplete_rows", value.get("incomplete_rows", "")),
        ("empty_question_rows", value.get("empty_question_rows", "")),
    ]
    items = [f"<li><code>{escape(key)}: {escape(str(item))}</code></li>" for key, item in rows]
    status_counts = value.get("status_counts", {})
    if isinstance(status_counts, dict):
        statuses = ", ".join(f"{key}={status_counts[key]}" for key in sorted(status_counts))
        items.append(f"<li><code>status_counts: {escape(statuses or 'none')}</code></li>")
    return f'<div class="box"><h3>Annotation progress</h3><ul>{"".join(items)}</ul></div>'


def _render_gold_evidence_coverage(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return '<div class="box"><h3>Gold evidence coverage</h3><p>Not reported.</p></div>'
    rows = [
        ("gold_evidence_references", value.get("gold_evidence_references", "")),
        ("unique_evidence_spans", value.get("unique_evidence_spans", "")),
        ("source_documents", value.get("source_documents", "")),
    ]
    items = [f"<li><code>{escape(key)}: {escape(str(item))}</code></li>" for key, item in rows]
    for key in ("source_document_counts", "section_kind_counts", "block_type_counts"):
        counts = value.get(key, {})
        if isinstance(counts, dict):
            count_text = ", ".join(f"{item_key}={counts[item_key]}" for item_key in sorted(counts))
            items.append(f"<li><code>{escape(key)}: {escape(count_text or 'none')}</code></li>")
    return f'<div class="box"><h3>Gold evidence coverage</h3><ul>{"".join(items)}</ul></div>'


def _render_records_box(label: str, records: Any, fields: list[str], *, empty: str) -> str:
    record_list = [dict(record) for record in records or [] if isinstance(record, dict)]
    if not record_list:
        return f'      <div class="box"><h3>{escape(label)}</h3><p>{escape(empty)}</p></div>'
    rows = []
    for record in record_list:
        values = ", ".join(f"{field}={record.get(field, '')}" for field in fields)
        rows.append(f"<li><code>{escape(values)}</code></li>")
    return f'      <div class="box"><h3>{escape(label)}</h3><ul>{"".join(rows)}</ul></div>'


def _render_records_table(label: str, records: Any, fields: list[str], *, empty: str) -> str:
    record_list = [dict(record) for record in records or [] if isinstance(record, dict)]
    if not record_list:
        return f"    <h3>{escape(label)}</h3><p>{escape(empty)}</p>"
    header = "".join(f"<th>{escape(field)}</th>" for field in fields)
    rows = []
    for record in record_list:
        cells = "".join(_render_table_cell(record, field) for field in fields)
        rows.append(f"<tr>{cells}</tr>")
    return "\n".join(
        [
            f"    <h3>{escape(label)}</h3>",
            "    <table>",
            f"      <thead><tr>{header}</tr></thead>",
            f"      <tbody>{''.join(rows)}</tbody>",
            "    </table>",
        ]
    )


def _render_table_cell(record: dict[str, Any], field: str) -> str:
    value = str(record.get(field, ""))
    if field == "question_id" and value:
        href = f"#question-{_safe_fragment_id(value)}"
        return f'<td><a href="{escape(href)}"><code>{escape(value)}</code></a></td>'
    return f"<td><code>{escape(value)}</code></td>"


def _render_issues_by_question(records: Any, question_summaries: Any) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        question_id = str(record.get("question_id", "")).strip()
        if not question_id:
            continue
        grouped.setdefault(question_id, []).append(record)
    summaries_by_id = {
        str(summary.get("question_id", "")).strip(): dict(summary)
        for summary in question_summaries or []
        if isinstance(summary, dict)
    }
    if not grouped:
        return "    <h3>Issues by question</h3><p>No question-specific issues.</p>"
    parts = ["    <h3>Issues by question</h3>"]
    for question_id in sorted(grouped):
        anchor_id = f"question-{_safe_fragment_id(question_id)}"
        summary = summaries_by_id.get(question_id, {})
        items = "".join(
            "<li>"
            f"<code>line {escape(str(issue.get('line', '')))}</code>: "
            f"{escape(str(issue.get('message', '')))}"
            "</li>"
            for issue in grouped[question_id]
        )
        parts.extend(
            [
                f'    <article class="question-issues" id="{escape(anchor_id)}" data-question-id="{escape(question_id)}">',
                f"      <h3>{escape(question_id)}</h3>",
                _render_question_summary(summary),
                f"      <ul>{items}</ul>",
                "    </article>",
            ]
        )
    return "\n".join(parts)


def _render_question_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    gold_ids = [str(item) for item in summary.get("gold_evidence_ids", []) or []]
    return "\n".join(
        [
            '      <div class="meta">',
            f"        <span>type: <strong>{escape(str(summary.get('answer_type', '') or 'unset'))}</strong></span>",
            f"        <span>status: <strong>{escape(str(summary.get('annotation_status', '') or 'unset'))}</strong></span>",
            f"        <span>answerable: <strong>{escape(str(summary.get('answerable', '')))}</strong></span>",
            f"        <span>line: <strong>{escape(str(summary.get('line', '')))}</strong></span>",
            "      </div>",
            f"      <p><code>{escape(str(summary.get('question', '')) or '[empty question]')}</code></p>",
            _render_suggestion_fields(summary),
            f"      <p>Gold evidence IDs: <code>{escape(', '.join(gold_ids) if gold_ids else 'none')}</code></p>",
            _render_gold_evidence_sources(summary.get("gold_evidence", [])),
        ]
    )


def _render_suggestion_fields(summary: dict[str, Any]) -> str:
    parts: list[str] = []
    suggested_question = str(summary.get("suggested_question", "") or "")
    if suggested_question:
        parts.append(f"      <p>Suggested question: <code>{escape(suggested_question)}</code></p>")
    suggested_required = _as_text_list(summary.get("suggested_required_points", []))
    if suggested_required:
        parts.append(
            f"      <p>Suggested required points: <code>{escape('; '.join(suggested_required))}</code></p>"
        )
    suggested_forbidden = _as_text_list(summary.get("suggested_forbidden_points", []))
    if suggested_forbidden:
        parts.append(
            f"      <p>Suggested forbidden points: <code>{escape('; '.join(suggested_forbidden))}</code></p>"
        )
    return "\n".join(parts)


def _as_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _render_gold_evidence_sources(records: Any) -> str:
    record_list = [dict(record) for record in records or [] if isinstance(record, dict)]
    if not record_list:
        return '      <p>Gold evidence source links: <code>not loaded</code></p>'
    items = "\n".join(_render_gold_evidence_source(record) for record in record_list)
    return "\n".join(
        [
            "      <h4>Gold evidence source links</h4>",
            '      <div class="evidence-sources">',
            items,
            "      </div>",
        ]
    )


def _render_gold_evidence_source(record: dict[str, Any]) -> str:
    evidence_id = str(record.get("evidence_id", ""))
    title = str(record.get("title", "") or "Untitled source")
    doi = str(record.get("doi", "") or "")
    section = str(record.get("section", "") or record.get("section_kind", "") or "")
    text = str(record.get("text", "") or "")
    href = _evidence_href(record)
    source_label = escape(title)
    source_link = (
        f'<a href="{escape(href)}">{source_label}</a>'
        if href
        else source_label
    )
    meta_parts = [
        f"<code>{escape(evidence_id)}</code>",
        f"doi: <code>{escape(doi)}</code>" if doi else "",
        f"section: <code>{escape(section)}</code>" if section else "",
    ]
    meta = " | ".join(part for part in meta_parts if part)
    return "\n".join(
        [
            f'        <article class="evidence-source" data-evidence-id="{escape(evidence_id)}">',
            f"          <strong>{source_link}</strong>",
            f'          <div class="meta">{meta}</div>',
            f"          <p>{escape(text)}</p>" if text else "",
            "        </article>",
        ]
    )


def _evidence_href(record: dict[str, Any]) -> str:
    html_path = str(record.get("html_path", "") or "")
    html_anchor = str(record.get("html_anchor", "") or "")
    if html_path and html_anchor:
        return f"{html_path}#{html_anchor}"
    return html_path


def _safe_fragment_id(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            safe.append(char)
        else:
            safe.append("-")
    return "".join(safe) or "unknown"


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"
