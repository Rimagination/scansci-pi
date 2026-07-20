import base64
from pathlib import Path

import pytest

from scansci_html.image_attachments import attachment_asset, persist_image_attachments, vision_image_blocks


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
