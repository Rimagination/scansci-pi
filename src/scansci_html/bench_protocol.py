from __future__ import annotations

from typing import Any


BENCHMARK_SPLITS = ("dev", "calibration", "blind")


def normalize_benchmark_split(value: object) -> str:
    split = str(value or "dev").strip().lower().replace("_", "-")
    aliases = {
        "development": "dev",
        "calibrate": "calibration",
        "calib": "calibration",
        "heldout": "blind",
        "held-out": "blind",
        "holdout": "blind",
        "hold-out": "blind",
        "test": "blind",
    }
    split = aliases.get(split, split)
    if split not in BENCHMARK_SPLITS:
        raise ValueError(f"unsupported benchmark split: {value!r}")
    return split


def benchmark_row_split(row: dict[str, Any]) -> str:
    for key in ("benchmark_split", "split"):
        if row.get(key):
            return normalize_benchmark_split(row.get(key))
    external_source = row.get("external_source", {})
    if isinstance(external_source, dict):
        for key in ("benchmark_split", "split"):
            if external_source.get(key):
                return normalize_benchmark_split(external_source.get(key))
    return "dev"


def filter_rows_for_benchmark_split(rows: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    resolved_split = normalize_benchmark_split(split)
    return [row for row in rows if benchmark_row_split(row) == resolved_split]


def benchmark_details_policy(split: str, *, include_details: bool) -> str:
    if not include_details:
        return "none"
    if normalize_benchmark_split(split) == "blind":
        return "aggregate_only"
    return "full"


def may_emit_question_details(split: str, *, include_details: bool) -> bool:
    return benchmark_details_policy(split, include_details=include_details) == "full"


def is_blind_benchmark_payload(payload: dict[str, Any]) -> bool:
    metrics = payload.get("metrics", payload)
    if not isinstance(metrics, dict):
        return False
    try:
        return normalize_benchmark_split(metrics.get("benchmark_split", "dev")) == "blind"
    except ValueError:
        return False

