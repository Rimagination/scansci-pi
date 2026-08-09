"""Lazy local speech recognition for downloaded Transformers snapshots.

ScanSci uses the official ``Qwen/Qwen3-ASR-0.6B-hf`` checkpoint.  It is the
native Transformers format and therefore matches the same runtime used by
local Hugging Face chat models.  The older ``Qwen/Qwen3-ASR-0.6B`` snapshot is
kept discoverable, but is intentionally rejected with a migration message:
that checkpoint belongs to the separate ``qwen-asr`` environment and must not
be loaded with the current Transformers 5.x process.

When the lightweight desktop core has no in-process Transformers packages,
the same code calls the installed ScanSci local-runtime sidecar over loopback.
This keeps model weights local while making the optional runtime component
actually usable for audio as well as chat.
"""

from __future__ import annotations

from dataclasses import dataclass
import gc
import importlib
from importlib.util import find_spec
from pathlib import Path
import json
import threading
from typing import Any
from urllib import error as url_error
from urllib import request

from .local_model_market import (
    QWEN3_ASR_LEGACY_MODEL_ID,
    QWEN3_ASR_NATIVE_MODEL_ID,
    installed_models,
)
from .local_runtime_component import default_local_runtime_component
from .local_transformers_compat import configure_text_only_transformers


@dataclass
class _LoadedASR:
    processor: Any
    model: Any
    torch: Any
    device: str
    dtype: Any | None = None


