"""Vision routing and conservative local OCR fallback.

The desktop app has two different kinds of models: the selected conversation
model and the model that can actually inspect an image.  Keeping the routing
decision here prevents the UI selection from becoming a hard failure when a
text model is selected.  The order is deliberately small and explicit:

1. honour an explicitly selected usable vision model;
2. prefer a ready local vision runtime (currently Ollama/MiniCPM-V);
3. use a configured cloud vision model;
4. if none is available, strip the image and add best-effort local OCR text.

No OCR package is required by the core app.  Tesseract is detected at runtime
and is treated as an optional last resort.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .app_settings import get_provider_api_key
from .ollama_runtime import ollama_status


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
        rows.append((model_id, dict(item)))
    return rows


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
) -> dict[str, Any] | None:
    """Choose a usable vision endpoint without making the user reselect it.

    ``allow_cloud`` gates the automatic fallback to a cloud vision provider
    that the user did not explicitly select.  Interactive chat keeps it on so
    images "just work"; evidence/research flows pass ``False`` so user images
    are never silently sent to a third-party vision API — they fall back to
    local vision or OCR instead.
    """

    providers = [item for item in list(settings.get("providers", []) or []) if isinstance(item, dict)]
    active = next((item for item in providers if str(item.get("id", "")) == str(active_provider_id)), None)
    if active is not None:
        active_model = _model_record(active, active_model_id)
        if "vision" in {str(value).lower() for value in list(active_model.get("capabilities", []) or [])}:
            selected = _route(workspace, active, str(active_model_id), active_model, "selected")
            if selected is not None:
                return selected

    local_candidates = []
    cloud_candidates = []
    for provider in providers:
        models = _model_candidates(provider, capability="vision")
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
            selected = _route(workspace, provider, model_id, model, "local")
            if selected is not None:
                return selected
    if allow_cloud:
        for provider, models in cloud_candidates:
            for model_id, model in models:
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


def ocr_image_blocks(images: list[dict[str, str]], *, languages: list[str] | None = None) -> dict[str, Any]:
    """Run optional local Tesseract OCR and return a truthful status object."""

    command = _tesseract_path()
    if not command:
        return {
            "text": "",
            "backend": "unavailable",
            "available": False,
            "message": "未发现 Tesseract；请安装本地 OCR，或在模型服务中配置视觉模型。",
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
        "message": "已使用本地 Tesseract OCR；仅能提取文字，无法理解图表布局。" if text else (errors[0] if errors else "OCR 未提取到文字"),
        "errors": errors[:4],
    }
