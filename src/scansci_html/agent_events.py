"""Stable model/agent event vocabulary used by all ScanSci harnesses.

The existing UI protocol has its own AG-UI-shaped events.  This module is the
provider-neutral layer underneath it: a Chat Completions response, a
Responses response, Pi, and optional Python harnesses can all emit the same
small set of events without exposing provider-specific payloads to callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


TEXT_DELTA = "text_delta"
REASONING_DELTA = "reasoning_delta"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
USAGE = "usage"
RETRY = "retry"
COMPLETED = "completed"
ERROR = "error"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class AgentEvent:
    """A normalized, JSON-safe event emitted by a model transport."""

    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    run_id: str = ""
    request_id: str = ""
    event_id: str = field(default_factory=lambda: f"evt-{uuid4().hex}")
    timestamp: str = field(default_factory=_timestamp)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": str(self.type),
            "event_id": self.event_id,
            "timestamp": self.timestamp,
        }
        if self.run_id:
            result["run_id"] = self.run_id
        if self.request_id:
            result["request_id"] = self.request_id
        result.update(dict(self.payload))
        return result


def make_event(
    event_type: str,
    *,
    run_id: str = "",
    request_id: str = "",
    **payload: Any,
) -> dict[str, Any]:
    """Build one normalized event as a plain dictionary."""

    return AgentEvent(
        event_type,
        payload=payload,
        run_id=str(run_id or ""),
        request_id=str(request_id or ""),
    ).to_dict()


def normalize_usage(value: object) -> dict[str, int]:
    """Normalize common OpenAI/Anthropic usage shapes without leaking extras."""

    if not isinstance(value, Mapping):
        return {}

    def integer(*keys: str) -> int | None:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                return candidate
        return None

    input_tokens = integer("input_tokens", "prompt_tokens")
    output_tokens = integer("output_tokens", "completion_tokens")
    total_tokens = integer("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    result: dict[str, int] = {}
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
    if total_tokens is not None:
        result["total_tokens"] = total_tokens
    return result


__all__ = [
    "AgentEvent",
    "COMPLETED",
    "ERROR",
    "REASONING_DELTA",
    "RETRY",
    "TEXT_DELTA",
    "TOOL_CALL",
    "TOOL_RESULT",
    "USAGE",
    "make_event",
    "normalize_usage",
]
