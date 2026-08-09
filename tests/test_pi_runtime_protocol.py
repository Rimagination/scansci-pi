from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from scansci_html.pi_agent import PiAgentClient


_TASK_CONTRACT_V2 = {"schema_version": "scansci.task-contract.v2", "version": 2}


def _tool_names(payload: dict[str, object]) -> set[str]:
    return {
        str(dict(item.get("function", {}) or {}).get("name", ""))
        for item in list(payload.get("tools", []) or [])
        if isinstance(item, dict)
    }


class _DynamicToolHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-search-tools",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": json.dumps({
                            "query": "workspace status",
                            "names": ["inspect_workspace"],
                            "activate": True,
                        }),
                    },
                }],
            }
            finish = "tool_calls"
        elif turn == 2:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-inspect-workspace",
                    "type": "function",
                    "function": {"name": "inspect_workspace", "arguments": "{}"},
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "Dynamic activation completed."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-dynamic-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-dynamic-{turn}",
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


class _InventoryCaptureHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        chunk = {
            "id": "chatcmpl-inventory",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fixture-model",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}],
        }
        stop = {
            **chunk,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        body = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(stop)}\n\ndata: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _PersistentActivationHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-persistent-search",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": json.dumps({"names": ["inspect_workspace"], "activate": True}),
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": f"turn-{turn}-complete"}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-persistent-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-persistent-{turn}",
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


class _EmptyLeaseSearchHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        turn = len(type(self).request_payloads)
        if turn == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-empty-search",
                    "type": "function",
                    "function": {
                        "name": "search_tools",
                        "arguments": json.dumps({"names": ["inspect_workspace"], "activate": True}),
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "Empty inventory confirmed."}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-empty-search-{turn}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-empty-search-{turn}",
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


def _serve(handler: type[BaseHTTPRequestHandler]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_sidecar_starts_bootstrap_only_then_additively_activates_an_authorized_tool(tmp_path: Path) -> None:
    _DynamicToolHandler.request_payloads = []
    server, thread = _serve(_DynamicToolHandler)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture-key",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Inspect the workspace after discovering the right tool."}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "contract_id": "dynamic-loader",
                "autonomy": "read_only",
                "risk_level": "read_only",
                "allowed_tools": ["inspect_workspace", "search_web"],
                "initial_tools": [],
                "required_tool_groups": [],
                "initial_tool_budget": 3,
                "max_tool_budget": 6,
            },
            session_id="dynamic-loader-session",
            timeout_seconds=30,
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert len(_DynamicToolHandler.request_payloads) == 3
    first, second, third = map(_tool_names, _DynamicToolHandler.request_payloads)
    assert first == {"ask_user", "search_tools", "submit_plan"}
    assert second == first | {"inspect_workspace"}
    assert third == second
    assert "search_web" not in third
    assert any(item.get("type") == "tool.completed" and item.get("name") == "inspect_workspace" for item in events)
    assert events[-1]["type"] == "done"
    inventory = events[-1]["stats"]["toolInventory"]
    assert inventory["registered"] == 5
    assert inventory["active"] == 4
    assert inventory["registeredNames"] == [
        "ask_user",
        "inspect_workspace",
        "search_tools",
        "search_web",
        "submit_plan",
    ]
    assert events[-1]["stats"]["prefixShape"]["components"]["registered_tool_count"] == 5
    assert events[-1]["stats"]["prefixShape"]["components"]["active_tool_count"] == 4


def test_explicit_empty_lease_keeps_loader_but_returns_an_empty_domain_inventory(tmp_path: Path) -> None:
    _InventoryCaptureHandler.request_payloads = []
    server, thread = _serve(_InventoryCaptureHandler)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture-key",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Hello"}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "contract_id": "explicit-empty",
                "risk_level": "none",
                "allowed_tools": [],
                "initial_tools": [],
                "initial_tool_budget": 2,
                "max_tool_budget": 4,
            },
            session_id="explicit-empty-session",
            timeout_seconds=30,
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert _tool_names(_InventoryCaptureHandler.request_payloads[0]) == {
        "ask_user",
        "search_tools",
        "submit_plan",
    }
    assert events[-1]["stats"]["toolInventory"]["registered"] == 3


