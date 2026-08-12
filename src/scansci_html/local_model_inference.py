"""Shared GPU-aware loading and streaming helpers for local chat models."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, replace
import io
import importlib
import json
import os
from pathlib import Path
from queue import Empty
import sys
import threading
from typing import Any, Iterator

from .local_transformers_compat import configure_text_only_transformers


@dataclass(frozen=True)
class LocalModelPlan:
    """Resolved execution plan for one local Transformers model."""

    device: str
    quantization: str
    compute_dtype: str
    cuda_available: bool
    cuda_runtime: str
    gpu_name: str
    total_vram_gib: float
    model_weight_gib: float


@dataclass
class LoadedLocalModel:
    tokenizer: Any
    model: Any
    torch: Any
    plan: LocalModelPlan
    input_device: str
    processor: Any | None = None
    is_vision: bool = False


def choose_local_model_plan(
    torch_module: Any,
    *,
    device_preference: str | None = None,
    quantization_preference: str | None = None,
    model_weight_gib: float | None = None,
) -> LocalModelPlan:
    """Choose CUDA/CPU and precision without silently ignoring explicit GPU use."""

    requested_device = (
        device_preference or os.getenv("SCANSCI_LOCAL_MODEL_DEVICE", "auto")
    ).strip().lower()
    requested_quantization = (
        quantization_preference or os.getenv("SCANSCI_LOCAL_MODEL_QUANTIZATION", "auto")
    ).strip().lower()
    if requested_device not in {"auto", "cpu", "cuda"}:
        raise RuntimeError("SCANSCI_LOCAL_MODEL_DEVICE 只能是 auto、cpu 或 cuda。")
    if requested_quantization not in {"auto", "4bit", "none"}:
        raise RuntimeError("SCANSCI_LOCAL_MODEL_QUANTIZATION 只能是 auto、4bit 或 none。")

    cuda_available = bool(torch_module.cuda.is_available())
    cuda_runtime = str(getattr(getattr(torch_module, "version", None), "cuda", "") or "")
    if requested_device == "cuda" and not cuda_available:
        build = str(getattr(torch_module, "__version__", "unknown"))
        raise RuntimeError(
            f"已要求使用 GPU，但当前 PyTorch {build} 无法使用 CUDA。"
            "请安装 CUDA 版 PyTorch，并确认 NVIDIA 驱动可用。"
        )

    use_cuda = cuda_available and requested_device != "cpu"
    if not use_cuda:
        if requested_quantization == "4bit":
            raise RuntimeError("4-bit 本地推理需要 NVIDIA CUDA GPU。")
        return LocalModelPlan(
            device="cpu",
            quantization="none",
            compute_dtype="float32",
            cuda_available=cuda_available,
            cuda_runtime=cuda_runtime,
            gpu_name="",
            total_vram_gib=0.0,
            model_weight_gib=round(float(model_weight_gib or 0.0), 2),
        )

    properties = torch_module.cuda.get_device_properties(0)
    total_vram_gib = round(float(properties.total_memory) / (1024**3), 2)
    gpu_name = str(getattr(properties, "name", "") or torch_module.cuda.get_device_name(0))
    # A vision model needs memory for the processor, image tokens, CUDA
    # kernels and generation KV cache in addition to its weight files.  On an
    # 8 GB card, loading a 4.2 GB checkpoint in fp16 is therefore not a safe
    # default even though the raw file appears to fit.  Keep roughly half of
    # VRAM available for those runtime allocations; larger cards still use
    # native precision for genuinely small models.
    native_budget_gib = max(1.0, total_vram_gib * 0.5)
    use_4bit = requested_quantization == "4bit" or (
        requested_quantization == "auto"
        and (
            model_weight_gib is None
            or float(model_weight_gib) > native_budget_gib
        )
    )
    bf16_supported = bool(getattr(torch_module.cuda, "is_bf16_supported", lambda: False)())
    return LocalModelPlan(
        device="cuda:0",
        quantization="4bit" if use_4bit else "none",
        compute_dtype="bfloat16" if bf16_supported else "float16",
        cuda_available=True,
        cuda_runtime=cuda_runtime,
        gpu_name=gpu_name,
        total_vram_gib=total_vram_gib,
        model_weight_gib=round(float(model_weight_gib or 0.0), 2),
    )


def _vision_snapshot_config(model_path: str | Path) -> dict[str, Any]:
    path = Path(model_path).resolve() / "config.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_vision_snapshot(model_path: str | Path) -> bool:
    config = _vision_snapshot_config(model_path)
    model_type = str(config.get("model_type", "")).casefold()
    architectures = " ".join(str(value) for value in config.get("architectures", []) or []).casefold()
    return bool(
        isinstance(config.get("vision_config"), dict)
        or "minicpmv" in model_type
        or "minicpmv" in architectures
        or "qwen3_vl" in model_type
    )


def _load_local_vision_model(model_path: str | Path, model_id: str) -> LoadedLocalModel:
    """Load a local multimodal Transformers snapshot without text-only patches."""

    resolved_path = Path(model_path).resolve()
    config = _vision_snapshot_config(resolved_path)
    quantization_config = config.get("quantization_config") if isinstance(config.get("quantization_config"), dict) else {}
    quantization_method = str(quantization_config.get("quant_method", "")).casefold()
    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        AutoProcessor = getattr(transformers, "AutoProcessor")
        AutoModelForImageTextToText = getattr(transformers, "AutoModelForImageTextToText", None)
        if AutoModelForImageTextToText is None:
            AutoModelForImageTextToText = getattr(transformers, "AutoModelForVision2Seq")
    except (ImportError, AttributeError) as exc:  # pragma: no cover - optional runtime
        raise RuntimeError("视觉模型需要完整的 Transformers 与图像处理运行组件。") from exc

    weight_bytes = sum(
        item.stat().st_size
        for item in resolved_path.iterdir()
        if item.is_file() and item.suffix.lower() in {".safetensors", ".bin", ".gguf"}
    )
    plan = choose_local_model_plan(torch, model_weight_gib=float(weight_bytes) / (1024**3))
    if quantization_method == "bitsandbytes":
        if not plan.device.startswith("cuda"):
            raise RuntimeError(f"{model_id} 是 BNB 4-bit 视觉模型，需要 NVIDIA CUDA 显卡。")
        try:
            importlib.import_module("bitsandbytes")
        except ImportError as exc:
            raise RuntimeError("视觉模型需要 bitsandbytes，但本地运行组件未安装。") from exc
        plan = replace(plan, quantization="4bit")
    elif quantization_method == "gptq":
        plan = replace(plan, quantization="gptq")

    kwargs: dict[str, Any] = {"local_files_only": True, "low_cpu_mem_usage": True}
    if plan.device.startswith("cuda"):
        kwargs["device_map"] = "auto"
        # Quantized checkpoints carry their own quantization config.  Passing
        # dtype=auto preserves BNB/GPTQ storage choices and is supported by
        # Transformers 5.x.
        if quantization_method:
            kwargs["dtype"] = "auto"
        elif plan.quantization == "4bit":
            try:
                quantization = importlib.import_module("transformers.utils.quantization_config")
                BitsAndBytesConfig = getattr(quantization, "BitsAndBytesConfig")
                importlib.import_module("bitsandbytes")
            except (ImportError, AttributeError) as exc:
                raise RuntimeError(
                    "检测到显存有限的 NVIDIA GPU，但 4-bit CUDA 组件 bitsandbytes 未安装；"
                    "请在本地运行组件中安装 GPU 依赖，或改用云端视觉模型。"
                ) from exc
            compute_dtype = torch.bfloat16 if plan.compute_dtype == "bfloat16" else torch.float16
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=compute_dtype,
            )
        else:
            kwargs["dtype"] = torch.bfloat16 if plan.compute_dtype == "bfloat16" else torch.float16

    try:
        processor = AutoProcessor.from_pretrained(str(resolved_path), local_files_only=True)
        model = AutoModelForImageTextToText.from_pretrained(str(resolved_path), **kwargs)
        if plan.device == "cpu":
            model.to("cpu")
        model.eval()
        tokenizer = getattr(processor, "tokenizer", None)
        input_device = str(next(model.parameters()).device)
    except Exception as exc:
        if plan.device.startswith("cuda") and "out of memory" in str(exc).lower():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            raise RuntimeError(
                f"GPU 显存不足，无法加载 {model_id}；当前显存约 {plan.total_vram_gib:.1f} GB。"
            ) from exc
        raise RuntimeError(f"无法加载视觉模型 {model_id}（设备 {plan.device}）：{exc}") from exc

    return LoadedLocalModel(
        tokenizer=tokenizer,
        model=model,
        torch=torch,
        plan=plan,
        input_device=input_device,
        processor=processor,
        is_vision=True,
    )


def load_local_chat_model(model_path: str | Path, model_id: str) -> LoadedLocalModel:
    """Load a verified local snapshot using the resolved CUDA-aware plan."""

    if _is_vision_snapshot(model_path):
        return _load_local_vision_model(model_path, model_id)

    configure_text_only_transformers()
    try:
        torch = importlib.import_module("torch")
        auto_models = importlib.import_module("transformers.models.auto.modeling_auto")
        auto_tokenizers = importlib.import_module("transformers.models.auto.tokenization_auto")
        AutoModelForCausalLM = getattr(auto_models, "AutoModelForCausalLM")
        AutoTokenizer = getattr(auto_tokenizers, "AutoTokenizer")
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError("本地 Transformers 运行时不完整，请重新安装本地 AI 组件。") from exc

    resolved_path = Path(model_path).resolve()
    weight_bytes = sum(
        item.stat().st_size
        for item in resolved_path.iterdir()
        if item.is_file() and item.suffix.lower() in {".safetensors", ".bin", ".gguf"}
    )
    weight_gib = float(weight_bytes) / (1024**3)
    plan = choose_local_model_plan(torch, model_weight_gib=weight_gib)
    path = str(resolved_path)
    kwargs: dict[str, Any] = {
        "local_files_only": True,
        "low_cpu_mem_usage": True,
    }
    if plan.device.startswith("cuda") and plan.quantization == "4bit":
        if os.name == "nt" and plan.model_weight_gib > plan.total_vram_gib:
            raise RuntimeError(
                f"{model_id} 的原始权重约 {plan.model_weight_gib:.1f} GB，超过本机 "
                f"{plan.total_vram_gib:.1f} GB 显存。Windows 下现场 4-bit 转换会触发"
                "原生内存映射崩溃；请改用 Qwen/Qwen3.5-2B，或安装已经量化好的 AWQ/GGUF 版本。"
            )
        try:
            quantization = importlib.import_module("transformers.utils.quantization_config")
            BitsAndBytesConfig = getattr(quantization, "BitsAndBytesConfig")
            importlib.import_module("bitsandbytes")  # validates native CUDA extension availability
        except ImportError as exc:
            raise RuntimeError(
                "检测到显存有限的 NVIDIA GPU，但 4-bit CUDA 组件 bitsandbytes 未安装。"
            ) from exc
        compute_dtype = torch.bfloat16 if plan.compute_dtype == "bfloat16" else torch.float16
        kwargs.update(
            {
                "device_map": {"": 0},
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=compute_dtype,
                ),
            }
        )
    elif plan.device.startswith("cuda"):
        kwargs["dtype"] = torch.bfloat16 if plan.compute_dtype == "bfloat16" else torch.float16

    try:
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(path, **kwargs)
        if plan.device.startswith("cuda") and plan.quantization != "4bit":
            model.to(plan.device)
        elif plan.device == "cpu":
            model.to("cpu")
        model.eval()
        input_device = str(next(model.parameters()).device)
    except Exception as exc:
        if plan.device.startswith("cuda") and "out of memory" in str(exc).lower():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            raise RuntimeError(
                f"GPU 显存不足，无法加载 {model_id}。当前计划：{plan.quantization}，"
                f"显存：{plan.total_vram_gib:.1f} GB。"
            ) from exc
        raise RuntimeError(
            f"无法加载 {model_id}（设备 {plan.device}，量化 {plan.quantization}）：{exc}"
        ) from exc

    return LoadedLocalModel(
        tokenizer=tokenizer,
        model=model,
        torch=torch,
        plan=plan,
        input_device=input_device,
    )


def local_runtime_status(loaded: LoadedLocalModel | None = None) -> dict[str, Any]:
    """Return actionable hardware state for health checks and diagnostics."""

    if loaded is not None:
        return {
            "loaded": True,
            **asdict(loaded.plan),
            "input_device": loaded.input_device,
        }
    if "torch" not in sys.modules:
        return {
            "loaded": False,
            "device": "pending",
            "quantization": "auto",
            "compute_dtype": "",
            "cuda_available": None,
            "cuda_runtime": "",
            "gpu_name": "",
            "total_vram_gib": 0.0,
            "model_weight_gib": 0.0,
            "input_device": "",
        }
    try:
        torch = importlib.import_module("torch")

        plan = choose_local_model_plan(torch)
        return {"loaded": False, **asdict(plan), "input_device": ""}
    except Exception as exc:
        return {
            "loaded": False,
            "device": "unavailable",
            "quantization": "none",
            "compute_dtype": "",
            "cuda_available": False,
            "cuda_runtime": "",
            "gpu_name": "",
            "total_vram_gib": 0.0,
            "model_weight_gib": 0.0,
            "input_device": "",
            "error": str(exc),
        }


def normalize_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in messages[-16:]:
        content = item.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        normalized.append({"role": str(item.get("role", "user")), "content": str(content)})
    return normalized


def _local_image_from_url(value: str) -> Any:
    """Decode a data URI into a PIL image without fetching remote URLs."""

    source = str(value or "").strip()
    if not source.startswith("data:") or "," not in source:
        raise ValueError("本地视觉模型只接受已经随请求传入的图片数据")
    _header, encoded = source.split(",", 1)
    try:
        raw = base64.b64decode(encoded, validate=True)
        image_module = importlib.import_module("PIL.Image")
        with image_module.open(io.BytesIO(raw)) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise ValueError(f"无法读取视觉输入图片：{exc}") from exc


def normalize_vision_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI image blocks into the native Transformers conversation format."""

    normalized: list[dict[str, Any]] = []
    for item in messages[-16:]:
        content = item.get("content", "")
        if not isinstance(content, list):
            normalized.append({"role": str(item.get("role", "user")), "content": str(content)})
            continue
        parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type", "")).casefold()
            if part_type == "text":
                parts.append({"type": "text", "text": str(part.get("text", ""))})
                continue
            if part_type == "image_url":
                image_url = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
                parts.append({"type": "image", "image": _local_image_from_url(str(image_url.get("url", "")))})
                continue
            if part_type == "image":
                source = part.get("image") or part.get("url")
                if hasattr(source, "convert"):
                    parts.append({"type": "image", "image": source})
                else:
                    parts.append({"type": "image", "image": _local_image_from_url(str(source or ""))})
        if not parts:
            parts = [{"type": "text", "text": ""}]
        normalized.append({"role": str(item.get("role", "user")), "content": parts})
    return normalized


