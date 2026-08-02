"""Reliable, China-friendly model snapshot downloads for ScanSci desktop.

The desktop core cannot assume that ``huggingface.co`` is reachable.  Public
Qwen retrieval models are therefore fetched from their official ModelScope
mirror first, with Hugging Face used as the secondary route.  Both routes use
the same resumable, checksummed downloader and produce the Hugging Face cache
layout already understood by ScanSci's model discovery code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from typing import Any
from urllib import error, parse, request
from uuid import uuid4


MODEL_SCOPE_BASE_URL = "https://modelscope.cn"
HUGGING_FACE_BASE_URL = "https://huggingface.co"
DEFAULT_REVISION = "master"
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_BYTES = 1024 * 1024
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_RETRY_DELAYS_SECONDS = (0.0, 1.0, 3.0)


class ModelDownloadError(RuntimeError):
    """Raised after every configured official model source has failed."""


class DownloadPaused(ModelDownloadError):
    """Raised when the user pauses a resumable model download."""


class DownloadCancelled(ModelDownloadError):
    """Raised when the user cancels a model download."""


class ModelSourceUnavailable(ModelDownloadError):
    """Raised when one source cannot provide the requested public snapshot."""


ProgressCallback = Callable[[dict[str, Any]], None]


def download_snapshot(
    repo_id: str,
    *,
    cache_root: str | Path,
    source: str = "auto",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Download one public model snapshot through official, resumable routes.

    ``auto`` deliberately tries ModelScope before Hugging Face.  This makes
    the curated Qwen retrieval bundle work on ordinary mainland-China
    networks without asking the user to configure a VPN or a third-party
    mirror.
    """

    clean = _validate_model_id(repo_id)
    selected = str(source or "auto").strip().lower()
    if selected not in {"auto", "modelscope", "huggingface"}:
        raise ValueError("模型下载源必须是 auto、modelscope 或 huggingface")
    routes = (
        ("modelscope", "huggingface")
        if selected == "auto"
        else (selected,)
    )
    failures: list[str] = []
    for route in routes:
        try:
            if route == "modelscope":
                manifest = _modelscope_manifest(clean)
            else:
                manifest = _huggingface_manifest(clean)
            path = _install_manifest(
                manifest,
                cache_root=Path(cache_root),
                progress_callback=progress_callback,
            )
            return {
                "ok": True,
                "id": clean,
                "path": str(path),
                "source": route,
                "revision": str(manifest["revision"]),
                "files": len(list(manifest["files"])),
                "size_bytes": sum(int(item.get("size", 0) or 0) for item in manifest["files"]),
                "fallback_used": route != routes[0],
                "source_failures": failures,
            }
        except (DownloadPaused, DownloadCancelled):
            raise
        except Exception as exc:  # one source must never prevent the fallback
            failures.append(f"{route}: {type(exc).__name__}: {exc}"[:1000])
    detail = "；".join(failures) or "没有可用下载源"
    raise ModelDownloadError(f"无法下载 {clean}。已尝试官方国内源和国际源：{detail}")


