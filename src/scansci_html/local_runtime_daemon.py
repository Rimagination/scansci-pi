"""Crash-resilient loopback daemon for the optional local model component.

The daemon never imports a model backend.  Every selected model is loaded and
used in a child worker process, so an access violation in Torch, CUDA or a
model extension only terminates that worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.client import HTTPConnection, IncompleteRead, RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

from .local_runtime_compatibility import ModelCompatibilityStore
from .local_runtime_contract import COMPONENT_VERSION


_NATIVE_FAILURE_MIN = 0xC0000000


@dataclass(frozen=True)
class ModelWorkerFailure(RuntimeError):
    code: str
    message: str
    model_id: str
    phase: str
    exit_code: int | None = None
    native_crash: bool = False
    retryable: bool = True
    details: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def as_error(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "message": self.message,
            "type": "local_runtime_error",
            "code": self.code,
            "model": self.model_id,
            "phase": self.phase,
            "native_crash": self.native_crash,
            "retryable": self.retryable,
        }
        if self.exit_code is not None:
            error["exit_code"] = self.exit_code
        if self.details:
            error["details"] = dict(self.details)
        return {"error": error}


def classify_worker_exit(*, model_id: str, phase: str, returncode: int | None) -> ModelWorkerFailure:
    normalized: int | None = None
    native = False
    if returncode is not None:
        normalized = int(returncode) & 0xFFFFFFFF
        native = normalized >= _NATIVE_FAILURE_MIN
    if native:
        message = (
            f"模型 {model_id} 的隔离子进程在{_phase_label(phase)}时原生崩溃"
            f"（退出码 0x{normalized:08X}）；本地运行服务仍在运行。"
        )
    else:
        message = (
            f"模型 {model_id} 的隔离子进程在{_phase_label(phase)}时退出"
            f"（退出码 {normalized if normalized is not None else 'unknown'}）；本地运行服务仍在运行。"
        )
    return ModelWorkerFailure(
        code="model_worker_crashed",
        message=message,
        model_id=model_id,
        phase=phase,
        exit_code=normalized,
        native_crash=native,
    )


def _phase_label(phase: str) -> str:
    return {
        "startup": "启动",
        "load": "加载",
        "generation": "生成",
        "load_or_generate": "加载或生成",
    }.get(str(phase), str(phase) or "运行")


def isolated_worker_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an offline-only environment while retaining existing cache roots."""

    environment = dict(base or os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "SCANSCI_LOCAL_MODEL_WORKER": "1",
        }
    )
    return environment


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _default_command_prefix() -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        return [sys.executable]
    return [sys.executable, "-m", "scansci_html.local_runtime_server"]


