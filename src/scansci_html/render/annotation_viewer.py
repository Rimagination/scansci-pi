from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
from typing import Any


DISPLAYABLE_EVIDENCE_STATUSES = {"supported", "partial_support"}


def render_annotation_overlay_viewer(
    payload: dict[str, Any],
    *,
    output_path: str | Path | None = None,
    title: str = "ScanSci 软标注图层",
) -> str:
    viewer_data = _viewer_data(payload, output_path=output_path)
    first_document_href = str(viewer_data.get("active_document_href", ""))
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
            _render_header(title, viewer_data),
            _render_toolbar(viewer_data),
            '  <section class="viewer-shell">',
            _render_document_pane(first_document_href),
            _render_layer_pane(viewer_data),
            "  </section>",
            f'  <script id="annotation-data" type="application/json">{_json_script(viewer_data)}</script>',
            _render_script(),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _viewer_data(payload: dict[str, Any], *, output_path: str | Path | None) -> dict[str, object]:
    documents = [
        _document_for_viewer(dict(document or {}), output_path=output_path)
        for document in payload.get("documents", []) or []
    ]
    layers = []
    for layer in payload.get("layers", []) or []:
        layer_dict = dict(layer or {})
        layer_items = []
        for item in layer_dict.get("items", []) or []:
            item_dict = dict(item or {})
            if not _is_displayable_evidence(item_dict):
                continue
            item_dict["source_href"] = _display_href(str(item_dict.get("source_href", "")), output_path=output_path)
            layer_items.append(item_dict)
        layer_dict["items"] = layer_items
        layers.append(layer_dict)
    summary = dict(payload.get("summary", {}) or {})
    summary["documents"] = len(documents)
    summary["layers"] = len(layers)
    summary["items"] = sum(len(dict(layer).get("items", []) or []) for layer in layers)
    return {
        "schema_version": str(payload.get("schema_version", "annotation_overlay_viewer.v1")),
        "summary": summary,
        "documents": documents,
        "layers": layers,
        "active_document_href": str(documents[0].get("viewer_href", "")) if documents else "",
    }


def _is_displayable_evidence(item: dict[str, Any]) -> bool:
    return str(item.get("support_status", "") or "") in DISPLAYABLE_EVIDENCE_STATUSES


def _document_for_viewer(document: dict[str, Any], *, output_path: str | Path | None) -> dict[str, object]:
    evidence_html_path = str(document.get("evidence_html_path") or document.get("html_path") or "")
    source_html = _read_source_html(evidence_html_path)
    return {
        "doc_id": str(document.get("doc_id", "")),
        "title": str(document.get("title", "")),
        "doi": str(document.get("doi", "")),
        "source_url": str(document.get("source_url", "")),
        "html_path": str(document.get("html_path", "")),
        "evidence_html_path": evidence_html_path,
        "viewer_href": _display_href(evidence_html_path, output_path=output_path),
        "source_html": source_html,
    }