def test_reused_logical_session_revokes_previous_domain_inventory_on_the_next_turn(tmp_path: Path) -> None:
    _InventoryCaptureHandler.request_payloads = []
    server, thread = _serve(_InventoryCaptureHandler)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    common = dict(
        provider_kind="openai-compatible",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="fixture-key",
        model_id="fixture-model",
        thinking_level="off",
        task_mode="general",
        session_id="revocation-session",
        timeout_seconds=30,
    )
    try:
        first = list(client.stream_chat(
            messages=[{"role": "user", "content": "First"}],
            task_contract={
                **_TASK_CONTRACT_V2,
                "contract_id": "grant",
                "risk_level": "read_only",
                "allowed_tools": ["inspect_workspace"],
                "initial_tools": ["inspect_workspace"],
            },
            **common,
        ))
        second = list(client.stream_chat(
            messages=[{"role": "user", "content": "Second"}],
            task_contract={
                **_TASK_CONTRACT_V2,
                "contract_id": "revoke",
                "risk_level": "none",
                "allowed_tools": [],
                "initial_tools": [],
            },
            **common,
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "inspect_workspace" in _tool_names(_InventoryCaptureHandler.request_payloads[0])
    assert "inspect_workspace" not in _tool_names(_InventoryCaptureHandler.request_payloads[1])
    assert first[-1]["type"] == "done"
    assert second[-1]["type"] == "done"


def test_additive_activation_survives_the_next_turn_in_the_same_session(tmp_path: Path) -> None:
    _PersistentActivationHandler.request_payloads = []
    server, thread = _serve(_PersistentActivationHandler)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    common = dict(
        provider_kind="openai-compatible",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="fixture-key",
        model_id="fixture-model",
        thinking_level="off",
        task_mode="general",
        session_id="persistent-activation-session",
        timeout_seconds=30,
    )
    contract = {
        **_TASK_CONTRACT_V2,
        "risk_level": "read_only",
        "allowed_tools": ["inspect_workspace", "search_web"],
        "initial_tools": [],
        "initial_tool_budget": 3,
        "max_tool_budget": 6,
    }
    try:
        first = list(client.stream_chat(
            messages=[{"role": "user", "content": "Discover the workspace tool."}],
            task_contract={**contract, "contract_id": "continuity-first", "goal": "first"},
            **common,
        ))
        second = list(client.stream_chat(
            messages=[{"role": "user", "content": "Continue with the same tool inventory."}],
            task_contract={**contract, "contract_id": "continuity-second", "goal": "second"},
            **common,
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert len(_PersistentActivationHandler.request_payloads) == 3
    first_surface, activated_surface, resumed_surface = map(
        _tool_names,
        _PersistentActivationHandler.request_payloads,
    )
    assert first_surface == {"ask_user", "search_tools", "submit_plan"}
    assert activated_surface == first_surface | {"inspect_workspace"}
    assert resumed_surface == activated_surface
    assert "search_web" not in resumed_surface
    assert next(event for event in second if event.get("type") == "session")["resumed"] is True
    assert first[-1]["type"] == "done"
    assert second[-1]["type"] == "done"


def test_empty_lease_loader_executes_but_cannot_activate_a_domain_tool(tmp_path: Path) -> None:
    _EmptyLeaseSearchHandler.request_payloads = []
    server, thread = _serve(_EmptyLeaseSearchHandler)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture-key",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "Check whether a workspace tool is available."}],
            thinking_level="off",
            task_mode="general",
            task_contract={
                **_TASK_CONTRACT_V2,
                "contract_id": "empty-loader-call",
                "risk_level": "none",
                "allowed_tools": [],
                "initial_tools": [],
                "initial_tool_budget": 2,
                "max_tool_budget": 4,
            },
            session_id="empty-loader-call-session",
            timeout_seconds=30,
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert len(_EmptyLeaseSearchHandler.request_payloads) == 2
    governance = {"ask_user", "search_tools", "submit_plan"}
    assert _tool_names(_EmptyLeaseSearchHandler.request_payloads[0]) == governance
    assert _tool_names(_EmptyLeaseSearchHandler.request_payloads[1]) == governance
    tool_messages = [
        message
        for message in list(_EmptyLeaseSearchHandler.request_payloads[1].get("messages", []) or [])
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    loader_result = json.loads(str(tool_messages[-1]["content"]))
    assert loader_result["matches"] == []
    assert loader_result["activated"] == []
    assert loader_result["rejected"] == [{
        "name": "inspect_workspace",
        "reason": "not_authorized_or_unavailable",
    }]
    assert not any(
        event.get("type") == "tool.completed" and event.get("name") == "inspect_workspace"
        for event in events
    )
    assert events[-1]["stats"]["toolInventory"]["registeredNames"] == [
        "ask_user",
        "search_tools",
        "submit_plan",
    ]


def test_ping_advertises_dynamic_tool_discovery() -> None:
    status = PiAgentClient.runtime_status()

    assert "dynamic_tools" in status["capabilities"]
