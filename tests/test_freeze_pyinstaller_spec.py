from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freezes_collection_inputs_and_aligns_analysis_cache(tmp_path: Path) -> None:
    spec = tmp_path / "ScanSci.spec"
    spec.write_text(
        "# generated\n"
        "datas = [('dynamic', 'value')]\n"
        "binaries = []\n"
        "hiddenimports = ['dynamic']\n"
        "a = Analysis(\n"
        "    ['entry.py'],\n"
        "    binaries=binaries,\n"
        "    datas=datas,\n"
        "    hiddenimports=hiddenimports,\n"
        ")\n"
        "pyz = PYZ(a.pure)\n",
        encoding="utf-8",
    )
    toc_values: list[object] = [
        ["entry.py"],
        [],
        ["litellm", "markitdown"],
        [],
        {},
        ["__main__"],
        [],
        False,
        {},
        0,
        [("vec0.dll", "C:/pkg/vec0.dll", "BINARY")],
        [("docx/py.typed", "C:/pkg/docx/py.typed", "DATA")],
    ]
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(repr(tuple(toc_values)), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "freeze_pyinstaller_spec.py"),
            "--spec",
            str(spec),
            "--analysis-toc",
            str(toc),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    frozen = spec.read_text(encoding="utf-8")
    stored = ast.literal_eval(toc.read_text(encoding="utf-8"))
    assert result.stdout.strip() == "frozen"
    assert "ScanSci frozen collection inputs v1" in frozen
    assert "frozen_hiddenimports = ['litellm', 'markitdown']" in frozen
    assert "a.binaries += frozen_binaries" in frozen
    assert "a.datas += frozen_datas" in frozen
    assert "    binaries=[]," in frozen
    assert "    datas=[]," in frozen
    assert stored[10] == []
    assert stored[11] == []
