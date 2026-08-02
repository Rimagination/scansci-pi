from __future__ import annotations

from html import escape
import json
from typing import Any


def render_answer_report(
    answer: dict[str, Any],
    evidence_table: list[dict[str, Any]],
    *,
    retrieval_metadata: dict[str, Any] | None = None,
) -> str:
    question = str(answer.get("question", "Evidence report"))
    claims = list(answer.get("answer", []) or [])
    reader_answer = dict(answer.get("reader_answer", {}) or {})
    limitations = list(answer.get("limitations", []) or [])
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            "  <title>ScanSci Evidence Report</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 2rem; color: #17202a; }",
            "    main { max-width: 1100px; margin: 0 auto; }",
            "    section { margin-block: 1.5rem; }",
            "    .claim, .evidence-row { border-top: 1px solid #d7dee8; padding-block: .75rem; }",
            "    .reader-answer { font-size: 1.04rem; }",
            "    .reader-sentence { margin-block: .8rem; }",
            "    .claim summary { cursor: pointer; }",
            "    .claim-meta { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: .5rem; font-size: .9rem; color: #455466; }",
            "    .citation { font-size: .86rem; margin-left: .4rem; }",
            "    .report-controls { display: flex; gap: 1rem; align-items: center; font-size: .92rem; color: #455466; }",
            "    .claim[data-support-status=\"unsupported\"], .claim[data-support-status=\"not_enough_information\"] { display: none; }",
            "    body[data-show-unsupported=\"true\"] .claim[data-support-status=\"unsupported\"], body[data-show-unsupported=\"true\"] .claim[data-support-status=\"not_enough_information\"] { display: block; }",
            "    .source-pane iframe { width: 100%; min-height: 360px; border: 1px solid #d7dee8; }",
            "    table { border-collapse: collapse; width: 100%; }",
            "    th, td { border-top: 1px solid #d7dee8; padding: .45rem; text-align: left; vertical-align: top; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(question)}</h1>",
            _render_reader_answer(reader_answer, claims, evidence_table),
            _render_claims(claims, evidence_table),
            _render_limitations(limitations),
            _render_evidence_table(evidence_table),
            _render_retrieval_audit(retrieval_metadata or {}),
            _render_source_pane(evidence_table),
            _render_script(),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_retrieval_audit(metadata: dict[str, Any]) -> str:
    if not metadata:
        return ""
    query_plan = dict(metadata.get("query_plan", {}) or {})
    agentic_trace = dict(metadata.get("agentic_trace", {}) or {})
    retrieval_queries = [str(query) for query in metadata.get("retrieval_queries", []) or []]
    adequacy = dict(metadata.get("adequacy", {}) or {})
    citation_verification = dict(metadata.get("citation_verification", {}) or {})
    filters = dict(query_plan.get("filters", {}) or {})
    rows = [
        ("Agentic profile", str(agentic_trace.get("profile", ""))),
        ("Agentic stop reason", str(agentic_trace.get("stop_reason", ""))),
        ("Slow path triggered", str(agentic_trace.get("slow_path_triggered", ""))),
        ("Question type", str(query_plan.get("question_type", ""))),
        ("Filters", _json_summary(filters)),
        ("Executed queries", " | ".join(retrieval_queries)),
        ("Evidence sufficient", str(adequacy.get("is_sufficient", ""))),
        ("Adequacy profile", str(adequacy.get("profile", ""))),
        ("Quote count", str(adequacy.get("quote_count", ""))),
        ("Minimum quotes", str(adequacy.get("min_quotes", ""))),
        ("Document count", str(adequacy.get("document_count", ""))),
        ("Minimum documents", str(adequacy.get("min_documents", ""))),
        ("Follow-up reason", str(adequacy.get("followup_reason", ""))),
        ("Citation verification", str(citation_verification.get("passed", ""))),
        ("Cited quotes", str(citation_verification.get("cited_quote_count", ""))),
        ("Cited evidence rows", str(citation_verification.get("cited_evidence_rows", ""))),
        ("Uncited claims", ", ".join(str(item) for item in citation_verification.get("uncited_claim_ids", []) or [])),
        (
            "Unsupported cited claims",
            ", ".join(str(item) for item in citation_verification.get("unsupported_cited_claim_ids", []) or []),
        ),
        ("Missing cited quotes", ", ".join(str(item) for item in citation_verification.get("missing_quote_ids", []) or [])),
        (
            "Missing source anchors",
            ", ".join(str(item) for item in citation_verification.get("missing_source_anchor_evidence_ids", []) or []),
        ),
    ]
    rendered_rows = "\n".join(
        "        "
        f'<tr><th scope="row">{escape(label)}</th><td>{escape(value)}</td></tr>'
        for label, value in rows
        if value
    )
    if not rendered_rows:
        return ""
    return "\n".join(
        [
            '  <section class="retrieval-audit">',
            "    <h2>Retrieval Audit</h2>",
            "    <table>",
            "      <tbody>",
            rendered_rows,
            "      </tbody>",
            "    </table>",
            "  </section>",
        ]
    )


