from pathlib import Path
from types import SimpleNamespace

from scansci_html.browser_config import (
    BrowserFetcherConfig,
    BrowserIdentityConfig,
    normalize_browser_extension_dirs,
)


def test_normalize_browser_extension_dirs_accepts_strings_and_lists():
    values = [r" D:\opencli\bridge ", r"C:\tools\reader-ext"]

    normalized = normalize_browser_extension_dirs(values)

    assert normalized == r"D:\opencli\bridge;C:\tools\reader-ext"
    assert normalize_browser_extension_dirs(r" D:\one ; C:\two ") == r"D:\one;C:\two"


def test_normalize_browser_extension_dirs_honors_disabled_extensions():
    assert normalize_browser_extension_dirs([r"D:\opencli\bridge"], enabled=False) == ""


def test_browser_identity_config_keeps_proxy_when_extensions_are_disabled():
    config = BrowserIdentityConfig.from_values(
        browser_proxy_url=" socks5://reader:secret@example.proxy:1080 ",
        browser_extension_dirs=[r"D:\opencli\bridge"],
        browser_extensions_enabled=False,
        chrome_profile_dir=r"D:\profiles\wiley",
    )

    assert config.browser_proxy_url == "socks5://reader:secret@example.proxy:1080"
    assert config.browser_extension_dirs == ""
    assert config.chrome_profile_dir == r"D:\profiles\wiley"


def test_browser_fetcher_config_from_cli_args_centralizes_browser_options(tmp_path: Path):
    output_dir = tmp_path / "html-papers"
    args = SimpleNamespace(
        browser_profile="",
        headless=True,
        browser_timeout_ms=45_000,
        institution="Tsinghua University",
        hold_on_auth=False,
        keep_browser_open=True,
        browser_proxy_url="socks5://reader:secret@example.proxy:1080",
        browser_extension_dirs=[str(tmp_path / "opencli"), str(tmp_path / "reader-ext")],
        disable_browser_extensions=False,
    )

    config = BrowserFetcherConfig.from_cli_args(
        args,
        output_dir=output_dir,
        wait_login_seconds=600,
    )

    assert config.profile_dir == output_dir / ".scansci-cloak-profile"
    assert config.headless is True
    assert config.timeout_ms == 45_000
    assert config.wait_login_seconds == 600
    assert config.institution_query == "Tsinghua University"
    assert config.hold_on_auth is False
    assert config.keep_pages_open is True
    assert config.identity.browser_proxy_url == "socks5://reader:secret@example.proxy:1080"
    assert config.identity.browser_extension_dirs == ";".join(
        [str(tmp_path / "opencli"), str(tmp_path / "reader-ext")]
    )


def test_browser_fetcher_config_to_kwargs_matches_browser_fetcher_constructor(tmp_path: Path):
    args = SimpleNamespace(
        browser_profile=str(tmp_path / "profile"),
        headless=False,
        browser_timeout_ms=120_000,
        institution="Example University",
        hold_on_auth=True,
        keep_browser_open=False,
        browser_proxy_url="",
        browser_extension_dirs=[],
        disable_browser_extensions=True,
    )
    config = BrowserFetcherConfig.from_cli_args(args, output_dir=tmp_path / "out", wait_login_seconds=300)

    kwargs = config.to_fetcher_kwargs()

    assert kwargs == {
        "profile_dir": tmp_path / "profile",
        "headless": False,
        "timeout_ms": 120_000,
        "wait_login_seconds": 300,
        "institution_query": "Example University",
        "hold_on_auth": True,
        "keep_pages_open": False,
        "browser_proxy_url": "",
        "browser_extension_dirs": "",
        "browser_extensions_enabled": False,
    }
