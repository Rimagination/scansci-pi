"""Vision routing and conservative OCR fallbacks.

The desktop app has two different kinds of models: the selected conversation
model and the model that can actually inspect an image.  Keeping the routing
decision here prevents the UI selection from becoming a hard failure when a
text model is selected.  The order is deliberately small and explicit:

1. honour an explicitly selected usable vision model;
2. prefer a ready local vision runtime (currently Ollama/MiniCPM-V);
3. use a configured cloud vision model;
4. if none is available, strip the image and add best-effort local OCR text.

Tesseract is the default local path because it is cross-platform and explicit.
Windows OCR remains a separate optional native provider, while the configured
remote OCR provider is handled explicitly below.
"""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from .app_settings import apply_storage_directories, get_document_service_api_key, get_provider_api_key
from .ollama_runtime import ollama_status


DEFAULT_DEEPSEEK_OCR_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_DEEPSEEK_OCR_MODEL = "deepseek-ai/DeepSeek-OCR"


def _model_record(provider: dict[str, Any], model_id: str) -> dict[str, Any]:
    wanted = str(model_id or "").strip()
    return next(
        (
            dict(item)
            for item in list(provider.get("models", []) or [])
            if isinstance(item, dict) and str(item.get("id", "")).strip() == wanted
        ),
        {},
    )