class LocalASRRuntime:
    """Own one lazily loaded local speech model per desktop process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model_id = ""
        self._model_path: Path | None = None
        self._loaded: _LoadedASR | None = None

    def transcribe(self, model_id: str, audio_path: str | Path, *, language: str = "") -> str:
        path = Path(audio_path).resolve()
        if not path.is_file():
            raise FileNotFoundError("待识别的音频文件不存在")
        wanted, record = self._validated_record(model_id)
        if not _in_process_dependencies_available():
            return _transcribe_with_component(wanted, path, language=language)
        with self._lock:
            self._ensure_model(wanted, record)
            loaded = self._loaded
            if loaded is None:
                raise RuntimeError("本地语音模型没有完成初始化")
            try:
                request_inputs = loaded.processor.apply_transcription_request(
                    audio=str(path),
                    language=str(language or "").strip() or None,
                )
                inputs = _move_inputs(request_inputs, loaded.device, floating_dtype=loaded.dtype)
                with loaded.torch.inference_mode():
                    output_ids = loaded.model.generate(**inputs, max_new_tokens=256)
                if hasattr(output_ids, "sequences"):
                    output_ids = output_ids.sequences
                input_ids = inputs.get("input_ids") if hasattr(inputs, "get") else None
                if input_ids is not None and getattr(output_ids, "ndim", 0) == 2:
                    output_ids = output_ids[:, input_ids.shape[1] :]
                decoded = loaded.processor.decode(
                    output_ids,
                    return_format="transcription_only",
                )
                if isinstance(decoded, (list, tuple)):
                    decoded = decoded[0] if decoded else ""
                text = str(decoded or "").strip()
                if not text:
                    raise RuntimeError("语音模型没有返回转写内容")
                return text
            except (FileNotFoundError, RuntimeError):
                raise
            except Exception as exc:
                raise RuntimeError(f"本地语音识别失败：{exc}") from exc

    def _validated_record(self, model_id: str) -> tuple[str, dict[str, Any]]:
        wanted = str(model_id or "").strip()
        record = next((item for item in installed_models() if str(item.get("id", "")) == wanted), None)
        if not record or not record.get("ready"):
            raise RuntimeError("本地语音模型尚未完整下载，请在设置 → 本地模型中下载 Qwen3 ASR")
        if str(record.get("format", "")) != "transformers":
            raise RuntimeError("当前语音模型不是 Transformers 格式，无法由 ScanSci 直接运行")
        compatible = record.get("runtime_compatible")
        if compatible is None:
            # Discovery records from older ScanSci versions did not include
            # compatibility metadata.  The exact legacy ID is unambiguous;
            # unknown audio checkpoints are not silently treated as Qwen.
            compatible = wanted != QWEN3_ASR_LEGACY_MODEL_ID
        if not compatible:
            message = str(record.get("runtime_message", "")).strip()
            if wanted == QWEN3_ASR_LEGACY_MODEL_ID or not message:
                message = (
                    "当前 Qwen3-ASR-0.6B 是旧版 qwen-asr 格式，不能直接放进 ScanSci 的 "
                    "Transformers 5.x 运行时；请在模型市场下载 Qwen3-ASR-0.6B-hf。"
                )
            raise RuntimeError(message)
        return wanted, record

    def _ensure_model(self, model_id: str, record: dict[str, Any]) -> None:
        model_path = Path(str(record.get("path", ""))).resolve()
        if self._loaded is not None and self._model_id == model_id and self._model_path == model_path:
            return
        self._loaded = None
        self._model_id = ""
        self._model_path = None
        gc.collect()
        configure_text_only_transformers()
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
            AutoProcessor = getattr(transformers, "AutoProcessor")
            AutoModelForMultimodalLM = getattr(transformers, "AutoModelForMultimodalLM")
        except (ImportError, AttributeError) as exc:
            raise RuntimeError("本地 AI 运行组件未安装或版本过旧，请先在设置 → 本地模型中安装") from exc

        kwargs: dict[str, Any] = {
            "local_files_only": True,
            "low_cpu_mem_usage": True,
        }
        cuda_available = bool(
            getattr(torch, "cuda", None) is not None
            and torch.cuda.is_available()
        )
        if cuda_available:
            supports_bf16 = bool(getattr(torch.cuda, "is_bf16_supported", lambda: False)())
            kwargs["dtype"] = torch.bfloat16 if supports_bf16 else torch.float16
        try:
            processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
            model = AutoModelForMultimodalLM.from_pretrained(str(model_path), **kwargs)
            if cuda_available:
                model.to("cuda:0")
            else:
                model.to("cpu")
            model.eval()
            device = str(next(model.parameters()).device)
        except Exception as exc:
            self._loaded = None
            gc.collect()
            if cuda_available and "out of memory" in str(exc).lower():
                raise RuntimeError("本地语音模型加载失败：显存不足，请关闭其他 GPU 程序后重试") from exc
            raise RuntimeError(f"无法加载本地语音模型 {model_id}：{exc}") from exc
        model_dtype = getattr(next(model.parameters()), "dtype", None)
        self._loaded = _LoadedASR(
            processor=processor,
            model=model,
            torch=torch,
            device=device,
            dtype=model_dtype,
        )
        self._model_id = model_id
        self._model_path = model_path


def _move_inputs(value: Any, device: str, *, floating_dtype: Any | None = None) -> Any:
    """Move a Transformers ``BatchFeature`` or test double to a device."""

    if isinstance(value, dict):
        return {
            key: _move_inputs(item, device, floating_dtype=floating_dtype)
            for key, item in value.items()
        }
    if hasattr(value, "items") and not hasattr(value, "dtype"):
        try:
            return {
                key: _move_inputs(item, device, floating_dtype=floating_dtype)
                for key, item in value.items()
            }
        except TypeError:
            pass
    if hasattr(value, "to"):
        try:
            moved = value.to(device)
        except TypeError:
            moved = value.to(device=device)
        is_floating = getattr(moved, "is_floating_point", None)
        if floating_dtype is not None and callable(is_floating) and bool(is_floating()):
            try:
                moved = moved.to(dtype=floating_dtype)
            except TypeError:
                moved = moved.to(floating_dtype)
        return moved
    if isinstance(value, list):
        return [_move_inputs(item, device, floating_dtype=floating_dtype) for item in value]
    if isinstance(value, tuple):
        return tuple(_move_inputs(item, device, floating_dtype=floating_dtype) for item in value)
    return value


def _in_process_dependencies_available() -> bool:
    """Check only import metadata so the core package stays lightweight."""

    try:
        return find_spec("torch") is not None and find_spec("transformers") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _transcribe_with_component(model_id: str, audio_path: Path, *, language: str = "") -> str:
    """Use the versioned ScanSci runtime when the core has no ML libraries."""

    base_url = default_local_runtime_component().ensure_process(model_id)
    payload = {
        "model": model_id,
        "audio_path": str(audio_path),
        "language": str(language or "").strip(),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/audio/transcriptions",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=600) as response:  # noqa: S310 - loopback component only
            raw = response.read(2_000_001)
    except url_error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(64_000).decode("utf-8"))
            message = str(dict(detail.get("error", {})).get("message", "")) if isinstance(detail, dict) else ""
        except (OSError, ValueError, json.JSONDecodeError):
            message = ""
        raise RuntimeError(message or f"本地语音组件返回 HTTP {exc.code}") from exc
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(f"本地语音运行组件未响应：{exc}") from exc
    if len(raw) > 2_000_000:
        raise RuntimeError("本地语音组件返回数据过大")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("本地语音组件返回了无效结果") from exc
    text = str(result.get("text", "")).strip() if isinstance(result, dict) else ""
    if not text:
        raise RuntimeError("语音模型没有返回转写内容")
    return text


_RUNTIME = LocalASRRuntime()


def transcribe_local_audio(
    model_id: str,
    audio_path: str | Path,
    *,
    language: str = "",
) -> str:
    """Transcribe one local audio file with the selected downloaded model."""

    return _RUNTIME.transcribe(model_id, audio_path, language=language)
