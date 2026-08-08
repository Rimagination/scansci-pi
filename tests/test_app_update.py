from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from scansci_html import app_update
from scansci_html.app_update import APP_VERSION, AppUpdateService


def test_update_status_is_honest_without_release_channel(tmp_path: Path) -> None:
    service = AppUpdateService(manifest_url="", updates_root=tmp_path)

    status = service.check()

    assert status["state"] == "idle"
    assert status["available"] is False
    assert status["current_version"] == APP_VERSION
    assert status["message"] == f"当前版本 v{APP_VERSION}"


def test_packaged_update_service_uses_the_public_channel_when_environment_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    service = AppUpdateService(updates_root=tmp_path)

    assert service.manifest_url == app_update.DEFAULT_UPDATE_MANIFEST_URL


def test_update_service_reads_verified_windows_release_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "ScanSci-0.3.0.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("ScanSci/ScanSci.exe", b"desktop-binary")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = tmp_path / "stable.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "0.3.0",
                "title": "ScanSci 0.3.0",
                "channel": "稳定版",
                "notes": [{"title": "新功能", "items": ["新增更新中心。"]}],
                "windows": {"url": archive.as_uri(), "sha256": checksum},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    status = AppUpdateService(manifest_url=manifest.as_uri(), updates_root=tmp_path / "updates").check()

    assert status["state"] == "available"
    assert status["latest_version"] == "0.3.0"
    assert status["can_install"] is True
    assert status["release_notes"][0]["items"] == ["新增更新中心。"]


def test_update_service_does_not_treat_equivalent_versions_as_new(tmp_path: Path) -> None:
    manifest = tmp_path / "stable.json"
    manifest.write_text(json.dumps({"version": "0.2", "windows": {}}), encoding="utf-8")

    status = AppUpdateService(
        manifest_url=manifest.as_uri(),
        current_version="0.2.0",
        updates_root=tmp_path / "updates",
    ).check()

    assert status["state"] == "current"
    assert status["available"] is False
