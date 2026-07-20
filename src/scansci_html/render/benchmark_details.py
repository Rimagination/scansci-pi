from __future__ import annotations

from html import escape
from typing import Any


def render_benchmark_details_report(
    metrics: dict[str, Any],
    questions: list[dict[str, Any]],
    *,
    title: str = "ScanSci Benchmark Diagnostics",
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
            "    .metric { border: 1px solid #d7dee8; border-radius: 6px; padding: .65rem .75rem; background: #f8fafc; }",
            "    .metric span { display: block; color: #455466; font-size: .86rem; }",
            "    .metric strong { font-size: 1.25rem; }",
            "    .question { border-top: 1px solid #d7dee8; padding-block: 1rem; }",
            "    .question h2 { font-size: 1.1rem; margin-block: 0 .4rem; }",
            "    .meta, .badges { display: flex; gap: .55rem; flex-wrap: wrap; color: #455466; font-size: .9rem; }",
            "    .badge { border: 1px solid #cbd5e1; border-radius: 999px; padding: .12rem .5rem; background: #fff; }",
            "    .badge.pass { border-color: #86b98b; color: #166534; background: #f0fdf4; }",
            "    .badge.fail { border-color: #e3a5a5; color: #991b1b; background: #fef2f2; }",
            "    .lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .75rem; margin-top: .75rem; }",
            "    .list-box { border: 1px solid #d7dee8; border-radius: 6px; padding: .65rem .75rem; }",
            "    .list-box h3 { font-size: .95rem; margin: 0 0 .35rem; }",
            "    code { white-space: pre-wrap; overflow-wrap: anywhere; }",
            "    ul { margin: .35rem 0 0; padding-left: 1.15rem; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            _render_summary(metrics),
            _render_questions(questions),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_summary(metrics: dict[str, Any]) -> str:
    rows = [
        ("Passed", _bool_text(metrics.get("passed", False))),
        ("Questions", str(metrics.get("questions", ""))),
        ("Answerable", str(metrics.get("answerable_questions", ""))),
        ("Retrieval recall@k", str(metrics.get("retrieval_recall_at_k", ""))),
        ("All-gold recall@k", str(metrics.get("all_gold_retrieval_recall_at_k", ""))),
        ("Gold evidence recall@k", str(metrics.get("gold_evidence_recall_at_k", ""))),
        ("Answerable adequacy", str(metrics.get("answerable_evidence_adequacy_rate", ""))),
        ("Citation F1", str(metrics.get("citation_f1", ""))),
        ("Unsupported claim rate", str(metrics.get("unsupported_claim_rate", ""))),
        ("Abstention accuracy", str(metrics.get("abstention_accuracy", ""))),
    ]
    cards = "\n".join(
        [
            "      <div class=\"metric\">"
            f"<span>{escape(label)}</span>"
            f"<strong>{escape(value)}</strong>"
            "</div>"
            for label, value in rows
            if value
        ]
    )
    failures = [str(item) for item in metrics.get("gate_failures", []) or []]
    return "\n".join(
        [
            '  <section aria-label="Benchmark summary">',
            "    <h2>Summary</h2>",
            '    <div class="summary">',
            cards,
            "    </div>",
            _render_gate_failures(failures),
            "  </section>",
        ]
    )


def _render_gate_failures(failures: list[str]) -> str:
    if not failures:
        return '    <p class="badges"><span class="badge pass">No gate failures</span></p>'
    items = "".join(f"<li>{escape(item)}</li>" for item in failures)
    return f'    <div class="list-box"><h3>Gate failures</h3><ul>{items}</ul></div>'


def _render_questions(questions: list[dict[str, Any]]) -> str:
    parts = ['  <section aria-label="Question diagnostics">', "    <h2>Questions</h2>"]
    for index, question in enumerate(questions, start=1):
        question_id = str(question.get("question_id", ""))
        answer_type = str(question.get("answer_type", ""))
        answerable = bool(question.get("answerable", True))
        adequacy = dict(question.get("adequacy", {}) or {})
        parts.extend(
            [
                f'    <article class="question" id="{escape(question_id) or f"question-{index:04d}"}" data-question-id="{escape(question_id)}" data-answer-type="{escape(answer_type)}">',
                f"      <h2>{index}. {escape(question_id or 'untitled question')}</h2>",
                '      <div class="meta">',
                f"        <span>Type: <strong>{escape(answer_type or 'unset')}</strong></span>",
                f"        <span>Answerable: <strong>{escape(str(answerable))}</strong></span>",
                f"        <span>Gold recall: <strong>{escape(str(question.get('gold_evidence_recall_at_k', '')))}</strong></span>",
                "      </div>",
                f"      <p><code>{escape(str(question.get('question', '')))}</code></p>",
                _render_badges(question, adequacy),
                _render_question_lists(question),
                "    </article>",
            ]
        )
    parts.append("  </section>")
    return "\n".join(parts)


def _render_badges(question: dict[str, Any], adequacy: dict[str, Any]) -> str:
    rows = [
        ("retrieval hit", bool(question.get("retrieval_hit", False)), bool(question.get("retrieval_hit", False))),
        (
            "all gold retrieved",
            bool(question.get("all_gold_retrieved", False)),
            bool(question.get("all_gold_retrieved", False)),
        ),
        (
            "adequacy sufficient",
            bool(adequacy.get("is_sufficient", False)),
            bool(adequacy.get("is_sufficient", False)),
        ),
        (
            "insufficient evidence",
            bool(question.get("insufficient_evidence", False)),
            not bool(question.get("insufficient_evidence", False)),
        ),
    ]
    badges = [
        _badge(
            f"{label}: {_bool_text(actual)}",
            passed,
        )
        for label, actual, passed in rows
    ]
    badges.append(
        '<span class="badge">'
        f"quotes {escape(str(adequacy.get('quote_count', '')))}"
        f"/{escape(str(adequacy.get('min_quotes', '')))}"
        "</span>"
    )
    badges.append(
        '<span class="badge">'
        f"documents {escape(str(adequacy.get('document_count', '')))}"
        f"/{escape(str(adequacy.get('min_documents', '')))}"
        "</span>"
    )
    answer_matches = question.get("answer_matches_points", None)
    if answer_matches is not None:
        badges.append(_badge(f"answer points: {_bool_text(bool(answer_matches))}", bool(answer_matches)))
    followup_reason = str(adequacy.get("followup_reason", ""))
    if followup_reason:
        badges.append(f'<span class="badge">follow-up: {escape(followup_reason)}</span>')
    return f'      <div class="badges">{"".join(badges)}</div>'


def _render_question_lists(question: dict[str, Any]) -> str:
    sections = [
        ("Gold evidence", question.get("gold_evidence_ids", [])),
        ("Retrieved evidence", question.get("retrieved_evidence_ids", [])),
        ("Retrieved gold", question.get("retrieved_gold_evidence_ids", [])),
        ("Missing gold", question.get("missing_gold_evidence_ids", [])),
        ("Quoted evidence", question.get("quoted_evidence_ids", [])),
        ("Cited gold", question.get("cited_gold_evidence_ids", [])),
        ("Missing cited gold", question.get("missing_cited_gold_evidence_ids", [])),
        ("Claim support counts", _dict_items(question.get("claim_support_counts", {}))),
    ]
    return "\n".join(
        [
            '      <div class="lists">',
            *[_render_list_box(label, values) for label, values in sections],
            "      </div>",
        ]
    )


def _render_list_box(label: str, values: Any) -> str:
    items = [str(item) for item in values or []]
    if not items:
        body = "<p>None.</p>"
    else:
        body = "<ul>" + "".join(f"<li><code>{escape(item)}</code></li>" for item in items) + "</ul>"
    return f'        <div class="list-box"><h3>{escape(label)}</h3>{body}</div>'


def _dict_items(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [f"{key}: {value[key]}" for key in sorted(value)]


def _badge(label: str, passed: bool) -> str:
    css_class = "pass" if passed else "fail"
    return f'<span class="badge {css_class}">{escape(label)}</span>'


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"
