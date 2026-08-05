"""Optional harness adapters and capability probes.

The production path is Pi.  These probes make alternative harnesses explicit
and testable without importing optional packages during normal startup.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Any

from .model_transport import CHAT_COMPLETIONS, RESPONSES, select_api_surface


class OptionalHarnessUnavailable(RuntimeError):
    """Raised when an optional harness was requested but is not installed."""


@dataclass(frozen=True)
class HarnessProbe:
    name: str
    import_name: str
    installed: bool
    api_surfaces: tuple[str, ...]
    role: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "import_name": self.import_name,
            "installed": self.installed,
            "api_surfaces": list(self.api_surfaces),
            "role": self.role,
            "notes": self.notes,
        }


def probe_optional_harnesses() -> list[HarnessProbe]:
    return [
        HarnessProbe(
            name="pydanticai",
            import_name="pydantic_ai",
            installed=importlib.util.find_spec("pydantic_ai") is not None,
            api_surfaces=(RESPONSES, CHAT_COMPLETIONS),
            role="structured_python_tasks",
            notes="Use for typed structured output and evidence validation; keep Pi as the main loop.",
        ),
        HarnessProbe(
            name="openai-agents",
            import_name="agents",
            installed=importlib.util.find_spec("agents") is not None,
            api_surfaces=(RESPONSES, CHAT_COMPLETIONS),
            role="openai_first_tasks",
            notes="Use for a narrow OpenAI-first comparison of tools, handoffs, guardrails, and tracing.",
        ),
        HarnessProbe(
            name="langgraph",
            import_name="langgraph",
            installed=importlib.util.find_spec("langgraph") is not None,
            api_surfaces=(RESPONSES, CHAT_COMPLETIONS),
            role="durable_workflow_only",
            notes="Adopt only for durable multi-stage workflows that need pause/resume checkpoints.",
        ),
    ]


def require_optional_harness(name: str) -> HarnessProbe:
    normalized = str(name or "").strip().lower()
    probe = next((item for item in probe_optional_harnesses() if item.name == normalized), None)
    if probe is None:
        raise OptionalHarnessUnavailable(f"Unknown optional harness: {name}")
    if not probe.installed:
        raise OptionalHarnessUnavailable(
            f"Optional harness {name} is not installed; install the project harness extra before enabling it."
        )
    return probe


def build_pydanticai_agent(
    *,
    name: str,
    instructions: str,
    model: str,
    api_surface: str = RESPONSES,
    base_url: str = "",
    api_key: str = "",
    output_type: Any | None = None,
) -> Any:
    """Build a PydanticAI Agent lazily with an explicit OpenAI API surface."""

    require_optional_harness("pydanticai")
    surface = select_api_surface(
        api_surface,
        provider_kind="openai-compatible",
        provider_id="openai" if not base_url or "api.openai.com" in base_url else "gateway",
        model=model,
        responses_enabled=True,
    )
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as error:  # pragma: no cover - exercised only with optional extra installed
        raise OptionalHarnessUnavailable("PydanticAI is installed but its OpenAI model modules are unavailable") from error

    provider_kwargs: dict[str, Any] = {}
    if base_url:
        provider_kwargs["base_url"] = base_url
    if api_key:
        provider_kwargs["api_key"] = api_key
    provider = OpenAIProvider(**provider_kwargs)
    model_type = OpenAIResponsesModel if surface == RESPONSES else OpenAIChatModel
    try:
        model_instance = model_type(model_name=model, provider=provider)
    except TypeError:
        # Keep the adapter tolerant of the short-lived positional constructor
        # used by older PydanticAI releases.
        model_instance = model_type(model, provider=provider)
    kwargs: dict[str, Any] = {"name": name, "instructions": instructions, "model": model_instance}
    if output_type is not None:
        kwargs["output_type"] = output_type
    return Agent(**kwargs)


def build_openai_agents_agent(
    *,
    name: str,
    instructions: str,
    model: str,
    api_surface: str = RESPONSES,
    base_url: str = "",
    api_key: str = "",
    tools: list[Any] | None = None,
) -> Any:
    """Build a narrow OpenAI Agents SDK Agent without enabling a new loop."""

    require_optional_harness("openai-agents")
    normalized_base_url = str(base_url or "").rstrip("/")
    if normalized_base_url and "api.openai.com/v1" not in normalized_base_url:
        raise OptionalHarnessUnavailable(
            "The OpenAI Agents SDK adapter only accepts the official OpenAI endpoint; "
            "use ScanSci ModelTransport for custom gateways."
        )
    try:
        from agents import Agent
        from agents import set_default_openai_api
        set_default_openai_api("responses" if api_surface == RESPONSES else "chat_completions")
        set_key = getattr(__import__("agents"), "set_default_openai_key", None)
        if callable(set_key) and api_key:
            set_key(api_key)
    except ImportError as error:  # pragma: no cover - exercised only with optional extra installed
        raise OptionalHarnessUnavailable("OpenAI Agents SDK is installed but its public Agent API is unavailable") from error
    kwargs: dict[str, Any] = {"name": name, "instructions": instructions, "model": model}
    if tools:
        kwargs["tools"] = list(tools)
    return Agent(**kwargs)


__all__ = [
    "HarnessProbe",
    "OptionalHarnessUnavailable",
    "build_openai_agents_agent",
    "build_pydanticai_agent",
    "probe_optional_harnesses",
    "require_optional_harness",
]
