import base64
from pathlib import Path

import pytest

from scansci_html.image_attachments import (
    attachment_asset,
    persist_image_attachments,
    validate_pi_image_blocks,
    vision_image_blocks,
)


_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
).decode("ascii")


def test_persisted_image_attachment_can_be_reopened_for_a_vision_request(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    records = persist_image_attachments(
        workspace,
        [{"name": "figure.png", "data_url": f"data:image/png;base64,{_PNG}"}],
    )

    assert records[0]["name"] == "figure.png"
    assert records[0]["preview_url"].startswith("/api/attachments/image-")
    path, content_type = attachment_asset(workspace, records[0]["id"])
    assert path.is_file()
    assert content_type == "image/png"
    assert vision_image_blocks(workspace, records) == [{"mime_type": "image/png", "data": _PNG}]


def test_image_attachment_rejects_non_image_data_urls(tmp_path: Path):
    with pytest.raises(ValueError, match="仅支持"):
        persist_image_attachments(tmp_path / "workspace.sqlite", [{"data_url": "data:text/plain;base64,aGVsbG8="}])


def test_pi_image_blocks_require_exact_canonical_wire_shape() -> None:
    assert validate_pi_image_blocks(
        [{"type": "image", "data": _PNG, "mimeType": "image/png"}]
    ) == [{"type": "image", "data": _PNG, "mimeType": "image/png"}]

    invalid = [
        {"type": "image", "data": _PNG, "mimeType": "image/png", "url": "https://example.test/x"},
        {"type": "image", "data": _PNG, "mimeType": "image/png", "path": "C:/secret.png"},
        {"type": "image", "data": _PNG, "mimeType": "image/png", "data_url": "data:image/png;base64," + _PNG},
        {"type": "image", "data": _PNG, "mime_type": "image/png"},
        {"type": "image", "data": _PNG + "=", "mimeType": "image/png"},
    ]
    for value in invalid:
        with pytest.raises(ValueError):
            validate_pi_image_blocks([value])


def test_pi_image_blocks_reject_mime_spoof_and_decode_before_allocating() -> None:
    jpeg_claim = {"type": "image", "data": _PNG, "mimeType": "image/jpeg"}
    with pytest.raises(ValueError, match="类型"):
        validate_pi_image_blocks([jpeg_claim])

    too_large_encoded = "A" * (((4 * 1024 * 1024 + 2) // 3) * 4 + 4)
    with pytest.raises(ValueError, match="4 MB"):
        validate_pi_image_blocks(
            [{"type": "image", "data": too_large_encoded, "mimeType": "image/png"}]
        )


def test_pi_image_blocks_reject_pixel_bombs() -> None:
    raw = bytearray(base64.b64decode(_PNG))
    raw[16:20] = (100_000).to_bytes(4, "big")
    raw[20:24] = (100_000).to_bytes(4, "big")
    encoded = base64.b64encode(raw).decode("ascii")
    with pytest.raises(ValueError, match="尺寸"):
        validate_pi_image_blocks(
            [{"type": "image", "data": encoded, "mimeType": "image/png"}]
        )


def test_pi_image_blocks_reject_magic_only_payload_without_dimensions() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\ntruncated").decode("ascii")
    with pytest.raises(ValueError, match="尺寸|解析"):
        validate_pi_image_blocks(
            [{"type": "image", "data": encoded, "mimeType": "image/png"}]
        )
