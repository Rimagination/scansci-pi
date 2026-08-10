"""Bounded context cleanup shared by direct chat and Agent bridges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import copy
import hashlib
import json
import math
from typing import Any

from .image_attachments import estimate_pi_image_tokens
from .model_metadata import ModelRuntimeDescriptor


_IMAGE_TOKEN_ESTIMATE = 1_200
_OMISSION_MARKER_MIN_TOKENS = 48


class ContextEnvelopeError(ValueError):
    """Raised when mandatory current-turn context cannot fit the model."""


@dataclass(frozen=True)
class TokenEnvelopeReport:
    policy: str
    context_window_tokens: int
    provider_input_tokens: int
    estimated_tokens_before: int
    estimated_tokens: int
    mandatory_tokens: int
    host_contract_tokens: int
    retained_messages: int
    omitted_messages: int
    truncated_messages: int
    omission_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "context_window_tokens": self.context_window_tokens,
            "provider_input_tokens": self.provider_input_tokens,
            "estimated_tokens_before": self.estimated_tokens_before,
            "estimated_tokens": self.estimated_tokens,
            "mandatory_tokens": self.mandatory_tokens,
            "host_contract_tokens": self.host_contract_tokens,
            "retained_messages": self.retained_messages,
            "omitted_messages": self.omitted_messages,
            "truncated_messages": self.truncated_messages,
            "omission_hashes": list(self.omission_hashes),
        }


def estimate_text_tokens(value: Any) -> int:
    """Return a conservative tokenizer-independent estimate.

    UTF-8 bytes/3 intentionally overestimates ordinary English while mapping
    CJK to roughly one token per character and emoji to more than one.  The
    safety envelope is not billing data and must remain provider-neutral.
    """

    text = str(value or "")
    return math.ceil(len(text.encode("utf-8")) / 3) if text else 0


def _estimate_content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return estimate_text_tokens(content)
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        total = 0
        for block in content:
            if not isinstance(block, Mapping):
                total += estimate_text_tokens(block)
                continue
            block_type = str(block.get("type", ""))
            if block_type in {"image", "input_image", "image_url"}:
                if block_type == "image":
                    try:
                        total += estimate_pi_image_tokens([dict(block)])
                    except ValueError:
                        total += _IMAGE_TOKEN_ESTIMATE
                else:
                    total += _IMAGE_TOKEN_ESTIMATE
            elif block_type == "text":
                total += estimate_text_tokens(block.get("text", ""))
            else:
                safe = {
                    key: ("[IMAGE_BYTES]" if key in {"data", "image_url", "url"} else value)
                    for key, value in block.items()
                }
                total += estimate_text_tokens(json.dumps(safe, ensure_ascii=False, default=str))
        return total
    if isinstance(content, Mapping):
        safe = {
            key: ("[IMAGE_BYTES]" if key in {"data", "image_url", "url"} else value)
            for key, value in content.items()
        }
        return estimate_text_tokens(json.dumps(safe, ensure_ascii=False, default=str))
    return estimate_text_tokens(content)


def estimate_message_tokens(message: Mapping[str, Any]) -> int:
    # Role/framing overhead is intentionally explicit so a large message count
    # cannot evade the byte-based content estimate.
    return 6 + estimate_text_tokens(message.get("role", "")) + _estimate_content_tokens(message.get("content", ""))


def _context_kind(message: Mapping[str, Any]) -> str:
    declared = str(message.get("context_kind", "")).strip().lower()
    if declared:
        return declared
    content = str(message.get("content", ""))
    role = str(message.get("role", "")).lower()
    if "HOST-OWNED TASK CONTRACT" in content:
        return "host_contract"
    if "<selected_skill" in content or "LOADED SKILL INSTRUCTIONS" in content:
        return "explicit_skill"
    if content.startswith("Earlier task conversation (deterministic recap):"):
        return "recap"
    if role in {"tool", "toolresult", "tool_result"}:
        return "referenced_tool_result" if message.get("context_ref") or message.get("tool_call_id") else "tool_result"
    if "attachment" in declared:
        return "attachment"
    return "dialogue"


def _message_reference(message: Mapping[str, Any]) -> str:
    for key in ("context_ref", "tool_call_id", "id", "message_id"):
        value = str(message.get(key, "")).strip()
        if value:
            return value[:160]
    return ""


def _truncate_referenced_message(
    message: Mapping[str, Any],
    *,
    budget_tokens: int,
) -> tuple[dict[str, Any] | None, str]:
    content = message.get("content", "")
    reference = _message_reference(message)
    if not reference or not isinstance(content, str) or budget_tokens < _OMISSION_MARKER_MIN_TOKENS:
        return None, ""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    marker = f"\n… [omitted; ref={reference}; omission_sha256={digest}] …\n"
    marker_tokens = estimate_text_tokens(marker) + 8
    if marker_tokens >= budget_tokens:
        return None, ""
    char_budget = max(0, (budget_tokens - marker_tokens) * 3)
    head_chars = max(1, char_budget // 2)
    tail_chars = max(1, char_budget - head_chars)
    projected = dict(message)
    projected["content"] = f"{content[:head_chars]}{marker}{content[-tail_chars:]}"
    projected["_scansci_context_omission"] = {
        "ref": reference,
        "omission_sha256": digest,
        "original_tokens": estimate_text_tokens(content),
    }
    while estimate_message_tokens(projected) > budget_tokens and head_chars + tail_chars > 2:
        if head_chars >= tail_chars:
            head_chars -= 1
        else:
            tail_chars -= 1
        projected["content"] = f"{content[:head_chars]}{marker}{content[-tail_chars:]}"
    if estimate_message_tokens(projected) > budget_tokens:
        return None, ""
    return projected, digest


def build_token_envelope(
    messages: Sequence[Mapping[str, Any]],
    *,
    descriptor: ModelRuntimeDescriptor,
    host_contract: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], TokenEnvelopeReport]:
    """Project conversation context into a model-aware, auditable envelope.

    Mandatory host/current-turn material is never clipped.  Optional content
    is admitted by semantic priority and recency; only entries carrying a
    stable reference may receive a head+tail omission preview.
    """

    clean = [copy.deepcopy(dict(message)) for message in messages if isinstance(message, Mapping)]
    final_user_index = next(
        (index for index in range(len(clean) - 1, -1, -1) if str(clean[index].get("role", "")).lower() == "user"),
        -1,
    )
    if final_user_index < 0:
        raise ContextEnvelopeError("A final user message is mandatory")
    host_contract_tokens = estimate_text_tokens(json.dumps(dict(host_contract or {}), ensure_ascii=False, default=str))
    before = host_contract_tokens + sum(estimate_message_tokens(message) for message in clean)
    mandatory_indices = {
        index
        for index, message in enumerate(clean)
        if index == final_user_index or _context_kind(message) in {"host_contract", "explicit_skill"}
    }
    mandatory_tokens = host_contract_tokens + sum(estimate_message_tokens(clean[index]) for index in mandatory_indices)
    limit = int(descriptor.provider_input_tokens)
    if mandatory_tokens > limit:
        raise ContextEnvelopeError(
            f"Model context mandatory input requires {mandatory_tokens} tokens but limit is {limit}"
        )

    retained: dict[int, dict[str, Any]] = {index: clean[index] for index in mandatory_indices}
    used = mandatory_tokens
    priority = {
        "dialogue": 4,
        "attachment": 3,
        "recap": 2,
        "referenced_tool_result": 1,
        "tool_result": 0,
        "host_contract": 6,
        "explicit_skill": 5,
    }
    optional_indices = [index for index in range(len(clean)) if index not in mandatory_indices]
    # Admit dialogue as complete user turns. This avoids retaining an answer
    # while silently dropping the question it answered (or vice versa) at the
    # model boundary. Referenced content may still receive a bounded preview
    # when the whole unit cannot fit.
    optional_units: list[tuple[int, int, list[int]]] = []
    dialogue_turn = 0
    dialogue_units: dict[int, list[int]] = {}
    for index in optional_indices:
        message = clean[index]
        kind = _context_kind(message)
        if kind == "dialogue":
            if str(message.get("role", "")).lower() == "user":
                dialogue_turn += 1
            dialogue_units.setdefault(dialogue_turn, []).append(index)
        else:
            optional_units.append((priority.get(kind, 0), index, [index]))
    optional_units.extend(
        (priority["dialogue"], max(indices), indices)
        for indices in dialogue_units.values()
        if indices
    )
    optional_units.sort(key=lambda unit: (unit[0], unit[1]), reverse=True)
    truncated = 0
    omission_hashes: list[str] = []
    for _semantic_priority, _recency, indices in optional_units:
        tokens = sum(estimate_message_tokens(clean[index]) for index in indices)
        remaining = limit - used
        if tokens <= remaining:
            for index in indices:
                retained[index] = clean[index]
            used += tokens
            continue
        # Dialogue admission is all-or-nothing at the user-turn boundary.
        # A reference on one message must not turn that message into a partial
        # orphan while its question or answer partner is omitted.
        if any(_context_kind(clean[index]) == "dialogue" for index in indices):
            continue
        for index in indices:
            remaining = limit - used
            if remaining < _OMISSION_MARKER_MIN_TOKENS:
                break
            projected, digest = _truncate_referenced_message(
                clean[index],
                budget_tokens=remaining,
            )
            if projected is not None:
                retained[index] = projected
                projected_tokens = estimate_message_tokens(projected)
                used += projected_tokens
                truncated += 1
                omission_hashes.append(digest)

    output = [retained[index] for index in sorted(retained)]
    estimated = host_contract_tokens + sum(estimate_message_tokens(message) for message in output)
    if estimated > limit:  # defensive invariant; never silently overrun.
        raise ContextEnvelopeError("Token envelope exceeded the provider input limit")
    report = TokenEnvelopeReport(
        policy="model_aware_token_envelope_v1",
        context_window_tokens=descriptor.context_window_tokens,
        provider_input_tokens=limit,
        estimated_tokens_before=before,
        estimated_tokens=estimated,
        mandatory_tokens=mandatory_tokens,
        host_contract_tokens=host_contract_tokens,
        retained_messages=len(output),
        omitted_messages=max(0, len(clean) - len(output)),
        truncated_messages=truncated,
        omission_hashes=tuple(omission_hashes),
    )
    return output, report


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


def context_view_with_stale_tool_pruning(
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


def prune_stale_tool_results(
    messages: Sequence[Mapping[str, Any]],
    *,
    keep_recent_turns: int = 2,
) -> tuple[list[dict[str, Any]], ContextPruneReport]:
    """Compatibility wrapper for the non-destructive provider context view."""

    return context_view_with_stale_tool_pruning(messages, keep_recent_turns=keep_recent_turns)


__all__ = [
    "ContextEnvelopeError",
    "ContextPruneReport",
    "TokenEnvelopeReport",
    "build_token_envelope",
    "context_view_with_stale_tool_pruning",
    "estimate_message_tokens",
    "estimate_text_tokens",
    "prune_stale_tool_results",
]
