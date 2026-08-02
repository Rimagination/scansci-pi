"""Discover, catalogue, and install local Hugging Face model snapshots.

The scanner is intentionally shallow: it checks sensible model/cache locations
on attached drives rather than recursively walking a user's disks.  This keeps
startup quick while still following a model collection when it is moved.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib import parse, request

from .model_downloads import ModelInstallManager, download_snapshot


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_CURATED = (
    {"id": "Qwen/Qwen2.5-1.5B-Instruct", "name": "Qwen2.5 1.5B Instruct", "kind": "chat", "size_hint": "约 3 GB", "description": "轻量中文对话，适合 CPU 或入门显卡。"},
    {"id": "Qwen/Qwen2.5-3B-Instruct", "name": "Qwen2.5 3B Instruct", "kind": "chat", "size_hint": "约 6 GB", "description": "本地中文通用对话的平衡选择。"},
    {"id": "Qwen/Qwen3-4B-Instruct-2507", "name": "Qwen3 4B Instruct", "kind": "chat", "size_hint": "约 8 GB", "description": "更强的本地推理与写作能力。"},
    {"id": "Qwen/Qwen3-Embedding-0.6B", "name": "Qwen3 Embedding 0.6B", "kind": "embedding", "size_hint": "约 1 GB", "description": "中文与英文语义检索。"},
    {"id": "Qwen/Qwen3-Reranker-0.6B", "name": "Qwen3 Reranker 0.6B", "kind": "reranking", "size_hint": "约 1 GB", "description": "提升资料库检索排序质量。"},
)


def model_root() -> Path:
    """Return a writable per-user install location on every desktop."""

    configured = os.getenv("SCANSCI_MODEL_ROOT", "").strip()
    if configured:
        return Path(configured)
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "ScanSci" / "models"
    return Path.home() / ".scansci" / "models"


def _env_paths(name: str) -> Iterable[Path]:
    for value in os.getenv(name, "").split(os.pathsep):
        if value.strip():
            yield Path(value.strip())


def discover_model_roots() -> list[Path]:
    """Return existing candidate roots without doing an expensive disk crawl."""
    explicit = os.getenv("SCANSCI_MODEL_ROOT", "").strip()
    # An explicit root is an operator choice (and keeps automated deployments
    # deterministic). Automatic discovery is used only when it is absent.
    if explicit:
        return [model_root()] if model_root().exists() else []
    candidates: list[Path] = [model_root(), *_env_paths("SCANSCI_MODEL_ROOTS")]
    candidates.extend(_env_paths("HF_HOME"))
    candidates.extend(_env_paths("HUGGINGFACE_HUB_CACHE"))
    home = Path.home()
    candidates.extend((home / "Models", home / ".cache" / "huggingface", home / ".cache" / "huggingface" / "hub"))
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        candidates.extend((
            drive / "AI" / "Models",
            drive / "Models",
            drive / "HuggingFace",
            drive / "huggingface",
            drive / "AI" / "HuggingFace",
        ))
    output: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key not in seen and resolved.exists() and resolved.is_dir():
            seen.add(key)
            output.append(resolved)
    return output


def _hub_roots(root: Path) -> Iterable[Path]:
    # Accept a model root, a huggingface root, or the hub directory itself.
    yield root / "HuggingFace" / "hub"
    yield root / "huggingface" / "hub"
    yield root / "hub"
    yield root


def hub_cache_root() -> Path:
    return model_root() / "HuggingFace" / "hub"


def _snapshot(folder: Path) -> Path | None:
    snapshots = folder / "snapshots"
    if not snapshots.is_dir():
        return None
    rows = [item for item in snapshots.iterdir() if item.is_dir()]
    return max(rows, key=lambda item: item.stat().st_mtime) if rows else None


def _bytes(path: Path) -> int:
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def _kind(identifier: str, config: dict[str, Any]) -> str:
    value = f"{identifier} {config.get('architectures', '')} {config.get('model_type', '')}".lower()
    if any(token in value for token in ("rerank", "reranker")):
        return "reranking"
    if any(token in value for token in ("embedding", "embed", "bge", "gte", "e5-")):
        return "embedding"
    if any(token in value for token in ("whisper", "asr", "speech")):
        return "audio"
    if any(token in value for token in ("vision", "-vl", "llava", "image")):
        return "vision"
    return "chat"


def installed_models() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    known: set[str] = set()
    for configured_root in discover_model_roots():
        for root in _hub_roots(configured_root):
            if not root.is_dir():
                continue
            for folder in sorted(root.glob("models--*"), key=lambda item: item.name.casefold()):
                snapshot = _snapshot(folder)
                if snapshot is None:
                    continue
                repo_id = folder.name.removeprefix("models--").replace("--", "/")
                marker = f"{repo_id}|{snapshot}".casefold()
                if marker in known:
                    continue
                known.add(marker)
                config_path = snapshot / "config.json"
                config: dict[str, Any] = {}
                if config_path.is_file():
                    try:
                        config = json.loads(config_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                weights = [*snapshot.glob("*.safetensors"), *snapshot.glob("*.bin"), *snapshot.glob("*.gguf")]
                rows.append({
                    "id": repo_id,
                    "name": repo_id,
                    "path": str(snapshot),
                    "size_bytes": _bytes(snapshot),
                    "ready": bool(weights),
                    "architecture": ", ".join(config.get("architectures", [])[:2]) if isinstance(config.get("architectures"), list) else "",
                    "model_type": str(config.get("model_type", "")),
                    "format": "gguf" if any(item.suffix.lower() == ".gguf" for item in weights) else "transformers",
                })
    return sorted(rows, key=lambda item: str(item["name"]).casefold())


def _remote_catalog(query: str, limit: int) -> list[dict[str, Any]]:
    parameters = {"limit": max(1, min(48, int(limit))), "full": "true", "sort": "downloads", "direction": "-1"}
    if query:
        parameters["search"] = query
    endpoint = "https://huggingface.co/api/models?" + parse.urlencode(parameters)
    with request.urlopen(endpoint, timeout=12) as response:  # nosec B310 - fixed official HTTPS host
        payload = json.loads(response.read().decode("utf-8"))
    output: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        repo_id = str(item.get("id", ""))
        if not _MODEL_ID.fullmatch(repo_id):
            continue
        pipeline = str(item.get("pipeline_tag") or "")
        kind = "chat" if pipeline in {"text-generation", "image-text-to-text", ""} else pipeline
        output.append({"id": repo_id, "name": repo_id, "kind": kind, "description": str(item.get("library_name") or "Hugging Face"), "downloads": int(item.get("downloads", 0) or 0), "likes": int(item.get("likes", 0) or 0)})
    return output


def market_catalog(query: str = "", *, limit: int = 30) -> dict[str, Any]:
    clean = str(query or "").strip()
    installed = {item["id"]: item for item in installed_models()}
    try:
        # The no-query view is intentionally broad; curated rows are merged to
        # retain reliable small embedding and reranking recommendations.
        remote = _remote_catalog(clean, limit)
        rows = [*(_CURATED if not clean else ()), *remote]
        return {"items": _merge_catalog(rows, installed, clean), "source": "curated" if not clean else "huggingface"}
    except Exception as exc:  # network catalog is optional
        return {"items": _merge_catalog(_CURATED, installed, clean), "source": "curated-cache", "warning": str(exc)}


def _merge_catalog(rows: Any, installed: dict[str, dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.casefold()
    output: list[dict[str, Any]] = []
    known: set[str] = set()
    for raw in rows:
        item = dict(raw)
        repo_id = str(item.get("id", ""))
        if not repo_id or repo_id in known or (needle and needle not in repo_id.casefold() and needle not in str(item.get("name", "")).casefold()):
            continue
        known.add(repo_id)
        local = installed.get(repo_id)
        item["installed"] = bool(local)
        item["ready"] = bool(local and local.get("ready"))
        item["local_path"] = str(local.get("path", "")) if local else ""
        output.append(item)
    return output


def download_model(repo_id: str) -> dict[str, Any]:
    clean = str(repo_id or "").strip()
    if not _MODEL_ID.fullmatch(clean):
        raise ValueError("模型标识必须采用“组织/模型名”格式")
    cache = hub_cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    result = download_snapshot(clean, cache_root=cache, source="auto")
    return {
        **result,
        "installed": next((item for item in installed_models() if item["id"] == clean), None),
    }


def create_install_manager() -> ModelInstallManager:
    """Create the non-blocking installer used by the desktop API."""

    def ready(model_id: str) -> bool:
        return any(
            str(item.get("id", "")).casefold() == str(model_id).casefold()
            and bool(item.get("ready"))
            for item in installed_models()
        )

    return ModelInstallManager(
        cache_root=hub_cache_root(),
        ready_checker=ready,
    )
