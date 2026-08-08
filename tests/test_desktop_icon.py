from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def test_windows_icon_contains_multiple_resolutions() -> None:
    icon = ROOT / "src" / "scansci_html" / "web" / "scansci.ico"
    reserved, image_type, image_count = struct.unpack("<HHH", icon.read_bytes()[:6])

    assert reserved == 0
    assert image_type == 1
    assert image_count >= 8


def test_desktop_build_embeds_scansci_icon() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '"--icon", $iconPath' in build_script
    assert '"scansci.ico"' in build_script


def test_scan_sci_mark_has_transparent_outer_canvas() -> None:
    mark = ROOT / "src" / "scansci_html" / "web" / "scansci-mark.png"

    with Image.open(mark) as image:
        rgba = image.convert("RGBA")

    assert rgba.getpixel((0, 0))[3] == 0
    assert rgba.getpixel((511, 511))[3] == 0
    assert rgba.getpixel((256, 256))[3] == 255
    # The white magnifying glass is intentional and must stay opaque.
    assert rgba.getpixel((256, 190))[3] == 255
