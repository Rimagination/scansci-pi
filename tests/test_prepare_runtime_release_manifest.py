from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prepare_runtime_release_manifest import prepare_release_manifest


def test_rewrites_only_part_urls_to_immutable_https_release(tmp_path: Path) -> None:
    manifest_path = tmp_path / "local-transformers.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "local-transformers",
                "version": "1.0.0",
                "windows": {
                    "sha256": "a" * 64,
                    "size": 12,
                    "parts": [
                        {
                            "url": (tmp_path / "runtime.zip.part001").as_uri(),
                            "sha256": "b" * 64,
                            "size": 12,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = prepare_release_manifest(
        manifest_path,
        "https://github.com/Rimagination/scansci-portal/releases/download/local-runtime-v1.0.0",
    )

    package = manifest["windows"]
    assert package["sha256"] == "a" * 64
    assert package["size"] == 12
    assert package["parts"][0]["sha256"] == "b" * 64
    assert package["parts"][0]["url"].endswith("/runtime.zip.part001")


def test_rejects_non_https_release_base(tmp_path: Path) -> None:
    manifest_path = tmp_path / "local-transformers.json"
    manifest_path.write_text(
        json.dumps({"windows": {"url": (tmp_path / "runtime.zip").as_uri()}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must use HTTPS"):
        prepare_release_manifest(manifest_path, "http://downloads.example.com/runtime")