def _modelscope_manifest(repo_id: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    pending = [""]
    revision = DEFAULT_REVISION
    commit = ""
    while pending:
        root = pending.pop(0)
        endpoint = (
            f"{MODEL_SCOPE_BASE_URL}/api/v1/models/{parse.quote(repo_id, safe='/')}/repo/files?"
            + parse.urlencode({"Revision": revision, "Root": root})
        )
        payload = _read_json(endpoint)
        if int(payload.get("Code", 0) or 0) != 200 or not bool(payload.get("Success", False)):
            raise ModelSourceUnavailable(str(payload.get("Message") or "ModelScope 未返回模型文件"))
        rows = list(dict(payload.get("Data", {}) or {}).get("Files") or [])
        for raw in rows:
            item = dict(raw or {})
            path = _safe_repo_path(item.get("Path") or item.get("Name"))
            if not path:
                continue
            if str(item.get("Type", "")).lower() == "tree":
                pending.append(path)
                continue
            if str(item.get("Type", "")).lower() != "blob":
                continue
            file_revision = str(item.get("Revision", "") or "")
            commit = commit or file_revision
            sha256 = str(item.get("Sha256", "") or "").strip().lower()
            files.append(
                {
                    "path": path,
                    "size": max(0, int(item.get("Size", 0) or 0)),
                    "sha256": sha256 if _SHA256.fullmatch(sha256) else "",
                    "url": (
                        f"{MODEL_SCOPE_BASE_URL}/api/v1/models/{parse.quote(repo_id, safe='/')}/repo?"
                        + parse.urlencode({"Revision": revision, "FilePath": path})
                    ),
                }
            )
    if not files:
        raise ModelSourceUnavailable("ModelScope 上没有找到该模型或模型文件为空")
    return {
        "repo_id": repo_id,
        "source": "modelscope",
        "revision": commit or revision,
        "files": _preferred_weight_files(files),
    }


def _huggingface_manifest(repo_id: str) -> dict[str, Any]:
    endpoint = f"{HUGGING_FACE_BASE_URL}/api/models/{parse.quote(repo_id, safe='/')}/revision/main"
    payload = _read_json(endpoint)
    commit = str(payload.get("sha", "") or "main")
    files: list[dict[str, Any]] = []
    for raw in list(payload.get("siblings", []) or []):
        item = dict(raw or {})
        path = _safe_repo_path(item.get("rfilename"))
        if not path:
            continue
        lfs = dict(item.get("lfs", {}) or {})
        sha256 = str(lfs.get("sha256", "") or "").strip().lower()
        size = int(lfs.get("size", 0) or item.get("size", 0) or 0)
        files.append(
            {
                "path": path,
                "size": max(0, size),
                "sha256": sha256 if _SHA256.fullmatch(sha256) else "",
                "url": (
                    f"{HUGGING_FACE_BASE_URL}/{parse.quote(repo_id, safe='/')}/resolve/"
                    f"{parse.quote(commit, safe='')}/{parse.quote(path, safe='/')}"
                ),
            }
        )
    if not files:
        raise ModelSourceUnavailable("Hugging Face 上没有找到该模型或模型文件为空")
    return {
        "repo_id": repo_id,
        "source": "huggingface",
        "revision": commit,
        "files": _preferred_weight_files(files),
    }


def _preferred_weight_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Avoid downloading duplicate framework/quantization weight formats."""

    paths = {str(item["path"]).lower() for item in files}
    has_safetensors = any(path.endswith(".safetensors") for path in paths)
    output: list[dict[str, Any]] = []
    for item in files:
        path = str(item["path"])
        lowered = path.lower()
        if lowered.startswith((".git/", "onnx/", "openvino/")):
            continue
        if lowered.endswith((".h5", ".msgpack", ".ot", ".gguf")):
            continue
        if has_safetensors and lowered.endswith((".bin", ".pt", ".pth")):
            continue
        output.append(item)
    return output


def _install_manifest(
    manifest: dict[str, Any],
    *,
    cache_root: Path,
    progress_callback: ProgressCallback | None,
) -> Path:
    repo_id = _validate_model_id(str(manifest["repo_id"]))
    revision = _safe_revision(str(manifest["revision"]))
    folder = cache_root / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    target = folder / revision
    partial = folder / f".{revision}.partial"
    files = [dict(item) for item in list(manifest["files"])]
    total_bytes = sum(max(0, int(item.get("size", 0) or 0)) for item in files)
    folder.mkdir(parents=True, exist_ok=True)
    if _snapshot_complete(target, files):
        _emit_progress(
            progress_callback,
            repo_id=repo_id,
            source=str(manifest["source"]),
            state="ready",
            completed_bytes=total_bytes,
            total_bytes=total_bytes,
            file="",
        )
        return target
    partial.mkdir(parents=True, exist_ok=True)
    completed_bytes = sum(
        min(max(0, int(item.get("size", 0) or 0)), _partial_file_size(partial / str(item["path"])))
        for item in files
    )
    for item in files:
        relative = _safe_repo_path(item["path"])
        destination = partial.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected_size = max(0, int(item.get("size", 0) or 0))

        def on_file_progress(downloaded: int, *, _before=completed_bytes, _path=relative) -> None:
            _emit_progress(
                progress_callback,
                repo_id=repo_id,
                source=str(manifest["source"]),
                state="downloading",
                completed_bytes=min(total_bytes, _before + downloaded) if total_bytes else _before + downloaded,
                total_bytes=total_bytes,
                file=_path,
            )

        downloaded = _download_file(
            str(item["url"]),
            destination,
            expected_size=expected_size,
            expected_sha256=str(item.get("sha256", "") or ""),
            progress_callback=on_file_progress,
        )
        completed_bytes += downloaded
    marker = {
        "repo_id": repo_id,
        "source": str(manifest["source"]),
        "revision": str(manifest["revision"]),
        "files": [
            {
                "path": str(item["path"]),
                "size": int(item.get("size", 0) or 0),
                "sha256": str(item.get("sha256", "") or ""),
            }
            for item in files
        ],
        "installed_at": int(time.time()),
    }
    (partial / ".scansci-model.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if target.exists():
        invalid = folder / f".{revision}.invalid-{uuid4().hex[:8]}"
        target.replace(invalid)
    partial.replace(target)
    _emit_progress(
        progress_callback,
        repo_id=repo_id,
        source=str(manifest["source"]),
        state="ready",
        completed_bytes=total_bytes or completed_bytes,
        total_bytes=total_bytes or completed_bytes,
        file="",
    )
    return target


def _download_file(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    progress_callback: Callable[[int], None] | None,
) -> int:
    if destination.is_file() and _file_valid(destination, expected_size, expected_sha256):
        if progress_callback:
            progress_callback(expected_size or destination.stat().st_size)
        return expected_size or destination.stat().st_size
    partial = destination.with_name(destination.name + ".download")
    if partial.is_file() and expected_size and partial.stat().st_size > expected_size:
        partial.unlink(missing_ok=True)
    if partial.is_file() and _file_valid(partial, expected_size, expected_sha256):
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial.replace(destination)
        if progress_callback:
            progress_callback(expected_size or destination.stat().st_size)
        return expected_size or destination.stat().st_size
    if partial.is_file() and expected_size and partial.stat().st_size == expected_size:
        # A complete-length file with the wrong digest cannot be resumed.  A
        # Range request at EOF would return 416 forever, so restart only this
        # corrupt file while retaining every other verified file.
        partial.unlink(missing_ok=True)
    last_error: Exception | None = None
    for delay in _RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            offset = partial.stat().st_size if partial.is_file() else 0
            headers = {"User-Agent": "ScanSci/0.2 model downloader"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            response = request.urlopen(request.Request(url, headers=headers), timeout=60)  # noqa: S310
            status = int(getattr(response, "status", 200) or 200)
            if offset and status != 206:
                response.close()
                partial.unlink(missing_ok=True)
                offset = 0
                response = request.urlopen(  # noqa: S310
                    request.Request(url, headers={"User-Agent": "ScanSci/0.2 model downloader"}),
                    timeout=60,
                )
            mode = "ab" if offset else "wb"
            with response, partial.open(mode) as output:
                downloaded = offset
                if progress_callback:
                    progress_callback(downloaded)
                while chunk := response.read(_CHUNK_BYTES):
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded)
            if not _file_valid(partial, expected_size, expected_sha256):
                raise ModelDownloadError(f"{destination.name} 下载后校验失败")
            partial.replace(destination)
            return destination.stat().st_size
        except (DownloadPaused, DownloadCancelled):
            raise
        except Exception as exc:
            last_error = exc
    raise ModelDownloadError(f"{destination.name} 下载失败：{last_error}") from last_error


def _snapshot_complete(target: Path, files: Iterable[dict[str, Any]]) -> bool:
    if not target.is_dir():
        return False
    rows = list(files)
    return bool(rows) and all(
        _file_valid(
            target.joinpath(*PurePosixPath(str(item["path"])).parts),
            int(item.get("size", 0) or 0),
            str(item.get("sha256", "") or ""),
        )
        for item in rows
    )


def _file_valid(path: Path, expected_size: int, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    if expected_size and path.stat().st_size != expected_size:
        return False
    if expected_sha256 and _sha256(path) != expected_sha256:
        return False
    return True


def _partial_file_size(destination: Path) -> int:
    if destination.is_file():
        return destination.stat().st_size
    partial = destination.with_name(destination.name + ".download")
    return partial.stat().st_size if partial.is_file() else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(url: str) -> dict[str, Any]:
    req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "ScanSci/0.2"})
    try:
        with request.urlopen(req, timeout=20) as response:  # noqa: S310 - fixed official HTTPS hosts
            payload = response.read(_MAX_METADATA_BYTES + 1)
    except error.HTTPError as exc:
        raise ModelSourceUnavailable(f"HTTP {exc.code}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise ModelSourceUnavailable(str(exc)) from exc
    if len(payload) > _MAX_METADATA_BYTES:
        raise ModelSourceUnavailable("模型元数据异常过大")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ModelSourceUnavailable("模型元数据格式无效")
    return value


def _safe_repo_path(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not text:
        return ""
    candidate = PurePosixPath(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ModelSourceUnavailable("模型仓库包含不安全路径")
    return candidate.as_posix()


def _safe_revision(value: str) -> str:
    clean = "".join(character for character in value if character.isalnum() or character in "._-").strip(".-")
    return clean[:96] or "snapshot"


def _validate_model_id(value: str) -> str:
    clean = str(value or "").strip()
    if not _MODEL_ID.fullmatch(clean):
        raise ValueError("模型标识必须采用“组织/模型名”格式")
    return clean


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    repo_id: str,
    source: str,
    state: str,
    completed_bytes: int,
    total_bytes: int,
    file: str,
) -> None:
    if callback is None:
        return
    callback(
        {
            "id": repo_id,
            "source": source,
            "state": state,
            "completed_bytes": max(0, int(completed_bytes)),
            "total_bytes": max(0, int(total_bytes)),
            "progress": (
                min(1.0, max(0.0, completed_bytes / total_bytes))
                if total_bytes
                else 0.0
            ),
            "file": file,
        }
    )


class ModelInstallManager:
    """Run resumable model installs without blocking the desktop HTTP thread."""

    def __init__(
        self,
        *,
        cache_root: str | Path,
        ready_checker: Callable[[str], bool],
        downloader: Callable[..., dict[str, Any]] = download_snapshot,
        state_path: str | Path | None = None,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.ready_checker = ready_checker
        self.downloader = downloader
        self.state_path = Path(state_path or self.cache_root / ".scansci-download-jobs.json")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._callbacks: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._speed_samples: dict[str, tuple[str, int, float, float]] = {}
        self._controls: dict[str, str] = {}
        self._last_persist_at = 0.0
        self._load_jobs()

    def start(
        self,
        repo_ids: Iterable[str],
        *,
        job_id: str = "",
        source: str = "auto",
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        models = list(dict.fromkeys(_validate_model_id(item) for item in repo_ids))
        if not models:
            raise ValueError("至少需要一个模型")
        identifier = str(job_id or "|".join(models)).strip()[:180]
        with self._lock:
            existing = self._jobs.get(identifier)
            thread = self._threads.get(identifier)
            if existing and thread and thread.is_alive():
                if on_complete:
                    self._callbacks.setdefault(identifier, []).append(on_complete)
                return deepcopy(existing)
            self._controls.pop(identifier, None)
            ready = [model for model in models if self.ready_checker(model)]
            state = "ready" if len(ready) == len(models) else "queued"
            job = {
                "job_id": identifier,
                "state": state,
                "models": models,
                "current_model": "",
                "completed_models": ready,
                "total_models": len(models),
                "completed_bytes": 0,
                "total_bytes": 0,
                "current_file": "",
                "speed_bytes_per_second": 0.0,
                "eta_seconds": None,
                "progress": 1.0 if state == "ready" else len(ready) / len(models),
                "source": "",
                "requested_source": str(source or "auto"),
                "source_policy": "国内 ModelScope 优先，Hugging Face 备用",
                "message": "模型已在本机，无需重复下载" if state == "ready" else "正在准备下载",
                "error": "",
                "started_at": int(time.time()),
                "updated_at": int(time.time()),
            }
            self._jobs[identifier] = job
            self._persist_locked(force=True)
            if on_complete:
                self._callbacks.setdefault(identifier, []).append(on_complete)
            if state == "ready":
                callbacks = self._callbacks.pop(identifier, [])
            else:
                callbacks = []
                worker = threading.Thread(
                    target=self._run,
                    args=(identifier, source),
                    daemon=True,
                    name=f"scansci-model-install-{identifier[:32]}",
                )
                self._threads[identifier] = worker
                worker.start()
        for callback in callbacks:
            callback(deepcopy(job))
        return deepcopy(job)

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            if job_id:
                return self._status_snapshot(self._jobs.get(job_id, {"job_id": job_id, "state": "idle"}))
            rows = sorted(
                (self._status_snapshot(item) for item in self._jobs.values()),
                key=lambda item: int(item.get("updated_at", 0) or 0),
                reverse=True,
            )
            return {
                "jobs": rows,
                "active": next(
                    (item for item in rows if item.get("state") in {"queued", "downloading", "pausing", "cancelling"}),
                    None,
                ),
            }

    def pause(self, job_id: str) -> dict[str, Any]:
        return self._request_control(job_id, "pause")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._request_control(job_id, "cancel")

    def resume(self, job_id: str) -> dict[str, Any]:
        return self._restart(job_id, action="resume")

    def retry(self, job_id: str) -> dict[str, Any]:
        return self._restart(job_id, action="retry")

    def _request_control(self, job_id: str, action: str) -> dict[str, Any]:
        identifier = str(job_id or "").strip()
        if not identifier:
            raise ValueError("下载任务缺少 job_id")
        with self._lock:
            job = self._jobs.get(identifier)
            if job is None:
                raise ValueError(f"下载任务不存在：{identifier}")
            state = str(job.get("state", ""))
            if state in {"ready", "failed", "cancelled"}:
                if action == "cancel" and state == "cancelled":
                    return self._status_snapshot(job)
                raise ValueError(f"下载任务当前状态不支持{('暂停' if action == 'pause' else '取消')}：{state}")
            thread = self._threads.get(identifier)
            if thread is None or not thread.is_alive():
                job.update(
                    {
                        "state": "paused" if action == "pause" else "cancelled",
                        "message": (
                            "下载已暂停；恢复时会继续使用已下载的临时文件"
                            if action == "pause"
                            else "下载已取消；已有临时文件会保留，重试时可续传"
                        ),
                        "error": "",
                        "updated_at": int(time.time()),
                    }
                )
                self._persist_locked(force=True)
                return self._status_snapshot(job)
            self._controls[identifier] = action
            job.update(
                {
                    "state": "pausing" if action == "pause" else "cancelling",
                    "message": "正在暂停下载…" if action == "pause" else "正在取消下载…",
                    "updated_at": int(time.time()),
                }
            )
            self._persist_locked(force=True)
            return self._status_snapshot(job)

    def _restart(self, job_id: str, *, action: str) -> dict[str, Any]:
        identifier = str(job_id or "").strip()
        if not identifier:
            raise ValueError("下载任务缺少 job_id")
        with self._lock:
            job = self._jobs.get(identifier)
            if job is None:
                raise ValueError(f"下载任务不存在：{identifier}")
            thread = self._threads.get(identifier)
            if thread is not None and thread.is_alive():
                return self._status_snapshot(job)
            state = str(job.get("state", ""))
            if state == "ready":
                return self._status_snapshot(job)
            if state not in {"paused", "interrupted", "failed", "cancelled", "queued", "downloading"}:
                raise ValueError(f"下载任务当前状态不支持{action}：{state}")
            models = [str(item) for item in list(job.get("models", [])) if str(item).strip()]
            source = str(job.get("requested_source", "auto") or "auto")
        return self.start(models, job_id=identifier, source=source)

    def _check_control(self, job_id: str) -> None:
        with self._lock:
            action = self._controls.get(job_id, "")
        if action == "pause":
            raise DownloadPaused("用户已暂停下载")
        if action == "cancel":
            raise DownloadCancelled("用户已取消下载")

    def _run(self, job_id: str, source: str) -> None:
        try:
            with self._lock:
                job = self._jobs[job_id]
                models = list(job["models"])
            for index, model_id in enumerate(models):
                self._check_control(job_id)
                if self.ready_checker(model_id):
                    self._mark_model_ready(job_id, model_id)
                    continue

                def on_progress(event: dict[str, Any], *, _index=index, _model=model_id) -> None:
                    self._check_control(job_id)
                    with self._lock:
                        current = self._jobs[job_id]
                        now = time.time()
                        completed_bytes = int(event.get("completed_bytes", 0) or 0)
                        total_bytes = int(event.get("total_bytes", 0) or 0)
                        previous = self._speed_samples.get(job_id)
                        speed = float(current.get("speed_bytes_per_second", 0.0) or 0.0)
                        if previous and previous[0] == _model and completed_bytes >= previous[1] and now > previous[2]:
                            instant = (completed_bytes - previous[1]) / (now - previous[2])
                            if instant > 0:
                                speed = instant if previous[3] <= 0 else previous[3] * 0.72 + instant * 0.28
                        self._speed_samples[job_id] = (_model, completed_bytes, now, speed)
                        eta = (total_bytes - completed_bytes) / speed if total_bytes > completed_bytes and speed > 0 else None
                        current.update(
                            {
                                "state": "downloading",
                                "current_model": _model,
                                "current_file": str(event.get("file", "")),
                                "source": str(event.get("source", "")),
                                "completed_bytes": completed_bytes,
                                "total_bytes": total_bytes,
                                "speed_bytes_per_second": round(speed, 2),
                                "eta_seconds": round(eta) if eta is not None else None,
                                "progress": min(
                                    0.999,
                                    (_index + float(event.get("progress", 0.0) or 0.0)) / max(1, len(models)),
                                ),
                                "message": f"正在下载 {_model}",
                                "updated_at": int(now),
                            }
                        )
                        self._persist_locked()

                result = self.downloader(
                    model_id,
                    cache_root=self.cache_root,
                    source=source,
                    progress_callback=on_progress,
                )
                self._check_control(job_id)
                with self._lock:
                    self._jobs[job_id]["source"] = str(result.get("source", ""))
                    self._persist_locked(force=True)
                if not self.ready_checker(model_id):
                    raise ModelDownloadError(f"{model_id} 下载完成但未通过本地完整性检查")
                self._mark_model_ready(job_id, model_id)
            with self._lock:
                job = self._jobs[job_id]
                job.update(
                    {
                        "state": "ready",
                        "current_model": "",
                        "current_file": "",
                        "progress": 1.0,
                        "speed_bytes_per_second": 0.0,
                        "eta_seconds": 0,
                        "message": "下载、校验与本地发现均已完成",
                        "error": "",
                        "updated_at": int(time.time()),
                    }
                )
                self._persist_locked(force=True)
                callbacks = self._callbacks.pop(job_id, [])
                snapshot = deepcopy(job)
            for callback in callbacks:
                try:
                    callback(deepcopy(snapshot))
                except Exception:
                    continue
        except DownloadPaused as exc:
            self._finish_controlled_job(job_id, "paused", str(exc) or "用户已暂停下载")
        except DownloadCancelled as exc:
            self._finish_controlled_job(job_id, "cancelled", str(exc) or "用户已取消下载")
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.update(
                    {
                        "state": "failed",
                        "message": "下载未完成，可重试并续传已下载内容",
                        "error": f"{type(exc).__name__}: {exc}"[:1200],
                        "updated_at": int(time.time()),
                    }
                )
                self._persist_locked(force=True)
                self._callbacks.pop(job_id, None)

    def _finish_controlled_job(self, job_id: str, state: str, detail: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._controls.pop(job_id, None)
            job.update(
                {
                    "state": state,
                    "message": (
                        "下载已暂停；恢复时会继续使用已下载的临时文件"
                        if state == "paused"
                        else "下载已取消；已有临时文件会保留，重试时可续传"
                    ),
                    "error": "" if state == "paused" else detail[:1200],
                    "updated_at": int(time.time()),
                }
            )
            self._persist_locked(force=True)
            self._callbacks.pop(job_id, None)

    def _mark_model_ready(self, job_id: str, model_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            completed = list(job.get("completed_models", []))
            if model_id not in completed:
                completed.append(model_id)
            job["completed_models"] = completed
            job["progress"] = len(completed) / max(1, int(job.get("total_models", 1) or 1))
            job["message"] = f"已完成 {len(completed)}/{max(1, int(job.get('total_models', 1) or 1))} 个模型"
            job["updated_at"] = int(time.time())
            self._persist_locked(force=True)

    def _status_snapshot(self, job: dict[str, Any]) -> dict[str, Any]:
        snapshot = deepcopy(job)
        now = time.time()
        updated_at = float(snapshot.get("updated_at", 0) or 0)
        age = max(0, round(now - updated_at)) if updated_at else 0
        snapshot["last_update_seconds"] = age
        snapshot["stalled"] = bool(snapshot.get("state") in {"queued", "downloading"} and age >= 90)
        return snapshot

    def _load_jobs(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return
        changed = False
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            identifier = str(raw.get("job_id", "")).strip()
            models = [str(item) for item in raw.get("models", []) if isinstance(item, str)]
            if not identifier or not models:
                continue
            job = deepcopy(raw)
            ready = [model for model in models if self.ready_checker(model)]
            job["completed_models"] = ready
            if len(ready) == len(models):
                job.update({"state": "ready", "progress": 1.0, "message": "模型已在本机，无需重复下载", "error": ""})
            elif job.get("state") in {"queued", "downloading", "installing"}:
                job.update(
                    {
                        "state": "interrupted",
                        "message": "上次下载因应用退出而中断，可继续并断点续传；已有文件会自动复用",
                        "error": "",
                    }
                )
            job.setdefault("current_file", "")
            job.setdefault("speed_bytes_per_second", 0.0)
            job.setdefault("eta_seconds", None)
            job.setdefault("message", "")
            self._jobs[identifier] = job
            changed = True
        if changed:
            with self._lock:
                self._persist_locked(force=True)

    def _persist_locked(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist_at < 0.75:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = {"version": 1, "saved_at": int(time.time()), "jobs": list(self._jobs.values())}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
        self._last_persist_at = now
