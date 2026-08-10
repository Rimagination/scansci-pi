from __future__ import annotations

from collections import deque
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from scansci_html.model_metadata import ModelRuntimeDescriptor
from scansci_html.pi_agent import (
    _PI_REQUIRED_FEATURES,
    _PendingToolCall,
    PiAgentClient,
    _ProtocolDispatcher,
    _RunContext,
    _ToolCompletion,
)


def _read_only_contract(*tools: str) -> dict[str, object]:
    return {
        "schema_version": "scansci.task-contract.v2",
        "version": 2,
        "contract_id": "parallel-fixture",
        "goal": "exercise the protocol dispatcher",
        "risk_level": "read_only",
        "allowed_tools": list(tools),
        "initial_tools": list(tools),
        "initial_tool_budget": 8,
        "max_tool_budget": 8,
    }


def _start_message(request_id: str, *tools: str) -> dict[str, object]:
    return {
        "type": "run.start",
        "request_id": request_id,
        "session_id": f"session-{request_id}",
        "task_mode": "general",
        "task_contract": _read_only_contract(*tools),
    }


def _fake_running_process() -> SimpleNamespace:
    return SimpleNamespace(poll=lambda: None)


class _IdenticalReadHandler(BaseHTTPRequestHandler):
    turns = 0
    tool_name = "inspect_available_tools"

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).turns += 1
        if type(self).turns == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": index,
                        "id": f"identical-{index}",
                        "type": "function",
                        "function": {"name": type(self).tool_name, "arguments": "{}"},
                    }
                    for index in range(2)
                ],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "coalesced reads completed"}
            finish = "stop"
        chunks = [
            {
                "id": f"chatcmpl-coalesce-{type(self).turns}",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-coalesce-{type(self).turns}",
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


class _NoProviderRequestHandler(BaseHTTPRequestHandler):
    requests = 0

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).requests += 1
        chunk = {
            "id": "chatcmpl-early-cancel",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fixture-model",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "should not run"},
                "finish_reason": "stop",
            }],
        }
        body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _DelayedLineStream:
    def __init__(self) -> None:
        self.lines: Queue[str | None] = Queue()

    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            yield line


class _WritableFixture:
    def write(self, _value: str) -> int:
        return 1

    def flush(self) -> None:
        return


class _DelayedProcess:
    def __init__(self) -> None:
        self.stdin = _WritableFixture()
        self.stdout = _DelayedLineStream()
        self.stderr = _DelayedLineStream()
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


@pytest.mark.parametrize("timing_round", range(3), ids=lambda value: f"round-{value + 1}")
def test_three_two_second_safe_reads_overlap_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timing_round: int,
) -> None:
    del timing_round
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: _fake_running_process())
    written: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_write", lambda message: written.append(dict(message)))
    lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_read(_name: str, arguments: dict[str, object]) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(2)
            return {"slot": arguments["slot"]}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(client, "_execute_tool", slow_read)
    for slot in range(3):
        client._output.put(json.dumps({
            "type": "tool.call",
            "request_id": "parallel-run",
            "call_id": f"call-{slot}",
            "name": "inspect_available_tools",
            "arguments": {"slot": slot},
        }))
    client._output.put(json.dumps({
        "type": "run.completed",
        "request_id": "parallel-run",
        "stats": {},
    }))

    started = time.monotonic()
    events = list(client._run_request(
        _start_message("parallel-run", "inspect_available_tools"),
        api_key="fixture",
        timeout_seconds=15,
    ))
    elapsed = time.monotonic() - started
    print(f"parallel timing elapsed={elapsed:.3f}s max_active={max_active}")

    assert elapsed <= 3.5
    assert max_active >= 3
    assert len([event for event in events if event.get("type") == "tool.completed"]) == 3
    assert {
        str(message.get("call_id", ""))
        for message in written
        if message.get("type") == "tool.result" and message.get("ok") is True
    } == {"call-0", "call-1", "call-2"}


