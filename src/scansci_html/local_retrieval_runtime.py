"""Shared device and model-placement helpers for local retrieval models."""

from __future__ import annotations

import importlib
import os
import re
import threading
from typing import Any


_CUDA_DEVICE_RE = re.compile(r"^cuda(?::\d+)?$")
_RETRIEVAL_INFERENCE_LOCK = threading.RLock()


def retrieval_inference_lock() -> threading.RLock:
    """Serialize short local-model batches across background and chat threads."""

    return _RETRIEVAL_INFERENCE_LOCK


def resolve_retrieval_device(device_preference: str | None = None) -> str:
    """Resolve the device used by local embedding and reranking models.

    ``SCANSCI_RETRIEVAL_DEVICE`` is intentionally separate from the chat-model
    setting so a small retrieval model can use CUDA without changing the
    generation runtime.  ``auto`` selects the first CUDA device when PyTorch
    exposes one and otherwise falls back to CPU.
    """

    requested = (
        device_preference
        or os.getenv("SCANSCI_RETRIEVAL_DEVICE", "")
        or os.getenv("SCANSCI_LOCAL_MODEL_DEVICE", "auto")
    ).strip().lower()
    if requested == "cuda":
        requested = "cuda:0"
    if requested not in {"auto", "cpu"} and not _CUDA_DEVICE_RE.fullmatch(requested):
        raise RuntimeError("SCANSCI_RETRIEVAL_DEVICE 只能是 auto、cpu 或 cuda[:index]。")
    if requested == "cpu":
        return "cpu"

    try:
        torch = importlib.import_module("torch")
    except ImportError:
        if requested != "auto":
            raise RuntimeError("已要求使用 GPU，但当前环境没有安装 PyTorch。")
        return "cpu"

    cuda_available = bool(torch.cuda.is_available())
    if requested != "auto":
        if not cuda_available:
            raise RuntimeError(
                f"已要求使用 GPU，但当前 PyTorch {getattr(torch, '__version__', 'unknown')} 无法使用 CUDA。"
            )
        index = int(requested.split(":", 1)[1])
        if index >= int(torch.cuda.device_count()):
            raise RuntimeError(f"请求的 CUDA 设备不存在：{requested}。")
        return requested
    return "cuda:0" if cuda_available else "cpu"


def model_device(model: Any) -> str:
    """Return a model's effective device without assuming a specific library."""

    direct = getattr(model, "device", None)
    if direct is not None:
        return str(direct)
    parameters = getattr(model, "parameters", None)
    if callable(parameters):
        try:
            return str(next(parameters()).device)
        except (StopIteration, TypeError, AttributeError):
            pass
    return ""


def move_model_to_device(model: Any, device: str) -> Any:
    """Move a Transformers/Sentence-Transformers model when it supports ``to``."""

    mover = getattr(model, "to", None)
    if callable(mover):
        moved = mover(device)
        return model if moved is None else moved
    return model
