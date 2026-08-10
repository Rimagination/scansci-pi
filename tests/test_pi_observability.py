from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading

from scansci_html.pi_agent import PiAgentClient


class _HookAuditHandler(BaseHTTPRequestHandler):
    prompts: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        messages = list(payload.get("messages", []) or [])
        type(self).prompts.append(json.dumps(messages, ensure_ascii=False))
        content = f"answer-{len(type(self).prompts)}"
        chunks = [
            {
                "id": "chatcmpl-hook",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-hook",
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


def _run_turn(
    client: PiAgentClient,
    *,
    base_url: str,
    request_marker: str,
    session_id: str,
) -> list[dict[str, object]]:
    return list(client.stream_chat(
        provider_kind="openai-compatible",
        base_url=base_url,
        api_key="fixture-secret-key",
        model_id="fixture-model",
        messages=[{"role": "user", "content": f"user-{request_marker}"}],
        thinking_level="off",
        task_mode="general",
        task_contract={
            "schema_version": "scansci.task-contract.v2",
            "version": 2,
            "contract_id": request_marker,
            "goal": f"goal-{request_marker}",
            "risk_level": "read_only",
            "allowed_tools": [],
            "initial_tools": [],
            "initial_tool_budget": 2,
            "max_tool_budget": 2,
        },
        timeout_seconds=30,
        session_id=session_id,
    ))


def test_runtime_hooks_emit_bounded_ordered_current_turn_audit(
    tmp_path: Path,
) -> None:
    _HookAuditHandler.prompts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HookAuditHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        first = _run_turn(client, base_url=base_url, request_marker="turn-one", session_id="hook-session")
        second = _run_turn(client, base_url=base_url, request_marker="turn-two", session_id="hook-session")
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    expected = [
        "before_agent_start",
        "context",
        "before_provider_request",
        "after_provider_response",
        "settled",
    ]
    for events in (first, second):
        hooks = [
            event
            for event in events
            if event.get("type") == "status" and event.get("status") == "hook"
        ]
        names = [str(event.get("name", "")) for event in hooks]
        positions = [names.index(name) for name in expected]
        assert positions == sorted(positions)
        sequences = [int(dict(event.get("details", {}) or {}).get("sequence", 0)) for event in hooks]
        assert sequences == sorted(sequences)
        encoded = json.dumps(hooks, ensure_ascii=False)
        assert "fixture-secret-key" not in encoded
        assert "user-turn-" not in encoded

    first_hooks = [event for event in first if event.get("status") == "hook"]
    second_hooks = [event for event in second if event.get("status") == "hook"]
    first_request_id = next(str(event["request_id"]) for event in first if event.get("type") == "session")
    second_request_id = next(str(event["request_id"]) for event in second if event.get("type") == "session")
    assert first_request_id != second_request_id
    assert {str(event.get("request_id", "")) for event in first_hooks} == {first_request_id}
    assert {str(event.get("request_id", "")) for event in second_hooks} == {second_request_id}


def test_context_policy_builds_a_non_destructive_view() -> None:
    from scansci_html.context_policy import context_view_with_stale_tool_pruning

    original = [
        {"role": "user", "content": "turn one"},
        {"role": "toolResult", "toolName": "search_web", "content": [{"type": "text", "text": "old payload"}]},
        {"role": "user", "content": "turn two"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "turn three"},
    ]
    snapshot = json.loads(json.dumps(original))

    view, report = context_view_with_stale_tool_pruning(original, keep_recent_turns=2)

    assert original == snapshot
    assert view is not original
    assert view[1]["content"] != original[1]["content"]
    assert report.pruned_tool_results == 1


def test_node_context_hook_projection_does_not_mutate_sdk_messages(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    entry = tmp_path / "context-probe.ts"
    bundle = tmp_path / "context-probe.mjs"
    runtime_extension = (repository / "pi-runtime" / "src" / "runtime-extension.ts").as_posix()
    entry.write_text(
        f'''import {{ buildNonDestructiveContextView, registerRuntimeLifecycleHooks }} from "{runtime_extension}";
const original = [
  {{ role: "user", content: "turn one" }},
  {{ role: "toolResult", toolName: "search_web", content: [{{ type: "text", text: "raw-result" }}] }},
  {{ role: "user", content: "turn two" }},
  {{ role: "assistant", content: [{{ type: "text", text: "ok" }}] }},
  {{ role: "user", content: "turn three" }},
];
const snapshot = structuredClone(original);
const projected = buildNonDestructiveContextView(original, 2);
const handlers = {{}};
const pi = {{ on: (name, handler) => {{ handlers[name] = handler; }} }};
registerRuntimeLifecycleHooks(pi, {{
  current: () => ({{ request_id: "fault-turn", session_id: "fault-session" }}),
  emit: () => {{ throw new Error("telemetry unavailable"); }},
  context: (event) => buildNonDestructiveContextView(event.messages, 2),
  onContextReport: () => {{ throw new Error("reporting unavailable"); }},
}});
const projectedThroughFaultyTelemetry = handlers.context({{ messages: original }});
process.stdout.write(JSON.stringify({{ original, snapshot, projected, projectedThroughFaultyTelemetry }}));
''',
        encoding="utf-8",
    )
    esbuild = repository / "node_modules" / ".bin" / "esbuild.cmd"
    built = subprocess.run(
        [
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=node",
            "--format=esm",
            "--banner:js=import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);",
            f"--outfile={bundle}",
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(
        [str(PiAgentClient.runtime_paths()[0]), str(bundle)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr
    payload = json.loads(executed.stdout)

    assert payload["original"] == payload["snapshot"]
    assert payload["projected"]["messages"][1]["content"] != payload["original"][1]["content"]
    assert payload["projected"]["report"]["pruned_tool_results"] == 1
    assert payload["projectedThroughFaultyTelemetry"]["messages"][1]["content"] != payload["original"][1]["content"]