class ModelWorkerSupervisor:
    """Own one persistent model worker and replace it after a crash."""

    def __init__(
        self,
        *,
        model_record: Mapping[str, Any],
        state_dir: str | Path,
        command_prefix: list[str] | tuple[str, ...] | None = None,
        startup_timeout: float = 180.0,
        auto_start: bool = True,
    ) -> None:
        self.model_record = dict(model_record)
        self.model_id = str(model_record.get("id", ""))
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.command_prefix = list(command_prefix or _default_command_prefix())
        self.startup_timeout = max(0.1, float(startup_timeout))
        self.auto_start = bool(auto_start)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._worker_base_url = ""
        self._status_file: Path | None = None
        self._stderr_file: Path | None = None
        self._stderr_handle: Any | None = None
        self._latest_failure: ModelWorkerFailure | None = None
        self._compatibility = ModelCompatibilityStore(self.state_dir / "model-compatibility.json")

    @property
    def latest_failure(self) -> ModelWorkerFailure | None:
        return self._latest_failure

    @property
    def worker_base_url(self) -> str:
        with self._lock:
            return self._worker_base_url

    def status(self) -> dict[str, Any]:
        # Health must remain responsive while another thread waits for a slow
        # model load.  These references are replaced atomically by CPython;
        # taking the launch lock here would make the daemon look dead for the
        # entire preflight window.
        process = self._process
        alive = process is not None and process.poll() is None
        failure = self._latest_failure
        return {
            "worker_alive": alive,
            "worker_pid": int(process.pid) if alive and process is not None else None,
            "available": bool(alive and self._worker_base_url),
            "error": failure.as_error()["error"] if failure is not None else None,
        }

    def ensure_worker(self) -> str:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self._worker_base_url:
                return self._worker_base_url
            self._close_stderr()
            self.state_dir.mkdir(parents=True, exist_ok=True)
            worker_dir = self.state_dir / "workers"
            worker_dir.mkdir(parents=True, exist_ok=True)
            token = uuid4().hex
            port = _free_loopback_port()
            self._status_file = worker_dir / f"{token}.json"
            self._stderr_file = worker_dir / f"{token}.stderr.log"
            self._stderr_handle = self._stderr_file.open("ab")
            command = [
                *self.command_prefix,
                "--worker-model-id",
                self.model_id,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--parent-pid",
                str(os.getpid()),
                "--worker-status-file",
                str(self._status_file),
            ]
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            worker_environment = isolated_worker_environment()
            worker_environment["SCANSCI_LOCAL_RUNTIME_STATE_DIR"] = str(self.state_dir)
            if not bool(getattr(sys, "frozen", False)):
                source_root = str(Path(__file__).resolve().parents[1])
                existing_pythonpath = worker_environment.get("PYTHONPATH", "")
                worker_environment["PYTHONPATH"] = os.pathsep.join(
                    value for value in (source_root, existing_pythonpath) if value
                )
            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=self._stderr_handle,
                    env=worker_environment,
                    creationflags=creationflags,
                )
            except OSError as error:
                self._close_stderr()
                failure = ModelWorkerFailure(
                    code="model_worker_start_failed",
                    message=f"无法启动模型隔离子进程：{error}",
                    model_id=self.model_id,
                    phase="startup",
                    retryable=True,
                )
                self._remember_failure(failure)
                raise failure from error
            worker_root = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                process = self._process
                if process is None or process.poll() is not None:
                    failure = self._failure_from_exit(process.returncode if process is not None else None)
                    self._process = None
                    self._worker_base_url = ""
                    self._close_stderr()
                    self._remember_failure(failure)
                    raise failure
                health = self._read_health(worker_root)
                if health is not None and str(health.get("model", "")) == self.model_id:
                    probe = health.get("probe") if isinstance(health.get("probe"), dict) else {}
                    if self._requires_generation_probe() and not (
                        probe.get("generated") is True and str(probe.get("generated_text", "")).strip()
                    ):
                        self.shutdown_worker()
                        failure = ModelWorkerFailure(
                            code="model_probe_incomplete",
                            message="Qwen3.5 未在隔离进程中完成真实加载与最小生成，因此不会标记为可用。",
                            model_id=self.model_id,
                            phase="load_or_generate",
                            retryable=False,
                            details={"probe": probe},
                        )
                        self._remember_failure(failure)
                        raise failure
                    self._worker_base_url = worker_root
                    self._latest_failure = None
                    if self._requires_generation_probe():
                        self._compatibility.record_success(
                            self.model_record,
                            component_version=COMPONENT_VERSION,
                            runtime_versions=health.get("runtime_versions", {}),
                            generated_text=str(probe.get("generated_text", "")),
                        )
                    return self._worker_base_url
                time.sleep(0.1)
            self.shutdown_worker()
            failure = ModelWorkerFailure(
                code="model_worker_timeout",
                message=f"模型 {self.model_id} 的隔离子进程启动或预检超时。",
                model_id=self.model_id,
                phase="startup",
                retryable=True,
            )
            self._remember_failure(failure)
            raise failure

    def _requires_generation_probe(self) -> bool:
        normalized = self.model_id.lower().replace("_", "").replace("-", "")
        return "qwen3.5" in self.model_id.lower() or "qwen35" in normalized

    def _read_health(self, worker_root: str) -> dict[str, Any] | None:
        try:
            with urlopen(worker_root + "/health", timeout=0.5) as response:  # noqa: S310 - loopback only
                payload = json.loads(response.read(512_000).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, json.JSONDecodeError, HTTPError, URLError):
            return None

    def _failure_from_exit(self, returncode: int | None) -> ModelWorkerFailure:
        payload: dict[str, Any] = {}
        if self._status_file is not None:
            try:
                loaded = json.loads(self._status_file.read_text(encoding="utf-8"))
                payload = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                payload = {}
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        if error:
            return ModelWorkerFailure(
                code=str(error.get("code") or "model_worker_failed"),
                message=str(error.get("message") or "模型隔离子进程预检失败。"),
                model_id=self.model_id,
                phase=str(error.get("phase") or "load_or_generate"),
                exit_code=(int(returncode) & 0xFFFFFFFF) if returncode is not None else None,
                native_crash=False,
                retryable=bool(error.get("retryable", False)),
                details={"stderr_tail": self._stderr_tail()} if self._stderr_tail() else None,
            )
        return classify_worker_exit(model_id=self.model_id, phase="startup", returncode=returncode)

    def _remember_failure(self, failure: ModelWorkerFailure) -> None:
        self._latest_failure = failure
        if self._requires_generation_probe():
            try:
                self._compatibility.record_failure(
                    self.model_record,
                    component_version=COMPONENT_VERSION,
                    error=failure.as_error()["error"],
                )
            except (OSError, ValueError):
                pass

    def record_stream_failure(
        self,
        *,
        cause: BaseException | None = None,
        wait_timeout: float = 0.75,
    ) -> ModelWorkerFailure:
        """Retire a broken worker and expose a generation-phase failure.

        A response may already be a public HTTP 200 when the model process
        terminates.  In that case the daemon cannot change the status code,
        so it records the failure here and lets the proxy finish the SSE
        protocol with an explicit error event.
        """

        with self._lock:
            process = self._process
            self._worker_base_url = ""
            returncode: int | None = None
            if process is not None:
                try:
                    returncode = process.wait(timeout=max(0.0, float(wait_timeout)))
                except subprocess.TimeoutExpired:
                    returncode = process.poll()

            if returncode is not None:
                failure = classify_worker_exit(
                    model_id=self.model_id,
                    phase="generation",
                    returncode=returncode,
                )
            else:
                details: dict[str, Any] = {}
                if cause is not None:
                    details["cause"] = f"{type(cause).__name__}: {cause}"
                failure = ModelWorkerFailure(
                    code="model_stream_interrupted",
                    message=(
                        f"模型 {self.model_id} 的流式生成在完成事件前中断；"
                        "本地运行服务仍在运行，可重试此请求。"
                    ),
                    model_id=self.model_id,
                    phase="generation",
                    retryable=True,
                    details=details or None,
                )

            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
            if self._process is process:
                self._process = None
            self._close_stderr()
            self._remember_failure(failure)
            return failure

    def _stderr_tail(self, limit: int = 4096) -> str:
        if self._stderr_file is None:
            return ""
        try:
            with self._stderr_file.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                return handle.read(limit).decode("utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _close_stderr(self) -> None:
        handle = self._stderr_handle
        self._stderr_handle = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def shutdown_worker(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._worker_base_url = ""
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
            self._close_stderr()


class LocalRuntimeDaemon:
    """Stable public API that proxies to a disposable model worker."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        model_record: Mapping[str, Any],
        supervisor: ModelWorkerSupervisor,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.model_record = dict(model_record)
        self.model_id = str(model_record.get("id", ""))
        self.supervisor = supervisor
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> str:
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler())
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="scansci-local-runtime-daemon",
        )
        self._thread.start()
        if self.supervisor.auto_start:
            threading.Thread(
                target=self._start_worker_quietly,
                daemon=True,
                name="scansci-local-model-preflight",
            ).start()
        return self.base_url + "/v1"

    def _start_worker_quietly(self) -> None:
        try:
            self.supervisor.ensure_worker()
        except ModelWorkerFailure:
            return

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"ScanSciLocalRuntimeDaemon/{COMPONENT_VERSION}"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") == "/health":
                    status = daemon.supervisor.status()
                    failure = daemon.supervisor.latest_failure
                    self._json(
                        HTTPStatus.OK,
                        {
                            "status": "ok" if status["available"] else "degraded" if failure else "starting",
                            "component": "local-transformers",
                            "version": COMPONENT_VERSION,
                            "model": daemon.model_id,
                            **status,
                        },
                    )
                    return
                if self.path.rstrip("/") == "/v1/models":
                    self._proxy()
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found", "code": "not_found"}})

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") not in {"/v1/chat/completions", "/v1/audio/transcriptions"}:
                    self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found", "code": "not_found"}})
                    return
                self._proxy()

            def _proxy(self) -> None:
                try:
                    worker_root = daemon.supervisor.ensure_worker()
                except ModelWorkerFailure as failure:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, failure.as_error())
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length > 0 else None
                connection = HTTPConnection(worker_root.removeprefix("http://"), timeout=600)
                headers = {
                    "Content-Type": self.headers.get("Content-Type", "application/json"),
                    "Accept": self.headers.get("Accept", "*/*"),
                }
                try:
                    connection.request(self.command, self.path, body=body, headers=headers)
                    response = connection.getresponse()
                except (OSError, RemoteDisconnected) as error:
                    process = daemon.supervisor._process
                    failure = classify_worker_exit(
                        model_id=daemon.model_id,
                        phase="load_or_generate",
                        returncode=process.poll() if process is not None else None,
                    )
                    daemon.supervisor._remember_failure(failure)
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, failure.as_error())
                    connection.close()
                    return
                self.send_response(response.status)
                content_type = response.getheader("Content-Type") or "application/octet-stream"
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", response.getheader("Cache-Control") or "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                is_event_stream = content_type.lower().startswith("text/event-stream")
                stream_tail = bytearray()
                stream_read_error: BaseException | None = None
                try:
                    while True:
                        try:
                            chunk = response.read(64 * 1024)
                        except (IncompleteRead, RemoteDisconnected, ConnectionResetError, OSError) as error:
                            stream_read_error = error
                            break
                        if not chunk:
                            break
                        if is_event_stream:
                            stream_tail.extend(chunk)
                            if len(stream_tail) > 8192:
                                del stream_tail[:-8192]
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            # The client left; this says nothing about worker
                            # health and must not mark the model incompatible.
                            return

                    if is_event_stream and b"data: [DONE]" not in stream_tail:
                        failure = daemon.supervisor.record_stream_failure(cause=stream_read_error)
                        error_payload = json.dumps(failure.as_error(), ensure_ascii=False).encode("utf-8")
                        terminal_events = (
                            b"event: error\n"
                            b"data: " + error_payload + b"\n\n"
                            b"event: done\n"
                            b"data: [DONE]\n\n"
                        )
                        try:
                            self.wfile.write(terminal_events)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            return
                finally:
                    connection.close()

        return Handler

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self.supervisor.shutdown_worker()
