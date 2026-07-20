"""Copy pinned browser runtimes into package data for offline desktop use."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = ROOT / "node_modules"
DESTINATION = ROOT / "src" / "scansci_html" / "web" / "vendor"
ASSETS = {
    "pdfjs/pdf.mjs": NODE_MODULES / "pdfjs-dist" / "legacy" / "build" / "pdf.mjs",
    "pdfjs/pdf.worker.mjs": NODE_MODULES / "pdfjs-dist" / "legacy" / "build" / "pdf.worker.mjs",
    "pdfjs/pdf_viewer.css": NODE_MODULES / "pdfjs-dist" / "web" / "pdf_viewer.css",
    "pptxgen/pptxgen.bundle.js": NODE_MODULES / "pptxgenjs" / "dist" / "pptxgen.bundle.js",
}


def main() -> int:
    manifest: dict[str, dict[str, object]] = {}
    for relative, source in ASSETS.items():
        if not source.is_file():
            raise FileNotFoundError(f"Run npm install before vendoring: {source}")
        target = DESTINATION / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        payload = target.read_bytes()
        manifest[relative] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest_path = DESTINATION / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Vendored {len(manifest)} browser assets into {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

