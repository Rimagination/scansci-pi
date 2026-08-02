"""Inspect or apply the verified ScanSci/ScanSciPi data-root migration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scansci_html.data_migration import inspect_data_roots, migrate_data_roots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-app-data", default=os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    parser.add_argument("--backup-parent", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    local_root = Path(args.local_app_data).expanduser().resolve()
    canonical = local_root / "ScanSci"
    pi = local_root / "ScanSciPi"
    if args.apply:
        report = migrate_data_roots(canonical, pi, backup_parent=args.backup_parent or None)
    else:
        report = inspect_data_roots(canonical, pi)
        report["status"] = "dry-run"
        report["message"] = "No files were changed. Pass --apply only after closing both desktop applications."
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
