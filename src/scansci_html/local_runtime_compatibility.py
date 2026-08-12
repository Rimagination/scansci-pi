"""Persistent compatibility evidence for the optional local Transformers runtime.

The record deliberately lives beside the separately installed runtime, never
inside a model snapshot.  A model is only considered verified when the same
component version has loaded the same snapshot fingerprint and produced text.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping


_SCHEMA_VERSION = 1
_MODEL_METADATA_NAMES = {
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
}
_WEIGHT_SUFFIXES = {".safetensors", ".bin", ".pt", ".pth"}


def default_compatibility_path() -> Path:
    override = os.getenv("SCANSCI_LOCAL_RUNTIME_STATE_DIR", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
    else:
        runtime_root = os.getenv("SCANSCI_LOCAL_RUNTIME_ROOT", "").strip()
        if runtime_root:
            root = Path(runtime_root).expanduser().resolve() / "state"
        else:
            local_app_data = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            root = Path(local_app_data) / "ScanSci" / "runtimes" / "local-transformers" / "state"
    return root / "model-compatibility.json"


def _is_qwen35(record: Mapping[str, Any]) -> bool:
    model_id = str(record.get("id", "")).lower().replace("_", "").replace("-", "")
    if "qwen3.5" in str(record.get("id", "")).lower() or "qwen35" in model_id:
        return True
    path = Path(str(record.get("path", "") or ""))
    try:
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    model_type = str(config.get("model_type", "")).lower().replace("_", "")
    return model_type == "qwen35"


def snapshot_fingerprint(record: Mapping[str, Any]) -> str:
    """Fingerprint an existing snapshot without reading or changing its weights."""

    root = Path(str(record.get("path", "") or "")).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"model snapshot is missing: {root}")
    digest = hashlib.sha256()
    digest.update(str(root).encode("utf-8", errors="surrogatepass"))
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in _MODEL_METADATA_NAMES or path.suffix.lower() in _WEIGHT_SUFFIXES:
            candidates.append(path)
    if not candidates:
        raise ValueError(f"model snapshot has no metadata or weights: {root}")
    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix().lower()):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8", errors="surrogatepass"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


class ModelCompatibilityStore:
    """Store probe results keyed by model id, snapshot and component version."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or default_compatibility_path()).expanduser().resolve()
        self._lock = threading.RLock()

    def apply(self, record: Mapping[str, Any], *, component_version: str) -> dict[str, Any]:
        result = dict(record)
        entry = self._entries().get(str(record.get("id", "")))
        # Qwen3.5 requires a probe before its first use.  Other local models
        # remain immediately selectable unless this component has previously
        # recorded a probe result for the same snapshot and version.
        if not _is_qwen35(record) and not isinstance(entry, dict):
            return result
        files_present = bool(record.get("model_files_present", record.get("ready")))
        result["model_files_present"] = files_present
        result["installed"] = bool(record.get("installed", files_present))
        try:
            fingerprint = snapshot_fingerprint(record)
        except ValueError as error:
            result.update(
                {
                    "runtime_verified": True,
                    "runtime_compatible": False,
                    "ready": False,
                    "runtime_probe_state": "failed",
                    "runtime_compatibility_message": str(error),
                    "runtime_message": str(error),
                    "runtime_error": {
                        "code": "model_snapshot_missing",
                        "message": str(error),
                        "phase": "discovery",
                    },
                }
            )
            return result
        matches = bool(
            isinstance(entry, dict)
            and entry.get("fingerprint") == fingerprint
            and entry.get("component_version") == str(component_version)
        )
        if not _is_qwen35(record) and not matches:
            return result
        if not matches:
            message = (
                "尚未由当前本地运行组件在隔离进程中完成真实加载和最小生成；"
                "将直接复用现有模型文件，不会重新下载。"
            )
            result.update(
                {
                    "runtime_verified": False,
                    "runtime_compatible": False,
                    "ready": False,
                    "runtime_probe_state": "pending",
                    "runtime_compatibility_message": message,
                    "runtime_message": message,
                }
            )
            result.pop("runtime_error", None)
            return result
        probe = dict(entry)
        result["runtime_verified"] = True
        result["runtime_probe"] = probe
        if bool(entry.get("compatible")) and bool(entry.get("generated")):
            result["runtime_compatible"] = True
            result["ready"] = files_present
            result["runtime_probe_state"] = "ready"
            result["runtime_compatibility_message"] = "已通过隔离进程真实加载与最小生成验证。"
            result["runtime_message"] = result["runtime_compatibility_message"]
            result.pop("runtime_error", None)
        else:
            error = entry.get("error") if isinstance(entry.get("error"), dict) else {}
            message = str(error.get("message") or "当前本地运行组件与该模型不兼容。")
            result["runtime_compatible"] = False
            result["ready"] = False
            result["runtime_probe_state"] = "failed"
            result["runtime_error"] = dict(error)
            result["runtime_compatibility_message"] = message
            result["runtime_message"] = message
        return result

    def record_success(
        self,
        record: Mapping[str, Any],
        *,
        component_version: str,
        runtime_versions: Mapping[str, Any],
        generated_text: str,
    ) -> dict[str, Any]:
        text = str(generated_text or "").strip()
        if not text:
            raise ValueError("generation probe did not produce text")
        entry = {
            "model_id": str(record.get("id", "")),
            "fingerprint": snapshot_fingerprint(record),
            "component_version": str(component_version),
            "compatible": True,
            "generated": True,
            "generated_preview": text[:160],
            "runtime_versions": dict(runtime_versions),
            "checked_at": int(time.time()),
        }
        self._write_entry(entry["model_id"], entry)
        return entry

    def record_failure(
        self,
        record: Mapping[str, Any],
        *,
        component_version: str,
        error: Mapping[str, Any],
        runtime_versions: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "model_id": str(record.get("id", "")),
            "fingerprint": snapshot_fingerprint(record),
            "component_version": str(component_version),
            "compatible": False,
            "generated": False,
            "runtime_versions": dict(runtime_versions or {}),
            "error": dict(error),
            "checked_at": int(time.time()),
        }
        self._write_entry(entry["model_id"], entry)
        return entry

    def _entries(self) -> dict[str, Any]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
                return {}
            entries = payload.get("models")
            return dict(entries) if isinstance(entries, dict) else {}

    def _write_entry(self, model_id: str, entry: Mapping[str, Any]) -> None:
        if not model_id:
            raise ValueError("model id is required")
        with self._lock:
            entries = self._entries()
            entries[model_id] = dict(entry)
            payload = {"schema_version": _SCHEMA_VERSION, "models": entries}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
