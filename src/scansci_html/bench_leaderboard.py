from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any


LEADERBOARD_METRICS = [
    "retrieval_recall_at_k",
    "all_gold_retrieval_recall_at_k",
    "gold_evidence_recall_at_k",
    "answer_accuracy",
    "answerable_evidence_adequacy_rate",
    "citation_f1",
    "unsupported_claim_rate",
    "abstention_accuracy",
]

LEADERBOARD_EFFICIENCY_METRICS = [
    "wall_time_seconds",
    "avg_wall_time_seconds_per_question",
    "embedding_cache_hit_rate",
    "query_embedding_cache_hit_rate",
    "reranker_score_cache_hit_rate",
]

LOWER_IS_BETTER = {"unsupported_claim_rate"}

LEADERBOARD_CSV_FIELDS = [
    "rank",
    "comparison_group",
    "label",
    "dataset",
    "questions",
    "answerable_questions",
    "benchmark_target",
    "benchmark_mode",
    "scope",
    "k",
    "candidate_pool",
    "query_variants",
    "max_followup_queries",
    "paper_recall_limit",
    "embedding_provider",
    "reranker",
    *LEADERBOARD_METRICS,
    *LEADERBOARD_EFFICIENCY_METRICS,
    "retrieval_trace_questions",
    "avg_search_calls_per_question",
    "avg_fts_candidates_per_question",
    "avg_dense_candidates_per_question",
    "source_path",
]


def build_benchmark_leaderboard(
    detail_paths: list[str | Path],
    *,
    labels: list[str] | None = None,
    sort_by: str = "gold_evidence_recall_at_k",
) -> dict[str, Any]:
    paths = [Path(path) for path in detail_paths]
    label_values = labels or []
    rows = [
        _leaderboard_row(path, label=label_values[index] if index < len(label_values) else "")
        for index, path in enumerate(paths)
    ]
    grouped_rows: list[dict[str, Any]] = []
    for group in sorted({str(row.get("comparison_group", "")) for row in rows}):
        group_rows = [row for row in rows if str(row.get("comparison_group", "")) == group]
        group_rows.sort(key=lambda row: _sort_key(row, sort_by=sort_by), reverse=_sort_descending(sort_by))
        for index, row in enumerate(group_rows, start=1):
            row["rank"] = index
        grouped_rows.extend(group_rows)
    return {
        "sort_by": sort_by,
        "sort_direction": "asc" if sort_by in LOWER_IS_BETTER else "desc",
        "rank_scope": "comparison_group",
        "runs": len(grouped_rows),
        "datasets": _count_values(grouped_rows, "dataset"),
        "comparison_groups": _count_values(grouped_rows, "comparison_group"),
        "rows": grouped_rows,
    }


