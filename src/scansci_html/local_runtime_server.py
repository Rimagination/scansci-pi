"""OpenAI-compatible sidecar that owns heavyweight local inference imports."""

from __future__ import annotations

import argparse
import gc
import importlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any, Iterator

from .local_model_market import installed_models
from .local_asr import LocalASRRuntime
from .local_model_inference import (
    LoadedLocalModel,
    generate_local_chat_stream,
    load_local_chat_model,
    local_runtime_status,
)
from .local_runtime_contract import COMPONENT_VERSION


def _runtime_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0], "component": COMPONENT_VERSION}
    for name in ("torch", "transformers", "safetensors", "bitsandbytes"):
        module = sys.modules.get(name)
        if module is not None:
            versions[name] = str(getattr(module, "__version__", ""))
    return versions


def run_model_preflight(
    record: dict[str, Any],
    *,
    load_model: Any | None = None,
    generate_stream: Any | None = None,
) -> dict[str, Any]:
    """Really load a model and generate text inside the disposable worker."""

    if load_model is None:
        loaded = load_local_chat_model(Path(str(record["path"])).resolve(), str(record["id"]))
    else:
        loaded = load_model(record)
    messages = [{"role": "user", "content": "只回答：好"}]
    if generate_stream is None:
        chunks = generate_local_chat_stream(loaded, messages, max_new_tokens=8)
    else:
        chunks = generate_stream(loaded, record, messages, max_new_tokens=8)
    generated_text = "".join(str(chunk or "") for chunk in chunks).strip()
    if not generated_text:
        raise RuntimeError("模型完成加载，但最小生成没有生成任何文本。")
    return {
        "loaded_model": loaded,
        "generated": True,
        "generated_text": generated_text,
        "runtime_versions": _runtime_versions(),
    }


def _requires_generation_probe(model_id: str) -> bool:
    normalized = str(model_id or "").lower().replace("_", "").replace("-", "")
    return "qwen3.5" in str(model_id or "").lower() or "qwen35" in normalized


def _model_record(model_id: str) -> dict[str, Any]:
    record = next((item for item in installed_models() if item.get("id") == model_id), None)
    if not record or not (record.get("ready") or record.get("model_files_present")):
        raise ValueError("本地模型权重尚未完整下载，暂时不能启动。")
    return dict(record)


def create_runtime_daemon(
    *,
    model_id: str,
    host: str,
    port: int,
    state_dir: str | Path,
    auto_start_worker: bool = True,
):
    """Create the stable public daemon; heavyweight imports stay in its worker."""

    from .local_runtime_daemon import LocalRuntimeDaemon, ModelWorkerSupervisor

    record = _model_record(model_id)
    supervisor = ModelWorkerSupervisor(
        model_record=record,
        state_dir=state_dir,
        auto_start=auto_start_worker,
    )
    return LocalRuntimeDaemon(
        host=host,
        port=port,
        model_record=record,
        supervisor=supervisor,
    )