def test_process_restart_keeps_old_stdout_and_stderr_out_of_the_new_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    old_process = _DelayedProcess()
    new_process = _DelayedProcess()
    processes = deque([old_process, new_process])
    monkeypatch.setattr(client, "runtime_paths", lambda: (tmp_path / "node", tmp_path / "main.mjs"))
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: processes.popleft())

    client._ensure_process(api_key="old-key")
    client._ensure_process(api_key="new-key")
    dispatcher = client._ensure_dispatcher()
    channel = dispatcher.register_request("new-request")
    dispatcher.start()

    old_process.stdout.lines.put(json.dumps({
        "type": "status.update",
        "request_id": "old-request",
        "status": "late-old-generation",
    }) + "\n")
    old_process.stdout.lines.put(None)
    old_process.stderr.lines.put("old-generation-error\n")
    old_process.stderr.lines.put(None)

    with pytest.raises(Empty):
        channel.get(timeout=0.2)
    assert "old-generation-error" not in client._errors

    new_process.stdout.lines.put(None)
    new_process.stderr.lines.put(None)
    assert channel.get(timeout=1) is None


def test_run_setup_failure_releases_lock_and_tombstones_partial_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: _fake_running_process())

    def broken_write(_message: dict[str, object]) -> None:
        raise RuntimeError("fixture startup failure")

    monkeypatch.setattr(client, "_write", broken_write)
    with pytest.raises(RuntimeError, match="startup failure"):
        list(client._run_request(
            _start_message("broken-setup", "inspect_available_tools"),
            api_key="fixture",
            timeout_seconds=2,
        ))

    monkeypatch.setattr(client, "_write", lambda _message: None)
    client._output.put(json.dumps({
        "type": "run.completed",
        "request_id": "after-setup-failure",
        "stats": {},
    }))
    events = list(client._run_request(
        _start_message("after-setup-failure", "inspect_available_tools"),
        api_key="fixture",
        timeout_seconds=2,
    ))

    assert events[-1]["type"] == "done"
    assert "broken-setup" not in client._run_contexts


@pytest.mark.parametrize(
    "order",
    [
        ("inspect_available_tools", "inspect_workspace"),
        ("inspect_workspace", "inspect_available_tools"),
        ("inspect_available_tools", "inspect_workspace", "inspect_available_tools"),
    ],
)
def test_sequential_sibling_prevents_overlap_in_the_host_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    order: tuple[str, ...],
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: _fake_running_process())
    monkeypatch.setattr(client, "_write", lambda _message: None)
    lock = threading.Lock()
    active = 0
    max_active = 0

    def measured(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.2)
            return {"ok": True}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(client, "_execute_tool", measured)
    for index, name in enumerate(order):
        client._output.put(json.dumps({
            "type": "tool.call",
            "request_id": "mixed-batch",
            "call_id": f"mixed-{index}",
            "name": name,
            "arguments": {},
        }))
    client._output.put(json.dumps({"type": "run.completed", "request_id": "mixed-batch", "stats": {}}))

    events = list(client._run_request(
        _start_message("mixed-batch", *order),
        api_key="fixture",
        timeout_seconds=5,
    ))

    assert max_active == 1
    assert len([event for event in events if event.get("type") == "tool.completed"]) == len(order)


