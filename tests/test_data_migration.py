from __future__ import annotations

import gc
import json
from pathlib import Path
import sqlite3

from scansci_html.data_migration import inspect_data_roots, migrate_data_roots
from scansci_html.research_runs import ResearchRunStore, StageSpec
from scansci_html.workspace import initialize_notebook


def _seed_root(root: Path, *, notebook_id: str, title: str, marker: str) -> str:
    root.mkdir(parents=True)
    workspace = root / "workspace.sqlite"
    initialize_notebook(workspace, notebook_id=notebook_id, title=title, root_path=root / "library")
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id=notebook_id,
        workflow_type="research",
        title=title,
        input_payload={"path": str(root / "library")},
        stages=[StageSpec(key="plan", title="Plan", kind="model")],
    )
    store.append_message(run["run_id"], role="user", content=f"message-{marker}")
    (root / ".scansci-notebook.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_model": {"provider_id": marker, "model_id": marker},
                "providers": [{"id": marker, "name": marker}],
                "skills": [{"id": marker, "enabled": True}],
            }
        ),
        encoding="utf-8",
    )
    (root / "unique" / f"{marker}.txt").parent.mkdir(parents=True)
    (root / "unique" / f"{marker}.txt").write_text(str(root), encoding="utf-8")
    (root / "shared.txt").write_text(marker, encoding="utf-8")
    return run["run_id"]


def test_inspect_data_roots_is_read_only(tmp_path: Path) -> None:
    canonical = tmp_path / "ScanSci"
    pi = tmp_path / "ScanSciPi"
    _seed_root(canonical, notebook_id="nb-original", title="Original", marker="original")
    _seed_root(pi, notebook_id="nb-pi", title="Pi", marker="pi")

    report = inspect_data_roots(canonical, pi)

    assert report["canonical_workspace"]["research_runs"] == 1
    assert report["pi_workspace"]["research_runs"] == 1
    assert report["shared_relative_files"] == 3
    assert not list(tmp_path.glob(".ScanSci-unified-*"))


def test_migration_merges_rows_files_settings_and_keeps_both_sources(tmp_path: Path) -> None:
    canonical = tmp_path / "ScanSci"
    pi = tmp_path / "ScanSciPi"
    original_run = _seed_root(canonical, notebook_id="nb-original", title="Original", marker="original")
    pi_run = _seed_root(pi, notebook_id="nb-pi", title="Pi", marker="pi")
    backups = tmp_path / "backups"
    gc.collect()

    report = migrate_data_roots(canonical, pi, backup_parent=backups)

    assert report["status"] == "complete"
    assert pi.is_dir()
    assert Path(report["preserved_previous_root"]).is_dir()
    assert (canonical / "unique" / "original.txt").is_file()
    assert (canonical / "unique" / "pi.txt").is_file()
    assert (canonical / ".scansci-migration" / "original-conflicts" / "shared.txt").read_text() == "original"
    assert (canonical / "shared.txt").read_text() == "pi"

    settings = json.loads((canonical / ".scansci-notebook.json").read_text(encoding="utf-8"))
    assert settings["active_model"]["provider_id"] == "pi"
    assert {item["id"] for item in settings["providers"]} == {"original", "pi"}
    assert {item["id"] for item in settings["skills"]} == {"original", "pi"}

    connection = sqlite3.connect(canonical / "workspace.sqlite")
    try:
        assert {row[0] for row in connection.execute("select run_id from research_runs")} == {original_run, pi_run}
        assert connection.execute("select count(*) from research_run_messages").fetchone()[0] == 2
        roots = {row[0] for row in connection.execute("select root_path from notebooks")}
        assert all("ScanSciPi" not in root for root in roots)
        assert str(canonical / "library") in roots
    finally:
        connection.close()

    backup_set = Path(report["backup_set"])
    assert (backup_set / "ScanSci" / "workspace.sqlite").is_file()
    assert (backup_set / "ScanSciPi" / "workspace.sqlite").is_file()
    assert (backup_set / "migration-report.json").is_file()
