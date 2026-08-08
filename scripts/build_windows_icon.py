"""Build the multi-resolution Windows application icon from the ScanSci mark."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image


WINDOWS_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# The original artwork was exported against a white canvas.  A white canvas is
# especially visible in Windows shortcuts, where the shell expects the icon
# itself to carry transparency.  Keep this threshold conservative: the outer
# rounded-rectangle edge is a dark/navy antialias blend, while the white
# magnifying glass is enclosed by the dark mark and therefore is not reached
# by the border flood fill below.
OUTER_BACKGROUND_MIN_CHANNEL = 32
OUTER_BACKGROUND_ALPHA_CUTOFF = 16
MARK_BACKGROUND = (2, 22, 59)


def normalise_mark_transparency(image: Image.Image) -> Image.Image:
    """Remove only the white canvas connected to the image border.

    The logo contains intentional white pixels (the magnifying glass and the
    small square), so a global ``white -> transparent`` replacement would
    damage the mark.  Flood-filling from the border removes the exported
    canvas and its antialiased edge while leaving enclosed white details
    untouched.
    """

    image = image.convert("RGBA")
    width, height = image.size
    pixels = image.load()
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()

    def is_outer_candidate(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        return alpha < OUTER_BACKGROUND_ALPHA_CUTOFF or min(red, green, blue) >= OUTER_BACKGROUND_MIN_CHANNEL

    for x in range(width):
        for y in (0, height - 1):
            if is_outer_candidate(x, y):
                queue.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if is_outer_candidate(x, y):
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in visited or not is_outer_candidate(x, y):
            continue
        visited.add((x, y))
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= next_x < width and 0 <= next_y < height and (next_x, next_y) not in visited:
                queue.append((next_x, next_y))

    for x, y in visited:
        red, green, blue, alpha = pixels[x, y]
        if alpha < OUTER_BACKGROUND_ALPHA_CUTOFF:
            pixels[x, y] = (*MARK_BACKGROUND, 0)
            continue

        # Recover a dark-mark colour from white-background antialias pixels
        # instead of leaving a pale halo around the transparent edge.
        opacity = sum(
            (255 - channel) / (255 - background_channel)
            for channel, background_channel in zip((red, green, blue), MARK_BACKGROUND)
        ) / 3
        opacity = max(0.0, min(1.0, opacity))
        pixels[x, y] = (*MARK_BACKGROUND, round(opacity * 255))

    return image


def build_windows_icon(source: Path, destination: Path) -> None:
    """Write an ICO containing the resolutions Windows uses across its shell UI."""

    with Image.open(source) as opened:
        image = normalise_mark_transparency(opened)
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
