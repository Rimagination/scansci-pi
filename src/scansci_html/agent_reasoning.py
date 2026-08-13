"""First-class reasoning controls shared by the composer and Agent runtime.

The user-facing thinking level is deliberately separate from the system prompt.
It alters the Agent's evidence budget for every provider and, when the selected
provider has a documented control, is translated into that provider's native
request fields.
"""

from __future__ import annotations

from typing import Any


THINKING_LEVELS = frozenset({"auto", "low", "medium", "high", "xhigh", "max"})


def managed_glm_thinking_mode(*, thinking_level: object, messages: list[dict[str, str]]) -> str:
    """Choose GLM-4.7's documented per-turn thinking switch for direct chat.

    GLM-4.7 enables thinking by default. That helps research work but makes a
    greeting or one-line follow-up wait for an unnecessary reasoning pass.
    ``auto`` preserves thinking for visibly substantial requests and favours an
    immediate response for lightweight conversation.
    """

    level = normalize_thinking_level(thinking_level)
    if level == "low":
        return "disabled"
    if level in {"medium", "high", "xhigh", "max"}:
        return "enabled"

    prompt = next(
        (
            str(item.get("content", "")).strip()
            for item in reversed(messages)
            if str(item.get("role", "")).strip().lower() == "user"
        ),
        "",
    )
    requires_reasoning = (
        len(prompt) > 180
        or "\n" in prompt
        or any(marker in prompt.lower() for marker in (
            "分析", "研究", "综述", "文献", "比较", "推导", "证明", "方案", "实验", "数据",
            "代码", "debug", "design", "analyze", "research", "compare", "derive", "prove",
        ))
    )
    return "enabled" if requires_reasoning else "disabled"


def normalize_thinking_level(value: object) -> str:
    """Return a safe persisted thinking level, defaulting to adaptive mode."""

    level = str(value or "").strip().lower()
    return level if level in THINKING_LEVELS else "auto"


def evidence_budget_for_thinking(level: object, *, default: int = 8) -> int:
    """Bound the number of evidence items the Agent can explore for a run."""

    normalized = normalize_thinking_level(level)
    return {"low": 5, "medium": 9, "high": 14, "xhigh": 18, "max": 20}.get(
        normalized,
        max(1, min(20, int(default))),
    )


def native_reasoning_options(
    *,
    provider_id: object,
    provider_kind: object,
    thinking_level: object,
) -> dict[str, Any]:
    """Return documented native options for direct providers only.

    OpenAI-compatible gateways are intentionally not treated as OpenAI.  Sending
    provider-specific fields to an arbitrary compatibility endpoint makes a
    successful-looking control unreliable, so unrecognised providers retain the
    Agent evidence-budget behaviour without pretending to expose a native dial.
    """

    level = normalize_thinking_level(thinking_level)
    provider = str(provider_id or "").strip().lower()
    kind = str(provider_kind or "").strip().lower()
    if level == "auto":
        return {}
    if provider == "openai" and kind in {"openai", "openai-compatible"}:
        # LangChain's ChatOpenAI forwards this as Responses API
        # ``reasoning: {effort: ...}``, not as a prompt instruction.
        return {"reasoning": {"effort": level}, "use_responses_api": True}
    if provider == "anthropic" and kind in {"anthropic", "anthropic-compatible"}:
        # Claude's current adaptive thinking API uses a request-level thinking
        # mode plus output_config.effort; the display is omitted for this UI.
        return {
            "thinking": {"type": "adaptive", "display": "omitted"},
            "output_config": {"effort": level},
        }
    return {}
