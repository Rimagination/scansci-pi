"""Freeze expensive PyInstaller collection helpers into a cache-local spec.

PyInstaller's generated spec calls ``collect_data_files``/``collect_all``
every time the spec is evaluated, even when Analysis itself is reusable.  A
ScanSci core build has enough provider packages for those calls to cost tens
of seconds.  This helper snapshots their resolved inputs after the first
successful build and keeps them outside Analysis so source-only rebuilds do
not need to rediscover immutable dependency data.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from pprint import pformat


MARKER = "# ScanSci frozen collection inputs v1"


def freeze_spec(spec_path: Path, analysis_toc_path: Path) -> bool:
    spec_text = spec_path.read_text(encoding="utf-8")
    if MARKER in spec_text:
        return False

    toc = list(ast.literal_eval(analysis_toc_path.read_text(encoding="utf-8")))
    if len(toc) < 12:
        raise ValueError(f"Unsupported PyInstaller Analysis TOC: {analysis_toc_path}")

    hidden_imports = toc[2]
    input_binaries = toc[10]
    input_datas = toc[11]
    analysis_offset = spec_text.find("a = Analysis(")
    if analysis_offset < 0:
        raise ValueError(f"Analysis declaration was not found in {spec_path}")

    body = spec_text[analysis_offset:]
    body = body.replace("    binaries=binaries,", "    binaries=[],", 1)
    body = body.replace("    datas=datas,", "    datas=[],", 1)
    body = body.replace("    hiddenimports=hiddenimports,", "    hiddenimports=frozen_hiddenimports,", 1)
    pyz_marker = ")\npyz = PYZ(a.pure)"
    if pyz_marker not in body:
        raise ValueError(f"PYZ declaration was not found in {spec_path}")
    body = body.replace(
        pyz_marker,
        ")\n"
        "a.binaries += frozen_binaries\n"
        "a.datas += frozen_datas\n"
        "pyz = PYZ(a.pure)",
        1,
    )

    frozen_header = (
        "# -*- mode: python ; coding: utf-8 -*-\n"
        f"{MARKER}\n"
        f"frozen_binaries = {pformat(input_binaries, width=160, sort_dicts=False)}\n"
        f"frozen_datas = {pformat(input_datas, width=160, sort_dicts=False)}\n"
        f"frozen_hiddenimports = {pformat(hidden_imports, width=160, sort_dicts=False)}\n\n"
    )
    spec_path.write_text(frozen_header + body, encoding="utf-8")

    # The frozen inputs are appended after Analysis.  Align the persisted TOC
    # with the new empty Analysis inputs so the first frozen-spec invocation
    # is already a cache hit rather than paying for one transition rebuild.
    toc[10] = []
    toc[11] = []
    analysis_toc_path.write_text(
        pformat(tuple(toc), width=160, sort_dicts=False),
        encoding="utf-8",
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--analysis-toc", required=True, type=Path)
    args = parser.parse_args()
    changed = freeze_spec(args.spec, args.analysis_toc)
    print("frozen" if changed else "already-frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
