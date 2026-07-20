from __future__ import annotations

from html import escape
from typing import Any

from ..bench import summarize_template_coverage


def render_gold_template_report(
    rows: list[dict[str, Any]],
    *,
    title: str = "ScanSci Gold Annotation Template",
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
            "    .summary { display: flex; gap: 1rem; flex-wrap: wrap; color: #455466; }",
            "    .question { border-top: 1px solid #d7dee8; padding-block: 1rem; }",
            "    .question h2 { font-size: 1.1rem; margin-block: 0 .5rem; }",
            "    .meta { display: flex; gap: .75rem; flex-wrap: wrap; font-size: .9rem; color: #455466; }",
            "    .field { margin-block: .65rem; }",
            "    .field code { white-space: pre-wrap; overflow-wrap: anywhere; }",
            "    .status { font-weight: 700; }",
            "    .status.todo { color: #9a3412; }",
            "    .evidence { border-left: 4px solid #94a3b8; padding: .65rem .85rem; margin-block: .65rem; background: #f8fafc; }",
            "    .evidence blockquote { margin: .4rem 0 0; }",
            "    .review-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: .75rem; }",
            "    .review-box { min-height: 3.5rem; border: 1px dashed #94a3b8; padding: .5rem; color: #64748b; }",
            "    a { color: #0f5aa6; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            _render_summary(rows),
            _render_questions(rows),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_summary(rows: list[dict[str, Any]]) -> str:
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("annotation_status", "") or "unset")
        answer_type = str(row.get("answer_type", "") or "unset")
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[answer_type] = type_counts.get(answer_type, 0) + 1
    coverage = summarize_template_coverage(rows)
    return "\n".join(
        [
            '  <section class="summary" aria-label="Template summary">',
            f"    <span>Rows: <strong>{len(rows)}</strong></span>",
            f"    <span>Annotation status: {escape(_format_counts(status_counts))}</span>",
            f"    <span>Answer types: {escape(_format_counts(type_counts))}</span>",
            f"    <span>Template coverage: Candidate evidence references: {escape(str(coverage['candidate_evidence_references']))}</span>",
            f"    <span>Unique evidence spans: {escape(str(coverage['unique_evidence_spans']))}</span>",
            f"    <span>Source documents: {escape(str(coverage['source_documents']))}</span>",
            f"    <span>Section kinds: {escape(_format_counts(dict(coverage['section_kind_counts'])))}</span>",
            f"    <span>Block types: {escape(_format_counts(dict(coverage['block_type_counts'])))}</span>",
            "  </section>",
        ]
    )


def _render_questions(rows: list[dict[str, Any]]) -> str:
    parts = ['  <section aria-label="Questions">']
    for index, row in enumerate(rows, start=1):
        question_id = str(row.get("question_id", ""))
        answer_type = str(row.get("answer_type", ""))
        status = str(row.get("annotation_status", "") or "unset")
        question = str(row.get("question", ""))
        candidate_question = str(row.get("candidate_question", ""))
        suggested_question = str(row.get("suggested_question", ""))
        notes = str(row.get("annotation_notes", ""))
        parts.extend(
            [
                f'    <article class="question" id="{escape(question_id) or f"row-{index:04d}"}" data-answer-type="{escape(answer_type)}" data-annotation-status="{escape(status)}">',
                f"      <h2>{index}. {escape(question_id or 'untitled question')}</h2>",
                '      <div class="meta">',
                f"        <span>Type: <strong>{escape(answer_type)}</strong></span>",
                f'        <span>Status: <strong class="status {escape(status)}">{escape(status)}</strong></span>',
                f"        <span>Answerable: <strong>{escape(str(row.get('answerable', '')))}</strong></span>",
                "      </div>",
                _render_field("Human question", question or "[write the final question here]"),
                _render_field("Candidate prompt", candidate_question),
                _render_field("Suggested question", suggested_question),
                _render_field("Gold evidence IDs", _join_list(row.get("gold_evidence_ids", []))),
                _render_field("Required points", _join_list(row.get("required_points", []))),
                _render_field("Forbidden points", _join_list(row.get("forbidden_points", []))),
                _render_field("Suggested required points", _join_list(row.get("suggested_required_points", []))),
                _render_field("Suggested forbidden points", _join_list(row.get("suggested_forbidden_points", []))),
                _render_field("Annotation notes", notes),
                _render_candidate_evidence(list(row.get("candidate_evidence", []) or [])),
                _render_review_boxes(),
                "    </article>",
            ]
        )
    parts.append("  </section>")
    return "\n".join(parts)


def _render_field(label: str, value: str) -> str:
    return "\n".join(
        [
            '      <div class="field">',
            f"        <strong>{escape(label)}:</strong>",
            f"        <code>{escape(value)}</code>",
            "      </div>",
        ]
    )


def _render_candidate_evidence(candidate_evidence: list[Any]) -> str:
    if not candidate_evidence:
        return '      <div class="field"><strong>Candidate evidence:</strong> <span>None.</span></div>'
    parts = ['      <div class="field"><strong>Candidate evidence:</strong></div>']
    for item in candidate_evidence:
        evidence = dict(item)
        evidence_id = str(evidence.get("evidence_id", ""))
        html_path = str(evidence.get("html_path", ""))
        html_anchor = str(evidence.get("html_anchor", ""))
        href = f"{html_path}#{html_anchor}" if html_path and html_anchor else ""
        link = (
            f'<a href="{escape(href)}" data-evidence-id="{escape(evidence_id)}">{escape(evidence_id)}</a>'
            if href
            else escape(evidence_id)
        )
        source = str(evidence.get("title", ""))
        doi = str(evidence.get("doi", ""))
        section = str(evidence.get("section", ""))
        text = str(evidence.get("text", ""))
        parts.extend(
            [
                '      <div class="evidence">',
                f"        <div>{link}</div>",
                f"        <div class=\"meta\"><span>{escape(source)}</span><span>{escape(doi)}</span><span>{escape(section)}</span></div>",
                f"        <blockquote>{escape(text)}</blockquote>",
                "      </div>",
            ]
        )
    return "\n".join(parts)


def _render_review_boxes() -> str:
    return "\n".join(
        [
            '      <div class="review-grid" aria-label="Human review worksheet">',
            '        <div class="review-box">Final question</div>',
            '        <div class="review-box">Required points</div>',
            '        <div class="review-box">Forbidden points</div>',
            '        <div class="review-box">Reviewer notes</div>',
            "      </div>",
        ]
    )


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) if counts else "none"
