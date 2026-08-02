from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_release_preserves_multipart_runtime_contract(tmp_path: Path) -> None:
    build = tmp_path / "build" / "ScanSci"
    build.mkdir(parents=True)
    (build / "ScanSci.exe").write_bytes(b"desktop")
    runtime = tmp_path / "local-transformers.json"
    runtime.write_text(
        json.dumps(
            {
                "id": "local-transformers",
                "version": "1.0.0",
                "windows": {
                    "sha256": "a" * 64,
                    "size": 12,
                    "parts": [
                        {
                            "url": "https://example.test/runtime.zip.part001",
                            "sha256": "b" * 64,
                            "size": 12,
                        }
                    ],
                    "diagnostics": {
                        "args": ["--diagnose-output", "{output}"],
                        "timeout_seconds": 180,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "release"

    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "package_desktop_release.ps1"),
            "-BuildDir",
            str(build),
            "-Version",
            "0.2.0-beta.1",
            "-PackageUrl",
            "https://example.test/ScanSci.zip",
            "-OutputDir",
            str(output),
            "-Channel",
            "beta",
            "-LocalRuntimeManifest",
            str(runtime),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stable = json.loads((output / "stable.json").read_text(encoding="utf-8-sig"))
    windows = stable["components"]["local-transformers"]["windows"]
    assert windows["sha256"] == "a" * 64
    assert windows["size"] == 12
    assert windows["parts"][0]["url"].endswith(".part001")
    assert windows["parts"][0]["sha256"] == "b" * 64
    assert windows["diagnostics"]["timeout_seconds"] == 180
