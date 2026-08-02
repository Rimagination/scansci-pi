from __future__ import annotations

import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
import requests


IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
}


def localize_image_assets(
    html: str,
    *,
    output_path: str | Path,
    source_url: str,
    session: object | None = None,
    timeout: float = 30.0,
) -> tuple[str, list[str]]:
    """Download remote image assets beside an HTML file and rewrite img src values."""
    output = Path(output_path)
    asset_dir = output.with_name(f"{output.stem}_assets")
    soup = BeautifulSoup(str(html or ""), "lxml")
    active_session = session or requests.Session()
    warnings: list[str] = []
    localized_by_url: dict[str, str] = {}

    for index, image in enumerate(soup.find_all("img"), start=1):
        if not isinstance(image, Tag):
            continue
        src = str(image.get("src") or "").strip()
        image_url = _downloadable_image_url(src, source_url=source_url, asset_dir_name=asset_dir.name)
        if not image_url:
            continue
        if image_url in localized_by_url:
            image["src"] = localized_by_url[image_url]
            continue
        try:
            response = active_session.get(
                image_url,
                timeout=float(timeout),
                headers=_request_headers(source_url),
            )
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            content = bytes(getattr(response, "content", b"") or b"")
            content_type = _content_type(getattr(response, "headers", {}) or {})
            if not content:
                raise ValueError("empty response body")
            if content_type and not content_type.startswith("image/") and not _has_image_extension(image_url):
                raise ValueError(f"non-image content type {content_type}")
            local_path = asset_dir / _asset_filename(index, image_url, content_type)
            _write_binary_atomic(local_path, content)
            relative_path = f"{asset_dir.name}/{local_path.name}"
            localized_by_url[image_url] = relative_path
            image["src"] = relative_path
        except Exception as exc:
            local_path = asset_dir / _captured_asset_filename(index, image_url)
            try:
                if _capture_image_asset(
                    active_session,
                    image_url,
                    local_path=local_path,
                    source_url=source_url,
                    timeout=float(timeout),
                ):
                    relative_path = f"{asset_dir.name}/{local_path.name}"
                    localized_by_url[image_url] = relative_path
                    image["src"] = relative_path
                    continue
            except Exception as capture_exc:
                warnings.append(
                    f"image asset download failed: {image_url} "
                    f"({type(exc).__name__}: {exc}; browser capture failed: "
                    f"{type(capture_exc).__name__}: {capture_exc})"
                )
                continue
            warnings.append(f"image asset download failed: {image_url} ({type(exc).__name__}: {exc})")

    return str(soup), warnings


def _downloadable_image_url(src: str, *, source_url: str, asset_dir_name: str) -> str:
    if not src:
        return ""
    parsed = urlparse(src)
    scheme = parsed.scheme.lower()
    if scheme in {"data", "cid", "blob", "file"}:
        return ""
    if scheme in {"http", "https"}:
        return src
    if src.replace("\\", "/").startswith(f"{asset_dir_name}/"):
        return ""
    if src.startswith("//"):
        return f"https:{src}"
    if src.startswith("/"):
        return urljoin(source_url, src)
    return ""


def _request_headers(source_url: str) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    if source_url:
        headers["Referer"] = source_url
    return headers


def _content_type(headers: object) -> str:
    get = getattr(headers, "get", None)
    if not callable(get):
        return ""
    return str(get("Content-Type") or get("content-type") or "").split(";", 1)[0].strip().lower()


def _asset_filename(index: int, url: str, content_type: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    basename = Path(path).name
    stem = Path(basename).stem or "image"
    extension = Path(basename).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        extension = _extension_from_content_type(content_type)
    safe_stem = _safe_filename_part(stem)[:80] or "image"
    return f"img_{index:03d}_{safe_stem}{extension}"


def _captured_asset_filename(index: int, url: str) -> str:
    parsed = urlparse(url)
    stem = Path(unquote(parsed.path or "")).stem or "image"
    safe_stem = _safe_filename_part(stem)[:80] or "image"
    return f"img_{index:03d}_{safe_stem}.png"


def _extension_from_content_type(content_type: str) -> str:
    if content_type == "image/jpeg":
        return ".jpg"
    extension = mimetypes.guess_extension(content_type or "")
    if extension in {".jpe", ".jpeg"}:
        return ".jpg"
    return extension if extension in IMAGE_EXTENSIONS else ".bin"


def _has_image_extension(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in IMAGE_EXTENSIONS


def _capture_image_asset(
    session: object,
    url: str,
    *,
    local_path: Path,
    source_url: str,
    timeout: float,
) -> bool:
    capture = getattr(session, "capture_image_asset", None)
    if not callable(capture):
        return False
    capture(url, output_path=local_path, source_url=source_url, timeout=timeout)
    return local_path.exists() and local_path.stat().st_size > 0


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")


def _write_binary_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