@pytest.mark.parametrize(
    ("tool_name", "expected_physical_calls", "expected_coalesced"),
    [
        ("inspect_available_tools", 1, True),
        ("inspect_workspace", 2, False),
    ],
)
def test_identical_reads_only_coalesce_for_the_explicit_safe_allowlist(
    tmp_path: Path,
    tool_name: str,
    expected_physical_calls: int,
    expected_coalesced: bool,
) -> None:
    _IdenticalReadHandler.turns = 0
    _IdenticalReadHandler.tool_name = tool_name
    server = ThreadingHTTPServer(("127.0.0.1", 0), _IdenticalReadHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    node, sidecar = PiAgentClient.runtime_paths()
    environment = PiAgentClient._node_environment()
    environment["SCANSCIPI_PROVIDER_KEY"] = "fixture-key"
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
    )
    output: Queue[str | None] = Queue()

    def drain() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.put(line)
        output.put(None)

    threading.Thread(target=drain, daemon=True).start()
    request_id = "coalesced-logical-calls"
    physical_calls: list[dict[str, object]] = []
    statuses: list[tuple[str, str]] = []
    completed: dict[str, object] = {}
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps({
            "type": "run.start",
            "pi_protocol_version": 7,
            "required_features": list(_PI_REQUIRED_FEATURES),
            "request_id": request_id,
            "session_id": request_id,
            "ephemeral_session": True,
            "cwd": str(tmp_path),
            "agent_dir": str(tmp_path / ".agent"),
            "provider_kind": "openai-compatible",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model_id": "fixture-model",
            "thinking_level": "off",
            "system_prompt": "",
            "prompt": "Make the two identical sibling calls.",
            "images": [],
            "model_runtime": ModelRuntimeDescriptor.for_testing().to_dict(),
            "task_mode": "general",
            "task_contract": _read_only_contract(tool_name),
            "mcp_servers": [],
            "disabled_tools": [],
        }) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 20
        replied = False
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=1)
            except Empty:
                continue
            assert line is not None, process.stderr.read() if process.stderr else "sidecar closed"
            event = json.loads(line)
            if event.get("type") == "tool.call":
                physical_calls.append(event)
                process.stdin.write(json.dumps({
                    "type": "tool.result",
                    "request_id": request_id,
                    "call_id": event["call_id"],
                    "ok": True,
                    "result": {"ready": True},
                }) + "\n")
                process.stdin.flush()
                replied = True
            if event.get("type") == "status.update":
                statuses.append((str(event.get("status", "")), str(event.get("name", ""))))
            if event.get("type") == "run.failed":
                raise AssertionError(event)
            if event.get("type") == "run.completed":
                completed = event
                break
        else:
            raise AssertionError("sidecar did not complete the coalesced read fixture")
    finally:
        process.kill()
        process.wait(timeout=5)
        server.shutdown()
        server_thread.join(timeout=2)
        server.server_close()

    assert len(physical_calls) == expected_physical_calls
    assert (("tool_coalesced", tool_name) in statuses) is expected_coalesced
    hook_names = [name for status, name in statuses if status == "hook"]
    assert hook_names.count("tool_call") == 2
    assert hook_names.count("tool_result") == 2
    assert "settled" in hook_names
    assert dict(completed.get("control", {}) or {})["tool_calls"] == 2


def test_immediate_cancel_during_session_setup_never_reaches_the_provider(
    tmp_path: Path,
) -> None:
    _NoProviderRequestHandler.requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _NoProviderRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    node, sidecar = PiAgentClient.runtime_paths()
    environment = PiAgentClient._node_environment()
    environment["SCANSCIPI_PROVIDER_KEY"] = "fixture-key"
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
    )
    output: Queue[str | None] = Queue()

    def drain() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.put(line)
        output.put(None)

    threading.Thread(target=drain, daemon=True).start()
    request_id = "cancel-during-setup"
    command_id = "cancel-during-setup-command"
    observed: list[dict[str, object]] = []
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps({
            "type": "run.start",
            "pi_protocol_version": 7,
            "required_features": list(_PI_REQUIRED_FEATURES),
            "request_id": request_id,
            "session_id": request_id,
            "ephemeral_session": True,
            "cwd": str(tmp_path),
            "agent_dir": str(tmp_path / ".agent"),
            "provider_kind": "openai-compatible",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model_id": "fixture-model",
            "thinking_level": "off",
            "system_prompt": "",
            "prompt": "This request must be cancelled before provider I/O.",
            "images": [],
            "model_runtime": ModelRuntimeDescriptor.for_testing().to_dict(),
            "task_mode": "general",
            "task_contract": _read_only_contract(),
            "mcp_servers": [],
            "disabled_tools": [],
        }) + "\n")
        process.stdin.write(json.dumps({
            "type": "run.cancel",
            "request_id": request_id,
            "command_id": command_id,
            "generation": 0,
        }) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=1)
            except Empty:
                continue
            assert line is not None, process.stderr.read() if process.stderr else "sidecar closed"
            event = json.loads(line)
            observed.append(event)
            if event.get("type") == "run.cancelled":
                break
        else:
            raise AssertionError("sidecar did not settle the early-cancel fixture")
    finally:
        process.kill()
        process.wait(timeout=5)
        server.shutdown()
        server_thread.join(timeout=2)
        server.server_close()

    assert _NoProviderRequestHandler.requests == 0
    assert any(
        event.get("type") == "run.cancel_ack" and event.get("command_id") == command_id
        for event in observed
    )
    assert not any(
        event.get("type") == "status.update"
        and event.get("status") == "hook"
        and event.get("name") == "before_provider_request"
        for event in observed
    )


