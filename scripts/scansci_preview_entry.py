"""Canonical source-checkout launcher for the browser preview.

Use this instead of ``python -m scansci_html.cli serve`` while developing.
It always imports ``<repository>/src`` first, even if another editable
ScanSci checkout is installed in the same Python environment.  ``--identity``
is deliberately lightweight so a person or an automated gate can prove which
runtime will be served before opening a browser.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"


def _select_checkout_source() -> None:
    if not SOURCE_ROOT.is_dir():
        raise RuntimeError(f"ScanSci source directory is missing: {SOURCE_ROOT}")
    source = str(SOURCE_ROOT)
    if source not in sys.path:
        sys.path.insert(0, source)


def runtime_identity() -> dict[str, object]:
    """Return the runtime provenance used by this preview launcher."""

    _select_checkout_source()
    from scansci_html.build_info import current_build_info

    identity = current_build_info()
    package_root = Path(str(identity["package_root"])).resolve()
    expected_package = (SOURCE_ROOT / "scansci_html").resolve()
    if package_root != expected_package:
        raise RuntimeError(
            "Preview launcher imported a different ScanSci checkout: "
            f"expected {expected_package}, got {package_root}"
        )
    identity["preview_root"] = str(PROJECT_ROOT)
    identity["preview_source_verified"] = True
    return identity


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--identity"]:
        print(json.dumps(runtime_identity(), ensure_ascii=False, indent=2))
        return 0

    _select_checkout_source()
    from scansci_html.cli import main as cli_main

    return int(cli_main(["serve", *arguments]))


if __name__ == "__main__":
    raise SystemExit(main())