def render_leaderboard_markdown(payload: dict[str, Any]) -> str:
    rows = list(payload.get("rows", []) or [])
    header = [
        "Rank",
        "Group",
        "Label",
        "Dataset",
        "Mode",
        "Scope",
        "k",
        "Candidates",
        "Embedding",
        "Reranker",
        "Retrieval@k",
        "All-gold@k",
        "Evidence recall@k",
        "Questions",
    ]
    lines = [
        "# ScanSci Evidence Retrieval Leaderboard",
        "",
        f"Sort: `{payload.get('sort_by', '')}` ({payload.get('sort_direction', '')}); rank scope: `{payload.get('rank_scope', '')}`",
        "",
        "|" + "|".join(header) + "|",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        values = [
            row.get("rank", ""),
            row.get("comparison_group", ""),
            row.get("label", ""),
            row.get("dataset", ""),
            row.get("benchmark_mode", ""),
            row.get("scope", ""),
            row.get("k", ""),
            row.get("candidate_pool", ""),
            row.get("embedding_provider", ""),
            row.get("reranker", ""),
            _format_metric(row.get("retrieval_recall_at_k")),
            _format_metric(row.get("all_gold_retrieval_recall_at_k")),
            _format_metric(row.get("gold_evidence_recall_at_k")),
            row.get("questions", ""),
        ]
        lines.append("|" + "|".join(_markdown_cell(value) for value in values) + "|")
    lines.extend(
        [
            "",
            "Notes:",
            "",
            "- `retrieval@k` means at least one gold evidence item was retrieved for an answerable question.",
            "- `all-gold@k` means all gold evidence items for the question were retrieved.",
            "- `evidence recall@k` is evidence-ID-level recall and is the default ranking metric.",
            "- Public benchmark rows are the paper-style validation baseline; local gold rows are optional acceptance evidence and must be reported separately.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_leaderboard_html(
    payload: dict[str, Any],
    *,
    title: str = "ScanSci Evidence Retrieval Leaderboard",
) -> str:
    rows = list(payload.get("rows", []) or [])
    table_rows = "\n".join(_render_html_row(row) for row in rows)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    body { font-family: system-ui, sans-serif; line-height: 1.45; margin: 2rem; color: #17202a; }",
            "    main { max-width: 1280px; margin: 0 auto; }",
            "    table { border-collapse: collapse; width: 100%; font-size: .92rem; }",
            "    th, td { border-bottom: 1px solid #d7dee8; padding: .45rem .5rem; text-align: left; vertical-align: top; }",
            "    th { background: #f8fafc; position: sticky; top: 0; }",
            "    code { white-space: pre-wrap; overflow-wrap: anywhere; }",
            "    .num { font-variant-numeric: tabular-nums; }",
            "    .notes { color: #455466; max-width: 900px; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            f"  <p class=\"notes\">Sort: <code>{escape(str(payload.get('sort_by', '')))}</code> ({escape(str(payload.get('sort_direction', '')))}). Rank scope: <code>{escape(str(payload.get('rank_scope', '')))}</code>. Runs: {escape(str(payload.get('runs', 0)))}.</p>",
            "  <table>",
            "    <thead>",
            "      <tr><th>Rank</th><th>Group</th><th>Label</th><th>Dataset</th><th>Mode</th><th>Scope</th><th>k</th><th>Candidates</th><th>Embedding</th><th>Reranker</th><th>Retrieval@k</th><th>All-gold@k</th><th>Evidence recall@k</th><th>Questions</th><th>Source</th></tr>",
            "    </thead>",
            "    <tbody>",
            table_rows,
            "    </tbody>",
            "  </table>",
            "  <p class=\"notes\">Public benchmark scores are the paper-style validation baseline. Keep local gold scores as optional acceptance evidence and report them separately.</p>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def render_leaderboard_chart_html(
    payload: dict[str, Any],
    *,
    title: str = "ScanSci Benchmark Performance",
    metric: str | None = None,
) -> str:
    resolved_metric = metric or str(payload.get("sort_by", "") or "gold_evidence_recall_at_k")
    chart_svg = render_leaderboard_chart_svg(payload, metric=resolved_metric, title=title)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    :root { color-scheme: light; }",
            "    body { font-family: Arial, Helvetica, sans-serif; margin: 0; color: #17202a; background: #ffffff; }",
            "    main { max-width: 1240px; margin: 0 auto; padding: 28px 30px 40px; }",
            "    h1 { font-size: 28px; margin: 0 0 8px; letter-spacing: 0; }",
            "    .subtitle { color: #687584; margin: 0 0 18px; max-width: 980px; line-height: 1.45; }",
            "    .chart-frame { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px; }",
            "    .note { color: #687584; font-size: 13px; line-height: 1.45; max-width: 980px; }",
            "    svg { display: block; max-width: none; }",
            "  </style>",
            "</head>",
            "<body>",
            "<main>",
            f"  <h1>{escape(title)}</h1>",
            f"  <p class=\"subtitle\">Grouped benchmark bars generated from leaderboard metric <code>{escape(resolved_metric)}</code>. Scores are shown as percentages when metric values are stored as 0-1 ratios.</p>",
            "  <div class=\"chart-frame\">",
            chart_svg,
            "  </div>",
            "  <p class=\"note\">Public benchmark scores are the paper-style validation baseline. Keep local acceptance benchmarks separate from public development sets when making model-selection decisions.</p>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def render_leaderboard_chart_svg(
    payload: dict[str, Any],
    *,
    metric: str = "gold_evidence_recall_at_k",
    title: str = "ScanSci Benchmark Performance",
) -> str:
    rows = [row for row in list(payload.get("rows", []) or []) if _float_or_empty(row.get(metric)) != ""]
    if not rows:
        return _empty_chart_svg(metric=metric, title=title)

    groups = _chart_groups(rows)
    series = _chart_series(rows)
    series_index = {label: index for index, label in enumerate(series)}
    palette = _chart_palette()
    chart_width = max(900, 160 + len(groups) * max(150, len(series) * 34 + 52))
    chart_height = 560
    margin_left = 78
    margin_top = 108
    margin_right = 32
    margin_bottom = 122
    plot_width = chart_width - margin_left - margin_right
    plot_height = chart_height - margin_top - margin_bottom
    group_width = plot_width / max(1, len(groups))
    bar_gap = 5
    group_inner = min(group_width * 0.82, max(34, len(series) * 30 + (len(series) - 1) * bar_gap))
    bar_width = max(14, min(28, (group_inner - bar_gap * max(0, len(series) - 1)) / max(1, len(series))))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{chart_width}" height="{chart_height}" viewBox="0 0 {chart_width} {chart_height}" role="img" aria-labelledby="chart-title chart-desc">',
        "  <defs>",
        '    <pattern id="diagonal-hatch" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(35)">',
        '      <line x1="0" y1="0" x2="0" y2="8" stroke="#ffffff" stroke-width="2" opacity="0.65" />',
        "    </pattern>",
        "  </defs>",
        f'  <title id="chart-title">{escape(title)}</title>',
        f'  <desc id="chart-desc">Grouped bar chart for {escape(metric)} across benchmark comparison groups.</desc>',
        '  <rect x="0" y="0" width="100%" height="100%" fill="#ffffff" />',
        f'  <text x="{margin_left}" y="34" font-size="24" font-weight="700" fill="#17202a">{escape(title)}</text>',
        f'  <text x="{margin_left}" y="58" font-size="13" fill="#687584">Metric: {escape(_metric_label(metric))}; k and question counts are shown under each benchmark.</text>',
    ]
    parts.extend(_render_chart_legend(series, palette, x=margin_left, y=78))
    parts.extend(_render_y_axis(metric, margin_left, margin_top, plot_height))

    baseline_y = margin_top + plot_height
    parts.append(
        f'  <line x1="{margin_left}" y1="{baseline_y:.2f}" x2="{margin_left + plot_width}" y2="{baseline_y:.2f}" stroke="#94a3b8" stroke-width="1" />'
    )

    for group_index, group in enumerate(groups):
        group_x = margin_left + group_index * group_width
        label_y = baseline_y + 28
        center_x = group_x + group_width / 2
        parts.append(
            f'  <text x="{center_x:.2f}" y="{label_y:.2f}" text-anchor="middle" font-size="13" font-weight="700" fill="#334155">{escape(group["label"])}</text>'
        )
        parts.append(
            f'  <text x="{center_x:.2f}" y="{label_y + 18:.2f}" text-anchor="middle" font-size="11" fill="#64748b">{escape(group["sub_label"])}</text>'
        )
        for row in group["rows"]:
            series_label = _series_label(row)
            index = series_index.get(series_label, 0)
            raw_value = float(_float_or_empty(row.get(metric)))
            value = _metric_to_percent(raw_value)
            bar_height = (value / 100.0) * plot_height
            x = group_x + (group_width - group_inner) / 2 + index * (bar_width + bar_gap)
            y = baseline_y - bar_height
            color = palette[index % len(palette)]
            pattern = ' style="fill: url(#diagonal-hatch);"' if index == 0 else ""
            parts.append(
                f'  <rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="2" fill="{color}" />'
            )
            if index == 0:
                parts.append(
                    f'  <rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="2"{pattern} />'
                )
            parts.append(
                f'  <text x="{x + bar_width / 2:.2f}" y="{max(margin_top + 13, y - 6):.2f}" text-anchor="middle" font-size="11" font-weight="700" fill="#17202a">{value:.1f}</text>'
            )

    parts.extend(
        [
            f'  <text transform="translate(20 {margin_top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle" font-size="14" font-weight="700" fill="#334155">{escape(_metric_label(metric))} (%)</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts)


def write_leaderboard_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEADERBOARD_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in LEADERBOARD_CSV_FIELDS})