def test_cancel_returns_within_two_seconds_and_late_tool_result_is_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: _fake_running_process())
    written: list[dict[str, object]] = []
    started = threading.Event()
    release = threading.Event()

    def fake_write(message: dict[str, object]) -> None:
        written.append(dict(message))
        if message.get("type") == "run.cancel":
            request_id = str(message.get("request_id", ""))
            client._output.put(json.dumps({
                "type": "run.cancel_ack",
                "request_id": request_id,
            }))
            client._output.put(json.dumps({
                "type": "run.cancelled",
                "request_id": request_id,
            }))

    monkeypatch.setattr(client, "_write", fake_write)

    def blocked_read(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        started.set()
        release.wait(timeout=10)
        return {"late": True}

    monkeypatch.setattr(client, "_execute_tool", blocked_read)
    client._output.put(json.dumps({
        "type": "tool.call",
        "request_id": "cancel-run",
        "call_id": "late-call",
        "name": "inspect_available_tools",
        "arguments": {},
    }))
    events: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            events.extend(client._run_request(
                _start_message("cancel-run", "inspect_available_tools"),
                api_key="fixture",
                timeout_seconds=20,
            ))
        except BaseException as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert started.wait(timeout=3)
        cancel_started = time.monotonic()
        assert client.cancel("cancel-run") is True
        consumer.join(timeout=2)
        cancel_elapsed = time.monotonic() - cancel_started
        assert not consumer.is_alive()
        assert cancel_elapsed <= 2
        assert not errors
        assert events[-1]["type"] == "cancelled"
    finally:
        release.set()
        consumer.join(timeout=3)

    time.sleep(0.1)
    assert not any(
        message.get("type") == "tool.result" and message.get("call_id") == "late-call"
        for message in written
    )
    threading.Timer(0.05, lambda: client._output.put(json.dumps({
        "type": "run.completed",
        "request_id": "after-cancel",
        "stats": {},
    }))).start()
    next_events = list(client._run_request(
        _start_message("after-cancel", "inspect_available_tools"),
        api_key="fixture",
        timeout_seconds=3,
    ))
    assert next_events[-1]["type"] == "done"
    assert any(record.get("kind") == "late_tool_completion" for record in client._dispatch_audit)


def test_timeout_tombstones_late_worker_and_does_not_poison_next_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: _fake_running_process())
    written: list[dict[str, object]] = []
    def capture_write(message: dict[str, object]) -> None:
        written.append(dict(message))
        if message.get("type") == "run.cancel":
            client._output.put(json.dumps({
                "type": "run.cancel_ack",
                "request_id": message.get("request_id"),
                "command_id": message.get("command_id"),
            }))
            client._output.put(json.dumps({
                "type": "run.cancelled",
                "request_id": message.get("request_id"),
            }))

    monkeypatch.setattr(client, "_write", capture_write)
    started = threading.Event()
    release = threading.Event()

    def blocked(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        started.set()
        release.wait(timeout=5)
        return {"late": True}

    monkeypatch.setattr(client, "_execute_tool", blocked)
    client._output.put(json.dumps({
        "type": "tool.call",
        "request_id": "timeout-run",
        "call_id": "timeout-call",
        "name": "inspect_available_tools",
        "arguments": {},
    }))
    timeout_started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="request timeout"):
            list(client._run_request(
                _start_message("timeout-run", "inspect_available_tools"),
                api_key="fixture",
                timeout_seconds=0.25,
            ))
        assert started.is_set()
        assert time.monotonic() - timeout_started < 2

        threading.Timer(0.05, lambda: client._output.put(json.dumps({
            "type": "run.completed",
            "request_id": "post-timeout",
            "stats": {},
        }))).start()
        next_events = list(client._run_request(
            _start_message("post-timeout", "inspect_available_tools"),
            api_key="fixture",
            timeout_seconds=2,
        ))
        assert next_events[-1]["type"] == "done"
    finally:
        release.set()
    time.sleep(0.1)

    assert not any(message.get("call_id") == "timeout-call" for message in written if message.get("type") == "tool.result")
    cancel_message = next(message for message in written if message.get("type") == "run.cancel")
    assert str(cancel_message.get("command_id", ""))
    assert any(record.get("kind") == "late_tool_completion" for record in client._dispatch_audit)


