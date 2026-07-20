from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from scansci_html.pi_agent import PiAgentClient


class _OpenAIStreamHandler(BaseHTTPRequestHandler):
    request_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(length))
        chunks = [
            {
                "id": "chatcmpl-scanscipi",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Pi bridge works"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-scanscipi",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
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


class _OpenAIToolLoopHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        if len(type(self).request_payloads) == 1:
            chunks = [
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_workspace",
                                        "type": "function",
                                        "function": {"name": "inspect_available_tools", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            ]
        else:
            chunks = [
                {
                    "id": "chatcmpl-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Tool result received"}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
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


def test_pi_sidecar_responds_to_runtime_probe() -> None:
    status = PiAgentClient.runtime_status()

    assert status["ready"] is True
    assert status["runtime"] == "pi"
    assert status["version"] == "0.80.10"


def test_pi_sdk_streams_through_the_python_bridge(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIStreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[
                    {"role": "system", "content": "Reply briefly."},
                    {"role": "user", "content": "Confirm the bridge."},
                ],
                thinking_level="off",
                task_mode="knowledge",
                timeout_seconds=30,
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "".join(str(item.get("content", "")) for item in events if item["type"] == "delta") == "Pi bridge works"
    assert events[-1]["type"] == "done"
    assert _OpenAIStreamHandler.request_payload["model"] == "fixture-model"
    assert _OpenAIStreamHandler.request_payload["stream"] is True
    assert _OpenAIStreamHandler.request_payload["tools"]


def test_pi_tool_call_round_trips_through_scansci_dispatcher(tmp_path: Path) -> None:
    _OpenAIToolLoopHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIToolLoopHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "Inspect the available tools."}],
                thinking_level="off",
                task_mode="knowledge",
                timeout_seconds=30,
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    completed = [item for item in events if item["type"] == "tool.completed"]
    assert completed[0]["name"] == "inspect_available_tools"
    assert completed[0]["result"]["workspace"] == str((tmp_path / "workspace.sqlite").resolve())
    assert "".join(str(item.get("content", "")) for item in events if item["type"] == "delta") == "Tool result received"
    assert len(_OpenAIToolLoopHandler.request_payloads) == 2
    second_messages = _OpenAIToolLoopHandler.request_payloads[1]["messages"]
    assert any(message.get("role") == "tool" for message in second_messages)