def _leaderboard_row(path: Path, *, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = _metrics_payload(payload)
    row = {
        "rank": 0,
        "label": label.strip() or _default_label(path, metrics),
        "source_path": str(path),
        "source_format": "nested_metrics" if isinstance(payload, dict) and isinstance(payload.get("metrics"), dict) else "metrics",
        "dataset": _string_metric(metrics, "dataset"),
        "questions": _int_or_empty(metrics.get("questions")),
        "answerable_questions": _int_or_empty(metrics.get("answerable_questions")),
        "benchmark_target": _string_metric(metrics, "benchmark_target"),
        "benchmark_mode": _string_metric(metrics, "benchmark_mode") or "legacy",
        "scope": _string_metric(metrics, "scope"),
        "k": _int_or_empty(metrics.get("k")),
        "initial_limit": _int_or_empty(metrics.get("initial_limit")),
        "dense_limit": _int_or_empty(metrics.get("dense_limit")),
        "candidate_pool": _candidate_pool(metrics),
        "query_variants": _int_or_empty(metrics.get("query_variants")),
        "max_followup_queries": _int_or_empty(metrics.get("max_followup_queries")),
        "paper_recall_limit": _int_or_empty(metrics.get("paper_recall_limit")),
        "embedding_provider": _string_metric(metrics, "embedding_provider"),
        "reranker": _reranker_label(metrics),
        "retrieval_trace_questions": _int_or_empty(metrics.get("retrieval_trace_questions")),
        "avg_search_calls_per_question": _float_or_empty(metrics.get("avg_search_calls_per_question")),
        "avg_fts_candidates_per_question": _float_or_empty(metrics.get("avg_fts_candidates_per_question")),
        "avg_dense_candidates_per_question": _float_or_empty(metrics.get("avg_dense_candidates_per_question")),
        "reranker_score_cache_rows": _int_or_empty(metrics.get("reranker_score_cache_rows")),
        "reranker_score_cache_hits": _int_or_empty(metrics.get("reranker_score_cache_hits")),
        "reranker_score_cache_misses": _int_or_empty(metrics.get("reranker_score_cache_misses")),
    }
    for field in LEADERBOARD_METRICS:
        row[field] = _float_or_empty(metrics.get(field))
    for field in LEADERBOARD_EFFICIENCY_METRICS:
        row[field] = _float_or_empty(metrics.get(field))
    row["embedding_cache_hit_rate"] = _cache_hit_rate(
        row.get("embedding_cache_hit_rate"),
        metrics.get("embedding_cache_hits"),
        metrics.get("embedding_cache_misses"),
    )
    row["query_embedding_cache_hit_rate"] = _cache_hit_rate(
        row.get("query_embedding_cache_hit_rate"),
        metrics.get("query_embedding_cache_hits"),
        metrics.get("query_embedding_cache_misses"),
    )
    row["reranker_score_cache_hit_rate"] = _cache_hit_rate(
        row.get("reranker_score_cache_hit_rate"),
        metrics.get("reranker_score_cache_hits"),
        metrics.get("reranker_score_cache_misses"),
    )
    row["comparison_group"] = _comparison_group(row)
    return row


def _metrics_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("metrics"), dict):
        return dict(payload["metrics"])
    if isinstance(payload, dict):
        return dict(payload)
    raise ValueError("Benchmark details must be a JSON object")


