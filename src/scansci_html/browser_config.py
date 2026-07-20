"""Shared browser configuration objects used by CLI, runtime, and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BrowserIdentityConfig:
    """Network and extension identity for a persistent CloakBrowser profile."""

    browser_proxy_url: str = ""
    browser_extension_dirs: str = ""
    chrome_profile_dir: str = ""

    @classmethod
    def from_values(
        cls,
        *,
        browser_proxy_url: str = "",
        browser_extension_dirs: str | Iterable[str] | None = None,
        browser_extensions_enabled: bool = True,
        chrome_profile_dir: str | Path = "",
    ) -> "BrowserIdentityConfig":
        return cls(
            browser_proxy_url=str(browser_proxy_url or "").strip(),
            browser_extension_dirs=normalize_browser_extension_dirs(
                browser_extension_dirs,
                enabled=browser_extensions_enabled,
            ),
            chrome_profile_dir=str(chrome_profile_dir or "").strip(),
        )


@dataclass(frozen=True)
class BrowserFetcherConfig:
    """Complete BrowserFetcher construction config derived from one CLI parse."""

    profile_dir: Path
    headless: bool = False
    timeout_ms: int = 120_000
    wait_login_seconds: int = 0
    institution_query: str = ""
    hold_on_auth: bool = True
    keep_pages_open: bool = False
    browser_extensions_enabled: bool = True
    identity: BrowserIdentityConfig = BrowserIdentityConfig()

    @classmethod
    def from_cli_args(
        cls,
        args: object,
        *,
        output_dir: str | Path,
        wait_login_seconds: int,
    ) -> "BrowserFetcherConfig":
        output_path = Path(output_dir)
        profile_arg = str(getattr(args, "browser_profile", "") or "").strip()
        profile_dir = Path(profile_arg) if profile_arg else output_path / ".scansci-cloak-profile"
        browser_extensions_enabled = not bool(getattr(args, "disable_browser_extensions", False))
        identity = BrowserIdentityConfig.from_values(
            browser_proxy_url=str(getattr(args, "browser_proxy_url", "") or ""),
            browser_extension_dirs=getattr(args, "browser_extension_dirs", None),
            browser_extensions_enabled=browser_extensions_enabled,
            chrome_profile_dir=profile_dir,
        )
        return cls(
            profile_dir=profile_dir,
            headless=bool(getattr(args, "headless", False)),
            timeout_ms=int(getattr(args, "browser_timeout_ms", 120_000)),
            wait_login_seconds=max(0, int(wait_login_seconds)),
            institution_query=str(getattr(args, "institution", "") or "").strip(),
            hold_on_auth=bool(getattr(args, "hold_on_auth", True)),
            keep_pages_open=bool(getattr(args, "keep_browser_open", False)),
            browser_extensions_enabled=browser_extensions_enabled,
            identity=identity,
        )

    def to_fetcher_kwargs(self) -> dict[str, object]:
        return {
            "profile_dir": self.profile_dir,
            "headless": self.headless,
            "timeout_ms": self.timeout_ms,
            "wait_login_seconds": self.wait_login_seconds,
            "institution_query": self.institution_query,
            "hold_on_auth": self.hold_on_auth,
            "keep_pages_open": self.keep_pages_open,
            "browser_proxy_url": self.identity.browser_proxy_url,
            "browser_extension_dirs": self.identity.browser_extension_dirs,
            "browser_extensions_enabled": self.browser_extensions_enabled,
        }


def normalize_browser_extension_dirs(
    values: str | Iterable[str] | None,
    *,
    enabled: bool = True,
) -> str:
    if not enabled:
        return ""
    if values is None:
        return ""
    if isinstance(values, str):
        chunks = values.replace("\n", ";").split(";")
    else:
        chunks = []
        for value in values:
            chunks.extend(str(value or "").replace("\n", ";").split(";"))
    normalized = []
    for chunk in chunks:
        value = str(chunk or "").strip().strip('"').strip("'")
        if value:
            normalized.append(value)
    return ";".join(normalized)