def test_cancel_during_persist_discards_file_history_and_wire_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id="persist-cancel", session_id="persist-cancel", generation=1)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context
    written: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_write", lambda message: written.append(dict(message)))
    persist_started = threading.Event()
    release_persist = threading.Event()

    def checkpoint(stage: str, _context: _RunContext, _completion: _ToolCompletion) -> None:
        if stage == "persist_prepared":
            persist_started.set()
            release_persist.wait(timeout=5)

    monkeypatch.setattr(client, "_tool_result_commit_checkpoint", checkpoint)
    completion = _ToolCompletion(
        request_id=context.request_id,
        generation=context.generation,
        call_id="persist-call",
        name="search_web",
        arguments={"query": "fixture"},
        parallel_safe=True,
        result={"payload": "x" * 200_000},
    )
    outcomes: list[dict[str, object] | None] = []
    errors: list[BaseException] = []

    def finish() -> None:
        try:
            outcomes.append(client._finish_tool_completion(context, completion, task_mode="general"))
        except BaseException as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    thread = threading.Thread(target=finish, daemon=True)
    thread.start()
    assert persist_started.wait(timeout=2)
    assert client.cancel(context.request_id) is True
    release_persist.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert not errors
    assert outcomes == [None]
    assert not list((client.agent_dir / "tool-results").glob("*.json"))
    assert not list((client.agent_dir / "tool-results").glob("*.tmp"))
    assert not any(entry.get("status") == "ok" for entry in context.history)
    assert not any(message.get("type") == "tool.result" for message in written)


@pytest.mark.parametrize("cancel_stage", ["result_renamed", "before_wire"])
def test_cancel_before_wire_rolls_back_renamed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_stage: str,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id=f"cancel-{cancel_stage}", session_id="atomic", generation=2)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context
    written: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_write", lambda message: written.append(dict(message)))

    def checkpoint(stage: str, _context: _RunContext, _completion: _ToolCompletion) -> None:
        if stage == cancel_stage:
            assert client.cancel(context.request_id) is True

    monkeypatch.setattr(client, "_tool_result_commit_checkpoint", checkpoint)
    completion = _ToolCompletion(
        request_id=context.request_id,
        generation=context.generation,
        call_id=f"call-{cancel_stage}",
        name="search_web",
        arguments={"query": "fixture"},
        parallel_safe=True,
        result={"payload": "x" * 200_000},
    )

    outcome = client._finish_tool_completion(context, completion, task_mode="general")

    assert outcome is None
    result_dir = client.agent_dir / "tool-results"
    assert not list(result_dir.glob("*.json"))
    assert not list(result_dir.glob("*.tmp"))
    assert not any(entry.get("status") == "ok" for entry in context.history)
    assert not any(message.get("type") == "tool.result" for message in written)


