from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from scansci_html import app_update
from scansci_html.app_update import APP_VERSION, AppUpdateService
from scansci_html.update_blockmap import build_blockmap


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


def test_update_status_marks_blockmap_capable_release(tmp_path: Path) -> None:
    archive = tmp_path / "ScanSci-0.3.0.zip"
    archive.write_bytes(_zip_bytes(b"new-desktop-binary"))
    blockmap = tmp_path / "ScanSci-0.3.0.zip.blockmap"
    blockmap.write_text(json.dumps(build_blockmap(archive)), encoding="utf-8")
    manifest = tmp_path / "stable.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "0.3.0",
                "windows": {
                    "url": archive.as_uri(),
                    "sha256": _sha256(archive),
                    "blockmap": {
                        "url": blockmap.as_uri(),
                        "sha256": _sha256(blockmap),
                        "size": blockmap.stat().st_size,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    status = AppUpdateService(manifest_url=manifest.as_uri(), updates_root=tmp_path / "updates").check()

    assert status["update_mode"] == "differential-capable"
    assert status["blockmap_size"] == blockmap.stat().st_size


def test_update_status_ignores_blockmap_with_wrong_declared_size(tmp_path: Path) -> None:
    archive = tmp_path / "ScanSci-0.3.0.zip"
    archive.write_bytes(_zip_bytes(b"new-desktop-binary"))
    blockmap = tmp_path / "ScanSci-0.3.0.zip.blockmap"
    blockmap.write_text(json.dumps(build_blockmap(archive)), encoding="utf-8")
    manifest = tmp_path / "stable.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "0.3.0",
                "windows": {
                    "url": archive.as_uri(),
                    "sha256": _sha256(archive),
                    "blockmap": {
                        "url": blockmap.as_uri(),
                        "sha256": _sha256(blockmap),
                        "size": blockmap.stat().st_size + 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    service = AppUpdateService(manifest_url=manifest.as_uri(), updates_root=tmp_path / "updates")
    service.check()
    destination = tmp_path / "updates" / "ScanSci-update.zip.blockmap"
    destination.parent.mkdir(parents=True)

    assert service._prepare_blockmap(service._windows_package(service._manifest or {}), destination) is None
    assert not destination.exists()


def test_install_prefers_differential_update_from_cached_current_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_version = "0.2.3"
    latest_version = "0.3.0"
    updates_root = tmp_path / "updates"
    base_dir = updates_root / current_version
    base_dir.mkdir(parents=True)
    base_archive = base_dir / "ScanSci-update.zip"
    base_archive.write_bytes(_zip_bytes(b"old-desktop-binary"))
    base_blockmap = base_dir / "ScanSci-update.zip.blockmap"
    base_blockmap.write_text(json.dumps(build_blockmap(base_archive)), encoding="utf-8")

    new_archive = tmp_path / "ScanSci-0.3.0.zip"
    new_archive.write_bytes(_zip_bytes(b"new-desktop-binary"))
    new_blockmap = tmp_path / "ScanSci-0.3.0.zip.blockmap"
    new_blockmap.write_text(json.dumps(build_blockmap(new_archive)), encoding="utf-8")
    manifest = tmp_path / "stable.json"
    manifest.write_text(
        json.dumps(
            {
                "version": latest_version,
                "windows": {
                    "url": new_archive.as_uri(),
                    "sha256": _sha256(new_archive),
                    "blockmap": {
                        "url": new_blockmap.as_uri(),
                        "sha256": _sha256(new_blockmap),
                        "size": new_blockmap.stat().st_size,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    executable = install_dir / "ScanSci.exe"
    executable.write_bytes(b"running")
    calls: list[Path] = []

    def fake_differential(old_file, old_map, new_url, new_map, destination):
        calls.append(Path(old_file))
        assert new_url == new_archive.as_uri()
        destination.write_bytes(new_archive.read_bytes())
        return {"used_differential": True, "bytes_downloaded": 17, "total_size": new_archive.stat().st_size}

    monkeypatch.setattr(app_update, "download_differential", fake_differential)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(sys, "executable", str(executable), raising=False)
    monkeypatch.setattr(app_update.subprocess, "Popen", lambda *_args, **_kwargs: None)

    service = AppUpdateService(
        manifest_url=manifest.as_uri(),
        current_version=current_version,
        updates_root=updates_root,
    )
    service.check()
    result = service.install()

    assert result["update_mode"] == "differential"
    assert result["bytes_downloaded"] == 17
    assert calls == [base_archive]


def _zip_bytes(executable_payload: bytes) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as output:
        output.writestr("ScanSci.exe", executable_payload)
    return stream.getvalue()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
