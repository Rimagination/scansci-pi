"""Bounded context cleanup shared by direct chat and Agent bridges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import copy
import json
from typing import Any


@dataclass(frozen=True)
class ContextPruneReport:
    examined_tool_results: int
    pruned_tool_results: int
    preserved_tool_results: int
    original_chars: int
    retained_chars: int
    policy: str = "stale_tool_result_pruning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "examined_tool_results": self.examined_tool_results,
            "pruned_tool_results": self.pruned_tool_results,
            "preserved_tool_results": self.preserved_tool_results,
            "original_chars": self.original_chars,
            "retained_chars": self.retained_chars,
            "saved_chars": max(0, self.original_chars - self.retained_chars),
        }


def _content_size(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _tool_name(message: Mapping[str, Any]) -> str:
    return str(message.get("name") or message.get("tool_name") or message.get("toolName") or "tool")[:80]


def _pruned_content(message: Mapping[str, Any], original_chars: int) -> Any:
    notice = {
        "_scansci_pruned": True,
        "tool": _tool_name(message),
        "original_chars": original_chars,
        "notice": "Stale tool output was pruned before context compaction; rerun a focused tool if needed.",
    }
    content = message.get("content")
    if isinstance(content, str):
        return json.dumps(notice, ensure_ascii=False)
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        return [{"type": "text", "text": json.dumps(notice, ensure_ascii=False)}]
    return notice


def prune_stale_tool_results(
    messages: Sequence[Mapping[str, Any]],
    *,
    keep_recent_turns: int = 2,
) -> tuple[list[dict[str, Any]], ContextPruneReport]:
    """Replace old tool payloads with small notices while preserving order.

    A *turn* is advanced by each user message. Tool results from the latest
    ``keep_recent_turns`` turns remain intact; older results keep their tool
    identity and size metadata but no longer consume the full context budget.
    """

    keep = max(1, int(keep_recent_turns))
    current_turn = 0
    locations: list[tuple[int, int]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", "")).lower()
        if role == "user":
            current_turn += 1
        if role in {"tool", "toolresult", "tool_result"}:
            locations.append((index, current_turn))

    latest_turn = current_turn
    output = [copy.deepcopy(dict(message)) for message in messages]
    examined = pruned = preserved = original_chars = retained_chars = 0
    for index, result_turn in locations:
        message = output[index]
        content = message.get("content")
        size = _content_size(content)
        examined += 1
        original_chars += size
        if latest_turn - result_turn >= keep:
            message["content"] = _pruned_content(message, size)
            message["_scansci_context_pruned"] = True
            pruned += 1
            retained_chars += _content_size(message["content"])
        else:
            preserved += 1
            retained_chars += size
    return output, ContextPruneReport(examined, pruned, preserved, original_chars, retained_chars)


__all__ = ["ContextPruneReport", "prune_stale_tool_results"]
