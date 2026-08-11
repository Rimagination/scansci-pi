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
import shutil
from typing import Any, Iterable
from urllib import parse, request

from .model_downloads import ModelInstallManager, download_snapshot
from .ollama_runtime import OLLAMA_VISION_CATALOG_ITEM
from .local_runtime_compatibility import ModelCompatibilityStore
from .local_runtime_contract import COMPONENT_VERSION


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

# 原厂组织图标（ModelScope org 头像 CDN，国内可直接访问）。
_ORG_ICON_URLS: dict[str, str] = {
    "Qwen": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg",
    "BAAI": "https://resouces.modelscope.cn/avatar/5b2ecfe4-6631-4f8d-8a69-9579f1a98b05.png",
    "openbmb": "https://resouces.modelscope.cn/avatar/e23b1834-049d-464e-8ffc-4b10093114d0.png",
    "jinaai": "https://resouces.modelscope.cn/avatar/ba3fee2f-0f59-4808-8c63-8aceb61da8ce.jpeg",
}


def _org_icon_url(repo_id: str) -> str:
    """Return the org avatar URL for a model repo id, or an empty string."""
    return _ORG_ICON_URLS.get(str(repo_id or "").split("/", 1)[0], "")
QWEN3_ASR_NATIVE_MODEL_ID = "Qwen/Qwen3-ASR-0.6B-hf"
QWEN3_ASR_LEGACY_MODEL_ID = "Qwen/Qwen3-ASR-0.6B"
_CURATED = (
    {"id": "Qwen/Qwen2.5-1.5B-Instruct", "name": "Qwen2.5 1.5B Instruct", "kind": "chat", "gpu": "recommended", "size_hint": "约 3 GB", "description": "轻量中文对话，适合 CPU 或入门显卡。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "Qwen/Qwen2.5-3B-Instruct", "name": "Qwen2.5 3B Instruct", "kind": "chat", "gpu": "recommended", "size_hint": "约 6 GB", "description": "本地中文通用对话的平衡选择。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "Qwen/Qwen3-4B-Instruct-2507", "name": "Qwen3 4B Instruct", "kind": "chat", "gpu": "recommended", "size_hint": "约 8 GB", "description": "更强的本地推理与写作能力。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "Qwen/Qwen3-Embedding-0.6B", "name": "Qwen3 Embedding 0.6B", "kind": "embedding", "gpu": "cpu", "size_hint": "约 1 GB", "description": "中文与英文语义检索。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "Qwen/Qwen3-Reranker-0.6B", "name": "Qwen3 Reranker 0.6B", "kind": "reranking", "gpu": "cpu", "size_hint": "约 1 GB", "description": "提升资料库检索排序质量。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "Qwen/Qwen3-Reranker-4B", "name": "Qwen3 Reranker 4B（推荐）", "kind": "reranking", "gpu": "recommended", "size_hint": "约 8 GB / 4-bit 约 4 GB", "description": "更强检索重排序；GPU 下自动加载 4-bit 量化，质量接近全量。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": QWEN3_ASR_NATIVE_MODEL_ID, "name": "Qwen3 ASR 0.6B（Transformers 原生）", "kind": "audio", "gpu": "recommended", "size_hint": "约 2 GB", "description": "本地语音转写；使用 Transformers 原生格式，下载后可由 ScanSci 直接运行。", "icon_url": "https://resources.modelscope.cn/avatar/4c40e6ce-1348-43b5-a3bc-6bafec6ac805.jpg"},
    {"id": "openbmb/MiniCPM-V-4.6-BNB", "name": "MiniCPM-V 4.6（BNB 4-bit）", "kind": "vision", "runtime": "local-huggingface", "gpu": "required", "size_hint": "约 1.1 GB", "description": "需要 NVIDIA 显卡的 4-bit 视觉模型；ScanSci 可通过本地 Transformers 运行。", "icon_url": "https://resouces.modelscope.cn/avatar/e23b1834-049d-464e-8ffc-4b10093114d0.png"},
    {"id": "openbmb/MiniCPM-V-4.6-GPTQ", "name": "MiniCPM-V 4.6（GPTQ）", "kind": "vision", "runtime": "local-huggingface", "gpu": "required", "size_hint": "约 1.9 GB", "description": "需要 NVIDIA 显卡的 GPTQ 4-bit 视觉模型；需要兼容 GPTQModel 的本地运行环境。", "icon_url": "https://resouces.modelscope.cn/avatar/e23b1834-049d-464e-8ffc-4b10093114d0.png"},
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
    """Return the cache used for both model discovery and new downloads.

    Hugging Face's standard cache variables are common in developer and
    packaged environments.  Prefer them when the operator has not explicitly
    selected a ScanSci model root; otherwise a download can be written to the
    default per-user directory while existing models are discovered elsewhere.
    """

    if os.getenv("SCANSCI_MODEL_ROOT", "").strip():
        return model_root() / "HuggingFace" / "hub"
    configured_cache = os.getenv("HF_HUB_CACHE", "").strip()
    if configured_cache:
        return Path(configured_cache)
    configured_home = os.getenv("HF_HOME", "").strip()
    if configured_home:
        return Path(configured_home) / "hub"
    return model_root() / "HuggingFace" / "hub"


def _snapshot(folder: Path) -> Path | None:
    snapshots = folder / "snapshots"
    if not snapshots.is_dir():
        return None
    rows = [item for item in snapshots.iterdir() if item.is_dir()]
    return max(rows, key=lambda item: item.stat().st_mtime) if rows else None


def _read_model_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _model_weight_files(folder: Path) -> list[Path]:
    """Return weights stored directly in a model directory.

    Hugging Face's cache layout keeps weights in a snapshot, while manually
    copied models usually put them beside ``config.json``.  Supporting both
    layouts is important after an app update: a user should not be sent back
    to a multi-gigabyte download merely because the folder was copied from a
    different tool.
    """

    weights: list[Path] = []
    for pattern in ("*.safetensors", "*.bin", "*.gguf", "*.pt", "*.pth"):
        try:
            weights.extend(item for item in folder.glob(pattern) if item.is_file())
        except OSError:
            continue
    return weights


def _canonical_model_id(folder: Path, config: dict[str, Any]) -> str:
    marker = _read_model_json(folder / ".scansci-model.json")
    candidates = [
        marker.get("repo_id"),
        marker.get("model_id"),
        config.get("_name_or_path"),
        config.get("name_or_path"),
        config.get("model_id"),
        folder.name,
    ]
    for value in candidates:
        value = str(value or "").strip().replace("\\", "/")
        if _MODEL_ID.fullmatch(value):
            return value
    folder_name = folder.name
    if folder_name.startswith("models--"):
        decoded = folder_name.removeprefix("models--").replace("--", "/")
        if _MODEL_ID.fullmatch(decoded):
            return decoded
    leaf = folder_name.casefold()
    for item in _CURATED:
        repo_id = str(item.get("id", ""))
        if repo_id.rsplit("/", 1)[-1].casefold() == leaf:
            return repo_id
    return folder_name


def _direct_model_directories(root: Path, *, max_depth: int = 3) -> Iterable[Path]:
    """Find manually copied model folders without crawling an entire drive."""

    pending: list[tuple[Path, int]] = [(root, 0)]
    seen: set[str] = set()
    while pending:
        folder, depth = pending.pop()
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        # Hugging Face cache snapshots are handled above by ``_hub_roots``.
        # Do not rediscover ``models--org--name/snapshots/<hash>`` as a second
        # model whose ID would otherwise be the opaque snapshot hash.
        parts = {part.casefold() for part in resolved.parts}
        if "snapshots" in parts and any(part.casefold().startswith("models--") for part in resolved.parts):
            continue
        if (resolved / "config.json").is_file() and _model_weight_files(resolved):
            yield resolved
            # A valid model directory is a leaf for discovery.  This avoids
            # walking its auxiliary cache folders and duplicate snapshots.
            continue
        if depth >= max_depth:
            continue
        try:
            children = list(resolved.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and not child.name.startswith("."):
                pending.append((child, depth + 1))


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
    if any(token in value for token in ("vision", "-vl", "llava", "image", "minicpmv", "minicpm-v")) or isinstance(config.get("vision_config"), dict):
        return "vision"
    return "chat"


def _audio_runtime_info(identifier: str, config: dict[str, Any]) -> dict[str, Any]:
    """Describe whether the snapshot matches ScanSci's in-process ASR backend.

    Qwen publishes two intentionally different checkpoints: the original
    package-format model and the newer ``-hf`` checkpoint for native
    Transformers.  They have the same broad model name but different weight
    layouts.  Marking this explicitly prevents a legacy snapshot from being
    reported as ready and then spending minutes in a doomed load attempt.
    """

    if identifier == QWEN3_ASR_NATIVE_MODEL_ID or (
        str(config.get("model_type", "")) == "qwen3_asr"
        and isinstance(config.get("audio_config"), dict)
    ):
        return {
            "runtime_compatible": True,
            "runtime_backend": "transformers-native",
            "runtime_message": "可由 ScanSci 当前本地 Transformers 运行组件直接识别。",
        }
    if identifier == QWEN3_ASR_LEGACY_MODEL_ID:
        return {
            "runtime_compatible": False,
            "runtime_backend": "qwen-asr-legacy",
            "runtime_message": "这是旧版 qwen-asr 格式；请下载 Qwen3-ASR-0.6B-hf，避免与当前 Transformers 版本冲突。",
        }
    return {
        "runtime_compatible": False,
        "runtime_backend": "unsupported",
        "runtime_message": "当前版本暂不支持此语音模型格式。",
    }


def installed_models() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    known: set[str] = set()
    compatibility = ModelCompatibilityStore()

    def add_snapshot(repo_id: str, snapshot: Path) -> None:
        marker = f"{repo_id}|{snapshot}".casefold()
        if marker in known:
            return
        known.add(marker)
        config = _read_model_json(snapshot / "config.json")
        weights = _model_weight_files(snapshot)
        kind = _kind(repo_id, config)
        row = {
            "id": repo_id,
            "name": repo_id,
            "path": str(snapshot),
            "size_bytes": _bytes(snapshot),
            "ready": bool(weights),
            "kind": kind,
            "architecture": ", ".join(config.get("architectures", [])[:2]) if isinstance(config.get("architectures"), list) else "",
            "model_type": str(config.get("model_type", "")),
            "format": "gguf" if any(item.suffix.lower() == ".gguf" for item in weights) else "transformers",
        }
        icon_url = _org_icon_url(repo_id)
        if icon_url:
            row["icon_url"] = icon_url
        if kind == "audio":
            row.update(_audio_runtime_info(repo_id, config))
        rows.append(compatibility.apply(row, component_version=COMPONENT_VERSION))

    for configured_root in discover_model_roots():
        for root in _hub_roots(configured_root):
            if not root.is_dir():
                continue
            for folder in sorted(root.glob("models--*"), key=lambda item: item.name.casefold()):
                snapshot = _snapshot(folder)
                if snapshot is None:
                    continue
                repo_id = folder.name.removeprefix("models--").replace("--", "/")
                add_snapshot(repo_id, snapshot)
        # Also accept a normal model folder selected by another downloader.
        # This scan is limited to known model roots and three directory levels;
        # it never recursively walks an arbitrary drive.
        for folder in _direct_model_directories(configured_root):
            repo_id = _canonical_model_id(folder, _read_model_json(folder / "config.json"))
            add_snapshot(repo_id, folder)
    return sorted(rows, key=lambda item: str(item["name"]).casefold())


def delete_installed_model(repo_id: str) -> dict[str, Any]:
    """Delete one discovered model and the files owned by its cache entry.

    Hugging Face stores snapshots below ``models--ORG--NAME`` and keeps the
    actual blobs beside them.  Removing only the snapshot would leave most of
    a model on disk, so cache entries are removed at the repository directory
    level.  Manually copied model folders are removed as-is.  In both cases we
    resolve the discovered path and require it to remain below a configured
    model root before touching the filesystem.
    """

    requested_id = str(repo_id or "").strip()
    if not _MODEL_ID.fullmatch(requested_id):
        raise ValueError("模型 ID 格式无效")

    requested_key = requested_id.casefold()
    row = next(
        (
            item
            for item in installed_models()
            if str(item.get("id", "")).strip().casefold() == requested_key
        ),
        None,
    )
    if row is None:
        raise FileNotFoundError(f"未找到已安装模型：{requested_id}")

    discovered_path = Path(str(row.get("path", ""))).expanduser()
    if discovered_path.is_symlink() or not discovered_path.is_dir():
        raise FileNotFoundError(f"模型目录不存在：{requested_id}")

    # A snapshot is only one revision inside the cache.  Remove the complete
    # ``models--ORG--NAME`` directory so blobs and refs do not become orphans.
    if (
        discovered_path.parent.name.casefold() == "snapshots"
        and discovered_path.parent.parent.name.casefold().startswith("models--")
    ):
        target = discovered_path.parent.parent
    else:
        target = discovered_path

    if target.is_symlink() or not target.is_dir():
        raise FileNotFoundError(f"模型目录不存在：{requested_id}")
    target = target.resolve()

    roots: list[Path] = []
    for root in discover_model_roots():
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        if resolved_root not in roots:
            roots.append(resolved_root)
    if not any(target != root and root in target.parents for root in roots):
        raise ValueError("模型目录不在受支持的本地模型目录中")

    shutil.rmtree(target)
    return {
        "deleted": True,
        "id": str(row.get("id") or requested_id),
        "path": str(target),
    }


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
        kind = "vision" if pipeline == "image-text-to-text" else "chat" if pipeline in {"text-generation", ""} else pipeline
        output.append({"id": repo_id, "name": repo_id, "kind": kind, "description": str(item.get("library_name") or "Hugging Face"), "downloads": int(item.get("downloads", 0) or 0), "likes": int(item.get("likes", 0) or 0)})
    return output


def market_catalog(query: str = "", *, limit: int = 30) -> dict[str, Any]:
    clean = str(query or "").strip()
    installed = {item["id"]: item for item in installed_models()}
    curated_rows = [*_CURATED, OLLAMA_VISION_CATALOG_ITEM]
    if clean:
        needle = clean.casefold()
        curated_rows = [
            item
            for item in curated_rows
            if any(
                needle in str(item.get(field, "")).casefold()
                for field in ("id", "name", "description", "kind")
            )
        ]
    try:
        # The initial view is intentionally curated and offline-friendly.  A
        # remote Hugging Face catalog probe is only useful after the user has
        # entered a search term, and otherwise adds avoidable latency on
        # mainland-China networks.
        if not clean:
            return {"items": _merge_catalog(curated_rows, installed, clean), "source": "curated"}
        # Curated rows are merged into search results to retain reliable small
        # embedding, reranking, audio, and vision recommendations. Matching
        # curated rows remain visible when the user searches, so the native ASR
        # checkpoint is not hidden by a remote result with the legacy
        # Qwen3-ASR name.
        remote = _remote_catalog(clean, limit)
        rows = [*curated_rows, *remote]
        return {"items": _merge_catalog(rows, installed, clean), "source": "curated" if not clean else "huggingface"}
    except Exception as exc:  # network catalog is optional
        rows = curated_rows or [*_CURATED, OLLAMA_VISION_CATALOG_ITEM]
        return {"items": _merge_catalog(rows, installed, clean), "source": "curated-cache", "warning": str(exc)}


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
        if local and "runtime_compatible" in local:
            item["runtime_compatible"] = bool(local.get("runtime_compatible"))
            item["runtime_backend"] = str(local.get("runtime_backend", ""))
            item["runtime_message"] = str(
                local.get("runtime_message", local.get("runtime_compatibility_message", ""))
            )
            item["runtime_verified"] = bool(local.get("runtime_verified", False))
            item["model_files_present"] = bool(local.get("model_files_present", local.get("ready")))
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
