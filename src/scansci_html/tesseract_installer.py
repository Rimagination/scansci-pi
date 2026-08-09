"""Small, user-initiated installer for ScanSci's default OCR backend.

The main installer deliberately does not embed Tesseract.  This manager keeps
that package lightweight while giving the settings page a real one-click
repair path: install the Windows engine with winget when necessary, then place
the requested official language data in ScanSci's per-user data directory.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Callable

import requests

from .vision_routing import _tesseract_language_ids, _tesseract_path, tesseract_status


_LANGUAGE_URLS = {
    "chi_sim": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata",
    "eng": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
}


def _user_tessdata_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    return base / "ScanSci" / "tessdata"


class TesseractInstallManager:
    """Install or repair Tesseract without blocking the local HTTP server."""

    def __init__(
        self,
        *,
        tessdata_dir: str | Path | None = None,
        status_provider: Callable[[list[str] | None], dict[str, Any]] = tesseract_status,
    ) -> None:
        self.tessdata_dir = Path(tessdata_dir).resolve() if tessdata_dir else _user_tessdata_dir()
        self._status_provider = status_provider
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._job: dict[str, Any] = {
            "state": "idle",
            "progress": 0.0,
            "message": "",
            "error": "",
            "languages": [],
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._job)

    def start(self, languages: list[str] | None = None) -> dict[str, Any]:
        requested = [value for value in _tesseract_language_ids(languages or ["zh", "en"]) if value in _LANGUAGE_URLS]
        requested = list(dict.fromkeys(requested)) or ["eng"]
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return deepcopy(self._job)
            self._job = {
                "state": "queued",
                "progress": 0.01,
                "message": "正在准备 Tesseract OCR",
                "error": "",
                "languages": requested,
            }
            self._thread = threading.Thread(target=self._run, args=(requested,), daemon=True)
            self._thread.start()
            return deepcopy(self._job)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._job.update(changes)

    def _run(self, languages: list[str]) -> None:
        try:
            command = _tesseract_path()
            if not command:
                self._update(state="installing", progress=0.08, message="正在安装 Tesseract OCR 引擎")
                self._install_windows_engine()
                command = _tesseract_path()
            if not command:
                raise RuntimeError("安装完成后仍未检测到 Tesseract OCR，请重新启动 ScanSci 后重试。")

            self.tessdata_dir.mkdir(parents=True, exist_ok=True)
            for index, language in enumerate(languages, start=1):
                progress = 0.2 + (index - 1) / max(1, len(languages)) * 0.65
                self._update(
                    state="downloading",
                    progress=progress,
                    message=f"正在准备 {language} 识别语言",
                )
                self._ensure_language(Path(command), language)

            verified = self._status_provider(languages)
            missing = list(verified.get("missing_languages", []) or [])
            if not verified.get("available") or missing:
                detail = f"缺少：{', '.join(map(str, missing))}" if missing else "引擎不可用"
                raise RuntimeError(f"Tesseract 安装校验未通过（{detail}）")
            self._update(
                state="ready",
                progress=1.0,
                message="Tesseract OCR 已就绪",
                error="",
            )
        except Exception as exc:
            self._update(
                state="failed",
                message="Tesseract OCR 安装未完成",
                error=str(exc).strip()[:800] or type(exc).__name__,
            )

    def _install_windows_engine(self) -> None:
        if os.name != "nt":
            raise RuntimeError("当前平台请先使用系统包管理器安装 Tesseract。")
        winget = shutil.which("winget")
        if not winget:
            raise RuntimeError("未检测到 winget，无法自动安装 Tesseract。")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        completed = subprocess.run(
            [
                winget,
                "install",
                "--id",
                "UB-Mannheim.TesseractOCR",
                "--exact",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "winget 未返回详细信息").strip()[-600:]
            raise RuntimeError(f"winget 安装 Tesseract 失败：{detail}")

    def _ensure_language(self, command: Path, language: str) -> None:
        target = self.tessdata_dir / f"{language}.traineddata"
        if target.is_file() and target.stat().st_size > 1024:
            return
        system_copy = command.parent / "tessdata" / target.name
        temporary = target.with_suffix(".traineddata.download")
        temporary.unlink(missing_ok=True)
        if system_copy.is_file() and system_copy.stat().st_size > 1024:
            shutil.copy2(system_copy, temporary)
        else:
            url = _LANGUAGE_URLS[language]
            with requests.get(url, stream=True, timeout=(15, 180)) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            output.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size <= 1024:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"{language} 语言数据下载不完整")
        temporary.replace(target)
