from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_update_channel.py"
SPEC = importlib.util.spec_from_file_location("scansci_verify_update_channel", SCRIPT)
assert SPEC and SPEC.loader
verify_update_channel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_update_channel)


class _Response:
    def __init__(self, payload: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.payload

    def getcode(self) -> int:
        return self.status


def test_update_channel_audit_checks_manifest_assets_and_http_range() -> None:
    package = b"desktop update payload"
    package_sha = hashlib.sha256(package).hexdigest()
    blockmap = json.dumps(
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "block_size": 65536,
            "size": len(package),
            "sha256": package_sha,
            "blocks": [package_sha],
        }
    ).encode("utf-8")
    blockmap_sha = hashlib.sha256(blockmap).hexdigest()
    manifest = json.dumps(
        {
            "version": "0.3.1",
            "channel": "stable",
            "windows": {
                "url": "https://downloads.example.com/ScanSci-0.3.1.zip",
                "sha256": package_sha,
                "size": len(package),
                "blockmap": {
                    "url": "https://downloads.example.com/ScanSci-0.3.1.zip.blockmap",
                    "sha256": blockmap_sha,
                    "size": len(blockmap),
                    "block_size": 65536,
                },
            },
        }
    ).encode("utf-8")
    requests: list[tuple[str, str, str]] = []

    def opener(request, timeout: int):
        assert timeout > 0
        method = request.get_method()
        range_header = request.headers.get("Range", "")
        requests.append((method, request.full_url, range_header))
        if request.full_url.endswith("stable.json"):
            return _Response(manifest)
        if request.full_url.endswith(".blockmap"):
            return _Response(blockmap)
        if method == "HEAD":
            return _Response(b"", headers={"Content-Length": str(len(package))})
        return _Response(
            package[:1],
            status=206,
            headers={"Content-Range": f"bytes 0-0/{len(package)}"},
        )

    result = verify_update_channel.verify_update_channel(
        "https://downloads.example.com/stable.json",
        expected_version="0.3.1",
        opener=opener,
    )

    assert result["ok"] is True
    assert result["version"] == "0.3.1"
    assert result["range_supported"] is True
    assert requests[-1] == ("GET", "https://downloads.example.com/ScanSci-0.3.1.zip", "bytes=0-0")


def test_update_channel_audit_keeps_full_package_fallback_when_range_is_unavailable() -> None:
    package = b"desktop update payload"
    package_sha = hashlib.sha256(package).hexdigest()
    blockmap = json.dumps(
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "block_size": 65536,
            "size": len(package),
            "sha256": package_sha,
            "blocks": [package_sha],
        }
    ).encode("utf-8")
    blockmap_sha = hashlib.sha256(blockmap).hexdigest()
    manifest = json.dumps(
        {
            "version": "0.3.1",
            "channel": "stable",
            "windows": {
                "url": "https://downloads.example.com/ScanSci-0.3.1.zip",
                "sha256": package_sha,
                "size": len(package),
                "blockmap": {
                    "url": "https://downloads.example.com/ScanSci-0.3.1.zip.blockmap",
                    "sha256": blockmap_sha,
                    "size": len(blockmap),
                    "block_size": 65536,
                },
            },
        }
    ).encode("utf-8")

    def opener(request, timeout: int):
        assert timeout > 0
        if request.full_url.endswith("stable.json"):
            return _Response(manifest)
        if request.full_url.endswith(".blockmap"):
            return _Response(blockmap)
        if request.get_method() == "HEAD":
            return _Response(b"", headers={"Content-Length": str(len(package))})
        return _Response(package, status=200, headers={"Content-Length": str(len(package))})

    result = verify_update_channel.verify_update_channel(
        "https://downloads.example.com/stable.json",
        expected_version="0.3.1",
        opener=opener,
    )

    assert result["ok"] is True
    assert result["range_supported"] is False
    assert result["download_strategy"] == "full-package-fallback"