def test_cancel_while_wire_commit_is_in_progress_linearizes_after_full_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id="cancel-during-wire", session_id="atomic", generation=3)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context
    write_started = threading.Event()
    release_write = threading.Event()
    written: list[dict[str, object]] = []

    def blocked_write(message: dict[str, object]) -> None:
        if message.get("type") == "tool.result":
            write_started.set()
            release_write.wait(timeout=5)
        written.append(dict(message))

    monkeypatch.setattr(client, "_write", blocked_write)
    completion = _ToolCompletion(
        request_id=context.request_id,
        generation=context.generation,
        call_id="wire-call",
        name="search_web",
        arguments={"query": "fixture"},
        parallel_safe=True,
        result={"payload": "x" * 200_000},
    )
    outcomes: list[dict[str, object] | None] = []
    finish_thread = threading.Thread(
        target=lambda: outcomes.append(
            client._finish_tool_completion(context, completion, task_mode="general")
        ),
        daemon=True,
    )
    finish_thread.start()
    assert write_started.wait(timeout=2)
    cancel_results: list[bool] = []
    cancel_thread = threading.Thread(
        target=lambda: cancel_results.append(client.cancel(context.request_id)),
        daemon=True,
    )
    cancel_thread.start()
    time.sleep(0.05)
    assert cancel_thread.is_alive()
    assert context.cancel_event.is_set()

    release_write.set()
    finish_thread.join(timeout=3)
    cancel_thread.join(timeout=3)

    assert not finish_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert cancel_results == [True]
    assert outcomes and outcomes[0] is not None
    assert len(list((client.agent_dir / "tool-results").glob("*.json"))) == 1
    assert len([entry for entry in context.history if entry.get("status") == "ok"]) == 1
    assert len([message for message in written if message.get("type") == "tool.result"]) == 1


def test_wire_failure_removes_unreferenced_persisted_result_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id="wire-failure", session_id="atomic", generation=4)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context

    def broken_write(message: dict[str, object]) -> None:
        if message.get("type") == "tool.result":
            raise BrokenPipeError("fixture wire failure")

    monkeypatch.setattr(client, "_write", broken_write)
    completion = _ToolCompletion(
        request_id=context.request_id,
        generation=context.generation,
        call_id="broken-wire-call",
        name="search_web",
        arguments={"query": "fixture"},
        parallel_safe=True,
        result={"payload": "x" * 200_000},
    )

    with pytest.raises(BrokenPipeError, match="wire failure"):
        client._finish_tool_completion(context, completion, task_mode="general")

    result_dir = client.agent_dir / "tool-results"
    assert not list(result_dir.glob("*.json"))
    assert not list(result_dir.glob("*.tmp"))
    assert not context.history


def test_discover_worker_defers_full_result_until_active_result_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_abstract = "A" * 20_000

    def fake_search(query: str, **_kwargs: object) -> dict[str, object]:
        return {
            "query": query,
            "count": 1,
            "items": [{"title": "Fixture paper", "doi": "10.1000/fixture", "abstract": full_abstract}],
        }

    monkeypatch.setattr("scansci_html.pi_agent.search_academic_papers", fake_search)
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id="discover-cancel", session_id="atomic", generation=5)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context
    completion = client._execute_tool_worker(
        context,
        _PendingToolCall(
            call_id="discover-call",
            name="discover_papers",
            arguments={"query": "forest productivity", "result_limit": 8},
            parallel_safe=False,
        ),
    )

    assert completion.error_type == "", completion.error
    result_dir = client.agent_dir / "tool-results"
    assert not list(result_dir.glob("*.json"))
    assert not list(result_dir.glob("*.tmp"))

    client._mark_context_cancelled(context)
    assert client._finish_tool_completion(context, completion, task_mode="research") is None
    assert not list(result_dir.glob("*.json"))
    assert not list(result_dir.glob("*.tmp"))
    assert not context.history