def _stylesheet() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --text: #17202a;
      --muted: #5b6675;
      --line: #d8e0e8;
      --accent: #0f766e;
      --accent-soft: #e1f3ef;
      --supported: #0f766e;
      --partial: #7a5b00;
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
      line-height: 1.45;
    }
    main {
      width: min(1500px, calc(100vw - 24px));
      margin: 18px auto 28px;
    }
    h1, h2, h3 { letter-spacing: 0; }
    h1 { margin: 0; font-size: 1.45rem; line-height: 1.2; }
    h2 { margin: 0 0 10px; font-size: 1rem; }
    h3 { margin: 0; font-size: .94rem; line-height: 1.3; }
    button, select { font: inherit; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
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
    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 10px;
      background: var(--surface);
      white-space: nowrap;
    }
    .toolbar {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .control {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: .84rem;
    }
    select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 9px;
      color: var(--text);
      background: var(--surface);
    }
    .viewer-shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(360px, .72fr);
      gap: 14px;
      align-items: start;
    }
    .document-pane, .layer-pane {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
    }
    .pane-head {
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
      height: calc(100vh - 190px);
      min-height: 560px;
      border: 0;
      background: #ffffff;
    }
    .layer-pane {
      position: sticky;
      top: 12px;
      max-height: calc(100vh - 36px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .layer-body {
      overflow: auto;
      padding: 12px;
    }
    .layer-meta {
      color: var(--muted);
      font-size: .86rem;
      margin-bottom: 10px;
    }
    .layer-view[data-hidden="true"] {
      display: none;
    }
    .claim-group {
      border-top: 1px solid var(--line);
      padding: 12px 0;
    }
    .claim-group:first-child { border-top: 0; padding-top: 0; }
    .claim-text {
      margin: 0 0 8px;
      font-size: .95rem;
    }
    .annotation-item {
      border-left: 3px solid var(--accent);
      margin: 8px 0;
      padding: 7px 0 7px 10px;
      color: #243141;
      font-size: .88rem;
      cursor: pointer;
    }
    .annotation-item[data-support-status="partial_support"] { border-left-color: var(--partial); }
    .annotation-item[data-support-status="weak_candidate"] { border-left-color: var(--weak); }
    .annotation-item[data-active="true"] {
      background: #f4f8ff;
      box-shadow: inset 0 0 0 1px rgba(37, 99, 235, .38);
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: .75rem;
      font-weight: 800;
    }
    .status-supported { color: var(--supported); background: #e5f6f0; }
    .status-partial_support { color: var(--partial); background: #fff3c4; }
    .status-weak_candidate { color: var(--weak); background: #ffe5d3; }
    .status-no_evidence_found { color: var(--missing); background: #ffe2e8; }
    .item-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 6px;
    }
    .item-actions button, .item-actions a {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 4px 8px;
      color: #075f59;
      background: #ffffff;
      text-decoration: none;
      cursor: pointer;
    }
    .empty {
      color: var(--muted);
      padding: 12px;
    }
    @media (max-width: 980px) {
      main { width: min(100vw - 20px, 780px); }
      .topbar { align-items: flex-start; flex-direction: column; }
      .summary { justify-content: flex-start; }
      .viewer-shell { grid-template-columns: 1fr; }
      .layer-pane { position: static; max-height: none; }
      iframe { height: 620px; min-height: 460px; }
    }
    """.strip()


def _render_header(title: str, payload: dict[str, Any]) -> str:
    summary = dict(payload.get("summary", {}) or {})
    rows = [
        ("文档", summary.get("documents", 0)),
        ("图层", summary.get("layers", 0)),
        ("证据项", summary.get("items", 0)),
    ]
    chips = "".join(f'<span class="chip">{escape(label)}: {escape(str(value))}</span>' for label, value in rows)
    return "\n".join(
        [
            '  <header class="topbar">',
            f"    <h1>{escape(title)}</h1>",
            f'    <div class="summary">{chips}</div>',
            "  </header>",
        ]
    )


def _render_toolbar(viewer_data: dict[str, Any]) -> str:
    documents = list(viewer_data.get("documents", []) or [])
    layers = list(viewer_data.get("layers", []) or [])
    document_options = "".join(
        (
            f'<option value="{escape(str(document.get("doc_id", "")))}">'
            f'{escape(str(document.get("title", "") or document.get("doc_id", "")))}</option>'
        )
        for document in documents
    )
    layer_options = "".join(
        (
            f'<option value="{escape(str(layer.get("layer_id", "")))}">'
            f'{escape(str(layer.get("name", "") or layer.get("layer_id", "")))}</option>'
        )
        for layer in layers
    )
    return "\n".join(
        [
            '  <section class="toolbar">',
            '    <label class="control">论文',
            f'      <select id="document-select">{document_options}</select>',
            "    </label>",
            '    <label class="control">标注图层',
            f'      <select id="layer-select">{layer_options}</select>',
            "    </label>",
            "  </section>",
        ]
    )


def _render_document_pane(first_href: str) -> str:
    return "\n".join(
        [
            '    <section class="document-pane">',
            '      <div class="pane-head">',
            '        <strong>原文</strong>',
            f'        <a id="document-open-link" href="{escape(first_href)}" target="_blank" rel="noreferrer">打开</a>',
            "      </div>",
            '      <iframe id="document-frame" title="原文"></iframe>',
            "    </section>",
        ]
    )


def _render_layer_pane(viewer_data: dict[str, Any]) -> str:
    layers = list(viewer_data.get("layers", []) or [])
    if not layers:
        body = '<p class="empty">暂无可用的标注图层。</p>'
    else:
        body = "".join(_render_layer(layer, index=index) for index, layer in enumerate(layers))
    return "\n".join(
        [
            '    <aside class="layer-pane">',
            '      <div class="pane-head">',
            "        <strong>标注内容</strong>",
            '        <span id="layer-count"></span>',
            "      </div>",
            f'      <div class="layer-body">{body}</div>',
            "    </aside>",
        ]
    )


def _render_layer(layer: Any, *, index: int) -> str:
    item = dict(layer or {})
    layer_id = str(item.get("layer_id", ""))
    hidden = "false" if index == 0 else "true"
    items = list(item.get("items", []) or [])
    groups = _items_by_segment(items)
    if not groups:
        group_html = '<p class="empty">这个图层还没有可定位的证据项。</p>'
    else:
        group_html = "".join(_render_claim_group(group) for group in groups)
    return "\n".join(
        [
            f'        <section class="layer-view" data-layer-id="{escape(layer_id)}" data-hidden="{hidden}">',
            f'          <div class="layer-meta">{escape(str(item.get("name", "") or layer_id))} | {escape(str(len(groups)))} 条主张 | {escape(str(len(items)))} 条证据</div>',
            group_html,
            "        </section>",
        ]
    )


def _items_by_segment(items: list[Any]) -> list[dict[str, object]]:
    groups_by_id: dict[str, dict[str, object]] = {}
    for raw_item in items:
        item = dict(raw_item or {})
        segment_id = str(item.get("segment_id", ""))
        payload = dict(item.get("payload", {}) or {})
        segment = dict(payload.get("segment", {}) or {})
        group = groups_by_id.setdefault(
            segment_id,
            {
                "segment_id": segment_id,
                "claim_text": str(item.get("claim_text") or segment.get("text") or ""),
                "items": [],
            },
        )
        group_items = list(group["items"])
        group_items.append(item)
        group["items"] = group_items
    return list(groups_by_id.values())


def _render_claim_group(group: dict[str, object]) -> str:
    items = list(group.get("items", []) or [])
    item_html = "".join(_render_annotation_item(item) for item in items)
    return "\n".join(
        [
            f'          <article class="claim-group" data-segment-id="{escape(str(group.get("segment_id", "")))}">',
            f'            <p class="claim-text">{escape(str(group.get("claim_text", "")))}</p>',
            item_html,
            "          </article>",
        ]
    )


def _render_annotation_item(item: Any) -> str:
    row = dict(item or {})
    status = str(row.get("support_status", "weak_candidate"))
    score = _bounded_score(row.get("support_score"))
    href = str(row.get("source_href", ""))
    anchor = str(row.get("html_anchor", ""))
    evidence_id = str(row.get("evidence_id", ""))
    return "\n".join(
        [
            (
                f'            <div class="annotation-item" data-evidence-id="{escape(evidence_id)}" '
                f'data-html-anchor="{escape(anchor)}" data-source-href="{escape(href)}" '
                f'data-doc-id="{escape(str(row.get("doc_id", "")))}" '
                f'data-support-status="{escape(status)}" role="button" tabindex="0">'
            ),
            f'              {_status_pill(status)} <span>支持度 {score}/100</span>',
            f'              <div>{escape(str(row.get("quote", "")))}</div>',
            '              <div class="item-actions">',
            (
                f'                <button type="button" data-jump-anchor="{escape(anchor)}" '
                f'data-source-href="{escape(href)}" data-doc-id="{escape(str(row.get("doc_id", "")))}">定位</button>'
            ),
            f'                <a href="{escape(href)}" target="_blank" rel="noreferrer">打开锚点</a>',
            "              </div>",
            "            </div>",
        ]
    )


def _status_pill(status: str) -> str:
    normalized = str(status or "no_evidence_found")
    return f'<span class="status-pill status-{escape(normalized)}">{escape(_status_label(normalized))}</span>'


def _status_label(status: str) -> str:
    labels = {
        "supported": "已支持",
        "partial_support": "部分支持",
        "weak_candidate": "证据不足",
        "no_evidence_found": "未找到证据",
    }
    normalized = str(status or "no_evidence_found")
    return labels.get(normalized, normalized.replace("_", " "))


def _bounded_score(value: object) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _display_href(raw_href: str, *, output_path: str | Path | None) -> str:
    raw = str(raw_href or "")
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


def _read_source_html(path_value: str) -> str:
    path_text = str(path_value or "").strip()
    if not path_text or _is_external_href(path_text):
        return ""
    path = Path(path_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _json_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def _render_script() -> str:
    return "\n".join(
        [
            "  <script>",
            "    const data = JSON.parse(document.getElementById('annotation-data').textContent);",
            "    const frame = document.getElementById('document-frame');",
            "    const openLink = document.getElementById('document-open-link');",
            "    const documentSelect = document.getElementById('document-select');",
            "    const layerSelect = document.getElementById('layer-select');",
            "    let currentDocId = '';",
            "    let pendingAnchor = '';",
            "    let activeEvidenceId = '';",
            "    let activeAnchor = '';",
            "    function activeLayer() {",
            "      return data.layers.find(layer => layer.layer_id === layerSelect.value) || data.layers[0];",
            "    }",
            "    function activeDocument(docId) {",
            "      return data.documents.find(doc => doc.doc_id === docId) || data.documents[0];",
            "    }",
            "    function layerItems(layer) {",
            "      return (layer && Array.isArray(layer.items)) ? layer.items : [];",
            "    }",
            "    function firstItemForDocument(layer, docId) {",
            "      return layerItems(layer).find(item => !docId || !item.doc_id || item.doc_id === docId) || null;",
            "    }",
            "    function itemFromElement(el) {",
            "      if (!el) return null;",
            "      const evidenceId = el.dataset.evidenceId || '';",
            "      const anchor = el.dataset.htmlAnchor || el.dataset.jumpAnchor || '';",
            "      const docId = el.dataset.docId || currentDocId;",
            "      return layerItems(activeLayer()).find(item => {",
            "        const sameDoc = !docId || !item.doc_id || item.doc_id === docId;",
            "        const sameEvidence = evidenceId && item.evidence_id === evidenceId;",
            "        const sameAnchor = anchor && item.html_anchor === anchor;",
            "        return sameDoc && (sameEvidence || sameAnchor);",
            "      }) || null;",
            "    }",
            "    function supportStatusLabel(status) {",
            "      const labels = { supported: '已支持', partial_support: '部分支持', weak_candidate: '证据不足', no_evidence_found: '未找到证据' };",
            "      return labels[status || 'no_evidence_found'] || String(status || '').replaceAll('_', ' ');",
            "    }",
            "    function hrefWithAnchor(href, anchor) {",
            "      if (!href || !anchor) return href || '';",
            "      return `${href.split('#')[0]}#${anchor}`;",
            "    }",
            "    function setDocument(docId, anchor = '', force = false) {",
            "      const doc = activeDocument(docId);",
            "      if (!doc) return;",
            "      const sameDocument = currentDocId === doc.doc_id && frame.contentDocument;",
            "      currentDocId = doc.doc_id;",
            "      pendingAnchor = anchor || '';",
            "      if (documentSelect && documentSelect.value !== currentDocId) documentSelect.value = currentDocId;",
            "      openLink.href = hrefWithAnchor(doc.viewer_href, pendingAnchor);",
            "      if (sameDocument && !force) {",
            "        applyLayerOverlay();",
            "      } else {",
            "        frame.srcdoc = doc.source_html || '<!doctype html><meta charset=\"utf-8\"><p>原文 HTML 不可用。</p>';",
            "      }",
            "    }",
            "    function clearLayerViews() {",
            "      for (const view of document.querySelectorAll('.layer-view')) view.dataset.hidden = 'true';",
            "    }",
            "    function showLayerView(layerId) {",
            "      clearLayerViews();",
            "      const view = document.querySelector(`[data-layer-id=\"${CSS.escape(layerId)}\"]`);",
            "      if (view) view.dataset.hidden = 'false';",
            "    }",
            "    function setActiveCards() {",
            "      for (const card of document.querySelectorAll('.annotation-item')) card.dataset.active = 'false';",
            "      if (!activeEvidenceId && !activeAnchor) return;",
            "      const selector = activeEvidenceId",
            "        ? `.annotation-item[data-evidence-id=\"${CSS.escape(activeEvidenceId)}\"]`",
            "        : `.annotation-item[data-html-anchor=\"${CSS.escape(activeAnchor)}\"]`;",
            "      const card = [...document.querySelectorAll(selector)].find(el => !currentDocId || !el.dataset.docId || el.dataset.docId === currentDocId);",
            "      if (card) {",
            "        card.dataset.active = 'true';",
            "        card.scrollIntoView({ block: 'nearest' });",
            "      }",
            "    }",
            "    function selectActiveItem(item, options = {}) {",
            "      if (!item) {",
            "        activeEvidenceId = '';",
            "        activeAnchor = '';",
            "        pendingAnchor = '';",
            "        setActiveCards();",
            "        applyLayerOverlay();",
            "        return;",
            "      }",
            "      activeEvidenceId = item.evidence_id || '';",
            "      activeAnchor = item.html_anchor || '';",
            "      setActiveCards();",
            "      setDocument(item.doc_id || currentDocId, activeAnchor, Boolean(options.forceDocument));",
            "    }",
            "    function injectOverlayStyles(doc) {",
            "      if (!doc || doc.getElementById('scansci-soft-layer-style')) return;",
            "      const style = doc.createElement('style');",
            "      style.id = 'scansci-soft-layer-style';",
            "      style.textContent = `",
            "        .scansci-evidence-span,",
            "        .scansci-evidence-row {",
            "          background: transparent !important;",
            "          border-bottom: 0 !important;",
            "        }",
            "        .scansci-evidence-span::after,",
            "        .scansci-evidence-row > :last-child::after {",
            "          content: none !important;",
            "        }",
            "        .scansci-evidence-span:hover,",
            "        .scansci-evidence-row:hover {",
            "          background: transparent !important;",
            "        }",
            "        .scansci-soft-layer-highlight { border-radius: 3px; }",
            "        .scansci-soft-layer-supported { background: #dff3ef !important; }",
            "        .scansci-soft-layer-partial_support { background: #fff2b8 !important; }",
            "        .scansci-soft-layer-weak_candidate { background: #ffe0c7 !important; }",
            "        .scansci-soft-layer-active { outline: 3px solid #2563eb !important; outline-offset: 2px; box-shadow: 0 0 0 4px rgba(37, 99, 235, .18) !important; }",
            "      `;",
            "      doc.head.appendChild(style);",
            "    }",
            "    function clearFrameHighlights(doc) {",
            "      if (!doc) return;",
            "      for (const el of doc.querySelectorAll('.scansci-soft-layer-highlight, .scansci-soft-layer-active')) {",
            "        el.classList.remove('scansci-soft-layer-highlight', 'scansci-soft-layer-active', 'scansci-soft-layer-supported', 'scansci-soft-layer-partial_support', 'scansci-soft-layer-weak_candidate');",
            "        el.removeAttribute('data-soft-layer-active');",
            "      }",
            "    }",
            "    function applyLayerOverlay() {",
            "      const layer = activeLayer();",
            "      const doc = frame.contentDocument;",
            "      if (!layer || !doc) return;",
            "      injectOverlayStyles(doc);",
            "      clearFrameHighlights(doc);",
            "      const items = layerItems(layer).filter(item => !currentDocId || !item.doc_id || item.doc_id === currentDocId);",
            "      for (const item of layer.items || []) {",
            "        if (currentDocId && item.doc_id && item.doc_id !== currentDocId) continue;",
            "        const anchor = item.html_anchor || '';",
            "        const evidenceId = item.evidence_id || '';",
            "        const el = (anchor && doc.getElementById(anchor)) || (evidenceId && doc.querySelector(`[data-evidence-id=\"${CSS.escape(evidenceId)}\"]`));",
            "        if (!el) continue;",
            "        el.classList.add('scansci-soft-layer-highlight', `scansci-soft-layer-${item.support_status || 'weak_candidate'}`);",
            "        const isActive = (activeEvidenceId && evidenceId === activeEvidenceId) || (activeAnchor && anchor === activeAnchor);",
            "        if (isActive) {",
            "          el.classList.add('scansci-soft-layer-active');",
            "          el.dataset.softLayerActive = layer.layer_id;",
            "        }",
            "        el.title = `${layer.name || layer.layer_id}: ${supportStatusLabel(item.support_status)}，支持度 ${Math.round(item.support_score || 0)}/100`;",
            "      }",
            "      const count = items.length;",
            "      const layerCount = document.getElementById('layer-count');",
            "      if (layerCount) layerCount.textContent = count ? `${count} 条证据` : '无可显示证据';",
            "      setActiveCards();",
            "      if (pendingAnchor) {",
            "        const target = doc.getElementById(pendingAnchor);",
            "        if (target) target.scrollIntoView({ block: 'center' });",
            "      }",
            "    }",
            "    function applyLayer() {",
            "      const layer = activeLayer();",
            "      if (!layer) return;",
            "      showLayerView(layer.layer_id);",
            "      const selected = firstItemForDocument(layer, currentDocId);",
            "      if (selected) selectActiveItem(selected);",
            "      else applyLayerOverlay();",
            "    }",
            "    documentSelect.addEventListener('change', () => {",
            "      const layer = activeLayer();",
            "      const selected = firstItemForDocument(layer, documentSelect.value);",
            "      if (selected) selectActiveItem(selected);",
            "      else {",
            "        activeEvidenceId = '';",
            "        activeAnchor = '';",
            "        setDocument(documentSelect.value);",
            "      }",
            "    });",
            "    layerSelect.addEventListener('change', applyLayer);",
            "    frame.addEventListener('load', applyLayerOverlay);",
            "    for (const button of document.querySelectorAll('[data-jump-anchor]')) {",
            "      button.addEventListener('click', () => {",
            "        const item = itemFromElement(button);",
            "        if (item) selectActiveItem(item);",
            "        else setDocument(button.dataset.docId || currentDocId, button.dataset.jumpAnchor || '');",
            "      });",
            "    }",
            "    for (const card of document.querySelectorAll('.annotation-item')) {",
            "      card.addEventListener('click', event => {",
            "        if (event.target.closest('a')) return;",
            "        const item = itemFromElement(card);",
            "        if (item) selectActiveItem(item);",
            "      });",
            "      card.addEventListener('keydown', event => {",
            "        if (event.key !== 'Enter' && event.key !== ' ') return;",
            "        event.preventDefault();",
            "        const item = itemFromElement(card);",
            "        if (item) selectActiveItem(item);",
            "      });",
            "    }",
            "    if (data.documents.length) {",
            "      const firstLayer = activeLayer();",
            "      const firstItem = firstItemForDocument(firstLayer, data.documents[0].doc_id);",
            "      if (firstItem) selectActiveItem(firstItem, { forceDocument: true });",
            "      else setDocument(data.documents[0].doc_id, '', true);",
            "    }",
            "    applyLayer();",
            "  </script>",
        ]
    )
