import os
from pathlib import Path

from scansci_html.cloakbrowser_compat import configure_builtin_cloakbrowser


def test_configure_builtin_cloakbrowser_sets_project_managed_cache(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLOAKBROWSER_CACHE_DIR", raising=False)

    cache_dir = configure_builtin_cloakbrowser(tmp_path / "runtime")

    assert cache_dir == (tmp_path / "runtime").resolve()
    assert os.environ["CLOAKBROWSER_CACHE_DIR"] == str(cache_dir)
    assert cache_dir.exists()


def test_configure_builtin_cloakbrowser_respects_existing_cache(tmp_path: Path, monkeypatch):
    existing = tmp_path / "existing"
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(existing))

    cache_dir = configure_builtin_cloakbrowser(tmp_path / "ignored")

    assert cache_dir == existing