def _json_summary(value: dict[str, Any]) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _render_reader_answer(
    reader_answer: dict[str, Any],
    claims: list[Any],
    evidence_table: list[dict[str, Any]],
) -> str:
    sentences = [dict(item or {}) for item in reader_answer.get("sentences", []) or []]
    if not sentences and claims:
        reader_answer = _fallback_reader_answer(claims, evidence_table)
        sentences = [dict(item or {}) for item in reader_answer.get("sentences", []) or []]
    if not sentences:
        return (
            '  <section class="reader-answer"><h2>Answer</h2>'
            '<p data-insufficient-evidence="true">Insufficient evidence.</p></section>'
        )
    parts = [
        '  <section class="reader-answer" data-reader-answer>',
        "    <h2>Answer</h2>",
    ]
    for sentence in sentences:
        status = str(sentence.get("support_status", ""))
        text = str(sentence.get("text", ""))
        citation_ids = [str(item) for item in sentence.get("citation_ids", []) or []]
        quote_ids = [str(item) for item in sentence.get("quote_ids", []) or []]
        citations = "".join(
            _render_reader_citation(citation_id, quote_id)
            for citation_id, quote_id in zip(citation_ids, quote_ids)
        )
        parts.append(
            "    "
            f'<p class="reader-sentence" data-reader-claim-id="{escape(str(sentence.get("claim_id", "")))}" '
            f'data-support-status="{escape(status)}">{escape(text)} {citations}</p>'
        )
    parts.append("  </section>")
    return "\n".join(parts)