class LocalRuntimeServer:
    """Host one selected Hugging Face chat model on a loopback-only port."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 17863) -> None:
        self.host = host
        self.port = int(port)
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._model_id = ""
        self._model_path: Path | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"
        self._loaded: LoadedLocalModel | None = None
        self._asr = LocalASRRuntime()
        self._probe_result: dict[str, Any] = {}

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def start(self, model_id: str, *, preflight: bool = False) -> str:
        record = _model_record(model_id)
        if not record or not (record.get("ready") or record.get("model_files_present")):
            raise ValueError("本地模型权重尚未完整下载，暂时不能启动。")
        if str(record.get("format")) != "transformers":
            raise ValueError("该模型是 GGUF 格式，请通过 llama.cpp 或 LM Studio 运行。")
        if str(record.get("kind", "")) == "audio" and record.get("runtime_compatible") is False:
            raise ValueError(str(record.get("runtime_message", "当前语音模型格式不受支持。")))
        self._model_id = str(record["id"])
        self._model_path = Path(str(record["path"])).resolve()
        if preflight:
            probe = run_model_preflight(record)
            loaded = probe.pop("loaded_model")
            self._loaded = loaded
            self._tokenizer = loaded.tokenizer
            self._model = loaded.model
            self._torch = loaded.torch
            self._device = loaded.input_device
            self._probe_result = probe
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler())
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="scansci-local-runtime")
        self._thread.start()
        return self.base_url

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"ScanSciLocalRuntime/{COMPONENT_VERSION}"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") == "/health":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "status": "ok",
                            "component": "local-transformers",
                            "process_role": "model-worker",
                            "version": COMPONENT_VERSION,
                            "model": runtime._model_id,
                            "probe": dict(runtime._probe_result),
                            "runtime_versions": _runtime_versions(),
                            **local_runtime_status(runtime._loaded),
                        },
                    )
                    return
                if self.path.rstrip("/") == "/v1/models":
                    self._json(HTTPStatus.OK, {"object": "list", "data": [{"id": runtime._model_id, "object": "model"}]})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

            def do_POST(self) -> None:  # noqa: N802
                endpoint = self.path.rstrip("/")
                if endpoint not in {"/v1/chat/completions", "/v1/audio/transcriptions"}:
                    self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
                    return
                cancel_event = threading.Event()
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if endpoint == "/v1/audio/transcriptions":
                        if str(payload.get("model", "")) != runtime._model_id:
                            raise ValueError("selected local speech model is no longer available")
                        text = runtime.transcribe_audio(
                            str(payload.get("audio_path", "")),
                            language=str(payload.get("language", "") or ""),
                        )
                        self._json(
                            HTTPStatus.OK,
                            {
                                "text": text,
                                "model": runtime._model_id,
                                "object": "audio.transcription",
                            },
                        )
                        return
                    messages = payload.get("messages")
                    if not isinstance(messages, list) or not messages:
                        raise ValueError("messages is required")
                    if str(payload.get("model", "")) != runtime._model_id:
                        raise ValueError("selected local model is no longer available")
                    max_new_tokens = max(1, min(int(payload.get("max_tokens", 1024) or 1024), 2048))
                    if bool(payload.get("stream")):
                        runtime.prepare()
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        for part in runtime.generate_stream(messages, max_new_tokens=max_new_tokens, cancel_event=cancel_event):
                            event = {"choices": [{"delta": {"content": part}, "index": 0, "finish_reason": None}]}
                            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        final = {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}]}
                        self.wfile.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode("utf-8"))
                        self.wfile.flush()
                        return
                    text = "".join(runtime.generate_stream(messages, max_new_tokens=max_new_tokens, cancel_event=cancel_event))
                    self._json(HTTPStatus.OK, {"id": f"local-{int(time.time())}", "object": "chat.completion", "model": runtime._model_id, "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})
                except (ValueError, RuntimeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})
                except (BrokenPipeError, ConnectionResetError):
                    cancel_event.set()
                    return
                except Exception as exc:  # pragma: no cover - backend-specific failure
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": f"Local model failed: {exc}"}})

        return Handler

    def _load_model(self) -> None:
        if self._loaded is not None:
            return
        if self._model_path is None or not self._model_id:
            raise RuntimeError("No local model has been selected")
        try:
            self._loaded = load_local_chat_model(self._model_path, self._model_id)
            self._tokenizer = self._loaded.tokenizer
            self._model = self._loaded.model
            self._torch = self._loaded.torch
            self._device = self._loaded.input_device
        except Exception as exc:
            self._loaded = None
            self._model = None
            self._tokenizer = None
            gc.collect()
            raise RuntimeError(f"无法加载 {self._model_id}：{exc}") from exc

    def prepare(self) -> None:
        with self._lock:
            self._load_model()

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        max_new_tokens: int = 1024,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        with self._lock:
            self._load_model()
            loaded = self._loaded
            if loaded is None:
                raise RuntimeError("Local model did not initialize")
            yield from generate_local_chat_stream(
                loaded,
                messages,
                max_new_tokens=max_new_tokens,
                cancel_event=cancel_event,
            )

    def transcribe_audio(self, audio_path: str, *, language: str = "") -> str:
        """Transcribe one file through the same isolated ASR runtime."""

        if not str(audio_path or "").strip():
            raise ValueError("audio_path is required")
        with self._lock:
            return self._asr.transcribe(self._model_id, audio_path, language=language)

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


def _parent_is_alive(parent_pid: int) -> bool:
    if parent_pid <= 0:
        return True
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, parent_pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(parent_pid, 0)
    except OSError:
        return False
    return True


def _write_diagnostics(output: Path) -> int:
    required = ("torch", "transformers", "sentence_transformers", "safetensors", "sentencepiece")
    optional = ("bitsandbytes",)
    modules: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in (*required, *optional):
        try:
            module = importlib.import_module(name)
            modules[name] = {
                "available": True,
                "version": str(getattr(module, "__version__", "")),
                "required": name in required,
            }
        except Exception as exc:
            modules[name] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "required": name in required,
            }
            if name in required:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
    torch_module = sys.modules.get("torch")
    payload: dict[str, Any] = {
        "ok": not errors,
        "component": "local-transformers",
        "version": COMPONENT_VERSION,
        "python": sys.version.split()[0],
        "modules": modules,
        "cuda_available": bool(
            torch_module is not None
            and getattr(torch_module, "cuda", None) is not None
            and torch_module.cuda.is_available()
        ),
    }
    if errors:
        payload["error"] = "; ".join(errors)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return 0 if payload["ok"] else 1


def _write_worker_failure(output: Path | None, *, model_id: str, error: Exception) -> None:
    if output is None:
        return
    payload = {
        "ok": False,
        "error": {
            "type": "local_runtime_error",
            "code": "model_probe_failed",
            "message": f"模型 {model_id} 的隔离加载或最小生成失败：{error}",
            "model": model_id,
            "phase": "load_or_generate",
            "native_crash": False,
            "retryable": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ScanSci local Transformers component.")
    parser.add_argument("--model-id")
    parser.add_argument("--worker-model-id")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--worker-status-file", type=Path)
    parser.add_argument("--diagnose-output", type=Path)
    args = parser.parse_args(argv)
    if args.diagnose_output is not None:
        return _write_diagnostics(args.diagnose_output)
    if not (args.model_id or args.worker_model_id) or args.port is None:
        parser.error("--model-id (daemon) or --worker-model-id (worker), plus --port, are required")
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The local runtime may only bind to loopback.")
    if args.worker_model_id:
        os.environ.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "SCANSCI_LOCAL_MODEL_WORKER": "1",
            }
        )
        runtime: Any = LocalRuntimeServer(host=args.host, port=args.port)
        try:
            runtime.start(
                args.worker_model_id,
                preflight=_requires_generation_probe(args.worker_model_id),
            )
        except Exception as error:
            _write_worker_failure(args.worker_status_file, model_id=args.worker_model_id, error=error)
            return 20
    else:
        from .local_runtime_compatibility import default_compatibility_path

        state_dir = (args.state_dir or default_compatibility_path().parent).expanduser().resolve()
        runtime = create_runtime_daemon(
            model_id=args.model_id,
            host=args.host,
            port=args.port,
            state_dir=state_dir,
        )
        runtime.start()
    if args.parent_pid:
        def monitor() -> None:
            while _parent_is_alive(args.parent_pid):
                time.sleep(2)
            runtime.shutdown()

        threading.Thread(target=monitor, daemon=True, name="scansci-parent-monitor").start()
    try:
        runtime.wait()
    except KeyboardInterrupt:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
