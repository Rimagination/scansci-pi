from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from .browser_config import BrowserIdentityConfig
from .browser_identity import (
    browser_extension_paths,
    browser_launch_args,
    build_profile_identity,
    ensure_profile_identity,
)


class BrowserRuntime(Protocol):
    def launch(self) -> "BrowserSession":
        ...


class BrowserSession:
    def __init__(self, *, context: object, source: str, runtime: object | None = None) -> None:
        self.context = context
        self.source = source
        self.runtime = runtime

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            if self.runtime is not None:
                self.runtime.stop()


class BrowserSessionBroker:
    """Own one live browser context for a batch and reopen only if it dies."""

    def __init__(self, runtime: BrowserRuntime) -> None:
        self.runtime = runtime
        self._session: BrowserSession | None = None

    def get_session(self) -> BrowserSession:
        if self._session is None:
            self._session = self.runtime.launch()
        return self._session

    def new_page(self) -> tuple[BrowserSession, object]:
        session = self.get_session()
        try:
            return session, session.context.new_page()
        except Exception:
            self.close()
            session = self.get_session()
            return session, session.context.new_page()

    def close(self) -> None:
        session = self._session
        if session is None:
            return
        self._session = None
        session.close()

    def __enter__(self) -> "BrowserSessionBroker":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()


class CloakBrowserRuntime:
    def __init__(
        self,
        *,
        profile_dir: str | Path,
        headless: bool = False,
        browser_proxy_url: str = "",
        browser_extension_dirs: str = "",
        browser_extensions_enabled: bool = True,
        institution: str = "",
        publisher: str = "scansci-html",
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = bool(headless)
        self.browser_proxy_url = str(browser_proxy_url or "").strip()
        self.browser_extension_dirs = str(browser_extension_dirs or "").strip()
        self.browser_extensions_enabled = bool(browser_extensions_enabled)
        self.institution = str(institution or "").strip()
        self.publisher = str(publisher or "scansci-html").strip()

    def launch(self) -> BrowserSession:
        from .cloakbrowser_compat import prepare_cloakbrowser_runtime

        prepare_cloakbrowser_runtime()
        from cloakbrowser import launch_persistent_context

        identity_config = self._identity_config()
        ensure_profile_identity(
            self.profile_dir,
            build_profile_identity(
                identity_config,
                publisher=self.publisher,
                institution=self.institution,
            ),
        )
        kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
            "humanize": not self.headless,
            "accept_downloads": False,
            "args": _merged_launch_args(self.profile_dir, identity_config),
        }
        if self.browser_extensions_enabled:
            kwargs["extension_paths"] = browser_extension_paths(identity_config)

        context = launch_persistent_context(
            **kwargs,
        )
        return BrowserSession(context=context, source="cloakbrowser")

    def _identity_config(self) -> object:
        return BrowserIdentityConfig.from_values(
            browser_proxy_url=self.browser_proxy_url,
            browser_extension_dirs=self.browser_extension_dirs,
            browser_extensions_enabled=self.browser_extensions_enabled,
        )


class PlaywrightBrowserRuntime:
    def __init__(self, *, profile_dir: str | Path, headless: bool = False) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = bool(headless)

    def launch(self) -> BrowserSession:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "CloakBrowser or Playwright is required for browser mode. Install requirements first."
            ) from exc

        runtime = sync_playwright().start()
        try:
            context = runtime.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                accept_downloads=False,
                args=["--disable-features=CrossOriginOpenerPolicy"],
            )
        except Exception:
            runtime.stop()
            raise
        return BrowserSession(context=context, source="browser", runtime=runtime)


class FallbackBrowserRuntime:
    def __init__(self, *, primary: BrowserRuntime, fallback: BrowserRuntime) -> None:
        self.primary = primary
        self.fallback = fallback

    def launch(self) -> BrowserSession:
        try:
            return self.primary.launch()
        except ImportError:
            return self.fallback.launch()


def _stable_cloakbrowser_args(profile_dir: str | Path) -> list[str]:
    return [
        f"--fingerprint={_stable_cloakbrowser_fingerprint(profile_dir)}",
        "--fingerprint-platform=windows",
        "--disable-features=CrossOriginOpenerPolicy",
    ]


def _merged_launch_args(profile_dir: str | Path, identity_config: object) -> list[str]:
    args = _stable_cloakbrowser_args(profile_dir)
    for arg in browser_launch_args(identity_config):
        if arg not in args:
            args.append(arg)
    return args


def _stable_cloakbrowser_fingerprint(profile_dir: str | Path) -> int:
    normalized = str(Path(profile_dir).expanduser().resolve()).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return 10_000 + (int(digest[:8], 16) % 90_000)