def _sort_key(row: dict[str, Any], *, sort_by: str) -> tuple[float, float, float, float, str]:
    primary = _sortable_number(row.get(sort_by), lower_is_better=sort_by in LOWER_IS_BETTER)
    return (
        primary,
        _sortable_number(row.get("gold_evidence_recall_at_k")),
        _sortable_number(row.get("all_gold_retrieval_recall_at_k")),
        _sortable_number(row.get("retrieval_recall_at_k")),
        str(row.get("label", "")),
    )


def _sort_descending(sort_by: str) -> bool:
    return sort_by not in LOWER_IS_BETTER


def _sortable_number(value: Any, *, lower_is_better: bool = False) -> float:
    number = _float_or_empty(value)
    if number == "":
        return float("inf") if lower_is_better else float("-inf")
    return float(number)


def _default_label(path: Path, metrics: dict[str, Any]) -> str:
    dataset = _string_metric(metrics, "dataset")
    embedding = _string_metric(metrics, "embedding_provider")
    reranker = _reranker_label(metrics)
    candidate = _candidate_pool(metrics)
    parts = [part for part in (dataset, embedding, reranker, candidate) if part]
    return " | ".join(parts) or path.stem


def _candidate_pool(metrics: dict[str, Any]) -> str:
    initial = _int_or_empty(metrics.get("initial_limit"))
    dense = _int_or_empty(metrics.get("dense_limit"))
    if initial == "" and dense == "":
        return ""
    return f"initial={initial},dense={dense}"