def test_discover_active_result_commit_persists_full_payload_and_sends_bounded_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_abstract = "A" * 20_000

    def fake_search(query: str, **_kwargs: object) -> dict[str, object]:
        return {
            "query": query,
            "count": 1,
            "items": [{"title": "Fixture paper", "doi": "10.1000/fixture", "abstract": full_abstract}],
        }

    monkeypatch.setattr("scansci_html.pi_agent.search_academic_papers", fake_search)
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    context = _RunContext(request_id="discover-success", session_id="atomic", generation=6)
    with client._contexts_lock:
        client._run_contexts[context.request_id] = context
    written: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_write", lambda message: written.append(dict(message)))
    completion = client._execute_tool_worker(
        context,
        _PendingToolCall(
            call_id="discover-call",
            name="discover_papers",
            arguments={"query": "forest productivity", "result_limit": 8},
            parallel_safe=False,
        ),
    )

    outcome = client._finish_tool_completion(context, completion, task_mode="research")

    assert outcome is not None
    result_files = list((client.agent_dir / "tool-results").glob("*.json"))
    assert len(result_files) == 1
    assert not list((client.agent_dir / "tool-results").glob("*.tmp"))
    assert json.loads(result_files[0].read_text(encoding="utf-8"))["items"][0]["abstract"] == full_abstract
    result_messages = [message for message in written if message.get("type") == "tool.result"]
    assert len(result_messages) == 1
    model_result = dict(result_messages[0]["result"])
    assert len(model_result["items"][0]["abstract_excerpt"]) == 600
    assert model_result["full_result_reference"].endswith(".json")
    assert model_result["full_result_bytes"] == result_files[0].stat().st_size
    assert len([entry for entry in context.history if entry.get("status") == "ok"]) == 1


