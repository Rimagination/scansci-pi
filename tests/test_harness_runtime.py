from __future__ import annotations

import json

from scansci_html.harness_adapters import (
    OptionalHarnessUnavailable,
    build_openai_agents_agent,
    build_pydanticai_agent,
    probe_optional_harnesses,
)
from scansci_html.run_manifest import RunManifest, load_manifest


def test_run_manifest_is_durable_and_redacted(tmp_path):
    manifest = RunManifest.start(
        tmp_path / "workspace.sqlite",
        harness="pi",
        provider="gateway",
        model="model",
        api_surface="chat_completions",
        session_id="session-1",
        prompt="do not persist this prompt",
        tool_set=["search_local_evidence"],
        timeout_seconds=12,
    )
    manifest.record("model.request.started", api_key="secret-value", input_chars=120)
    manifest.finish(status="completed", total_tokens=3)

    payload = load_manifest(manifest.path)
    raw = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "completed"
    assert payload["api_surface"] == "chat_completions"
    assert payload["prompt_version"]
    assert "secret-value" not in raw
    assert "api_key" not in raw
    assert payload["metrics"]["total_tokens"] == 3


def test_optional_harness_probe_is_lazy_and_serializable():
    probes = probe_optional_harnesses()
    assert {item.name for item in probes} == {"pydanticai", "openai-agents", "langgraph"}
    assert all(item.api_surfaces for item in probes)
    assert all(isinstance(item.to_dict(), dict) for item in probes)


def test_optional_adapters_fail_closed_when_not_installed():
    installed = {item.name: item.installed for item in probe_optional_harnesses()}
    if not installed["pydanticai"]:
        try:
            build_pydanticai_agent(name="probe", instructions="probe", model="gpt")
        except OptionalHarnessUnavailable:
            pass
        else:  # pragma: no cover - protects the optional dependency contract
            raise AssertionError("PydanticAI adapter unexpectedly ran without its optional dependency")
    if not installed["openai-agents"]:
        try:
            build_openai_agents_agent(name="probe", instructions="probe", model="gpt")
        except OptionalHarnessUnavailable:
            pass
        else:  # pragma: no cover - protects the optional dependency contract
            raise AssertionError("OpenAI Agents adapter unexpectedly ran without its optional dependency")