def _comparison_group(row: dict[str, Any]) -> str:
    values = [
        str(row.get("benchmark_target", "") or "target-unset"),
        str(row.get("benchmark_mode", "") or "mode-unset"),
        str(row.get("dataset", "") or "dataset-unset"),
        str(row.get("scope", "") or "scope-unset"),
        f"k{row.get('k', '') or 'unset'}",
        f"q{row.get('questions', '') or 'unset'}",
    ]
    return "/".join(values)


def _reranker_label(metrics: dict[str, Any]) -> str:
    for field in ("reranker", "reranker_model", "reranker_score_cache_name"):
        value = _string_metric(metrics, field)
        if value:
            return value
    return ""


def _string_metric(metrics: dict[str, Any], field: str) -> str:
    value = metrics.get(field, "")
    return "" if value is None else str(value).strip()


def _int_or_empty(value: Any) -> int | str:
    if value in {"", None}:
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return ""


def _float_or_empty(value: Any) -> float | str:
    if value in {"", None}:
        return ""
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return ""


def _cache_hit_rate(explicit_value: Any, hits: Any, misses: Any) -> float | str:
    value = _float_or_empty(explicit_value)
    if value != "":
        return value
    hit_count = _float_or_empty(hits)
    miss_count = _float_or_empty(misses)
    if hit_count == "" or miss_count == "":
        return ""
    total = float(hit_count) + float(miss_count)
    if total <= 0:
        return ""
    return round(float(hit_count) / total, 6)


def _count_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field, "")).strip() or "unset"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _format_metric(value: Any) -> str:
    number = _float_or_empty(value)
    if number == "":
        return ""
    return f"{float(number):.4f}"


def _metric_label(metric: str) -> str:
    labels = {
        "retrieval_recall_at_k": "Retrieval@k",
        "all_gold_retrieval_recall_at_k": "All-gold@k",
        "gold_evidence_recall_at_k": "Evidence recall@k",
        "answer_accuracy": "Answer accuracy",
        "answerable_evidence_adequacy_rate": "Evidence adequacy",
        "citation_f1": "Citation F1",
        "unsupported_claim_rate": "Unsupported claim rate",
        "abstention_accuracy": "Abstention accuracy",
    }
    return labels.get(metric, metric.replace("_", " "))


def _metric_to_percent(value: float) -> float:
    return value * 100.0 if 0.0 <= value <= 1.0 else value


def _chart_palette() -> list[str]:
    return [
        "#2563eb",
        "#94a3b8",
        "#38bdf8",
        "#10b981",
        "#cbd5e1",
        "#f59e0b",
        "#8b5cf6",
        "#ef4444",
    ]


def _chart_series(rows: list[dict[str, Any]]) -> list[str]:
    series: list[str] = []
    for row in rows:
        label = _series_label(row)
        if label not in series:
            series.append(label)
    return series


