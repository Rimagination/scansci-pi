"""Focused contracts for the Windows installer verification harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_windows_installer",
    ROOT / "scripts" / "verify_windows_installer.py",
)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def test_verifier_uses_a_bounded_user_level_install_target(tmp_path: Path, monkeypatch) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    install_dir = verifier._verification_install_dir(tmp_path / "long-temporary-root")

    assert install_dir.parent == local_app_data / "ScanSciVerify"
    assert len(install_dir.name) == 10
    assert install_dir != tmp_path / "long-temporary-root" / "installed"


def test_verifier_retains_the_end_of_an_inno_log(tmp_path: Path) -> None:
    log = tmp_path / "install.log"
    log.write_text("old\n" + ("x" * 20) + "\nfinal diagnostic\n", encoding="utf-8")

    assert verifier._log_tail(log, limit=20) == "xx\nfinal diagnostic\n"
    assert verifier._log_tail(tmp_path / "missing.log") == "<installer did not create a log>"


def test_uninstall_wait_accepts_an_already_removed_directory(tmp_path: Path) -> None:
    assert verifier._wait_for_uninstall(tmp_path / "already-gone", timeout=0.01) is True
