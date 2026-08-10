from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.evidence_store import index_evidence_library
from scansci_html.pi_agent import PiAgentClient
from scansci_html.research_agent import ResearchAgentRuntime


_TASK_CONTRACT_V2 = {"schema_version": "scansci.task-contract.v2", "version": 2}


def _probe(
    tmp_path: Path,
    *,
    allow_write: bool,
    deferred: bool = False,
    server_id: str = "fixture",
    fixture_name: str = "fake_mcp_server.mjs",
    tool_effects: dict[str, str] | None = None,
    tool_policies: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    node, sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / fixture_name
    if not deferred:
        return PiAgentClient.probe_mcp_server(
            workspace=tmp_path,
            server={
                "id": server_id,
                "name": "Fixture MCP",
                "enabled": True,
                "transport": "stdio",
                "command": str(node),
                "args_list": [str(fixture)],
                "allow_write": allow_write,
                "tool_effects": dict(tool_effects or {}),
                "tool_policies": list(tool_policies or []),
            },
        )
    environment = dict(os.environ)
    for variable in ("PYTHONPATH", "PYTHONUTF8"):
        environment.pop(variable, None)
    process = subprocess.Popen(
        [str(node), str(sidecar)],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            json.dumps(
                {
                    "type": "mcp.probe",
                    "request_id": "fixture-probe",
                    "activation_mode": "deferred" if deferred else "direct",
                    "cwd": str(tmp_path),
                    "mcp_servers": [
                        {
                            "id": server_id,
                            "name": "Fixture MCP",
                            "enabled": True,
                            "transport": "stdio",
                            "command": str(node),
                            "args_list": [str(fixture)],
                            "allow_write": allow_write,
                            "tool_effects": dict(tool_effects or {}),
                            "tool_policies": list(tool_policies or []),
                            "deferred": deferred,
                        }
                    ],
                }
            )
            + "\n"
        )
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "Pi sidecar exited"
            message = json.loads(line)
            if message.get("type") == "mcp.probe.completed":
                return message
            assert message.get("type") != "mcp.probe.failed", message
    finally:
        process.kill()
        process.wait(timeout=5)


def test_pi_mcp_bridge_discovers_read_tools_and_hides_write_tools_by_default(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=False, tool_effects={"search_library": "read"})

    assert result["server_count"] == 1
    assert result["tool_count"] == 1
    assert [tool["name"] for tool in result["tools"]] == ["mcp__fixture__search_library"]


def test_pi_mcp_bridge_exposes_write_tools_after_explicit_authorization(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=True, tool_effects={"search_library": "read"})

    assert result["server_count"] == 1
    assert {tool["name"] for tool in result["tools"]} == {
        "mcp__fixture__search_library",
        "mcp__fixture__create_note",
        "mcp__fixture__notes_put",
    }


def test_pi_mcp_bridge_deferred_mode_exposes_compact_proxy_without_starting_server(tmp_path: Path) -> None:
    result = _probe(tmp_path, allow_write=False, deferred=True)

    assert result["server_count"] == 0
    assert {tool["name"] for tool in result["tools"]} == {
        "mcp__fixture__search",
        "mcp__fixture__call",
    }


def test_pi_mcp_unknown_effect_is_denied_by_default(tmp_path: Path) -> None:
    result = _probe(
        tmp_path,
        allow_write=True,
        fixture_name="fake_mcp_unknown_server.mjs",
    )

    assert result["tool_count"] == 0
    assert result["tools"] == []


def test_pi_mcp_server_annotations_cannot_create_read_authority(tmp_path: Path) -> None:
    result = _probe(
        tmp_path,
        allow_write=False,
        fixture_name="fake_mcp_malicious_annotations_server.mjs",
    )

    assert result["tool_count"] == 0
    assert result["tools"] == []


def test_pi_mcp_host_policy_classifies_reads_while_server_hints_only_raise_risk(tmp_path: Path) -> None:
    result = _probe(
        tmp_path,
        allow_write=False,
        fixture_name="fake_mcp_malicious_annotations_server.mjs",
        tool_policies=[
            {"name": "lookup_records", "effect": "read", "idempotent": True},
            {"name": "lookup_non_idempotent", "effect": "read", "idempotent": True},
            {"name": "lookup_dangerous", "effect": "read", "idempotent": True},
        ],
    )

    tools = {tool["remote_name"]: tool for tool in result["tools"]}
    assert set(tools) == {"lookup_records", "lookup_non_idempotent"}
    assert tools["lookup_records"]["effect"] == "read"
    assert tools["lookup_records"]["idempotent"] is True
    assert tools["lookup_non_idempotent"]["effect"] == "read"
    assert tools["lookup_non_idempotent"]["idempotent"] is False


def test_pi_mcp_keeps_raw_dotted_slashed_server_id_separate_from_local_alias(tmp_path: Path) -> None:
    result = _probe(
        tmp_path,
        allow_write=False,
        server_id="lab.v1/search",
        tool_effects={"search_library": "read"},
    )

    tool = result["tools"][0]
    assert tool["server_id"] == "lab.v1/search"
    assert tool["server_alias"] == "lab_v1_search"
    assert tool["remote_name"] == "search_library"
    assert tool["effect"] == "read"
    assert tool["name"] == "mcp__lab_v1_search__search_library"


class _DeferredDottedWriteHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "search-dotted-write-tool",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["mcp__fixture__call"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 2:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-dotted-write",
                    "type": "function",
                    "function": {
                        "name": "mcp__fixture__call",
                        "arguments": '{"tool":"notes.put","arguments":{}}',
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "The unapproved write was denied."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OrdinaryMcpDiscoveryHandler(_DeferredDottedWriteHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "discover-ordinary-mcp",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["mcp__reader__search"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "The ordinary turn discovered its read-only MCP."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-ordinary-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-ordinary-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _LocalOnlyMcpAttemptHandler(_DeferredDottedWriteHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "try-local-only-mcp",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["mcp__reader__search"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 2:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "activate-local-evidence",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["search_local_evidence"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 3:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "read-local-evidence",
                    "type": "function",
                    "function": {
                        "name": "search_local_evidence",
                        "arguments": '{"query":"local concept","result_limit":3}',
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "The explanation used only local evidence."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-local-only-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-local-only-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _DeferredReadFilterHandler(_DeferredDottedWriteHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "activate-deferred-search",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["mcp__fixture__search"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 2:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "search-deferred-catalog",
                    "type": "function",
                    "function": {"name": "mcp__fixture__search", "arguments": "{}"},
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "Only read-authorized remote tools were visible."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-filter-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-filter-mcp-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def test_ordinary_non_social_turn_discovers_enabled_read_only_mcp_without_regex_intent(
    tmp_path: Path,
) -> None:
    node, _sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.mjs"
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["mcp_servers"] = [
        {
            "id": "reader",
            "name": "Reader MCP",
            "enabled": True,
            "transport": "stdio",
            "command": str(node),
            "args": f'"{fixture}"',
            "allow_write": False,
            "tool_effects": {"search_library": "read"},
            "deferred": True,
        },
        {
            "id": "writer",
            "name": "Writer MCP",
            "enabled": True,
            "transport": "stdio",
            "command": str(node),
            "args": f'"{fixture}"',
            "allow_write": True,
            "deferred": True,
        },
        {
            "id": "disabled-reader",
            "name": "Disabled reader",
            "enabled": False,
            "transport": "stdio",
            "command": str(node),
            "args": f'"{fixture}"',
            "allow_write": False,
            "deferred": True,
        },
    ]
    save_settings(workspace, settings)
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")
    contract = runtime._compile_contract(
        task_mode="general",
        user_text="Help me think through this research idea.",
    )

    assert contract["allowed_mcp_servers"] == ["reader"]

    _OrdinaryMcpDiscoveryHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OrdinaryMcpDiscoveryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Help me think through this research idea."}],
            thinking_level="off",
            task_mode="general",
            task_contract=contract,
            timeout_seconds=30,
            session_id="ordinary-read-mcp",
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    loader_messages = [
        message
        for message in _OrdinaryMcpDiscoveryHandler.request_payloads[1]["messages"]
        if message.get("role") == "tool"
    ]
    loader = json.loads(str(loader_messages[-1]["content"]))
    assert loader["activated"] == ["mcp__reader__search"]
    assert "mcp__reader__search" in events[-1]["stats"]["toolInventory"]["names"]


@pytest.mark.parametrize(
    ("entrypoint", "user_text"),
    [
        (
            "chat",
            "Use only local documents. Do not use the web or internet. Explain this concept.",
        ),
        (
            "chat_stream",
            "仅使用本地文档，不要联网或使用互联网。请解释这个概念。",
        ),
    ],
)
def test_local_only_language_blocks_mcp_discovery_in_real_chat_entrypoints(
    tmp_path: Path,
    entrypoint: str,
    user_text: str,
) -> None:
    node, _sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.mjs"
    workspace = tmp_path / "workspace.sqlite"

    _LocalOnlyMcpAttemptHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalOnlyMcpAttemptHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = load_settings(workspace)
    settings["active_model"] = {"provider_id": "fixture-provider", "model_id": "fixture-model"}
    settings["providers"] = [{
        "id": "fixture-provider",
        "name": "Fixture provider",
        "kind": "openai-compatible",
        "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        "auth_mode": "local",
        "enabled": True,
        "models": [{"id": "fixture-model", "name": "Fixture model"}],
    }]
    settings["mcp_servers"] = [{
        "id": "reader",
        "name": "Reader MCP",
        "enabled": True,
        "transport": "stdio",
        "command": str(node),
        "args": f'"{fixture}"',
        "allow_write": False,
        "tool_effects": {"search_library": "read"},
        "deferred": True,
    }]
    save_settings(workspace, settings)
    library = tmp_path / "local-library"
    library.mkdir()
    (library / "concept.html").write_text(
        "<article><h1>Local concept</h1><h2>Results</h2>"
        "<p>Local documents contain a verified explanation of this concept.</p></article>",
        encoding="utf-8",
    )
    evidence_db = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=evidence_db, min_sentence_length=10)
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=evidence_db)
    payload = {
        "chat_mode": "general",
        "messages": [{"role": "user", "content": user_text}],
    }
    try:
        if entrypoint == "chat":
            result = runtime.chat(payload)
        else:
            events = list(runtime.chat_stream(payload))
            assert events[-1]["type"] == "RUN_FINISHED"
            result = dict(events[-1]["result"])
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    contract = dict(result["agent_runtime"]["task_contract"])
    assert contract["allowed_mcp_servers"] == []
    assert len(_LocalOnlyMcpAttemptHandler.request_payloads) == 4
    for provider_request in _LocalOnlyMcpAttemptHandler.request_payloads:
        provider_tools = {
            str(dict(item.get("function", {}) or {}).get("name", ""))
            for item in list(provider_request.get("tools", []) or [])
            if isinstance(item, dict)
        }
        assert not any(name.startswith("mcp__reader__") for name in provider_tools)
    loader_messages = [
        message
        for message in _LocalOnlyMcpAttemptHandler.request_payloads[1]["messages"]
        if message.get("role") == "tool"
    ]
    loader = json.loads(str(loader_messages[-1]["content"]))
    assert loader["activated"] == []
    assert loader["matches"] == []
    assert loader["rejected"] == [{
        "name": "mcp__reader__search",
        "reason": "not_authorized_or_unavailable",
    }]


@pytest.mark.parametrize("mcp_scope", ["local-only", "selected-library"])
def test_explicit_local_scopes_do_not_lease_unrelated_mcp_servers(
    tmp_path: Path,
    mcp_scope: str,
) -> None:
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["mcp_servers"] = [{
        "id": "reader",
        "name": "Reader MCP",
        "enabled": True,
        "allow_write": False,
        "deferred": True,
    }]
    save_settings(workspace, settings)
    runtime = ResearchAgentRuntime(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    contract = runtime._compile_contract(
        task_mode="knowledge",
        user_text="Summarize only the selected local library.",
        mcp_scope=mcp_scope,
    )

    assert contract["allowed_mcp_servers"] == []


def test_deferred_remote_search_filters_write_and_unknown_tools_by_current_read_only_contract(
    tmp_path: Path,
) -> None:
    node, _sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.mjs"
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["mcp_servers"] = [{
        "id": "fixture",
        "name": "Fixture MCP",
        "enabled": True,
        "transport": "stdio",
        "command": str(node),
        "args": f'"{fixture}"',
        "allow_write": True,
        "tool_effects": {"search_library": "read"},
        "deferred": True,
    }]
    save_settings(workspace, settings)
    _DeferredReadFilterHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeferredReadFilterHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Discover only read-authorized remote tools."}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "allowed_tools": [],
                "initial_tools": [],
                "allowed_mcp_servers": ["fixture"],
                "risk_level": "read_only",
                "allow_external_write": False,
                "initial_tool_budget": 3,
                "max_tool_budget": 5,
            },
            timeout_seconds=30,
            session_id="deferred-read-filter",
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert events[-1]["type"] == "done"
    tool_messages = [
        message
        for message in _DeferredReadFilterHandler.request_payloads[2]["messages"]
        if message.get("role") == "tool"
    ]
    remote_catalog = json.loads(str(tool_messages[-1]["content"]))
    assert {tool["remote_name"] for tool in remote_catalog["tools"]} == {"search_library"}


class _DeferredMaliciousReadHintHandler(_DeferredDottedWriteHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "search-malicious-read-hint",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": '{"names":["mcp__fixture__call"],"activate":true}',
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 2:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-malicious-read-hint",
                    "type": "function",
                    "function": {
                        "name": "mcp__fixture__call",
                        "arguments": '{"tool":"create_record","arguments":{}}',
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "The spoofed read annotation was denied."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-malicious-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-malicious-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def test_pi_mcp_deferred_call_rejects_spoofed_read_annotation(tmp_path: Path) -> None:
    node, _sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_malicious_annotations_server.mjs"
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["mcp_servers"] = [{
        "id": "fixture",
        "name": "Fixture MCP",
        "enabled": True,
        "transport": "stdio",
        "command": str(node),
        "args": f'"{fixture}"',
        "allow_write": False,
        "deferred": True,
    }]
    save_settings(workspace, settings)
    _DeferredMaliciousReadHintHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeferredMaliciousReadHintHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Do not let a server spoof write authority."}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "allowed_tools": [],
                "allowed_mcp_servers": ["fixture"],
                "risk_level": "read_only",
                "initial_tool_budget": 2,
                "max_tool_budget": 4,
            },
            timeout_seconds=30,
            session_id="deferred-malicious-read-hint",
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert events[-1]["type"] == "done"
    assert not any(event.get("status") == "mcp_called" for event in events)
    tool_messages = [
        message
        for message in _DeferredMaliciousReadHintHandler.request_payloads[2]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages
    assert "unavailable or not authorized" in str(tool_messages[-1].get("content", "")).lower()


def test_pi_mcp_deferred_dotted_write_requires_explicit_plan_approval(tmp_path: Path) -> None:
    node, _sidecar = PiAgentClient.runtime_paths()
    fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.mjs"
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    settings["mcp_servers"] = [{
        "id": "fixture",
        "name": "Fixture MCP",
        "enabled": True,
        "transport": "stdio",
        "command": str(node),
        "args": f'"{fixture}"',
        "allow_write": True,
        "deferred": True,
    }]
    save_settings(workspace, settings)
    _DeferredDottedWriteHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeferredDottedWriteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Write only after approval."}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "allowed_tools": [],
                "allowed_mcp_servers": ["fixture"],
                "risk_level": "high",
                "allow_external_write": True,
                "requires_plan": True,
                "initial_tool_budget": 2,
                "max_tool_budget": 4,
            },
            timeout_seconds=30,
            session_id="deferred-dotted-write",
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert events[-1]["type"] == "done"
    assert not any(event.get("status") == "mcp_called" for event in events)
    search_messages = [
        message
        for message in _DeferredDottedWriteHandler.request_payloads[1]["messages"]
        if message.get("role") == "tool"
    ]
    catalog_result = json.loads(str(search_messages[-1].get("content", "{}")))
    assert catalog_result["matches"][0]["executionMode"] == "sequential"
    tool_messages = [
        message
        for message in _DeferredDottedWriteHandler.request_payloads[2]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages
    assert "approved plan" in str(tool_messages[-1].get("content", "")).lower()
