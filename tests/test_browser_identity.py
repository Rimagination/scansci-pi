import json
from pathlib import Path
import sys
import types

from scansci_html.browser_config import BrowserIdentityConfig
from scansci_html.browser_identity import (
    IDENTITY_MANIFEST_NAME,
    browser_extension_paths,
    browser_launch_args,
    build_profile_identity,
    ensure_profile_identity,
    mask_secret_url,
)
from scansci_html.browser_runtime import CloakBrowserRuntime


def test_browser_launch_args_use_browser_proxy_not_general_proxy():
    cfg = BrowserIdentityConfig(
        browser_proxy_url="socks5://reader:secret@example.proxy:1080",
    )

    args = browser_launch_args(cfg)

    assert "--disable-features=CrossOriginOpenerPolicy" in args
    assert "--proxy-server=socks5://reader:secret@example.proxy:1080" in args
    assert "--proxy-server=socks5://127.0.0.1:1080" not in args


def test_browser_extension_paths_parse_configured_directories():
    cfg = BrowserIdentityConfig.from_values(browser_extension_dirs=r" D:\opencli\bridge ; C:\tools\reader-ext ")

    assert browser_extension_paths(cfg) == [r"D:\opencli\bridge", r"C:\tools\reader-ext"]


def test_mask_secret_url_hides_proxy_password():
    masked = mask_secret_url("socks5://reader:secret@example.proxy:1080")

    assert masked == "socks5://reader:****@example.proxy:1080"
    assert "secret" not in masked


def test_profile_identity_manifest_records_hash_without_proxy_secret_or_extension_path(tmp_path: Path):
    profile = tmp_path / "profile"
    extension_dir = tmp_path / "opencli-extension"
    cfg = BrowserIdentityConfig(
        browser_proxy_url="socks5://reader:secret@example.proxy:1080",
        browser_extension_dirs=str(extension_dir),
    )

    ensure_profile_identity(
        profile,
        build_profile_identity(cfg, publisher="wiley", institution="Tsinghua University"),
    )
    ensure_profile_identity(
        profile,
        build_profile_identity(cfg, publisher="science", institution="Tsinghua University"),
    )

    manifest = json.loads((profile / IDENTITY_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest_text = json.dumps(manifest, ensure_ascii=False)

    assert manifest["institution"] == "Tsinghua University"
    assert manifest["browser_proxy_url"] == "socks5://reader:****@example.proxy:1080"
    assert len(manifest["browser_proxy_url_hash"]) == 64
    assert manifest["browser_extension_count"] == 1
    assert len(manifest["browser_extension_hash"]) == 64
    assert manifest["publishers"] == ["science", "wiley"]
    assert "secret" not in manifest_text
    assert "opencli-extension" not in manifest_text


def test_cloakbrowser_runtime_passes_proxy_extensions_and_writes_identity_manifest(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def launch_persistent_context(**kwargs):
        captured.update(kwargs)
        return "context"

    fake_cloakbrowser = types.SimpleNamespace(launch_persistent_context=launch_persistent_context)
    profile = tmp_path / "profile"
    extension_dir = tmp_path / "opencli-extension"

    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_cloakbrowser)
    monkeypatch.setattr(
        "scansci_html.cloakbrowser_compat.prepare_cloakbrowser_runtime",
        lambda: None,
    )

    runtime = CloakBrowserRuntime(
        profile_dir=profile,
        headless=False,
        browser_proxy_url="socks5://reader:secret@example.proxy:1080",
        browser_extension_dirs=str(extension_dir),
        institution="Tsinghua University",
        publisher="wiley",
    )
    session = runtime.launch()

    manifest = json.loads((profile / IDENTITY_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest_text = json.dumps(manifest, ensure_ascii=False)

    assert session.context == "context"
    assert captured["user_data_dir"] == str(profile)
    assert "--proxy-server=socks5://reader:secret@example.proxy:1080" in captured["args"]
    assert captured["extension_paths"] == [str(extension_dir)]
    assert manifest["institution"] == "Tsinghua University"
    assert manifest["browser_extension_count"] == 1
    assert manifest["publishers"] == ["wiley"]
    assert "secret" not in manifest_text
    assert "opencli-extension" not in manifest_text
