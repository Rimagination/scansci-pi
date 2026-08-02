from __future__ import annotations

from html import escape
import os
from pathlib import Path
from typing import Any


DISPLAYABLE_EVIDENCE_STATUSES = {"supported", "partial_support"}


def render_grounded_annotation_report(
    payload: dict[str, Any],
    *,
    output_path: str | Path | None = None,
) -> str:
    summary = dict(payload.get("summary", {}) or {})
    segments = [dict(item or {}) for item in payload.get("segments", []) or []]
    cards = [dict(item or {}) for item in payload.get("evidence_cards", []) or [] if _is_displayable_evidence(item)]
    summary["evidence_cards"] = len(cards)
    first_href = _display_href(cards[0], output_path=output_path) if cards else ""
    title = "ScanSci 证据标注工作台"
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            _stylesheet(),
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            _render_header(title, summary),
            _render_filters(),
            '  <div class="workbench">',
            _render_claims(segments, output_path=output_path),
            _render_source_panel(cards, first_href, output_path=output_path),
            "  </div>",
            _render_retrieval_settings(dict(payload.get("retrieval", {}) or {})),
            _render_script(),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _stylesheet() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --surface: #ffffff;
      --text: #18212d;
      --muted: #5a6675;
      --line: #d9e0e8;
      --line-strong: #b8c3cf;
      --accent: #0f766e;
      --accent-soft: #dff3ef;
      --supported: #0f766e;
      --partial: #6f5b00;
      --weak: #93411f;
      --missing: #7a1f2b;
      --focus: #2563eb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    main {
      width: min(1440px, calc(100vw - 28px));
      margin: 22px auto 34px;
    }
    h1, h2, h3 { letter-spacing: 0; }
    h1 {
      margin: 0;
      font-size: 1.45rem;
      line-height: 1.2;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 1rem;
    }
    h3 {
      margin: 0;
      font-size: .95rem;
      line-height: 1.35;
    }
    button, a {
      font: inherit;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }
    .summary {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      color: var(--muted);
      font-size: .86rem;
    }
    .chip, .status-pill {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 10px;
      background: var(--surface);
      white-space: nowrap;
    }
    .status-pill {
      font-size: .78rem;
      font-weight: 700;
      letter-spacing: 0;
    }
    .status-supported { color: var(--supported); background: #e5f6f0; border-color: #a4dfc8; }
    .status-partial_support { color: var(--partial); background: #fff3c4; border-color: #e7c85f; }
    .status-weak_candidate { color: var(--weak); background: #ffe5d3; border-color: #e5ae8b; }
    .status-no_evidence_found { color: var(--missing); background: #ffe2e8; border-color: #eba8b5; }
    .filters {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 14px;
    }
    .filter-button, .review-button, .source-button {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 5px 9px;
      color: var(--text);
      background: var(--surface);
      cursor: pointer;
    }
    .filter-button[aria-pressed="true"], .review-button[aria-pressed="true"] {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #064f49;
    }
    .workbench {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(380px, .88fr);
      gap: 16px;
      align-items: start;
    }
    .claims-panel, .source-panel {
      min-width: 0;
    }
    .panel-inner {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }
    .claims-panel .panel-inner {
      padding: 0;
    }
    .claim-row {
      border-top: 1px solid var(--line);
      padding: 14px 16px;
      scroll-margin-top: 14px;
    }
    .claim-row:first-child { border-top: 0; }
    .claim-row[data-active="true"] {
      box-shadow: inset 3px 0 0 var(--focus);
      background: #fbfdff;
    }
    .claim-row[data-hidden="true"] { display: none; }
    .claim-head {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }
    .claim-meta {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .score-meter {
      position: relative;
      width: 86px;
      height: 8px;
      border-radius: 999px;
      background: #e8edf2;
      overflow: hidden;
    }
    .score-meter span {
      display: block;
      height: 100%;
      width: var(--score-width);
      background: var(--accent);
    }
    .claim-text {
      margin: 0 0 10px;
      font-size: 1rem;
    }
    .citation {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 1.7em;
      height: 1.55em;
      margin-left: .25em;
      border-radius: 999px;
      color: #ffffff;
      background: var(--accent);
      font-size: .78em;
      font-weight: 800;
      text-decoration: none;
      vertical-align: .08em;
    }
    .citation[data-support-status="partial_support"] { background: var(--partial); }
    .citation[data-support-status="weak_candidate"] { background: var(--weak); }
    .citation:hover, .citation:focus {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .no-source {
      display: inline-block;
      margin-left: .35rem;
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--missing);
      background: #ffe2e8;
      font-size: .78rem;
      font-weight: 700;
      vertical-align: .08em;
    }
    .evidence-lines {
      display: grid;
      gap: 8px;
      margin: 10px 0;
    }
    .evidence-line {
      border-left: 3px solid var(--accent);
      padding: 6px 0 6px 10px;
      color: #273444;
      font-size: .9rem;
    }
    .review-strip {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    details {
      margin-top: 10px;
      color: var(--muted);
      font-size: .88rem;
    }
    summary { cursor: pointer; }
    .query-list, .alternative-list {
      margin: 8px 0 0;
      padding-left: 18px;
    }
    .source-panel {
      position: sticky;
      top: 14px;
      align-self: start;
      display: grid;
      gap: 12px;
    }
    .source-preview {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
    }
    .source-preview-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      color: var(--muted);
      font-size: .88rem;
    }
    iframe {
      display: block;
      width: 100%;
      min-height: 380px;
      border: 0;
      background: #ffffff;
    }
    .source-list {
      display: grid;
      gap: 10px;
      max-height: calc(100vh - 520px);
      min-height: 220px;
      overflow: auto;
      padding-right: 2px;
    }
    .source-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface);
      scroll-margin-top: 16px;
    }
    .source-card[data-active="true"], .source-card:target {
      border-color: var(--focus);
      box-shadow: 0 0 0 3px #dbeafe;
    }
    .source-card-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 8px;
    }
    .source-label {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2em;
      height: 1.7em;
      margin-right: .4rem;
      border-radius: 999px;
      color: #ffffff;
      background: var(--accent);
      font-size: .78rem;
      font-weight: 800;
    }
    blockquote {
      margin: 9px 0;
      padding-left: 11px;
      border-left: 3px solid var(--accent);
      color: #243141;
    }
    .source-meta, .diagnostics, .retrieval-settings {
      color: var(--muted);
      font-size: .84rem;
    }
    .source-actions {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .source-actions a {
      color: #075f59;
      overflow-wrap: anywhere;
    }
    .retrieval-settings {
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface);
    }
    .settings-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 7px 14px;
    }
    @media (max-width: 960px) {
      main { width: min(100vw - 20px, 780px); margin-top: 14px; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .summary { justify-content: flex-start; }
      .workbench { grid-template-columns: 1fr; }
      .source-panel { position: static; }
      .source-list { max-height: none; }
    }
    """.strip()


def _render_header(title: str, summary: dict[str, Any]) -> str:
    rows = [
        ("主张", summary.get("segments", 0)),
        ("已支持", summary.get("supported_segments", 0)),
        ("部分支持", summary.get("partial_support_segments", 0)),
        ("证据不足", summary.get("weak_candidate_segments", 0)),
        ("待审", summary.get("needs_review_segments", 0)),
        ("证据", summary.get("evidence_cards", 0)),
    ]
    chips = "".join(f'<span class="chip">{escape(label)}: {escape(str(value))}</span>' for label, value in rows)
    return "\n".join(
        [
            '  <header class="topbar">',
            f"    <h1>{escape(title)}</h1>",
            f'    <div class="summary" aria-label="标注摘要">{chips}</div>',
            "  </header>",
        ]
    )


def _render_filters() -> str:
    filters = [
        ("all", "全部"),
        ("supported", "已支持"),
        ("partial_support", "部分支持"),
        ("weak_candidate", "证据不足"),
        ("needs_review", "待审"),
    ]
    buttons = "".join(
        (
            f'<button class="filter-button" type="button" data-filter="{escape(value)}" '
            f'aria-pressed="{str(value == "all").lower()}">{escape(label)}</button>'
        )
        for value, label in filters
    )
    return f'  <nav class="filters" aria-label="主张筛选">{buttons}</nav>'


def _render_claims(
    segments: list[dict[str, Any]],
    *,
    output_path: str | Path | None,
) -> str:
    parts = ['    <section class="claims-panel">', '      <div class="panel-inner">']
    if not segments:
        parts.append('        <article class="claim-row"><p class="claim-text">没有找到需要标注的文本片段。</p></article>')
    for segment in segments:
        parts.append(_render_claim(segment, output_path=output_path))
    parts.extend(["      </div>", "    </section>"])
    return "\n".join(parts)


def _render_claim(
    segment: dict[str, Any],
    *,
    output_path: str | Path | None,
) -> str:
    segment_id = str(segment.get("segment_id", ""))
    status = str(segment.get("support_status") or segment.get("status") or "no_evidence_found")
    score = _bounded_score(segment.get("best_support_score"))
    evidence_items = [dict(item or {}) for item in segment.get("evidence", []) or [] if _is_displayable_evidence(item)]
    citations = "".join(_citation_link(item, output_path=output_path) for item in evidence_items)
    if not citations:
        citations = '<span class="no-source">无来源</span>'
    evidence_lines = "".join(_render_evidence_line(item) for item in evidence_items)
    if not evidence_lines:
        evidence_lines = '<div class="evidence-line">没有达到引用阈值的证据。</div>'
    return "\n".join(
        [
            (
                f'        <article class="claim-row" id="{escape(segment_id)}" '
                f'data-claim-id="{escape(segment_id)}" data-support-status="{escape(status)}" '
                'data-review-state="unreviewed">'
            ),
            '          <div class="claim-head">',
            f'            <div class="claim-meta">{_status_pill(status)}{_score_meter(score)}</div>',
            f'            <span class="diagnostics">{escape(str(score))}/100</span>',
            "          </div>",
            f'          <p class="claim-text">{escape(str(segment.get("text", "")))} {citations}</p>',
            f'          <div class="evidence-lines">{evidence_lines}</div>',
            _render_missing_terms(segment),
            _render_review_strip(segment_id),
            _render_claim_details(segment),
            "        </article>",
        ]
    )


def _citation_link(evidence: Any, *, output_path: str | Path | None) -> str:
    item = dict(evidence or {})
    citation_id = str(item.get("citation_id", ""))
    if not citation_id:
        return ""
    status = str(item.get("support_status", "weak_candidate"))
    if not _is_displayable_evidence(item):
        return ""
    href = _display_href(item, output_path=output_path)
    return (
        f'<a class="citation" href="#source-{escape(citation_id)}" '
        f'data-citation-id="{escape(citation_id)}" data-source-href="{escape(href)}" '
        f'data-support-status="{escape(status)}">[{escape(citation_id)}]</a>'
    )


def _render_evidence_line(evidence: Any) -> str:
    item = dict(evidence or {})
    citation_id = str(item.get("citation_id", ""))
    quote = str(item.get("exact_quote", ""))
    status = str(item.get("support_status", "weak_candidate"))
    if not _is_displayable_evidence(item):
        return ""
    score = _bounded_score(item.get("support_score"))
    return (
        '<div class="evidence-line">'
        f'<strong>[{escape(citation_id)}]</strong> {escape(quote)} '
        f'<span class="diagnostics">{escape(_status_label(status))}，支持度 {score}/100</span>'
        "</div>"
    )


def _render_missing_terms(segment: dict[str, Any]) -> str:
    terms = [str(term) for term in segment.get("missing_terms", []) or []]
    if not terms:
        return ""
    return f'          <div class="diagnostics">缺失词：{escape(", ".join(terms))}</div>'


def _render_review_strip(segment_id: str) -> str:
    actions = [
        ("confirmed", "确认"),
        ("needs_evidence", "需补证据"),
        ("rejected", "驳回"),
    ]
    buttons = "".join(
        (
            f'<button class="review-button" type="button" data-review-action="{escape(action)}" '
            f'data-claim-id="{escape(segment_id)}">{escape(label)}</button>'
        )
        for action, label in actions
    )
    return f'          <div class="review-strip">{buttons}</div>'


def _render_claim_details(segment: dict[str, Any]) -> str:
    queries = list(segment.get("queries", []) or [])
    alternatives = [item for item in segment.get("alternatives", []) or [] if _is_displayable_evidence(item)]
    query_items = "".join(
        f'<li><strong>{escape(str(item.get("label", "")))}</strong>: {escape(str(item.get("query", "")))}</li>'
        for item in queries
    )
    alternative_items = "".join(
        (
            f'<li>{_status_pill(str(item.get("support_status", "weak_candidate")))} '
            f'{escape(str(item.get("exact_quote", "")))} '
            f'<span class="diagnostics">{escape(str(_bounded_score(item.get("support_score"))))}/100</span></li>'
        )
        for item in alternatives
    )
    return "\n".join(
        [
            "          <details>",
            "            <summary>检索诊断</summary>",
            f'            <ul class="query-list">{query_items or "<li>没有查询变体。</li>"}</ul>',
            f'            <ul class="alternative-list">{alternative_items or "<li>没有备选证据。</li>"}</ul>',
            "          </details>",
        ]
    )


def _render_source_panel(
    cards: list[dict[str, Any]],
    first_href: str,
    *,
    output_path: str | Path | None,
) -> str:
    preview = escape(first_href)
    card_html = "\n".join(_render_source_card(card, output_path=output_path) for card in cards)
    if not card_html:
        card_html = '<article class="source-card">没有找到候选证据。</article>'
    return "\n".join(
        [
            '    <aside class="source-panel">',
            '      <section class="source-preview">',
            '        <div class="source-preview-head">',
            '          <strong>证据预览</strong>',
            f'          <a id="source-open-link" href="{preview}" target="_blank" rel="noreferrer">打开</a>',
            "        </div>",
            f'        <iframe id="source-frame" src="{preview}" title="证据预览"></iframe>',
            "      </section>",
            '      <section class="source-list" aria-label="证据卡片">',
            card_html,
            "      </section>",
            "    </aside>",
        ]
    )


def _render_source_card(card: dict[str, Any], *, output_path: str | Path | None) -> str:
    citation_id = str(card.get("citation_id", ""))
    status = str(card.get("support_status", "weak_candidate"))
    if not _is_displayable_evidence(card):
        return ""
    score = _bounded_score(card.get("support_score"))
    title = str(card.get("title", "未命名来源"))
    quote = str(card.get("exact_quote", ""))
    section = str(card.get("section", ""))
    doi = str(card.get("doi", ""))
    href = _display_href(card, output_path=output_path)
    diagnostics = _source_diagnostics(card)
    context = str(card.get("context_text", ""))
    cited_by = ", ".join(str(value) for value in card.get("cited_by", []) or [])
    return "\n".join(
        [
            (
                f'        <article class="source-card" id="source-{escape(citation_id)}" '
                f'data-citation-id="{escape(citation_id)}" data-source-href="{escape(href)}" '
                f'data-support-status="{escape(status)}">'
            ),
            '          <div class="source-card-head">',
            (
                f'            <h3><span class="source-label">[{escape(citation_id)}]</span>'
                f"{escape(title)}</h3>"
            ),
            f"            {_status_pill(status)}",
            "          </div>",
            f"          <blockquote>{escape(quote)}</blockquote>",
            f"          <div class=\"source-meta\">{escape(section)}{_doi_meta(doi)} | 支持度 {score}/100</div>",
            f"          <div class=\"diagnostics\">{diagnostics}</div>",
            f"          <div class=\"diagnostics\">被引用于：{escape(cited_by or '无')}</div>",
            _render_context_details(context),
            '          <div class="source-actions">',
            f'            <button class="source-button" type="button" data-load-source="{escape(href)}">预览</button>',
            f'            <a href="{escape(href)}" target="_blank" rel="noreferrer">打开原文锚点</a>',
            "          </div>",
            "        </article>",
        ]
    )


def _render_context_details(context: str) -> str:
    if not context:
        return ""
    return f"          <details><summary>上下文</summary><p>{escape(context)}</p></details>"


def _source_diagnostics(card: dict[str, Any]) -> str:
    bits = [
        f"词项覆盖 {card.get('term_coverage', 0)}",
        f"短语重合 {card.get('phrase_overlap', 0)}",
        f"数字匹配 {card.get('numeric_status', '')}",
    ]
    missing_terms = ", ".join(str(term) for term in card.get("missing_terms", []) or [])
    if missing_terms:
        bits.append(f"缺失 {missing_terms}")
    return escape(" | ".join(str(bit) for bit in bits if str(bit)))


def _render_retrieval_settings(settings: dict[str, Any]) -> str:
    if not settings:
        return ""
    rows = "".join(
        f"<div><strong>{escape(str(key))}</strong>: {escape(str(value))}</div>"
        for key, value in settings.items()
    )
    return "\n".join(
        [
            '  <section class="retrieval-settings">',
            "    <h2>检索设置</h2>",
            f'    <div class="settings-grid">{rows}</div>',
            "  </section>",
        ]
    )


def _status_pill(status: str) -> str:
    normalized = str(status or "no_evidence_found")
    label = _status_label(normalized)
    return f'<span class="status-pill status-{escape(normalized)}">{escape(label)}</span>'


def _status_label(status: str) -> str:
    labels = {
        "supported": "已支持",
        "partial_support": "部分支持",
        "weak_candidate": "证据不足",
        "no_evidence_found": "未找到证据",
    }
    normalized = str(status or "no_evidence_found")
    return labels.get(normalized, normalized.replace("_", " "))


def _score_meter(score: int) -> str:
    width = max(0, min(100, int(score)))
    return f'<span class="score-meter" aria-label="支持度"><span style="--score-width: {width}%"></span></span>'


def _bounded_score(value: object) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _is_displayable_evidence(item: Any) -> bool:
    row = dict(item or {})
    return str(row.get("support_status", "") or "") in DISPLAYABLE_EVIDENCE_STATUSES


def _doi_meta(doi: str) -> str:
    return f" | DOI: {escape(doi)}" if doi else ""


def _display_href(card: dict[str, Any], *, output_path: str | Path | None) -> str:
    raw = str(card.get("source_href", "") or "")
    if not raw:
        return ""
    path_part, anchor = _split_anchor(raw)
    if _is_external_href(path_part) or output_path is None:
        return raw
    try:
        source_path = Path(path_part)
        if not source_path.is_absolute():
            source_path = Path.cwd() / source_path
        output = Path(output_path)
        if not output.is_absolute():
            output = Path.cwd() / output
        relative = os.path.relpath(source_path, start=output.parent)
        display = Path(relative).as_posix()
    except (OSError, ValueError):
        display = path_part
    return f"{display}#{anchor}" if anchor else display


def _split_anchor(href: str) -> tuple[str, str]:
    if "#" not in href:
        return href, ""
    path_part, anchor = href.split("#", 1)
    return path_part, anchor


def _is_external_href(href: str) -> bool:
    lowered = href.lower()
    return "://" in lowered or lowered.startswith("mailto:") or lowered.startswith("data:")


def _render_script() -> str:
    return "\n".join(
        [
            "  <script>",
            "    const frame = document.getElementById('source-frame');",
            "    const openLink = document.getElementById('source-open-link');",
            "    function loadSource(href) {",
            "      if (!href) return;",
            "      if (frame) frame.src = href;",
            "      if (openLink) openLink.href = href;",
            "    }",
            "    function setActiveSource(citationId) {",
            "      for (const card of document.querySelectorAll('.source-card')) card.dataset.active = 'false';",
            "      const card = document.getElementById(`source-${citationId}`);",
            "      if (card) {",
            "        card.dataset.active = 'true';",
            "        card.scrollIntoView({ block: 'nearest' });",
            "      }",
            "    }",
            "    for (const link of document.querySelectorAll('.citation')) {",
            "      link.addEventListener('click', (event) => {",
            "        const citationId = link.dataset.citationId;",
            "        const href = link.dataset.sourceHref;",
            "        loadSource(href);",
            "        setActiveSource(citationId);",
            "        const claim = link.closest('.claim-row');",
            "        for (const row of document.querySelectorAll('.claim-row')) row.dataset.active = 'false';",
            "        if (claim) claim.dataset.active = 'true';",
            "      });",
            "    }",
            "    for (const button of document.querySelectorAll('[data-load-source]')) {",
            "      button.addEventListener('click', () => loadSource(button.dataset.loadSource));",
            "    }",
            "    for (const button of document.querySelectorAll('[data-review-action]')) {",
            "      button.addEventListener('click', () => {",
            "        const claim = document.querySelector(`[data-claim-id=\"${button.dataset.claimId}\"]`);",
            "        if (!claim) return;",
            "        claim.dataset.reviewState = button.dataset.reviewAction;",
            "        localStorage.setItem(`scansci-grounding-review:${button.dataset.claimId}`, button.dataset.reviewAction);",
            "        for (const peer of claim.querySelectorAll('[data-review-action]')) peer.setAttribute('aria-pressed', 'false');",
            "        button.setAttribute('aria-pressed', 'true');",
            "      });",
            "    }",
            "    for (const claim of document.querySelectorAll('.claim-row[data-claim-id]')) {",
            "      const saved = localStorage.getItem(`scansci-grounding-review:${claim.dataset.claimId}`);",
            "      if (!saved) continue;",
            "      claim.dataset.reviewState = saved;",
            "      const button = claim.querySelector(`[data-review-action=\"${saved}\"]`);",
            "      if (button) button.setAttribute('aria-pressed', 'true');",
            "    }",
            "    function applyFilter(value) {",
            "      for (const row of document.querySelectorAll('.claim-row[data-support-status]')) {",
            "        const needsReview = row.dataset.reviewState !== 'confirmed' && row.dataset.supportStatus !== 'supported';",
            "        const visible = value === 'all' || row.dataset.supportStatus === value || (value === 'needs_review' && needsReview);",
            "        row.dataset.hidden = visible ? 'false' : 'true';",
            "      }",
            "    }",
            "    for (const button of document.querySelectorAll('[data-filter]')) {",
            "      button.addEventListener('click', () => {",
            "        for (const peer of document.querySelectorAll('[data-filter]')) peer.setAttribute('aria-pressed', 'false');",
            "        button.setAttribute('aria-pressed', 'true');",
            "        applyFilter(button.dataset.filter);",
            "      });",
            "    }",
            "  </script>",
        ]
    )