def _series_label(row: dict[str, Any]) -> str:
    label = str(row.get("label", "")).strip()
    dataset = str(row.get("dataset", "")).strip()
    if label and dataset and label.lower().startswith(f"{dataset.lower()}-"):
        return label[len(dataset) + 1 :]
    if label:
        return label
    fallback = str(row.get("embedding_provider", "")).strip()
    candidate = str(row.get("candidate_pool", "")).strip()
    return " | ".join(part for part in (fallback, candidate) if part) or "run"


def _chart_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("comparison_group", "")).strip()
        if key in seen:
            continue
        group_rows = [candidate for candidate in rows if str(candidate.get("comparison_group", "")).strip() == key]
        groups.append(
            {
                "key": key,
                "label": _chart_group_label(group_rows[0]),
                "sub_label": _chart_group_sub_label(group_rows[0]),
                "rows": group_rows,
            }
        )
        seen.add(key)
    return groups


def _chart_group_label(row: dict[str, Any]) -> str:
    dataset = str(row.get("dataset", "")).strip() or "benchmark"
    return dataset.upper()


def _chart_group_sub_label(row: dict[str, Any]) -> str:
    scope = str(row.get("scope", "")).strip() or "scope"
    k = str(row.get("k", "")).strip() or "?"
    questions = str(row.get("questions", "")).strip() or "?"
    return f"{scope}; k={k}; n={questions}"


def _render_chart_legend(series: list[str], palette: list[str], *, x: int, y: int) -> list[str]:
    parts: list[str] = []
    cursor_x = x
    for index, label in enumerate(series):
        color = palette[index % len(palette)]
        parts.append(f'  <rect x="{cursor_x}" y="{y - 10}" width="13" height="13" rx="2" fill="{color}" />')
        if index == 0:
            parts.append(
                f'  <rect x="{cursor_x}" y="{y - 10}" width="13" height="13" rx="2" style="fill: url(#diagonal-hatch);" />'
            )
        parts.append(f'  <text x="{cursor_x + 18}" y="{y + 1}" font-size="12" font-weight="700" fill="#334155">{escape(label)}</text>')
        cursor_x += 28 + max(70, len(label) * 7)
    return parts


def _render_y_axis(metric: str, margin_left: int, margin_top: int, plot_height: int) -> list[str]:
    parts: list[str] = []
    for tick in range(0, 101, 20):
        y = margin_top + plot_height - (tick / 100.0) * plot_height
        parts.append(
            f'  <line x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + 10}" y2="{y:.2f}" stroke="#94a3b8" stroke-width="1" />'
        )
        parts.append(
            f'  <line x1="{margin_left}" y1="{y:.2f}" x2="100%" y2="{y:.2f}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="3 5" />'
        )
        parts.append(
            f'  <text x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end" font-size="12" fill="#475569">{tick}</text>'
        )
    parts.append(
        f'  <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#94a3b8" stroke-width="1" />'
    )
    return parts


def _empty_chart_svg(*, metric: str, title: str) -> str:
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" viewBox="0 0 900 320" role="img">',
            '<rect x="0" y="0" width="900" height="320" fill="#ffffff" />',
            f'<text x="40" y="52" font-size="24" font-weight="700" fill="#17202a">{escape(title)}</text>',
            f'<text x="40" y="92" font-size="14" fill="#64748b">No numeric rows found for metric {escape(metric)}.</text>',
            "</svg>",
        ]
    )


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_html_row(row: dict[str, Any]) -> str:
    cells = [
        row.get("rank", ""),
        row.get("comparison_group", ""),
        row.get("label", ""),
        row.get("dataset", ""),
        row.get("benchmark_mode", ""),
        row.get("scope", ""),
        row.get("k", ""),
        row.get("candidate_pool", ""),
        row.get("embedding_provider", ""),
        row.get("reranker", ""),
        _format_metric(row.get("retrieval_recall_at_k")),
        _format_metric(row.get("all_gold_retrieval_recall_at_k")),
        _format_metric(row.get("gold_evidence_recall_at_k")),
        row.get("questions", ""),
        row.get("source_path", ""),
    ]
    rendered = "".join(f"<td><code>{escape(str(cell))}</code></td>" for cell in cells)
    return f"      <tr>{rendered}</tr>"
