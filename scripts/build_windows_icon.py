"""Build the multi-resolution Windows application icon from the ScanSci mark."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


WINDOWS_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_windows_icon(source: Path, destination: Path) -> None:
    """Write an ICO containing the resolutions Windows uses across its shell UI."""

    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if image.width != image.height:
        raise ValueError(f"ScanSci icon source must be square, got {image.size!r}")
    if image.width < max(WINDOWS_ICON_SIZES):
        raise ValueError(
            f"ScanSci icon source must be at least {max(WINDOWS_ICON_SIZES)} px, got {image.width} px"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        destination,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_ICON_SIZES],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build_windows_icon(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
