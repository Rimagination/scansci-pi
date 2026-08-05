"""Cache-prefix diagnostics that never persist prompt contents.

The model provider only needs a stable prefix hash to explain cache misses.
Keeping the hash inputs here makes the diagnostic usable by Pi, direct chat,
and future optional harness adapters without coupling it to one SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from typing import Any


PREFIX_SHAPE_SCHEMA = "scansci.prefix-shape.v1"


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical(item) for item in value]
    if isinstance(value, os.PathLike):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

def stable_hash(value: Any) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def build_prefix_shape(
    *,
    provider: str,
    model: str,
    api_surface: str,
    system_prompt: str = "",
    tool_set: Any = (),
    selected_skills: Any = (),
    memory_keys: Any = (),
    task_contract: Any = (),
) -> dict[str, Any]:
    """Return a redacted, comparable shape of the provider-visible prefix."""

    components = {
        "provider": str(provider or ""),
        "model": str(model or ""),
        "api_surface": str(api_surface or ""),
        "system_prompt_hash": stable_hash(system_prompt or ""),
        "tool_set_hash": stable_hash(sorted(str(item) for item in (tool_set or []))) if isinstance(tool_set, (list, tuple, set, frozenset)) else stable_hash(tool_set),
        "selected_skills_hash": stable_hash(sorted(str(item) for item in (selected_skills or []))),
        "memory_keys_hash": stable_hash(sorted(str(item) for item in (memory_keys or []))),
        "task_contract_shape_hash": stable_hash(task_contract),
    }
    return {
        "schema_version": PREFIX_SHAPE_SCHEMA,
        "hash": stable_hash(components),
        "components": components,
    }


def cache_metrics(stats: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize provider cache counters from either Pi or LiteLLM names."""

    raw = dict(stats or {})
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), Mapping) else raw

    def number(*names: str) -> int:
        for name in names:
            value = tokens.get(name) if isinstance(tokens, Mapping) else None
            try:
                return max(0, int(float(value or 0)))
            except (TypeError, ValueError):
                continue
        return 0

    cache_read = number("cacheRead", "cache_read_tokens", "cache_read_input_tokens")
    cache_write = number("cacheWrite", "cache_write_tokens", "cache_creation_input_tokens")
    input_tokens = number("input", "inputTokens", "prompt_tokens")
    output_tokens = number("output", "outputTokens", "completion_tokens")
    denominator = cache_read + cache_write
    return {
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cache_miss_tokens": cache_write,
        "cache_hit_rate": round(cache_read / denominator, 6) if denominator else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def prefix_change_reason(previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> str:
    """Explain a shape change without exposing either prefix."""

    if not previous or not current:
        return "unknown"
    old = dict(previous.get("components", {}) or {})
    new = dict(current.get("components", {}) or {})
    changed = [key for key in new if old.get(key) != new.get(key)]
    return "stable" if not changed else "changed:" + ",".join(sorted(changed))


__all__ = [
    "PREFIX_SHAPE_SCHEMA",
    "build_prefix_shape",
    "cache_metrics",
    "prefix_change_reason",
    "stable_hash",
]
