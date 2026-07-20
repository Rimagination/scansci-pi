"""Runtime identity for distinguishing source, preview, and packaged builds."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .app_update import APP_VERSION


def current_build_info() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": APP_VERSION,
        "build_id": "source",
        "built_at": "",
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": Path(sys.executable).name,
    }
    candidates = [
        Path(__file__).with_name("build-info.json"),
        Path(getattr(sys, "_MEIPASS", "")) / "scansci_html" / "build-info.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            stored = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(stored, dict):
            payload.update({str(key): value for key, value in stored.items() if key in {"version", "build_id", "built_at", "commit"}})
            break
    return payload
