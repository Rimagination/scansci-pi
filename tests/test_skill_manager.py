from pathlib import Path
import zipfile

import pytest

from scansci_html.builtin_skills import builtin_skill_asset_path, default_skill_records
from scansci_html.skill_manager import SkillInstallError, install_skill, installed_skills, marketplace_skills, skill_library_path


def test_web_access_is_packaged_as_builtin_skill(tmp_path: Path):
    records = default_skill_records()
    assert any(record["id"] == "web-access" and record["path"] == "builtin:web-access" for record in records)

    asset_path = builtin_skill_asset_path("web-access")
    assert (asset_path / "SKILL.md").is_file()
    assert (asset_path / "scripts" / "check-deps.mjs").is_file()
    assert (asset_path / "scripts" / "cdp-proxy.mjs").is_file()
    assert (asset_path / "references" / "cdp-api.md").is_file()

    rows = installed_skills(tmp_path / "workspace.sqlite")
    web_access = next(item for item in rows if item["id"] == "web-access")
    assert web_access["builtin"] is True
    assert web_access["available"] is True
    assert Path(web_access["skill_file"]).read_text(encoding="utf-8").startswith("---\nname: web-access")


def test_local_skill_install_copies_package_and_registers_provenance(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    source = tmp_path / "literature-map"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: Literature Map\ndescription: Map a research field from source papers.\n---\n# Literature Map\n", encoding="utf-8")
    (source / "references" / "workflow.md").write_text("Use explicit inclusion criteria.", encoding="utf-8")

    result = install_skill(workspace, {"source_type": "local", "source": str(source)})

    record = result["installed"][0]
    destination = Path(record["path"])
    assert destination == skill_library_path(workspace) / "literature-map"
    assert (destination / "SKILL.md").is_file()
    assert (destination / "references" / "workflow.md").read_text(encoding="utf-8") == "Use explicit inclusion criteria."
    assert record["source_type"] == "local"
    assert record["source"] == str(source.resolve())
    assert any(item["id"] == "literature-map" and item["available"] for item in installed_skills(workspace))


def test_archive_skill_install_and_zip_slip_protection(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    archive = tmp_path / "peer-review.skill"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("peer-review/SKILL.md", "---\nname: Peer Review\n---\n# Peer review\n")
        bundle.writestr("peer-review/checklist.txt", "Methods\nResults\n")

    result = install_skill(workspace, {"source_type": "archive", "source": str(archive)})

    assert result["installed"][0]["source_type"] == "archive"
    assert (Path(result["installed"][0]["path"]) / "checklist.txt").is_file()

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        bundle.writestr("../escaped/SKILL.md", "# not allowed")
    with pytest.raises(SkillInstallError, match="不安全"):
        install_skill(workspace, {"source_type": "archive", "source": str(unsafe)})


def test_marketplace_listing_uses_fallback_when_remote_catalog_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    def unavailable(_view: str, *, limit: int):
        raise SkillInstallError("offline")

    monkeypatch.setattr("scansci_html.skill_manager._fetch_marketplace_leaderboard", unavailable)

    listing = marketplace_skills()

    assert listing["offline"] is True
    assert listing["items"][0]["id"] == "vercel-labs/agent-skills/web-design-guidelines"
