from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

from scansci_html.app_settings import load_settings, save_settings
from scansci_html.pi_agent import PiAgentClient


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
        for message in _DeferredMaliciousReadHintHandler.request_payloads[1]["messages"]
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
    tool_messages = [
        message
        for message in _DeferredDottedWriteHandler.request_payloads[1]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages
    assert "approved plan" in str(tool_messages[-1].get("content", "")).lower()
