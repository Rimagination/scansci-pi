"""Install and locate ScanSci's versioned local-model runtime component.

The desktop core deliberately does not bundle PyTorch or Transformers.  Those
packages live in a separately versioned sidecar that is downloaded once and
reused by later ScanSci desktop releases.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from .build_info import current_build_info
from .local_runtime_contract import COMPONENT_ID, COMPONENT_VERSION, EXECUTABLE_NAME


RUNTIME_MANIFEST_ENV = "SCANSCI_LOCAL_RUNTIME_MANIFEST_URL"
RUNTIME_EXECUTABLE_ENV = "SCANSCI_LOCAL_RUNTIME_EXECUTABLE"
UPDATE_MANIFEST_ENV = "SCANSCI_UPDATE_MANIFEST_URL"


class LocalRuntimeComponent:
    """Manage ScanSci's optional local Transformers sidecar after user approval."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        manifest_url: str | None = None,
        fallback_manifest_url: str | None = None,
    ) -> None:
        local_app_data = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        self.root = Path(root or Path(local_app_data) / "ScanSci" / "runtimes" / COMPONENT_ID).resolve()
        build = current_build_info()
        configured = (
            manifest_url
            if manifest_url is not None
            else os.getenv(RUNTIME_MANIFEST_ENV)
            or build.get("runtime_manifest_url")
            or fallback_manifest_url
            or os.getenv(UPDATE_MANIFEST_ENV)
            or ""
        )
        self.manifest_url = str(configured).strip()
        self._install_lock = threading.RLock()
        self._install_job: dict[str, Any] = {
            "job_id": "local-runtime",
            "state": "idle",
            "phase": "",
            "progress": 0.0,
            "message": "",
            "error": "",
            "current_file": "",
            "completed_bytes": 0,
            "total_bytes": 0,
            "speed_bytes_per_second": 0.0,
            "eta_seconds": None,
            "updated_at": int(time.time()),
        }
        self._install_thread: threading.Thread | None = None
        self._download_sample: tuple[int, float, float] | None = None
        self._last_install_persist_at = 0.0
        self._load_install_job()

    @property
    def active_path(self) -> Path:
        return self.root / "active.json"

    def executable(self) -> Path | None:
        override = os.getenv(RUNTIME_EXECUTABLE_ENV, "").strip()
        if override:
            candidate = Path(override).expanduser().resolve()
            return candidate if candidate.is_file() else None
        try:
            active = json.loads(self.active_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(active, dict):
            return None
        relative = str(active.get("executable", "")).strip()
        if not relative:
            return None
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def status(self) -> dict[str, Any]:
        executable = self.executable()
        build = current_build_info()
        source_runtime = not bool(build.get("frozen"))
        embedded_runtime = bool(build.get("frozen")) and build.get("package_profile") == "full"
        source_dependencies_ready = source_runtime and all(
            find_spec(module) is not None
            for module in ("torch", "transformers", "sentence_transformers")
        )
        installed = executable is not None
        version = ""
        if installed:
            try:
                active = json.loads(self.active_path.read_text(encoding="utf-8"))
                version = str(active.get("version", ""))
            except (OSError, json.JSONDecodeError):
                version = "external"
        mode = "component" if installed else "embedded" if embedded_runtime else "source" if source_dependencies_ready else "missing"
        return {
            "id": COMPONENT_ID,
            "version": version or (COMPONENT_VERSION if source_runtime or embedded_runtime else ""),
            "installed": bool(installed or source_dependencies_ready or embedded_runtime),
            "mode": mode,
            "executable": str(executable or ""),
            "install_available": bool(self.manifest_url),
            "manifest_configured": bool(self.manifest_url),
            "root": str(self.root),
            "install_job": self.install_status(),
        }

    def install_status(self) -> dict[str, Any]:
        with self._install_lock:
            snapshot = dict(self._install_job)
            updated_at = float(snapshot.get("updated_at", 0) or 0)
            age = max(0, round(time.time() - updated_at)) if updated_at else 0
            snapshot["last_update_seconds"] = age
            snapshot["stalled"] = bool(snapshot.get("state") in {"queued", "installing"} and age >= 90)
            return snapshot

    def start_install(self) -> dict[str, Any]:
        with self._install_lock:
            if self._install_thread is not None and self._install_thread.is_alive():
                return dict(self._install_job)
            self._install_job = {
                "job_id": "local-runtime",
                "state": "queued",
                "phase": "preparing",
                "progress": 0.0,
                "message": "准备 ScanSci 官方本地运行能力",
                "error": "",
                "started_at": time.time(),
                "updated_at": int(time.time()),
                "current_file": "",
                "completed_bytes": 0,
                "total_bytes": 0,
                "speed_bytes_per_second": 0.0,
                "eta_seconds": None,
            }
            self._download_sample = None
            self._persist_install_job(force=True)
            self._install_thread = threading.Thread(
                target=self._install_in_background,
                daemon=True,
                name="scansci-local-runtime-install",
            )
            self._install_thread.start()
            return dict(self._install_job)

    def _install_in_background(self) -> None:
        try:
            result = self.install(progress_callback=self._update_install_progress)
            with self._install_lock:
                self._install_job.update(
                    {
                        "state": "ready",
                        "phase": "ready",
                        "progress": 1.0,
                        "message": "ScanSci 本地运行能力已就绪",
                        "error": "",
                        "result": result,
                        "finished_at": time.time(),
                        "updated_at": int(time.time()),
                        "speed_bytes_per_second": 0.0,
                        "eta_seconds": 0,
                    }
                )
                self._persist_install_job(force=True)
        except Exception as exc:
            with self._install_lock:
                self._install_job.update(
                    {
                        "state": "failed",
                        "phase": "failed",
                        "message": "安装未完成",
                        "error": str(exc),
                        "finished_at": time.time(),
                        "updated_at": int(time.time()),
                    }
                )
                self._persist_install_job(force=True)

    def _update_install_progress(
        self,
        phase: str,
        progress: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._install_lock:
            details = details or {}
            now = time.time()
            completed = int(details.get("completed_bytes", self._install_job.get("completed_bytes", 0)) or 0)
            total = int(details.get("total_bytes", self._install_job.get("total_bytes", 0)) or 0)
            speed = float(self._install_job.get("speed_bytes_per_second", 0.0) or 0.0)
            if phase == "download":
                previous = self._download_sample
                if previous and completed >= previous[0] and now > previous[1]:
                    instant = (completed - previous[0]) / (now - previous[1])
                    if instant > 0:
                        speed = instant if previous[2] <= 0 else previous[2] * 0.72 + instant * 0.28
                self._download_sample = (completed, now, speed)
            eta = (total - completed) / speed if total > completed and speed > 0 else None
            self._install_job.update(
                {
                    "state": "installing",
                    "phase": phase,
                    "progress": max(0.0, min(1.0, float(progress))),
                    "message": message,
                    "current_file": str(details.get("current_file", self._install_job.get("current_file", ""))),
                    "completed_bytes": completed,
                    "total_bytes": total,
                    "speed_bytes_per_second": round(speed, 2),
                    "eta_seconds": round(eta) if eta is not None else None,
                    "updated_at": int(now),
                }
            )
            self._persist_install_job()

    @property
    def install_job_path(self) -> Path:
        return self.root / "install-job.json"

    def _load_install_job(self) -> None:
        try:
            payload = json.loads(self.install_job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("job_id") != "local-runtime":
            return
        if payload.get("state") in {"queued", "installing"}:
            payload.update(
                {
                    "state": "interrupted",
                    "message": "上次安装因应用退出而中断，可继续安装并断点续传；已下载内容会自动复用",
                    "error": "",
                    "updated_at": int(time.time()),
                }
            )
        self._install_job.update(payload)
        self._persist_install_job(force=True)

    def _persist_install_job(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_install_persist_at < 0.75:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.install_job_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._install_job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.install_job_path)
        self._last_install_persist_at = now

    def ensure_installed(self) -> Path | None:
        """Return an active component without starting a download.

        ``install()`` is deliberately the only operation that may fetch the
        optional runtime. Importing a library, opening a conversation, or
        checking an index must never become an unannounced installation.
        """

        executable = self.executable()
        if executable is not None:
            return executable
        build = current_build_info()
        if not bool(build.get("frozen")):
            if self.status().get("installed"):
                return None
            raise RuntimeError("当前源代码环境缺少本地 AI 运行依赖。请安装运行组件或配置外部本地运行时。")
        if build.get("package_profile") == "full":
            return None
        if not self.manifest_url:
            raise RuntimeError("本地 AI 组件尚未安装，当前发行渠道也没有提供组件下载清单。")
        raise RuntimeError("本地 AI 组件尚未安装。请在设置中确认安装后再下载本地模型。")

    def install(self, progress_callback=None) -> dict[str, Any]:
        """Download, verify, and atomically activate one runtime version."""

        if not self.manifest_url:
            raise RuntimeError("当前发行渠道没有配置本地 AI 组件下载清单。")
        with self._process_install_lock():
            return self._install_component(progress_callback=progress_callback)

    def _install_component(self, progress_callback=None) -> dict[str, Any]:
        self._emit_progress(progress_callback, "manifest", 0.02, "读取官方组件清单")
        manifest = self._read_json(self.manifest_url)
        component = self._component_record(manifest)
        version = str(component.get("version", "")).strip()
        package = component.get("windows", {})
        if not version or not isinstance(package, dict):
            raise RuntimeError("本地 AI 组件清单缺少版本或 Windows 包。")
        expected = str(package.get("sha256", "")).strip().lower()
        if not self._is_sha256(expected):
            raise RuntimeError("本地 AI 组件清单缺少有效的 SHA256。")

        self.root.mkdir(parents=True, exist_ok=True)
        downloads = self.root / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / f"{COMPONENT_ID}-{version}.zip"
        if not archive.is_file() or self._sha256(archive) != expected:
            archive.unlink(missing_ok=True)
            self._acquire_package(package, archive, expected, progress_callback=progress_callback)
        else:
            self._emit_progress(progress_callback, "download", 0.78, "复用已校验的组件归档")

        versions = self.root / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / self._safe_segment(version)
        if not (target / EXECUTABLE_NAME).is_file():
            self._emit_progress(progress_callback, "extract", 0.86, "解压本地运行能力")
            staging = Path(tempfile.mkdtemp(prefix="install-", dir=self.root)).resolve()
            try:
                matches = self._extract_verified(archive, staging)
                if len(matches) != 1:
                    raise RuntimeError(f"本地 AI 组件包必须只包含一个 {EXECUTABLE_NAME}。")
                payload = matches[0].parent
                if target.exists():
                    invalid = versions / f"{target.name}.invalid-{uuid4().hex[:8]}"
                    target.replace(invalid)
                shutil.move(str(payload), str(target))
            finally:
                self._remove_private_tree(staging)

        diagnostics = package.get("diagnostics")
        self._emit_progress(progress_callback, "diagnostics", 0.95, "验证运行依赖")
        diagnostic_result = self._run_diagnostics(target / EXECUTABLE_NAME, diagnostics)
        active_payload = {
            "id": COMPONENT_ID,
            "version": version,
            "executable": str((target / EXECUTABLE_NAME).relative_to(self.root)),
            "sha256": expected,
            "diagnostics": diagnostic_result,
        }
        temporary = self.active_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(active_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.active_path)
        self._emit_progress(progress_callback, "ready", 1.0, "ScanSci 本地运行能力已就绪")
        return {**self.status(), "installed": True}

    def _acquire_package(
        self,
        package: dict[str, Any],
        archive: Path,
        expected: str,
        *,
        progress_callback=None,
    ) -> None:
        parts = package.get("parts")
        if isinstance(parts, list) and parts:
            if len(parts) > 128:
                raise RuntimeError("本地 AI 组件分片数量异常。")
            downloaded: list[Path] = []
            total_bytes = sum(max(0, int(dict(record).get("size", 0) or 0)) for record in parts if isinstance(record, dict))
            completed_bytes = 0
            for index, record in enumerate(parts, start=1):
                if not isinstance(record, dict):
                    raise RuntimeError("本地 AI 组件分片清单格式无效。")
                url = str(record.get("url", "")).strip()
                checksum = str(record.get("sha256", "")).strip().lower()
                size = int(record.get("size", 0) or 0)
                if not url or not self._is_sha256(checksum) or size < 1:
                    raise RuntimeError("本地 AI 组件分片缺少有效的地址、大小或 SHA256。")
                destination = archive.with_suffix(f".zip.part{index:03d}")
                if (
                    not destination.is_file()
                    or destination.stat().st_size != size
                    or self._sha256(destination) != checksum
                ):
                    destination.unlink(missing_ok=True)
                    self._download(
                        url,
                        destination,
                        progress_callback=lambda received, _total, before=completed_bytes: self._emit_download_progress(
                            progress_callback,
                            before + received,
                            total_bytes,
                            current_file=destination.name,
                        ),
                    )
                if destination.stat().st_size != size or self._sha256(destination) != checksum:
                    destination.unlink(missing_ok=True)
                    raise RuntimeError(f"本地 AI 组件第 {index} 个分片校验失败，已取消安装。")
                downloaded.append(destination)
                completed_bytes += size
                self._emit_download_progress(progress_callback, completed_bytes, total_bytes)
            temporary = archive.with_suffix(".zip.assembling")
            temporary.unlink(missing_ok=True)
            with temporary.open("wb") as output:
                for part in downloaded:
                    with part.open("rb") as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            temporary.replace(archive)
        else:
            url = str(package.get("url", "")).strip()
            if not url:
                raise RuntimeError("本地 AI 组件清单缺少有效的下载地址。")
            expected_size = int(package.get("size", 0) or 0)
            self._download(
                url,
                archive,
                progress_callback=lambda received, total: self._emit_download_progress(
                    progress_callback,
                    received,
                    expected_size or total,
                    current_file=archive.name,
                ),
            )

        self._emit_progress(progress_callback, "verify", 0.82, "校验组件完整性")
        expected_size = int(package.get("size", 0) or 0)
        if expected_size and archive.stat().st_size != expected_size:
            archive.unlink(missing_ok=True)
            raise RuntimeError("本地 AI 组件大小校验失败，已取消安装。")
        if self._sha256(archive) != expected:
            archive.unlink(missing_ok=True)
            raise RuntimeError("本地 AI 组件校验失败，已取消安装。")

    def _run_diagnostics(self, executable: Path, diagnostics: object) -> dict[str, Any]:
        if not isinstance(diagnostics, dict):
            return {"status": "not_requested"}
        raw_args = diagnostics.get("args")
        if not isinstance(raw_args, list) or not raw_args or not all(isinstance(arg, str) for arg in raw_args):
            raise RuntimeError("本地 AI 组件自检配置无效。")
        timeout = max(10, min(int(diagnostics.get("timeout_seconds", 180) or 180), 600))
        report = executable.parent / "diagnostics.json"
        args = [arg.replace("{output}", str(report)) for arg in raw_args]
        try:
            completed = subprocess.run(
                [str(executable), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"本地 AI 组件自检未能完成：{exc}") from exc
        try:
            result = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"本地 AI 组件没有生成有效的自检报告（退出码 {completed.returncode}）。"
            ) from exc
        if completed.returncode != 0 or not isinstance(result, dict) or not result.get("ok"):
            detail = str(result.get("error", "") if isinstance(result, dict) else "").strip()
            raise RuntimeError(f"本地 AI 组件自检失败。{detail}".rstrip())
        return result

    @staticmethod
    def _component_record(manifest: dict[str, Any]) -> dict[str, Any]:
        if str(manifest.get("id", "")) == COMPONENT_ID:
            return manifest
        components = manifest.get("components", {})
        if isinstance(components, dict) and isinstance(components.get(COMPONENT_ID), dict):
            return dict(components[COMPONENT_ID])
        raise RuntimeError(f"发行清单中没有 {COMPONENT_ID} 组件。")

    @staticmethod
    def _validate_url(url: str) -> None:
        if urlparse(url).scheme.lower() not in {"https", "file"}:
            raise ValueError("组件地址必须使用 HTTPS。")

    @classmethod
    def _read_json(cls, url: str) -> dict[str, Any]:
        cls._validate_url(url)
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "ScanSci local runtime"})
        with urlopen(req, timeout=12) as response:  # noqa: S310 - scheme validated above
            payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            raise ValueError("组件清单过大。")
        result = json.loads(payload.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("组件清单必须是 JSON 对象。")
        return result

    @classmethod
    def _download(cls, url: str, destination: Path, progress_callback=None) -> None:
        cls._validate_url(url)
        temporary = Path(f"{destination}.download")
        resumed = temporary.stat().st_size if temporary.is_file() else 0
        headers = {"User-Agent": "ScanSci local runtime"}
        if resumed:
            headers["Range"] = f"bytes={resumed}-"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=300) as response:  # noqa: S310
            content_range = str(response.headers.get("Content-Range", ""))
            accepted_range = resumed > 0 and content_range.lower().startswith(f"bytes {resumed}-")
            if resumed and not accepted_range:
                resumed = 0
            remaining = int(response.headers.get("Content-Length", 0) or 0)
            total = resumed + remaining if remaining else 0
            received = resumed
            mode = "ab" if accepted_range else "wb"
            output = temporary.open(mode)
            try:
                if progress_callback is not None:
                    progress_callback(received, total)
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    received += len(chunk)
                    if progress_callback is not None:
                        progress_callback(received, total)
            finally:
                output.close()
        temporary.replace(destination)

    @staticmethod
    def _is_sha256(value: str) -> bool:
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    @staticmethod
    def _emit_progress(
        callback,
        phase: str,
        progress: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if callback is not None:
            try:
                callback(phase, progress, message, details or {})
            except TypeError:
                callback(phase, progress, message)

    @classmethod
    def _emit_download_progress(
        cls,
        callback,
        received: int,
        total: int,
        *,
        current_file: str = "",
    ) -> None:
        ratio = min(1.0, received / total) if total > 0 else 0.0
        percent = max(0, min(100, round(ratio * 100)))
        cls._emit_progress(
            callback,
            "download",
            0.05 + 0.73 * ratio,
            f"下载官方组件 {percent}%",
            {
                "current_file": current_file,
                "completed_bytes": max(0, int(received)),
                "total_bytes": max(0, int(total)),
            },
        )

    @classmethod
    def _extract_verified(cls, archive_path: Path, destination: Path) -> list[Path]:
        executable_paths: list[Path] = []
        try:
            with ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    name = PurePosixPath(info.filename.replace("\\", "/"))
                    if name.is_absolute() or ".." in name.parts:
                        raise RuntimeError("本地 AI 组件包包含不安全路径。")
                    if not name.parts:
                        continue
                    unix_mode = info.external_attr >> 16
                    if unix_mode and stat.S_ISLNK(unix_mode):
                        raise RuntimeError("本地 AI 组件包不能包含符号链接。")
                    target = destination.joinpath(*name.parts)
                    if info.is_dir():
                        os.makedirs(cls._extended_windows_path(target), exist_ok=True)
                        continue
                    os.makedirs(cls._extended_windows_path(target.parent), exist_ok=True)
                    with archive.open(info, "r") as source, open(cls._extended_windows_path(target), "wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if name.name == EXECUTABLE_NAME:
                        executable_paths.append(target)
        except BadZipFile as exc:
            raise RuntimeError("本地 AI 组件包不是有效的 ZIP 文件。") from exc
        return executable_paths

    @staticmethod
    def _extended_windows_path(path: Path) -> str:
        resolved = str(path.resolve())
        if os.name != "nt" or resolved.startswith("\\\\?\\"):
            return resolved
        if resolved.startswith("\\\\"):
            return "\\\\?\\UNC\\" + resolved.lstrip("\\")
        return "\\\\?\\" + resolved

    @contextmanager
    def _process_install_lock(self):
        """Prevent two ScanSci processes from mutating one runtime root."""

        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "install.lock"
        stream = lock_path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        locked = False
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RuntimeError("另一个 ScanSci 窗口正在安装本地运行组件，请等待当前安装完成。") from exc
            else:
                import fcntl

                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise RuntimeError("另一个 ScanSci 进程正在安装本地运行组件，请等待当前安装完成。") from exc
            locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def _remove_private_tree(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError("拒绝清理运行时目录之外的临时路径。") from exc
        if resolved.name.startswith("install-"):
            shutil.rmtree(self._extended_windows_path(resolved), ignore_errors=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_segment(value: str) -> str:
        clean = "".join(ch for ch in value if ch.isalnum() or ch in ".-_").strip(".-")
        return clean or uuid4().hex
