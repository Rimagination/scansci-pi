"""Version checks and verified Windows desktop updates for ScanSci."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import BadZipFile, ZipFile


APP_VERSION = "0.2.2"
UPDATE_MANIFEST_ENV = "SCANSCI_UPDATE_MANIFEST_URL"
_USER_AGENT = f"ScanSci/{APP_VERSION} Windows"
_DEFAULT_RELEASE_NOTES = [
    {
        "title": "资源下载",
        "items": [
            "修复研究检索组件可能把错误响应写成模型文件的问题。",
            "断点续传只复用已校验片段，并分别显示整组与当前模型进度。",
        ],
    },
    {
        "title": "软件状态问答",
        "items": [
            "询问失败的下载任务时，直接读取本机任务记录，不再误进论文检索。",
            "回答会给出组件、模型、文件、来源、失败原因和重试位置。",
        ],
    },
]


class AppUpdateService:
    """Read a release manifest and prepare a verified self-update."""

    def __init__(
        self,
        *,
        manifest_url: str | None = None,
        current_version: str = APP_VERSION,
        updates_root: str | Path | None = None,
    ) -> None:
        self.current_version = current_version
        self.manifest_url = str(manifest_url if manifest_url is not None else os.getenv(UPDATE_MANIFEST_ENV, "")).strip()
        local_root = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        self.updates_root = Path(updates_root or Path(local_root) / "ScanSciPi" / "updates").resolve()
        self._manifest: dict[str, Any] | None = None
        self._status = self._current_status()

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    def check(self) -> dict[str, Any]:
        if not self.manifest_url:
            self._status = self._current_status(checked=True)
            return self.status()
        try:
            manifest = self._read_manifest(self.manifest_url)
            self._manifest = manifest
            self._status = self._status_from_manifest(manifest)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._status = {
                **self._current_status(checked=True),
                "state": "error",
                "message": "暂时无法检查更新",
                "error": str(error),
            }
        return self.status()

    def install(self, *, relaunch_args: list[str] | None = None) -> dict[str, Any]:
        """Download, verify and schedule a Windows onedir replacement."""

        status = self._status
        if not status.get("available"):
            raise RuntimeError("当前没有可安装的 ScanSci 更新。")
        if not getattr(sys, "frozen", False):
            raise RuntimeError("源码预览不会覆盖安装目录，请在 ScanSci 桌面应用中更新。")
        if sys.platform != "win32":
            raise RuntimeError("当前自动更新器仅支持 Windows 桌面版。")

        package = self._windows_package(self._manifest or {})
        package_url = str(package.get("url", "")).strip()
        expected_sha256 = str(package.get("sha256", "")).strip().lower()
        if not package_url or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise RuntimeError("更新清单缺少经过校验的 Windows 安装包。")

        version = str(status.get("latest_version", "update"))
        update_dir = self.updates_root / _safe_segment(version)
        update_dir.mkdir(parents=True, exist_ok=True)
        archive = update_dir / "ScanSci-update.zip"
        self._download(package_url, archive)
        actual_sha256 = _sha256(archive)
        if actual_sha256 != expected_sha256:
            archive.unlink(missing_ok=True)
            raise RuntimeError("更新包校验失败，已取消安装。")
        _validate_release_archive(archive)

        executable = Path(sys.executable).resolve()
        install_dir = executable.parent
        helper = update_dir / "apply-update.ps1"
        arguments_path = update_dir / "relaunch-args.json"
        arguments_path.write_text(json.dumps(list(relaunch_args or []), ensure_ascii=False), encoding="utf-8")
        helper.write_text(_UPDATER_SCRIPT, encoding="utf-8-sig")

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(helper),
            "-ParentPid",
            str(os.getpid()),
            "-Archive",
            str(archive),
            "-InstallDir",
            str(install_dir),
            "-ExecutableName",
            executable.name,
            "-RelaunchArgsPath",
            str(arguments_path),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(command, creationflags=creation_flags, close_fds=True)  # noqa: S603 - fixed local helper
        return {
            **status,
            "state": "restarting",
            "message": "更新已验证，ScanSci 即将重新启动",
            "archive": str(archive),
        }

    def _current_status(self, *, checked: bool = False) -> dict[str, Any]:
        return {
            "state": "idle" if not self.manifest_url else "current",
            "available": False,
            "current_version": self.current_version,
            "latest_version": self.current_version,
            "release_title": f"ScanSci {self.current_version}",
            "published_at": "",
            "release_notes": _DEFAULT_RELEASE_NOTES,
            "can_install": False,
            "channel": "稳定版",
            "message": f"当前版本 v{self.current_version}" if not self.manifest_url else "当前已是最新版本",
            "checked_at": _now_iso() if checked else "",
        }

    def _status_from_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        latest = str(manifest.get("version", "")).strip()
        if not latest:
            raise ValueError("更新清单缺少 version。")
        available = _version_key(latest) > _version_key(self.current_version)
        package = self._windows_package(manifest)
        notes = _normalise_release_notes(manifest.get("notes")) or _DEFAULT_RELEASE_NOTES
        return {
            "state": "available" if available else "current",
            "available": available,
            "current_version": self.current_version,
            "latest_version": latest if available else self.current_version,
            "release_title": str(manifest.get("title", "")).strip() or f"ScanSci {latest}",
            "published_at": str(manifest.get("published_at", "")).strip(),
            "release_notes": notes,
            "can_install": bool(available and package.get("url") and package.get("sha256")),
            "channel": str(manifest.get("channel", "稳定版")).strip() or "稳定版",
            "message": "有可用更新" if available else "当前已是最新版本",
            "checked_at": _now_iso(),
        }

    @staticmethod
    def _windows_package(manifest: dict[str, Any]) -> dict[str, Any]:
        package = manifest.get("windows", {})
        return package if isinstance(package, dict) else {}

    @staticmethod
    def _read_manifest(url: str) -> dict[str, Any]:
        _validate_update_url(url, allow_file=True)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT})
        with urlopen(request, timeout=8) as response:  # noqa: S310 - scheme is validated above
            payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            raise ValueError("更新清单过大。")
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("更新清单必须是 JSON 对象。")
        return parsed

    @staticmethod
    def _download(url: str, destination: Path) -> None:
        _validate_update_url(url, allow_file=True)
        request = Request(url, headers={"User-Agent": _USER_AGENT})
        temporary = destination.with_suffix(".download")
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:  # noqa: S310
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(destination)


def _normalise_release_notes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sections: list[dict[str, Any]] = []
    for raw in value[:8]:
        if not isinstance(raw, dict):
            continue
        items = [str(item).strip() for item in raw.get("items", []) if str(item).strip()][:16]
        if items:
            sections.append({"title": str(raw.get("title", "更新内容")).strip() or "更新内容", "items": items})
    return sections


def _validate_update_url(url: str, *, allow_file: bool = False) -> None:
    parsed = urlparse(url)
    allowed = {"https"}
    if allow_file:
        allowed.add("file")
    if parsed.scheme.lower() not in allowed:
        raise ValueError("更新地址必须使用 HTTPS。")


def _version_key(value: str) -> tuple[tuple[int, ...], int, str]:
    clean = value.strip().lstrip("vV")
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:[-+]?([0-9A-Za-z.-]+))?", clean)
    if not match:
        raise ValueError(f"无效版本号：{value}")
    number_parts = [int(part) for part in match.group(1).split(".")]
    while len(number_parts) > 1 and number_parts[-1] == 0:
        number_parts.pop()
    numbers = tuple(number_parts)
    prerelease = match.group(2) or ""
    return numbers, 1 if not prerelease else 0, prerelease


def _safe_segment(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip(".-") or uuid4().hex


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_release_archive(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            names = [PurePosixPath(name.replace("\\", "/")) for name in archive.namelist()]
            if not names or any(name.is_absolute() or ".." in name.parts for name in names):
                raise ValueError("更新包包含不安全路径。")
            if not any(name.name.lower() == "scansci.exe" for name in names):
                raise ValueError("更新包中没有 ScanSci.exe。")
    except BadZipFile as error:
        raise ValueError("更新包不是有效的 ZIP 文件。") from error


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_UPDATER_SCRIPT = r'''param(
  [Parameter(Mandatory = $true)][int]$ParentPid,
  [Parameter(Mandatory = $true)][string]$Archive,
  [Parameter(Mandatory = $true)][string]$InstallDir,
  [Parameter(Mandatory = $true)][string]$ExecutableName,
  [Parameter(Mandatory = $true)][string]$RelaunchArgsPath
)
$ErrorActionPreference = "Stop"
Wait-Process -Id $ParentPid -Timeout 180 -ErrorAction SilentlyContinue
$staging = Join-Path ([IO.Path]::GetTempPath()) ("ScanSci-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $staging -Force
$payload = $staging
$children = @(Get-ChildItem -LiteralPath $staging)
if ($children.Count -eq 1 -and $children[0].PSIsContainer -and (Test-Path -LiteralPath (Join-Path $children[0].FullName $ExecutableName))) {
  $payload = $children[0].FullName
}
if (-not (Test-Path -LiteralPath (Join-Path $payload $ExecutableName) -PathType Leaf)) {
  throw "The update package does not contain $ExecutableName"
}
$backup = $InstallDir + ".previous-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Move-Item -LiteralPath $InstallDir -Destination $backup
Move-Item -LiteralPath $payload -Destination $InstallDir
$relaunchArgs = @(Get-Content -Raw -LiteralPath $RelaunchArgsPath | ConvertFrom-Json)
$quotedArgs = (($relaunchArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' ')
Start-Process -FilePath (Join-Path $InstallDir $ExecutableName) -ArgumentList $quotedArgs -WorkingDirectory $InstallDir
'''