def test_timeout_waits_for_real_sidecar_cancellation_before_reusing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _IdenticalReadHandler.turns = 0
    _IdenticalReadHandler.tool_name = "inspect_available_tools"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _IdenticalReadHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    started = threading.Event()
    release = threading.Event()

    def blocked(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        started.set()
        release.wait(timeout=10)
        return {"late": True}

    monkeypatch.setattr(client, "_execute_tool", blocked)
    common = dict(
        provider_kind="openai-compatible",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="fixture-key",
        model_id="fixture-model",
        thinking_level="off",
        task_mode="general",
        task_contract=_read_only_contract("inspect_available_tools"),
        session_id="timeout-reuse-session",
    )
    try:
        with pytest.raises(TimeoutError, match="request timeout"):
            list(client.stream_chat(
                messages=[{"role": "user", "content": "start a tool"}],
                timeout_seconds=3,
                **common,
            ))
        assert started.is_set()
        resumed = list(client.stream_chat(
            messages=[{"role": "user", "content": "continue after timeout"}],
            timeout_seconds=10,
            **common,
        ))
    finally:
        release.set()
        client.close()
        server.shutdown()
        server_thread.join(timeout=2)
        server.server_close()

    assert resumed[-1]["type"] == "done"
    assert not any(
        event.get("type") == "error"
        and "session_busy" in json.dumps(event)
        for event in resumed
    )


def test_session_close_registers_command_before_write_and_waits_for_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    client._process = _fake_running_process()  # type: ignore[assignment]
    sent: list[dict[str, object]] = []

    def reply_immediately(message: dict[str, object]) -> None:
        sent.append(dict(message))
        if message.get("type") == "session.close":
            client._output.put(json.dumps({
                "type": "session.closed",
                "command_id": message.get("command_id"),
                "session_id": message.get("session_id"),
                "generation": message.get("generation"),
            }))

    monkeypatch.setattr(client, "_write", reply_immediately)

    acknowledgement = client.close_session("durable-session", timeout_seconds=2)

    assert acknowledgement["type"] == "session.closed"
    assert acknowledgement["session_id"] == "durable-session"
    assert sent[0]["command_id"] == acknowledgement["command_id"]


def test_same_session_commands_are_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    client._process = _fake_running_process()  # type: ignore[assignment]
    sent_at: list[float] = []

    def delayed_reply(message: dict[str, object]) -> None:
        if message.get("type") != "session.close":
            return
        sent_at.append(time.monotonic())

        def reply() -> None:
            time.sleep(0.2)
            client._output.put(json.dumps({
                "type": "session.closed",
                "command_id": message["command_id"],
                "session_id": message["session_id"],
                "generation": message["generation"],
            }))

        threading.Thread(target=reply, daemon=True).start()

    monkeypatch.setattr(client, "_write", delayed_reply)
    results: list[dict[str, object]] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(client.close_session("same-session", timeout_seconds=2)),
            daemon=True,
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert len(sent_at) == 2
    assert sent_at[1] - sent_at[0] >= 0.15


def test_same_session_run_waits_for_an_inflight_management_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    client._process = _fake_running_process()  # type: ignore[assignment]
    monkeypatch.setattr(client, "_ensure_process", lambda **_kwargs: client._process)
    close_written = threading.Event()
    release_close = threading.Event()
    run_written = threading.Event()

    def coordinated_write(message: dict[str, object]) -> None:
        if message.get("type") == "session.close":
            close_written.set()

            def acknowledge() -> None:
                release_close.wait(timeout=3)
                client._output.put(json.dumps({
                    "type": "session.closed",
                    "command_id": message["command_id"],
                    "session_id": message["session_id"],
                    "generation": message["generation"],
                }))

            threading.Thread(target=acknowledge, daemon=True).start()
        elif message.get("type") == "run.start":
            run_written.set()

    monkeypatch.setattr(client, "_write", coordinated_write)
    command_results: list[dict[str, object]] = []
    command = threading.Thread(
        target=lambda: command_results.append(client.close_session("shared-session", timeout_seconds=3)),
        daemon=True,
    )
    run_events: list[dict[str, object]] = []
    run_errors: list[BaseException] = []

    def run() -> None:
        try:
            run_events.extend(client._run_request(
                {
                    **_start_message("after-command", "inspect_available_tools"),
                    "session_id": "shared-session",
                },
                api_key="fixture",
                timeout_seconds=3,
            ))
        except BaseException as error:  # noqa: BLE001 - asserted below
            run_errors.append(error)

    command.start()
    assert close_written.wait(timeout=1)
    runner = threading.Thread(target=run, daemon=True)
    runner.start()
    assert not run_written.wait(timeout=0.2)

    release_close.set()
    command.join(timeout=2)
    assert run_written.wait(timeout=1)
    client._output.put(json.dumps({
        "type": "run.completed",
        "request_id": "after-command",
        "stats": {},
    }))
    runner.join(timeout=2)

    assert command_results[0]["type"] == "session.closed"
    assert not run_errors
    assert run_events[-1]["type"] == "done"


def test_dispatcher_routes_interleaved_requests_and_commands_and_broadcasts_eof() -> None:
    raw: Queue[str | None] = Queue()
    audit: deque[dict[str, object]] = deque(maxlen=32)
    dispatcher = _ProtocolDispatcher(raw, generation=7, audit=audit)
    request = dispatcher.register_request("request-a")
    command_a = dispatcher.register_command("command-a")
    command_b = dispatcher.register_command("command-b")
    dispatcher.start()

    raw.put(json.dumps({"type": "session.loaded", "command_id": "command-b", "generation": 7}))
    raw.put(json.dumps({"type": "status.update", "request_id": "request-a", "status": "working"}))
    raw.put(json.dumps({"type": "session.closed", "command_id": "command-a", "generation": 7}))

    assert command_b.get(timeout=1)["command_id"] == "command-b"
    assert request.get(timeout=1)["request_id"] == "request-a"
    assert command_a.get(timeout=1)["command_id"] == "command-a"

    dispatcher.unregister_request("request-a")
    raw.put(json.dumps({"type": "tool.result", "request_id": "request-a", "call_id": "late"}))
    deadline = time.monotonic() + 1
    while not any(record.get("kind") == "late" for record in audit) and time.monotonic() < deadline:
        time.sleep(0.01)
    raw.put(None)

    assert command_a.get(timeout=1) is None
    assert command_b.get(timeout=1) is None
    assert any(record.get("kind") == "late" and record.get("request_id") == "request-a" for record in audit)