def _model_candidates(provider: dict[str, Any], *, capability: str = "") -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for item in list(provider.get("models", []) or []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id:
            continue
        capabilities = {str(value).strip().lower() for value in list(item.get("capabilities", []) or [])}
        if capability and capability not in capabilities:
            continue
        if capability == "vision" and not _is_image_understanding_model(model_id, item):
            continue
        rows.append((model_id, dict(item)))
    return rows


def _is_image_understanding_model(model_id: str, model: dict[str, Any]) -> bool:
    """Exclude image generators and visual embedding/reranking models from chat routing."""

    label = f"{model_id} {model.get('name', '')}".casefold()
    return not any(
        marker in label
        for marker in (
            "embedding",
            "reranker",
            "rerank",
            "z-image",
            "kolors",
            "wan2",
            "ernie-image",
            "text-to-image",
            "image-to-video",
            "i2v",
            "t2v",
        )
    )


def _vision_model_priority(model_id: str, model: dict[str, Any]) -> tuple[int, str]:
    """Prefer broadly available captioning/VL models over fragile legacy entries.

    Provider catalogs are user-editable and often contain image generators,
    rerankers, and retired 72B checkpoints side by side.  When more than one
    vision model is enabled, a small instruction model or OCR-VL model is a
    safer first attempt: it starts faster, costs less, and is less likely to be
    excluded by a provider account's model allow-list.  The explicit priority
    can still be overridden by selecting a model in the composer.
    """

    explicit = model.get("vision_priority")
    try:
        if explicit is not None:
            return int(explicit), str(model_id)
    except (TypeError, ValueError):
        pass
    marker = f"{model_id} {model.get('name', '')}".casefold()
    if "qwen3-vl-8b-instruct" in marker:
        return 0, str(model_id)
    if "paddleocr-vl" in marker:
        return 1, str(model_id)
    if "qwen3-vl" in marker or "qwen3-omni" in marker:
        return 2, str(model_id)
    if "qwen2.5-vl-72b" in marker:
        return 20, str(model_id)
    return 10, str(model_id)


def _provider_api_key(workspace: str | os.PathLike[str], provider: dict[str, Any]) -> str:
    if str(provider.get("auth_mode", "")).strip().lower() == "managed":
        return "scansci-managed-gateway"
    if str(provider.get("auth_mode", "")).strip().lower() == "local":
        return "local"
    try:
        return str(get_provider_api_key(workspace, str(provider.get("id", ""))) or "").strip()
    except (OSError, ValueError):
        return ""


def _provider_ready(workspace: str | os.PathLike[str], provider: dict[str, Any], model_id: str) -> bool:
    if not provider.get("enabled", True):
        return False
    if not str(provider.get("base_url", "")).strip():
        return False
    provider_id = str(provider.get("id", "")).strip()
    if provider_id == "local-huggingface":
        # A model snapshot can be present while its last isolated generation
        # probe failed (for example because the Windows page file is too
        # small).  Do not keep selecting that model on every image turn; the
        # caller will use another vision provider or the OCR fallback instead.
        try:
            from .local_model_market import installed_models

            local = next(
                (item for item in installed_models() if str(item.get("id", "")) == str(model_id)),
                None,
            )
            if isinstance(local, dict) and str(local.get("runtime_probe_state", "")) == "failed":
                return False
        except Exception:
            pass
    if str(provider.get("logo", "")).strip().lower() == "ollama" or provider_id.startswith("local-runtime-") and str(provider.get("runtime", "")).lower() == "ollama":
        status = ollama_status(str(provider.get("base_url", "")))
        if not status.get("reachable"):
            return False
        # Readiness is per-model, not tied to the single bundled vision
        # snapshot.  Honour whichever Ollama model the caller asked for.
        # Statuses that do not report an installed model list fall back to
        # the bundled snapshot's readiness flag.
        installed = {
            str(item.get("name", "")).strip()
            for item in list(status.get("models", []) or [])
        }
        wanted = str(model_id or "").strip()
        if installed and wanted and wanted not in installed and f"{wanted}:latest" not in installed:
            return False
        if not installed and not status.get("model_ready"):
            return False
    return bool(_provider_api_key(workspace, provider))


def _route(workspace: str | os.PathLike[str], provider: dict[str, Any], model_id: str, model: dict[str, Any], mode: str) -> dict[str, Any] | None:
    if not _provider_ready(workspace, provider, model_id):
        return None
    return {
        "provider": deepcopy(provider),
        "provider_id": str(provider.get("id", "")),
        "provider_name": str(provider.get("name", provider.get("id", ""))),
        "provider_kind": str(provider.get("kind", "")),
        "base_url": str(provider.get("base_url", "")),
        "api_key": _provider_api_key(workspace, provider),
        "model_id": model_id,
        "model": model,
        "mode": mode,
    }


def select_vision_route(
    workspace: str | os.PathLike[str],
    settings: dict[str, Any],
    *,
    active_provider_id: str = "",
    active_model_id: str = "",
    allow_cloud: bool = True,
    excluded_routes: set[tuple[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Choose a usable vision endpoint without making the user reselect it.

    ``allow_cloud`` gates the automatic fallback to a cloud vision provider
    that the user did not explicitly select.  Interactive chat keeps it on so
    images "just work"; evidence/research flows pass ``False`` so user images
    are never silently sent to a third-party vision API — they fall back to
    local vision or OCR instead.
    """

    # Routing can be called by the research worker without first constructing
    # the web app.  Apply the persisted runtime root here as well, otherwise a
    # failed local probe in a user-selected directory would be invisible and
    # the same broken vision model would be launched again on every turn.
    apply_storage_directories(settings)
    excluded = set(excluded_routes or set())
    providers = [item for item in list(settings.get("providers", []) or []) if isinstance(item, dict)]
    active = next((item for item in providers if str(item.get("id", "")) == str(active_provider_id)), None)
    if active is not None:
        active_model = _model_record(active, active_model_id)
        if "vision" in {str(value).lower() for value in list(active_model.get("capabilities", []) or [])}:
            selected = _route(workspace, active, str(active_model_id), active_model, "selected")
            if selected is not None and (str(active.get("id", "")), str(active_model_id)) not in excluded:
                return selected

    local_candidates = []
    cloud_candidates = []
    for provider in providers:
        models = sorted(
            _model_candidates(provider, capability="vision"),
            key=lambda item: _vision_model_priority(item[0], item[1]),
        )
        if not models:
            continue
        provider_id = str(provider.get("id", ""))
        is_local = (
            str(provider.get("auth_mode", "")).strip().lower() == "local"
            or provider_id.startswith("local-runtime-")
            or str(provider.get("category", "")).strip() == "本地模型"
        )
        (local_candidates if is_local else cloud_candidates).append((provider, models))

    # Local candidates are intentionally tried before cloud candidates.  A
    # user can still select a cloud vision model explicitly in the model menu;
    # that path was handled above as mode="selected".
    for provider, models in local_candidates:
        for model_id, model in models:
            if (str(provider.get("id", "")), model_id) in excluded:
                continue
            selected = _route(workspace, provider, model_id, model, "local")
            if selected is not None:
                return selected
    if allow_cloud:
        for provider, models in cloud_candidates:
            for model_id, model in models:
                if (str(provider.get("id", "")), model_id) in excluded:
                    continue
                selected = _route(workspace, provider, model_id, model, "cloud")
                if selected is not None:
                    return selected
    return None


def select_text_route(
    workspace: str | os.PathLike[str],
    settings: dict[str, Any],
    *,
    active_provider_id: str = "",
    active_model_id: str = "",
) -> dict[str, Any] | None:
    """Find a normal text endpoint for OCR-assisted answers."""

    apply_storage_directories(settings)
    providers = [item for item in list(settings.get("providers", []) or []) if isinstance(item, dict)]
    ordered = []
    active = next((item for item in providers if str(item.get("id", "")) == str(active_provider_id)), None)
    if active is not None:
        ordered.append((active, str(active_model_id), _model_record(active, active_model_id)))
    ordered.extend(
        (provider, model_id, model)
        for provider in providers
        if provider is not active
        for model_id, model in _model_candidates(provider)
    )
    seen: set[tuple[str, str]] = set()
    for provider, model_id, model in ordered:
        key = (str(provider.get("id", "")), model_id)
        if key in seen or not model_id or not model:
            continue
        seen.add(key)
        selected = _route(workspace, provider, model_id, model, "text-fallback")
        if selected is not None:
            return selected
    return None


def _tesseract_path() -> str:
    detected = shutil.which("tesseract")
    if detected:
        return detected
    if os.name != "nt":
        return ""
    candidates = [
        Path(os.getenv("ProgramFiles", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.getenv("ProgramFiles(x86)", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Tesseract-OCR" / "tesseract.exe",
    ]
    return next((str(path) for path in candidates if str(path) and path.is_file()), "")


def _tesseract_environment() -> dict[str, str]:
    """Prefer the per-user ScanSci language bundle without requiring admin rights."""

    environment = dict(os.environ)
    local_data = Path(os.getenv("LOCALAPPDATA", "")) / "ScanSci" / "tessdata"
    if local_data.is_dir() and any(local_data.glob("*.traineddata")):
        environment["TESSDATA_PREFIX"] = f"{local_data}{os.sep}"
    return environment


def _tesseract_language_ids(languages: list[str] | None) -> list[str]:
    aliases = {
        "zh": "chi_sim",
        "zh-cn": "chi_sim",
        "zh-hans": "chi_sim",
        "chinese": "chi_sim",
        "en": "eng",
        "en-us": "eng",
        "english": "eng",
    }
    values = [str(value).strip().lower() for value in (languages or []) if str(value).strip()]
    return list(dict.fromkeys(aliases.get(value, value) for value in values))


def _tesseract_available_languages(command: str) -> list[str]:
    result = subprocess.run(
        [command, "--list-langs"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=_tesseract_environment(),
    )
    languages: list[str] = []
    listing_started = False
    for line in (result.stdout or "").splitlines():
        value = line.strip()
        if value.lower().startswith("list of available languages"):
            listing_started = True
            continue
        if listing_started and value and value not in languages:
            languages.append(value)
    return languages


def tesseract_status(languages: list[str] | None = None) -> dict[str, Any]:
    """Return an actionable, credential-free status for the local Tesseract engine."""

    requested = [str(value).strip() for value in (languages or []) if str(value).strip()]
    result: dict[str, Any] = {
        "available": False,
        "backend": "unavailable",
        "platform": os.name,
        "languages": [],
        "requested_languages": requested,
        "missing_languages": [],
        "requested_supported": False,
        "path": "",
        "version": "",
        "message": "未检测到 Tesseract OCR",
        "solution": "Windows 可直接安装：winget install --id UB-Mannheim.TesseractOCR --exact；安装后点击重新检测。",
    }
    command = _tesseract_path()
    if not command:
        return result
    try:
        version_result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=_tesseract_environment(),
        )
        version = next((line.strip() for line in (version_result.stdout or "").splitlines() if line.strip()), "")
        available = _tesseract_available_languages(command)
    except (OSError, subprocess.SubprocessError) as exc:
        result["message"] = f"Tesseract 检测失败：{type(exc).__name__}"
        result["solution"] = "请确认 Tesseract 安装完整，或重新安装后点击重新检测。"
        result["details"] = str(exc)[:240]
        return result
    required = _tesseract_language_ids(requested)
    missing = [value for value in required if value not in {item.lower() for item in available}]
    result.update(
        {
            "available": True,
            "backend": "tesseract",
            "languages": available,
            "missing_languages": missing,
            "requested_supported": not missing,
            "path": command,
            "version": version,
            "message": (
                f"Tesseract 已安装，但缺少识别语言数据：{', '.join(missing)}。"
                if missing
                else "Tesseract 已安装，可直接进行本地 OCR。"
            ),
            "solution": (
                "中文识别需要 chi_sim.traineddata；安装对应语言数据后点击重新检测。"
                if missing
                else ""
            ),
        }
    )
    return result


def _load_windows_ocr_runtime(*, require_image: bool = False) -> dict[str, Any]:
    """Load the optional Python projection of Windows.Media.Ocr.

    ``winsdk`` is the current projection name; ``winrt`` is retained as a
    compatibility path for existing installations.  Importing it lazily is
    important because ScanSci also runs on macOS/Linux and the base install
    should not require Windows-only wheels.
    """

    if os.name != "nt":
        return {"available": False, "error": "当前平台不是 Windows"}
    failures: list[str] = []
    for package in ("winsdk", "winrt"):
        try:
            if package == "winsdk":
                from winsdk.windows.globalization import Language
                from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
                from winsdk.windows.media.ocr import OcrEngine
                from winsdk.windows.storage.streams import DataWriter
            else:
                from winrt.windows.globalization import Language
                from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
                from winrt.windows.media.ocr import OcrEngine
                from winrt.windows.storage.streams import DataWriter
            runtime: dict[str, Any] = {
                "package": package,
                "Language": Language,
                "OcrEngine": OcrEngine,
                "SoftwareBitmap": SoftwareBitmap,
                "BitmapPixelFormat": BitmapPixelFormat,
                "BitmapAlphaMode": None,
                "DataWriter": DataWriter,
            }
            if require_image:
                from PIL import Image

                runtime["Image"] = Image
            return {"available": True, **runtime}
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            failures.append(f"{package}: {type(exc).__name__}")
    return {
        "available": False,
        "error": "未安装 Windows OCR 的 Python WinRT 桥接（需要安装桌面版 OCR 依赖）",
        "details": "; ".join(failures),
    }


def _runtime_member(owner: Any, *names: str) -> Any:
    for name in names:
        member = getattr(owner, name, None)
        if member is not None:
            return member
    return None


def _runtime_static_call(owner: Any, *names: str) -> Any:
    member = _runtime_member(owner, *names)
    return member() if callable(member) else member


def _runtime_language_tag(language: Any) -> str:
    value = _runtime_member(language, "language_tag", "languageTag")
    return str(value or "").strip()


def _requested_language_candidates(value: str) -> list[str]:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return []
    if normalized in {"zh", "zh-cn", "zh-hans", "chinese"}:
        return ["zh-hans", "zh-cn", "zh-sg", "zh"]
    if normalized in {"en", "en-us", "english"}:
        return ["en-us", "en-gb", "en"]
    return [normalized]


def _pick_supported_language(requested: list[str] | None, available: list[str]) -> str:
    normalized = {item.lower(): item for item in available if item}
    for value in requested or []:
        for candidate in _requested_language_candidates(value):
            if candidate in normalized:
                return normalized[candidate]
            prefix = next((tag for tag in available if tag.lower().startswith(f"{candidate}-")), "")
            if prefix:
                return prefix
    return ""


def system_ocr_status(languages: list[str] | None = None) -> dict[str, Any]:
    """Return a truthful, credential-free status for the native OCR engine."""

    result: dict[str, Any] = {
        "available": False,
        "backend": "unavailable",
        "platform": "windows" if os.name == "nt" else os.name,
        "languages": [],
        "requested_languages": [str(value).strip() for value in (languages or []) if str(value).strip()],
        "message": "未检测到系统 OCR 引擎",
    }
    runtime = _load_windows_ocr_runtime()
    if not runtime.get("available"):
        result["message"] = str(runtime.get("error") or result["message"])
        result["details"] = str(runtime.get("details") or "")
        return result
    engine_type = runtime["OcrEngine"]
    try:
        available_objects = _runtime_static_call(
            engine_type,
            "get_available_recognizer_languages",
            "GetAvailableRecognizerLanguages",
            "available_recognizer_languages",
            "AvailableRecognizerLanguages",
        ) or []
        available = [_runtime_language_tag(item) for item in available_objects]
        available = [item for item in available if item]
        profile_engine = _runtime_static_call(
            engine_type,
            "try_create_from_user_profile_languages",
            "TryCreateFromUserProfileLanguages",
        )
        selected = _pick_supported_language(languages, available)
        requested_supported = bool(selected) or not languages
        missing = [
            value
            for value in list(languages or [])
            if not _pick_supported_language([value], available)
        ]
        result.update(
            {
                "available": bool(profile_engine or available),
                "backend": "windows-ocr" if (profile_engine or available) else "unavailable",
                "languages": available,
                "selected_language": selected,
                "missing_languages": missing,
                "requested_supported": not missing and requested_supported,
                "message": (
                    "检测到 Windows OCR 引擎可用；速度快，准确率受系统版本和语言包影响。"
                    if profile_engine or available
                    else "Windows OCR 引擎未提供可用识别语言，请在系统中安装语言包。"
                ),
            }
        )
        if missing:
            result["message"] = f"检测到 Windows OCR 引擎，但尚未安装：{', '.join(missing)} 语言包。"
        return result
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        result["message"] = f"Windows OCR 引擎检测失败：{type(exc).__name__}"
        result["details"] = str(exc)[:240]
        return result


def _system_ocr_engine(runtime: dict[str, Any], languages: list[str] | None) -> Any:
    engine_type = runtime["OcrEngine"]
    available_objects = _runtime_static_call(
        engine_type,
        "get_available_recognizer_languages",
        "GetAvailableRecognizerLanguages",
        "available_recognizer_languages",
        "AvailableRecognizerLanguages",
    ) or []
    available = [_runtime_language_tag(item) for item in available_objects]
    selected = _pick_supported_language(languages, available)
    if selected and len(list(languages or [])) == 1:
        language = runtime["Language"](selected)
        engine = _runtime_member(engine_type, "try_create_from_language", "TryCreateFromLanguage")
        if callable(engine):
            return engine(language)
    return _runtime_static_call(
        engine_type,
        "try_create_from_user_profile_languages",
        "TryCreateFromUserProfileLanguages",
    )


async def _system_software_bitmap(runtime: dict[str, Any], raw: bytes) -> Any:
    image = runtime["Image"].open(BytesIO(raw)).convert("RGBA")
    writer = runtime["DataWriter"]()
    pixels = image.tobytes()
    try:
        writer.write_bytes(pixels)
    except TypeError:
        # Older winrt projections accept a list of integers instead of bytes.
        writer.write_bytes(list(pixels))
    buffer = writer.detach_buffer()
    pixel_format = _runtime_member(runtime["BitmapPixelFormat"], "rgba8", "RGBA8")
    alpha_mode = _runtime_member(runtime.get("BitmapAlphaMode"), "straight", "STRAIGHT")
    create = runtime["SoftwareBitmap"].create_copy_from_buffer
    try:
        if alpha_mode is not None:
            return create(buffer, pixel_format, image.width, image.height, alpha_mode)
        return create(buffer, pixel_format, image.width, image.height)
    except TypeError:
        return create(buffer, pixel_format, image.width, image.height)


async def _system_ocr_async(images: list[dict[str, str]], languages: list[str] | None) -> dict[str, Any]:
    runtime = _load_windows_ocr_runtime(require_image=True)
    if not runtime.get("available"):
        return {
            "text": "",
            "backend": "windows-ocr",
            "available": False,
            "message": str(runtime.get("error") or "Windows OCR 引擎不可用"),
        }
    engine = _system_ocr_engine(runtime, languages)
    if engine is None:
        return {
            "text": "",
            "backend": "windows-ocr",
            "available": False,
            "message": "Windows OCR 引擎未提供当前语言的识别器，请安装对应语言包。",
        }
    recognize = _runtime_member(engine, "recognize_async", "RecognizeAsync")
    if not callable(recognize):
        return {"text": "", "backend": "windows-ocr", "available": False, "message": "Windows OCR API 不完整"}
    texts: list[str] = []
    errors: list[str] = []
    for image in images[:4]:
        try:
            raw = base64.b64decode(str(image.get("data", "")), validate=True)
            bitmap = await _system_software_bitmap(runtime, raw)
            result = await recognize(bitmap)
            text = str(_runtime_member(result, "text", "Text") or "").strip()
            if text:
                texts.append(text)
            close = _runtime_member(bitmap, "close", "Close")
            if callable(close):
                close()
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}"[:240])
    text = "\n\n".join(texts).strip()
    return {
        "text": text,
        "backend": "windows-ocr",
        "available": bool(text),
        "message": "已使用 Windows 系统 OCR" if text else (errors[0] if errors else "Windows OCR 未提取到文字"),
        "errors": errors[:4],
    }


def _run_system_ocr(images: list[dict[str, str]], languages: list[str] | None) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        return asyncio.run(_system_ocr_async(images, languages))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()
    # Research work may be called from an async host.  WinRT awaits must run
    # on a separate loop instead of nesting asyncio.run in that loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


def _system_ocr_image_blocks(images: list[dict[str, str]], *, languages: list[str] | None = None) -> dict[str, Any]:
    try:
        return _run_system_ocr(images, languages)
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "text": "",
            "backend": "windows-ocr",
            "available": False,
            "message": f"Windows OCR 调用失败：{type(exc).__name__}",
            "errors": [str(exc)[:240]],
        }


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and str(item.get("type", "text")).lower() == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part.strip()).strip()
    return ""


def _deepseek_ocr_image_blocks(
    images: list[dict[str, str]],
    *,
    base_url: str,
    api_key: str,
    languages: list[str] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Run DeepSeek-OCR through SiliconFlow's OpenAI-compatible endpoint."""

    if not images:
        return {"text": "", "backend": "deepseek-ocr", "available": False, "message": "没有可识别的图片"}
    estimated_bytes = 0
    content: list[dict[str, Any]] = []
    for image in images[:4]:
        encoded = str(image.get("data", ""))
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return {"text": "", "backend": "deepseek-ocr", "available": False, "message": "图片数据不是有效的 Base64"}
        if len(raw) > 4 * 1024 * 1024:
            return {"text": "", "backend": "deepseek-ocr", "available": False, "message": "单张图片超过 4 MB 限制"}
        estimated_bytes += len(raw)
        mime_type = str(image.get("mime_type", "image/png")).strip().lower() or "image/png"
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded}", "detail": "high"},
        })
    if estimated_bytes > 10 * 1024 * 1024:
        return {"text": "", "backend": "deepseek-ocr", "available": False, "message": "图片总大小超过 10 MB 限制"}
    image_tokens = "\n".join("<image>" for _ in content)
    language_names = {"zh": "Chinese", "en": "English"}
    language_hint = ", ".join(language_names.get(str(value).strip().lower(), str(value).strip()) for value in (languages or []) if str(value).strip())
    language_instruction = f" Recognize {language_hint}." if language_hint else ""
    content.insert(
        0,
        {
            "type": "text",
            "text": f"{image_tokens}\n<|grounding|>Convert the document to markdown. Preserve reading order, tables, formulas, and page breaks.{language_instruction} Output only markdown.",
        },
    )
    active_session = session or requests.Session()
    try:
        response = active_session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": DEFAULT_DEEPSEEK_OCR_MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 8192,
                "temperature": 0,
                "stream": False,
            },
            timeout=90.0,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") if isinstance(payload, dict) else []
        message = choices[0].get("message", {}) if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        text = _message_text(message.get("content") if isinstance(message, dict) else "")
        return {
            "text": text,
            "backend": "deepseek-ocr",
            "available": bool(text),
            "message": "已使用 DeepSeek-OCR（硅基流动）" if text else "DeepSeek-OCR 未返回可用文字",
        }
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" HTTP {status}" if status else ""
        return {"text": "", "backend": "deepseek-ocr", "available": False, "message": f"DeepSeek-OCR 调用失败{suffix}：{type(exc).__name__}"}
    except (OSError, TypeError, ValueError, KeyError, IndexError) as exc:
        return {"text": "", "backend": "deepseek-ocr", "available": False, "message": f"DeepSeek-OCR 响应无效：{type(exc).__name__}"}


