"""Private image attachments used by ScanSci conversation runs.

Pasted images are kept outside the notebook evidence library: they are user
inputs, not scholarly sources.  The run stores only small, validated metadata
and the bytes remain local to the workspace until a vision-capable provider is
called for that request.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
import re
import uuid
from typing import Any


_ATTACHMENTS_DIR = ".scansci-attachments"
_MAX_IMAGES = 4
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 10 * 1024 * 1024
_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_DATA_URL = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)$")
_ATTACHMENT_ID = re.compile(r"^image-[a-f0-9]{32}$")


def persist_image_attachments(workspace: str | Path, images: object) -> list[dict[str, Any]]:
    """Validate clipboard data URLs and persist them under the local workspace."""

    if images in (None, ""):
        return []
    if not isinstance(images, list):
        raise ValueError("images must be a list")
    if len(images) > _MAX_IMAGES:
        raise ValueError(f"一次最多可发送 {_MAX_IMAGES} 张图片")

    root = _attachments_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    total = 0
    for index, item in enumerate(images, start=1):
        if not isinstance(item, dict):
            raise ValueError("图片附件格式无效")
        mime_type, raw = _decode_data_url(str(item.get("data_url", "")))
        if len(raw) > _MAX_IMAGE_BYTES:
            raise ValueError("单张图片不能超过 4 MB")
        total += len(raw)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("本次图片总大小不能超过 10 MB")
        attachment_id = f"image-{uuid.uuid4().hex}"
        target = root / f"{attachment_id}{_IMAGE_TYPES[mime_type]}"
        target.write_bytes(raw)
        name = _display_name(str(item.get("name", "")), index, _IMAGE_TYPES[mime_type])
        records.append(
            {
                "id": attachment_id,
                "name": name,
                "mime_type": mime_type,
                "size": len(raw),
                "preview_url": f"/api/attachments/{attachment_id}",
            }
        )
    return records


def vision_image_blocks(workspace: str | Path, attachments: object) -> list[dict[str, str]]:
    """Read persisted attachment bytes as provider-neutral base64 blocks."""

    if not isinstance(attachments, list) or not attachments:
        return []
    blocks: list[dict[str, str]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("图片附件格式无效")
        attachment_id = str(item.get("id", ""))
        mime_type = str(item.get("mime_type", ""))
        path, detected_type = attachment_asset(workspace, attachment_id)
        if mime_type and mime_type != detected_type:
            raise ValueError("图片附件类型不匹配")
        blocks.append(
            {
                "mime_type": detected_type,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        )
    return blocks


def attachment_asset(workspace: str | Path, attachment_id: str) -> tuple[Path, str]:
    """Resolve a single stored image without allowing workspace traversal."""

    if not _ATTACHMENT_ID.fullmatch(str(attachment_id or "")):
        raise FileNotFoundError("图片附件不存在")
    root = _attachments_root(workspace)
    matches = [path for path in root.glob(f"{attachment_id}.*") if path.is_file()]
    if len(matches) != 1:
        raise FileNotFoundError("图片附件不存在")
    path = matches[0].resolve()
    if root.resolve() not in path.parents:
        raise FileNotFoundError("图片附件不存在")
    mime_type = next((kind for kind, extension in _IMAGE_TYPES.items() if path.suffix.lower() == extension), "")
    if not mime_type:
        raise FileNotFoundError("图片附件不存在")
    return path, mime_type


def _attachments_root(workspace: str | Path) -> Path:
    # ``workspace`` is the SQLite workspace file; keep transient user inputs
    # beside it, never inside the database path itself.
    return Path(workspace).resolve().parent / _ATTACHMENTS_DIR


def _decode_data_url(value: str) -> tuple[str, bytes]:
    match = _DATA_URL.fullmatch(value.strip())
    if match is None:
        raise ValueError("仅支持 PNG、JPG、WebP 或 GIF 图片")
    mime_type = match.group(1).lower()
    if mime_type not in _IMAGE_TYPES:
        raise ValueError("仅支持 PNG、JPG、WebP 或 GIF 图片")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("图片数据损坏") from error
    if not raw:
        raise ValueError("图片内容为空")
    return mime_type, raw


def _display_name(value: str, index: int, extension: str) -> str:
    clean = " ".join(value.replace("\x00", "").split()).strip()
    if clean:
        return clean[:120]
    return f"粘贴图片 {index}{extension}"
