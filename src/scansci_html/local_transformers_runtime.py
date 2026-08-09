"""A small local OpenAI-compatible server for Hugging Face chat snapshots.

The desktop app deliberately keeps model discovery separate from inference.  A
model from ``F:\\AI\\Models`` only reaches this runtime after its snapshot has
been verified as complete and selected from ScanSci's model picker.
"""

from __future__ import annotations

import gc
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from importlib.util import find_spec
from pathlib import Path
import threading
import time
from typing import Any, Iterator

from .local_model_market import installed_models
from .local_runtime_component import default_local_runtime_component
from .local_model_inference import (
    LoadedLocalModel,
    generate_local_chat_stream,
    load_local_chat_model,
    local_runtime_status,
)


_HOST = "127.0.0.1"
_PORT = 17863


class LocalTransformersRuntime:
    """Host one selected HF chat model behind a loopback-only API."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._model_id = ""
        self._loaded_model_id = ""
        self._model_path: Path | None = None
        self._tokenizer: Any | None = None
        self._processor: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"
        self._loaded: LoadedLocalModel | None = None

    @property
    def base_url(self) -> str:
        return f"http://{_HOST}:{_PORT}/v1"

    def ensure(self, model_id: str) -> str:
        """Start the loopback server and register the requested local snapshot."""

        record = next((item for item in installed_models() if item.get("id") == model_id), None)
        if not record or not record.get("ready"):
            raise ValueError("本地模型权重尚未完整下载，暂时不能启动。")
        if str(record.get("format")) != "transformers":
            raise ValueError("该模型是 GGUF 格式，请通过 llama.cpp 或 LM Studio 运行。")
        with self._lock:
            if self._model is not None and self._loaded_model_id != str(record["id"]):
                self._model = None
                self._tokenizer = None
                self._processor = None
                self._loaded_model_id = ""
                self._loaded = None
                gc.collect()
            self._model_id = str(record["id"])
            self._model_path = Path(str(record["path"])).resolve()
            if self._server is None:
                self._start_server()
        return self.base_url

    def _start_server(self) -> None:
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ScanSciLocalModel/1.0"

            def log_message(self, _format: str, *_args: object) -> None:  # pragma: no cover - avoid noisy desktop logs
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
                    self._json(HTTPStatus.OK, {"status": "ok", "model": runtime._model_id, **local_runtime_status(runtime._loaded)})
                    return
                if self.path.rstrip("/") == "/v1/models":
                    self._json(HTTPStatus.OK, {"object": "list", "data": [{"id": runtime._model_id, "object": "model"}]})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
                    return
                cancel_event = threading.Event()
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    messages = payload.get("messages")
                    if not isinstance(messages, list) or not messages:
                        raise ValueError("messages is required")
                    if str(payload.get("model", "")) != runtime._model_id:
                        raise ValueError("selected local model is no longer available")
                    stream = bool(payload.get("stream"))
                    max_new_tokens = max(1, min(int(payload.get("max_tokens", 1024) or 1024), 2048))
                    if stream:
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
                except (BrokenPipeError, ConnectionResetError):  # pragma: no cover - user cancelled browser request
                    cancel_event.set()
                    return
                except Exception as exc:  # pragma: no cover - backend dependencies vary by desktop
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": f"Local model failed: {exc}"}})

        try:
            self._server = ThreadingHTTPServer((_HOST, _PORT), Handler)
        except OSError as exc:
            raise RuntimeError("本地模型端口 17863 被其他程序占用，请关闭占用程序后重试。") from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="scansci-local-transformers")
        self._thread.start()

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
            self._loaded_model_id = self._model_id
        except Exception as exc:
            self._loaded = None
            self._model = None
            self._tokenizer = None
            self._loaded_model_id = ""
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
        """Generate incremental text; first use may spend time loading weights."""

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


_RUNTIME = LocalTransformersRuntime()


def ensure_local_transformers_runtime(model_id: str) -> str:
    """Return a ready loopback OpenAI-compatible base URL for an installed model."""

    # Prefer the independently versioned component whenever it is installed,
    # including in a source checkout.  Importing PyTorch in the desktop web
    # process makes a native inference crash fatal to the entire application;
    # the component keeps that failure behind a loopback process boundary and
    # is also the runtime users expect to be reused across app upgrades.
    component = default_local_runtime_component()
    if component.executable() is not None:
        return component.ensure_process(model_id)

    # Full/source developer environments may intentionally run without the
    # optional component. Keep the in-process implementation as a development
    # fallback only; lightweight core releases still require the component.
    try:
        has_in_process_runtime = find_spec("torch") is not None and find_spec("transformers") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        has_in_process_runtime = False
    if not has_in_process_runtime:
        return default_local_runtime_component().ensure_process(model_id)
    return _RUNTIME.ensure(model_id)