def _fallback_reader_answer(claims: list[Any], evidence_table: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_quote_id = {
        str(row.get("quote_id", "")): row
        for row in evidence_table
        if str(row.get("quote_id", ""))
    }
    citation_id_by_quote_id: dict[str, str] = {}
    sentences: list[dict[str, Any]] = []
    for claim in claims:
        status = str(claim.get("support_status", ""))
        if status not in {"supported", "partially_supported"}:
            continue
        quote_ids = [str(quote_id) for quote_id in claim.get("quote_ids", []) or [] if str(quote_id) in rows_by_quote_id]
        citation_ids: list[str] = []
        for quote_id in quote_ids:
            citation_id = citation_id_by_quote_id.get(quote_id)
            if citation_id is None:
                citation_id = str(len(citation_id_by_quote_id) + 1)
                citation_id_by_quote_id[quote_id] = citation_id
            citation_ids.append(citation_id)
        text = _sentence_with_terminal_punctuation(str(claim.get("text", "")).strip())
        if text and citation_ids:
            sentences.append(
                {
                    "claim_id": str(claim.get("claim_id", "")),
                    "text": text,
                    "quote_ids": quote_ids,
                    "citation_ids": citation_ids,
                    "support_status": status,
                }
            )
    return {"sentences": sentences}


def _render_reader_citation(citation_id: str, quote_id: str) -> str:
    if not citation_id or not quote_id:
        return ""
    return (
        f'<a class="citation" href="#quote-{escape(quote_id)}" '
        f'data-citation-id="{escape(citation_id)}" data-quote-id="{escape(quote_id)}">[{escape(citation_id)}]</a>'
    )


def _sentence_with_terminal_punctuation(text: str) -> str:
    value = " ".join(text.split())
    if not value:
        return ""
    if value[-1] in ".!?。！？":
        return value
    return value + "."


def _render_claims(claims: list[Any], evidence_table: list[dict[str, Any]]) -> str:
    if not claims:
        return ""
    quote_text_by_id = {
        str(row.get("quote_id", "")): str(row.get("exact_quote", ""))
        for row in evidence_table
        if str(row.get("quote_id", ""))
    }
    parts = [
        "  <section>",
        "    <h2>Claim Audit</h2>",
        '    <div class="report-controls">',
        '      <label><input id="show-unsupported" type="checkbox" data-toggle-unsupported> Show unsupported</label>',
        "    </div>",
    ]
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        text = str(claim.get("text", ""))
        status = str(claim.get("support_status", "not_enough_information"))
        score = str(claim.get("verification_score", ""))
        quote_ids = list(claim.get("quote_ids", []) or [])
        citations = " ".join(
            _render_citation(str(quote_id), quote_text_by_id.get(str(quote_id), ""))
            for quote_id in quote_ids
        )
        parts.extend(
            [
                f'    <details class="claim" data-claim-id="{escape(claim_id)}" data-support-status="{escape(status)}" open>',
                f"      <summary>{escape(text)} {citations}</summary>",
                "      <div class=\"claim-meta\">",
                f"        <span>Status: <strong data-support-status>{escape(status)}</strong></span>",
                f"        <span>Verification score: <strong data-verification-score>{escape(score)}</strong></span>",
                "      </div>",
                "    </details>",
            ]
        )
    parts.append("  </section>")
    return "\n".join(parts)


def _render_citation(quote_id: str, quote_text: str) -> str:
    escaped_id = escape(quote_id)
    escaped_quote = escape(quote_text)
    return (
        f'<a class="citation" href="#quote-{escaped_id}" data-quote-id="{escaped_id}" '
        f'title="{escaped_quote}" data-quote-preview="{escaped_quote}">{escaped_id}</a>'
    )


def _render_limitations(limitations: list[Any]) -> str:
    if not limitations:
        return ""
    items = "".join(f"<li>{escape(str(item))}</li>" for item in limitations)
    return f"  <section><h2>Limitations</h2><ul>{items}</ul></section>"


def _render_evidence_table(evidence_table: list[dict[str, Any]]) -> str:
    parts = [
        "  <section>",
        "    <h2>Evidence</h2>",
        "    <table>",
        "      <thead><tr><th>Quote</th><th>Evidence</th><th>Source</th><th>Section</th><th>Confidence</th></tr></thead>",
        "      <tbody>",
    ]
    for row in evidence_table:
        quote_id = str(row.get("quote_id", ""))
        evidence_id = str(row.get("evidence_id", ""))
        html_path = str(row.get("html_path", ""))
        html_anchor = str(row.get("html_anchor", ""))
        href = f"{html_path}#{html_anchor}" if html_path and html_anchor else "#"
        source_link = (
            f'<a href="{escape(href)}" data-evidence-id="{escape(evidence_id)}">{escape(evidence_id)}</a>'
        )
        paper = str(row.get("paper", ""))
        doi = str(row.get("doi", ""))
        source = f"{paper} ({doi})" if doi else paper
        evidence_cell = _render_evidence_cell(row)
        parts.append(
            "        "
            f'<tr id="quote-{escape(quote_id)}" class="evidence-row">'
            f"<td>{escape(quote_id)}</td>"
            f"<td>{evidence_cell}</td>"
            f"<td>{escape(source)}<br>{source_link}</td>"
            f"<td>{escape(str(row.get('section', '')))}</td>"
            f"<td>{escape(str(row.get('confidence', '')))}</td>"
            "</tr>"
        )
    parts.extend(["      </tbody>", "    </table>", "  </section>"])
    return "\n".join(parts)


def _render_evidence_cell(row: dict[str, Any]) -> str:
    quote = str(row.get("exact_quote", ""))
    context = str(row.get("context_text", ""))
    parent_block_id = str(row.get("parent_block_id", ""))
    quote_html = f'<div class="exact-quote">{escape(quote)}</div>'
    if not context or context == quote:
        return quote_html
    return (
        quote_html
        + f'<details class="evidence-context" data-context-for="{escape(str(row.get("quote_id", "")))}" '
        + f'data-parent-block-id="{escape(parent_block_id)}">'
        + "<summary>Context</summary>"
        + f"<p>{escape(context)}</p>"
        + "</details>"
    )


def _render_source_pane(evidence_table: list[dict[str, Any]]) -> str:
    seen: set[str] = set()
    parts = ["  <section class=\"source-pane\">", "    <h2>Source</h2>"]
    for row in evidence_table:
        evidence_id = str(row.get("evidence_id", ""))
        html_path = str(row.get("html_path", ""))
        html_anchor = str(row.get("html_anchor", ""))
        if not evidence_id or not html_path or not html_anchor or evidence_id in seen:
            continue
        seen.add(evidence_id)
        src = f"{html_path}#{html_anchor}"
        parts.extend(
            [
                f'    <h3>{escape(evidence_id)}</h3>',
                f'    <iframe src="{escape(src)}" title="Source {escape(evidence_id)}" data-evidence-id="{escape(evidence_id)}"></iframe>',
            ]
        )
    if not seen:
        parts.append("    <p>No source anchors available.</p>")
    parts.append("  </section>")
    return "\n".join(parts)


def _render_script() -> str:
    return "\n".join(
        [
            "  <script>",
            "    const toggle = document.querySelector('[data-toggle-unsupported]');",
            "    if (toggle) {",
            "      toggle.addEventListener('change', () => {",
            "        document.body.dataset.showUnsupported = toggle.checked ? 'true' : 'false';",
            "      });",
            "    }",
            "  </script>",
        ]
    )
