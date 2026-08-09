from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class UpdateChannelFailure(RuntimeError):
    """Raised when a published update channel cannot satisfy its contract."""


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BLOCKMAP_BYTES = 32 * 1024 * 1024


def _https_url(value: object, label: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise UpdateChannelFailure(f"{label} must be an absolute HTTPS URL")
    return url


def _positive_int(value: object, label: str) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateChannelFailure(f"{label} must be an integer") from exc
    if result <= 0:
        raise UpdateChannelFailure(f"{label} must be greater than zero")
    return result


def _sha256(value: object, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise UpdateChannelFailure(f"{label} must be a SHA256 digest")
    return digest


def _read_response(response: Any, limit: int, label: str) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise UpdateChannelFailure(f"{label} exceeds the audit size limit")
    return payload


def _header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    if hasattr(headers, "get"):
        return str(headers.get(name, "") or headers.get(name.lower(), "") or "")
    return ""


def _status(response: Any) -> int:
    value = getattr(response, "status", None)
    if value is None and hasattr(response, "getcode"):
        value = response.getcode()
    return int(value or 0)


def _open(
    opener: Callable[..., Any],
    request: Request,
    *,
    timeout: int,
    label: str,
) -> Any:
    try:
        return opener(request, timeout=timeout)
    except Exception as exc:
        raise UpdateChannelFailure(f"Unable to reach {label}: {exc}") from exc


def verify_update_channel(
    manifest_url: str,
    *,
    expected_version: str = "",
    opener: Callable[..., Any] = urlopen,
    timeout: int = 30,
) -> dict[str, Any]:
    """Audit the public manifest, immutable assets, and differential-download capability.

    HTTP Range support is an optimization. A channel remains valid when Range is absent,
    provided the complete package is reachable with the declared size; clients then use
    the mandatory full-package fallback.
    """

    manifest_url = _https_url(manifest_url, "manifest URL")
    manifest_request = Request(manifest_url, headers={"Accept": "application/json"})
    with _open(opener, manifest_request, timeout=timeout, label="update manifest") as response:
        if _status(response) not in {0, 200}:
            raise UpdateChannelFailure(f"Update manifest returned HTTP {_status(response)}")
        manifest_bytes = _read_response(response, MAX_MANIFEST_BYTES, "update manifest")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateChannelFailure("Update manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise UpdateChannelFailure("Update manifest root must be an object")

    version = str(manifest.get("version", "")).strip()
    if not version:
        raise UpdateChannelFailure("Update manifest is missing version")
    if expected_version and version != str(expected_version).strip():
        raise UpdateChannelFailure(
            f"Update manifest version {version!r} does not match expected {expected_version!r}"
        )
    if str(manifest.get("channel", "")).strip().casefold() != "stable":
        raise UpdateChannelFailure("Public update manifest must use the stable channel")

    windows = manifest.get("windows")
    if not isinstance(windows, dict):
        raise UpdateChannelFailure("Update manifest is missing the Windows package")
    package_url = _https_url(windows.get("url"), "Windows package URL")
    package_sha256 = _sha256(windows.get("sha256"), "Windows package SHA256")
    package_size = _positive_int(windows.get("size"), "Windows package size")

    blockmap_info = windows.get("blockmap")
    if not isinstance(blockmap_info, dict):
        raise UpdateChannelFailure("Update manifest is missing blockmap metadata")
    blockmap_url = _https_url(blockmap_info.get("url"), "blockmap URL")
    blockmap_sha256 = _sha256(blockmap_info.get("sha256"), "blockmap SHA256")
    blockmap_size = _positive_int(blockmap_info.get("size"), "blockmap size")
    declared_block_size = _positive_int(blockmap_info.get("block_size"), "blockmap block size")

    blockmap_request = Request(blockmap_url, headers={"Accept": "application/json"})
    with _open(opener, blockmap_request, timeout=timeout, label="update blockmap") as response:
        if _status(response) not in {0, 200}:
            raise UpdateChannelFailure(f"Update blockmap returned HTTP {_status(response)}")
        blockmap_bytes = _read_response(response, MAX_BLOCKMAP_BYTES, "update blockmap")
    if len(blockmap_bytes) != blockmap_size:
        raise UpdateChannelFailure("Downloaded blockmap size does not match stable.json")
    if hashlib.sha256(blockmap_bytes).hexdigest() != blockmap_sha256:
        raise UpdateChannelFailure("Downloaded blockmap SHA256 does not match stable.json")
    try:
        blockmap = json.loads(blockmap_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateChannelFailure("Downloaded blockmap is not valid UTF-8 JSON") from exc
    if not isinstance(blockmap, dict):
        raise UpdateChannelFailure("Downloaded blockmap root must be an object")
    block_size = _positive_int(blockmap.get("block_size"), "downloaded blockmap block size")
    blocks = blockmap.get("blocks")
    expected_blocks = (package_size + block_size - 1) // block_size
    if (
        int(blockmap.get("schema_version", 0) or 0) != 1
        or str(blockmap.get("algorithm", "")).casefold() != "sha256"
        or block_size != declared_block_size
        or int(blockmap.get("size", 0) or 0) != package_size
        or str(blockmap.get("sha256", "")).casefold() != package_sha256
        or not isinstance(blocks, list)
        or len(blocks) != expected_blocks
        or any(len(str(item)) != 64 for item in blocks)
    ):
        raise UpdateChannelFailure("Downloaded blockmap does not describe the declared full package")

    head_request = Request(package_url, method="HEAD")
    with _open(opener, head_request, timeout=timeout, label="full update package") as response:
        head_status = _status(response)
        if head_status not in {0, 200, 204}:
            raise UpdateChannelFailure(f"Full update package returned HTTP {head_status} to HEAD")
        content_length = _header(response, "Content-Length")
    if content_length and int(content_length) != package_size:
        raise UpdateChannelFailure("Published full package size does not match stable.json")

    range_request = Request(package_url, headers={"Range": "bytes=0-0"})
    with _open(opener, range_request, timeout=timeout, label="full update package range probe") as response:
        range_status = _status(response)
        content_range = _header(response, "Content-Range")
        # Read only enough to distinguish a one-byte partial response.  A server that
        # ignores Range may start returning the full archive; that is a supported
        # full-package fallback, not an audit failure.
        probe = response.read(2)
    range_supported = (
        range_status == 206
        and content_range.strip().casefold() == f"bytes 0-0/{package_size}".casefold()
        and len(probe) == 1
    )

    return {
        "ok": True,
        "manifest_url": manifest_url,
        "version": version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "package_size": package_size,
        "blockmap_url": blockmap_url,
        "blockmap_sha256": blockmap_sha256,
        "blockmap_size": blockmap_size,
        "range_supported": range_supported,
        "download_strategy": "differential" if range_supported else "full-package-fallback",
    }


def _write_report(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the public ScanSci automatic-update channel")
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        result = verify_update_channel(
            args.manifest_url,
            expected_version=args.expected_version,
            timeout=max(1, args.timeout),
        )
    except UpdateChannelFailure as exc:
        result = {"ok": False, "error": str(exc)}
        _write_report(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 1
    _write_report(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
