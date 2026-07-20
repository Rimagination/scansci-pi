from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any


CLOAKBROWSER_CACHE_ENV = "CLOAKBROWSER_CACHE_DIR"
SCANSCI_CACHE_ENV = "SCANSCI_HTML_CLOAKBROWSER_CACHE_DIR"
DEFAULT_CACHE_DIR = Path.home() / ".scansci-html" / "cloakbrowser"


def configure_builtin_cloakbrowser(
    cache_dir: str | os.PathLike[str] | None = None,
    *,
    create_dir: bool = True,
) -> Path:
    existing = os.environ.get(CLOAKBROWSER_CACHE_ENV)
    if existing:
        return Path(existing)

    target = Path(cache_dir or os.environ.get(SCANSCI_CACHE_ENV, "") or DEFAULT_CACHE_DIR)
    target = target.expanduser().resolve()
    if create_dir:
        target.mkdir(parents=True, exist_ok=True)
    os.environ[CLOAKBROWSER_CACHE_ENV] = str(target)
    return target


def prepare_cloakbrowser_runtime(config_module: Any | None = None) -> Path:
    cache_dir = configure_builtin_cloakbrowser()
    ensure_cloakbrowser_platform_compatible(config_module)
    return cache_dir


def ensure_cloakbrowser_platform_compatible(config_module: Any | None = None) -> bool:
    if platform.system() != "Windows" or platform.machine():
        return False

    try:
        config = config_module
        if config is None:
            from cloakbrowser import config as config  # type: ignore[no-redef]
    except Exception:
        return False

    supported = getattr(config, "SUPPORTED_PLATFORMS", None)
    if not isinstance(supported, dict) or ("Windows", "") in supported:
        return False

    is_64bit_windows = bool(os.environ.get("ProgramFiles(x86)")) or bool(
        os.environ.get("PROCESSOR_ARCHITEW6432")
    )
    if not is_64bit_windows:
        return False

    supported[("Windows", "")] = supported.get(("Windows", "AMD64"), "windows-x64")
    return True