def _vision_processor_kwargs() -> dict[str, Any]:
    try:
        max_slice_nums = int(os.getenv("SCANSCI_VISION_MAX_SLICE_NUMS", "1"))
    except ValueError:
        max_slice_nums = 1
    return {
        "downsample_mode": os.getenv("SCANSCI_VISION_DOWNSAMPLE", "16x").strip() or "16x",
        "max_slice_nums": max(1, min(max_slice_nums, 36)),
    }


def generate_local_chat_stream(
    loaded: LoadedLocalModel,
    messages: list[dict[str, Any]],
    *,
    max_new_tokens: int = 1024,
    cancel_event: threading.Event | None = None,
) -> Iterator[str]:
    """Stream generation and propagate worker failures instead of hanging forever."""

    stopping_criteria = importlib.import_module("transformers.generation.stopping_criteria")
    streamers = importlib.import_module("transformers.generation.streamers")
    StoppingCriteria = getattr(stopping_criteria, "StoppingCriteria")
    StoppingCriteriaList = getattr(stopping_criteria, "StoppingCriteriaList")
    TextIteratorStreamer = getattr(streamers, "TextIteratorStreamer")

    cancel = cancel_event or threading.Event()
    generation_kwargs: dict[str, Any] = {}
    streamer_tokenizer = loaded.tokenizer
    if loaded.is_vision and loaded.processor is not None:
        normalized = normalize_vision_messages(messages)
        processor_kwargs = _vision_processor_kwargs()
        inputs = loaded.processor.apply_chat_template(
            normalized,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
            processor_kwargs=processor_kwargs,
        )
        streamer_tokenizer = getattr(loaded.processor, "tokenizer", None) or loaded.tokenizer
        generation_kwargs["downsample_mode"] = processor_kwargs["downsample_mode"]
    else:
        normalized = normalize_chat_messages(messages)
        try:
            prompt = loaded.tokenizer.apply_chat_template(
                normalized,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            prompt = "\n".join(f"{item['role']}: {item['content']}" for item in normalized) + "\nassistant:"
        inputs = loaded.tokenizer(prompt, return_tensors="pt")
    inputs = {
        key: value.to(loaded.input_device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }

    class Cancelled(StoppingCriteria):
        def __call__(self, _input_ids: Any, _scores: Any, **_kwargs: Any) -> bool:
            return cancel.is_set()

    streamer = TextIteratorStreamer(
        streamer_tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
        timeout=0.25,
    )
    worker_error: list[BaseException] = []

    def run_generation() -> None:
        try:
            loaded.model.generate(
                **inputs,
                **generation_kwargs,
                max_new_tokens=max(1, min(int(max_new_tokens), 2048)),
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                streamer=streamer,
                stopping_criteria=StoppingCriteriaList([Cancelled()]),
            )
        except BaseException as exc:  # relay failures from the model worker
            worker_error.append(exc)

    worker = threading.Thread(target=run_generation, daemon=True, name="scansci-local-generation")
    worker.start()
    iterator = iter(streamer)
    while True:
        try:
            text = next(iterator)
        except Empty:
            if not worker.is_alive():
                break
            continue
        except StopIteration:
            break
        if text:
            yield str(text)
    worker.join(timeout=5)
    if worker_error:
        exc = worker_error[0]
        raise RuntimeError(f"本地模型生成失败：{exc}") from exc
