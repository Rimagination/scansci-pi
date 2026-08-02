"""Rewrite a built local-runtime manifest to immutable release asset URLs.

The runtime archive and its checksums are produced before a hosting target is
selected. This helper changes only download URLs; it never recalculates or
weakens the recorded size and SHA256 contracts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlparse


def prepare_release_manifest(manifest_path: Path, base_url: str) -> dict[str, object]:
    parsed_base = urlparse(base_url)
    if parsed_base.scheme.lower() != "https" or not parsed_base.netloc:
        raise ValueError("Release asset base URL must use HTTPS.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Runtime manifest must be a JSON object.")
    windows = manifest.get("windows")
    if not isinstance(windows, dict):
        raise ValueError("Runtime manifest is missing the Windows package.")

    prefix = base_url.rstrip("/")
    parts = windows.get("parts")
    if isinstance(parts, list) and parts:
        for record in parts:
            if not isinstance(record, dict):
                raise ValueError("Runtime manifest has an invalid part record.")
            current_url = str(record.get("url", "")).strip()
            filename = Path(urlparse(current_url).path).name
            if not filename or filename in {".", ".."}:
                raise ValueError("Runtime manifest part is missing a safe filename.")
            record["url"] = f"{prefix}/{quote(filename)}"
    else:
        current_url = str(windows.get("url", "")).strip()
        filename = Path(urlparse(current_url).path).name
        if not filename or filename in {".", ".."}:
            raise ValueError("Runtime manifest package is missing a safe filename.")
        windows["url"] = f"{prefix}/{quote(filename)}"

    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    prepare_release_manifest(args.manifest.resolve(), args.base_url)
    print(args.manifest.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
