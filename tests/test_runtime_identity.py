"""Regression contracts for the runtime that actually serves ScanSci."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import tomllib
from urllib.request import urlopen

from scansci_html.app_update import APP_VERSION, AppUpdateService
import scansci_html.build_info as build_info_module
from scansci_html.build_info import current_build_info
from scansci_html.webapp import create_notebook_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = (PROJECT_ROOT / "src" / "scansci_html").resolve()
PREVIEW_ENTRY = PROJECT_ROOT / "scripts" / "scansci_preview_entry.py"


def test_source_and_release_version_declarations_cannot_drift() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    release_contract = json.loads((PROJECT_ROOT / "config" / "release-gate.json").read_text(encoding="utf-8"))
    expected = str(release_contract["version"])

    assert APP_VERSION == expected
    assert pyproject["project"]["version"] == expected
    assert package["version"] == expected
    assert package_lock["version"] == expected
    assert package_lock["packages"][""]["version"] == expected


def test_update_service_defaults_to_the_runtime_build_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(build_info_module, "current_build_info", lambda: {"version": "9.8.7"})

    service = AppUpdateService(manifest_url="", updates_root=tmp_path)

    assert service.current_version == "9.8.7"


def test_packaged_build_info_keeps_local_runtime_distribution_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "scansci_html"
    package_dir.mkdir()
    fake_module = package_dir / "build_info.py"
    fake_module.write_text("# packaged test module\n", encoding="utf-8")
    (package_dir / "build-info.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "build_id": "internal-beta-lightweight",
                "package_profile": "core",
                "runtime_manifest_url": "https://downloads.example.com/local-transformers.json",
                "node_component_manifest_url": "https://downloads.example.com/node.json",
                "tectonic_component_manifest_url": "https://downloads.example.com/tectonic.json",
                "cache_key": "desktop-cache",
                "source_tree_sha256": "a" * 64,
                "release_source_sha256": "b" * 64,
                "untrusted_extra": "must-not-leak",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_info_module, "__file__", str(fake_module))

    identity = current_build_info()

    assert identity["package_profile"] == "core"
    assert identity["runtime_manifest_url"] == "https://downloads.example.com/local-transformers.json"
    assert identity["node_component_manifest_url"] == "https://downloads.example.com/node.json"
    assert identity["tectonic_component_manifest_url"] == "https://downloads.example.com/tectonic.json"
    assert identity["cache_key"] == "desktop-cache"
    assert identity["source_tree_sha256"] == "a" * 64
    assert identity["release_source_sha256"] == "b" * 64
    assert "untrusted_extra" not in identity


def test_preview_entry_proves_it_selected_this_checkout() -> None:
    completed = subprocess.run(
        [sys.executable, str(PREVIEW_ENTRY), "--identity"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    identity = json.loads(completed.stdout)
    assert identity["preview_source_verified"] is True
    assert Path(identity["package_root"]).resolve() == SOURCE_PACKAGE
    assert Path(identity["preview_root"]).resolve() == PROJECT_ROOT


def test_loopback_health_exposes_runtime_provenance(tmp_path: Path) -> None:
    server = create_notebook_server(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert health["status"] == "ok"
    assert health["runtime_kind"] == "source"
    assert Path(health["package_root"]).resolve() == SOURCE_PACKAGE
    assert Path(health["source_root"]).resolve() == SOURCE_PACKAGE.parent
