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
from pathlib import Path
import threading
import time
from typing import Any, Iterator

from .local_model_market import installed_models


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
                if self.path.rstrip("/") == "/v1/models":
                    self._json(HTTPStatus.OK, {"object": "list", "data": [{"id": runtime._model_id, "object": "model"}]})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    messages = payload.get("messages")
                    if not isinstance(messages, list) or not messages:
                        raise ValueError("messages is required")
                    if str(payload.get("model", "")) != runtime._model_id:
                        raise ValueError("selected local model is no longer available")
                    stream = bool(payload.get("stream"))
                    if stream:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        for part in runtime.generate_stream(messages):
                            event = {"choices": [{"delta": {"content": part}, "index": 0, "finish_reason": None}]}
                            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        final = {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}]}
                        self.wfile.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode("utf-8"))
                        self.wfile.flush()
                        return
                    text = "".join(runtime.generate_stream(messages))
                    self._json(HTTPStatus.OK, {"id": f"local-{int(time.time())}", "object": "chat.completion", "model": runtime._model_id, "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})
                except (ValueError, RuntimeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})
                except BrokenPipeError:  # pragma: no cover - user cancelled browser request
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
        if self._model is not None:
            return
        if self._model_path is None or not self._model_id:
            raise RuntimeError("No local model has been selected")
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("本地 Transformers 运行时未安装；请使用包含本地模型组件的 ScanSci 版本。") from exc

        self._torch = torch
        self._device = "cuda" if bool(torch.cuda.is_available()) else "cpu"
        model_path = str(self._model_path)
        # A 4B BF16 model does not fit on many 8 GB laptop GPUs.  CPU is slower
        # but deterministic and avoids an opaque CUDA out-of-memory failure.
        kwargs: dict[str, Any] = {"local_files_only": True, "low_cpu_mem_usage": True}
        if self._device == "cuda":
            kwargs["torch_dtype"] = torch.bfloat16
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            self._model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
            self._model.to(self._device)
            self._model.eval()
            self._loaded_model_id = self._model_id
        except Exception as exc:
            self._model = None
            self._tokenizer = None
            self._loaded_model_id = ""
            gc.collect()
            raise RuntimeError(f"无法加载 {self._model_id}：{exc}") from exc

    def generate_stream(self, messages: list[dict[str, Any]]) -> Iterator[str]:
        """Generate incremental text; first use may spend time loading weights."""

        with self._lock:
            self._load_model()
            tokenizer = self._tokenizer
            model = self._model
            torch = self._torch
            device = self._device
            if tokenizer is None or model is None or torch is None:
                raise RuntimeError("Local model did not initialize")
            normalized = []
            for item in messages[-16:]:
                role = str(item.get("role", "user"))
                content = item.get("content", "")
                if isinstance(content, list):
                    content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
                normalized.append({"role": role, "content": str(content)})
            try:
                prompt = tokenizer.apply_chat_template(normalized, tokenize=False, add_generation_prompt=True)
            except Exception:
                prompt = "\n".join(f"{item['role']}: {item['content']}" for item in normalized) + "\nassistant:"
            inputs = tokenizer(prompt, return_tensors="pt")
            inputs = {key: value.to(device) for key, value in inputs.items()}
            try:
                from transformers import TextIteratorStreamer

                streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
                worker = threading.Thread(target=model.generate, kwargs={**inputs, "max_new_tokens": 1024, "do_sample": True, "temperature": 0.6, "top_p": 0.9, "streamer": streamer}, daemon=True)
                worker.start()
                for text in streamer:
                    if text:
                        yield str(text)
                worker.join(timeout=1)
            except Exception as exc:
                raise RuntimeError(f"本地模型生成失败：{exc}") from exc


_RUNTIME = LocalTransformersRuntime()


def ensure_local_transformers_runtime(model_id: str) -> str:
    """Return a ready loopback OpenAI-compatible base URL for an installed model."""

    return _RUNTIME.ensure(model_id)
