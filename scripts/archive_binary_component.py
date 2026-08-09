"""Create a checksummed ScanSci component archive for a standalone binary.

This is used for small optional runtimes such as Node.js and Tectonic.  The
main installer stays lightweight; users download these archives once, and
later ScanSci versions reuse the active component under LOCALAPPDATA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def archive_binary_component(
    package_dir: Path,
    output_dir: Path,
    *,
    component_id: str,
    version: str,
    executable_name: str,
    package_url: str = "",
    notice_files: tuple[Path, ...] = (),
) -> tuple[Path, Path]:
    """Archive one installable component and emit its immutable manifest."""

    package_dir = package_dir.resolve()
    output_dir = output_dir.resolve()
    component_id = str(component_id).strip()
    version = str(version).strip()
    executable_name = Path(str(executable_name).strip()).name
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", component_id):
        raise ValueError("component_id must be a lowercase filesystem-safe identifier")
    if not version or any(character in version for character in "\\/\r\n"):
        raise ValueError("version must be a non-empty filesystem-safe value")
    if not package_dir.is_dir():
        raise FileNotFoundError(f"Component package directory is missing: {package_dir}")
    executable_matches = [
        path for path in package_dir.rglob(executable_name) if path.is_file()
    ]
    if len(executable_matches) != 1:
        raise FileNotFoundError(
            f"Component package must contain exactly one {executable_name}: {package_dir}"
        )
    if package_url:
        parsed_url = urlparse(package_url)
        if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
            raise ValueError("package_url must use HTTPS")

    for notice in notice_files:
        if not notice.is_file():
            raise FileNotFoundError(f"Component notice file is missing: {notice}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{component_id}-{version}-windows.zip"
    temporary = archive.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    archive_root = Path(f"{component_id}-{version}")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        for source in sorted(path for path in package_dir.rglob("*") if path.is_file()):
            bundle.write(source, (archive_root / source.relative_to(package_dir)).as_posix())
        for notice in notice_files:
            bundle.write(notice, (archive_root / "licenses" / notice.name).as_posix())
    temporary.replace(archive)

    manifest = output_dir / f"{component_id}.json"
    manifest.write_text(
        json.dumps(
            {
                "id": component_id,
                "version": version,
                "windows": {
                    "url": package_url or archive.as_uri(),
                    "sha256": _sha256(archive),
                    "size": archive.stat().st_size,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return archive, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--component-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--executable-name", required=True)
    parser.add_argument("--package-url", default="")
    parser.add_argument("--notice-file", action="append", default=[], type=Path)
    args = parser.parse_args()
    archive, manifest = archive_binary_component(
        args.package_dir,
        args.output_dir,
        component_id=args.component_id,
        version=args.version,
        executable_name=args.executable_name,
        package_url=args.package_url,
        notice_files=tuple(args.notice_file),
    )
    print(archive)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
