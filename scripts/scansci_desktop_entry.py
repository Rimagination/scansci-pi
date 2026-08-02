"""PyInstaller entry point for the ScanSci desktop executable."""

from pathlib import Path
import sys


# A source checkout may coexist with another editable ScanSci installation.
# Prefer this checkout when the entry point is launched directly; frozen builds
# already bundle the intended package and do not need a path override.
if not getattr(sys, "frozen", False):
    source_root = Path(__file__).resolve().parents[1] / "src"
    if source_root.is_dir():
        sys.path.insert(0, str(source_root))

from scansci_html.desktop import main  # noqa: E402 - source checkout path must be selected first


if __name__ == "__main__":
    raise SystemExit(main())