def ocr_image_blocks(
    images: list[dict[str, str]],
    *,
    languages: list[str] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    settings: dict[str, Any] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Use the configured OCR provider with a truthful local fallback chain."""

    remote_message = ""
    system_message = ""
    ocr_settings = dict((settings or {}).get("document_processing", {}).get("ocr", {}) or {}) if isinstance(settings, dict) else {}
    provider = str(ocr_settings.get("provider", "system")).strip().lower()
    if bool(ocr_settings.get("enabled", True)) and provider == "system":
        native = _system_ocr_image_blocks(images, languages=languages)
        if native.get("available"):
            return native
        system_message = str(native.get("message", "Windows OCR 不可用"))
    if bool(ocr_settings.get("enabled", True)) and provider == "deepseek":
        api_key = ""
        if workspace is not None:
            api_key = get_document_service_api_key(workspace, "ocr")
        if api_key:
            remote = _deepseek_ocr_image_blocks(
                images,
                base_url=str(ocr_settings.get("base_url", "")).strip() or DEFAULT_DEEPSEEK_OCR_BASE_URL,
                api_key=api_key,
                languages=languages,
                session=session,
            )
            if remote.get("available"):
                return remote
            remote_message = str(remote.get("message", "DeepSeek-OCR 不可用"))
        else:
            remote_message = "DeepSeek-OCR 尚未配置硅基流动 API 密钥"

    command = _tesseract_path()
    if not command:
        prefix = "；".join(value for value in (system_message, remote_message) if value)
        return {
            "text": "",
            "backend": "unavailable",
            "available": False,
            "message": f"{prefix}；未发现 Tesseract" if prefix else "未发现 Tesseract；请安装本地 OCR，或在模型服务中配置视觉模型。",
        }
    language_values = [str(value).strip().lower() for value in (languages or ["zh", "en"]) if str(value).strip()]
    language = "+".join({"zh": "chi_sim", "en": "eng"}.get(value, value) for value in language_values) or "eng"
    texts: list[str] = []
    errors: list[str] = []
    suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
    try:
        with tempfile.TemporaryDirectory(prefix="scansci-ocr-") as folder:
            root = Path(folder)
            for index, image in enumerate(images[:4]):
                try:
                    raw = base64.b64decode(str(image.get("data", "")), validate=True)
                    source = root / f"image-{index}{suffixes.get(str(image.get('mime_type', '')).lower(), '.bin')}"
                    source.write_bytes(raw)
                    output_base = root / f"result-{index}"
                    result = subprocess.run(
                        [command, str(source), str(output_base), "-l", language, "--psm", "6"],
                        capture_output=True,
                        text=True,
                        timeout=45,
                        check=False,
                        env=_tesseract_environment(),
                    )
                    text_path = output_base.with_suffix(".txt")
                    if text_path.is_file():
                        text = text_path.read_text(encoding="utf-8", errors="replace").strip()
                        if text:
                            texts.append(text)
                    if result.returncode != 0 and not text_path.is_file():
                        errors.append((result.stderr or "OCR failed").strip()[:240])
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    errors.append(f"{type(exc).__name__}: {exc}"[:240])
    except OSError as exc:
        return {"text": "", "backend": "tesseract", "available": False, "message": f"OCR 无法启动：{exc}"}
    text = "\n\n".join(texts).strip()
    return {
        "text": text,
        "backend": "tesseract",
        "available": bool(text),
        "message": (f"；".join(value for value in (system_message, remote_message) if value) + "；" if (system_message or remote_message) else "") + ("已回退到本地 Tesseract OCR" if (system_message or remote_message) else "已使用本地 Tesseract OCR；仅能提取文字，无法理解图表布局。") if text else (system_message or remote_message or (errors[0] if errors else "OCR 未提取到文字")),
        "errors": errors[:4],
    }
