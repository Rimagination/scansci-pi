from __future__ import annotations

import json
from pathlib import Path

import pytest

from scansci_html import research_tools
from scansci_html.research_tools import create_ppt_project
from scansci_html.slides_templates import (
    get_slide_template,
    list_slide_templates,
    resolve_slide_template_dir,
    slide_template_asset,
)
from scansci_html.webapp import NotebookWebApp


def _easy_slides_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "easyslides"
    layouts = root / "templates" / "layouts"
    template = layouts / "academic_general"
    template.mkdir(parents=True)
    (layouts / "layouts_index.json").write_text(
        json.dumps(
            {
                "academic_general": {
                    "summary": "General academic presentation template.",
                    "keywords": ["academic", "research"],
                }
            }
        ),
        encoding="utf-8",
    )
    (template / "design_spec.md").write_text(
        """---
template_id: academic_general
display_name_zh: 学术通用
category: general
primary_color: "#003366"
canvas_format: ppt169
replication_mode: classic
use_cases: Research talks and progress reviews
design_tone: Professional and rigorous
---
""",
        encoding="utf-8",
    )
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="#fff"/></svg>'
    (template / "01_cover.svg").write_text(svg, encoding="utf-8")
    (template / "03_content.svg").write_text(svg, encoding="utf-8")
    (template / "layouts.json").write_text('{"template_id":"academic_general"}', encoding="utf-8")
    return root


def _add_nsfc_template(root: Path) -> Path:
    layouts = root / "templates" / "layouts"
    index_path = layouts / "layouts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["nsfc_purple_semantic"] = {
        "summary": "Purple semantic defense template.",
        "keywords": ["nsfc", "defense"],
    }
    index_path.write_text(json.dumps(index), encoding="utf-8")
    template = layouts / "nsfc_purple_semantic"
    template.mkdir()
    (template / "design_spec.md").write_text(
        "---\ntemplate_id: nsfc_purple_semantic\ncanvas: ppt169\nmode: semantic\n---\n",
        encoding="utf-8",
    )
    (template / "template_status.json").write_text(
        json.dumps({"status": "production", "production_eligible": True}),
        encoding="utf-8",
    )
    (template / "template.json").write_text(
        json.dumps(
            {
                "display_name": "NSFC Purple Semantic",
                "recommended_template_route": "semantic_named_slots",
                "output_contract": "editable-native-pptx",
            }
        ),
        encoding="utf-8",
    )
    (template / "layouts.json").write_text('{"layouts":[]}', encoding="utf-8")
    (template / "01_cover.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"></svg>',
        encoding="utf-8",
    )
    return template


def test_active_easyslides_templates_expose_svg_previews(tmp_path: Path):
    root = _easy_slides_fixture(tmp_path)

    catalog = list_slide_templates(root)
    template = catalog["templates"][0]

    assert catalog["available"] is True
    assert template["id"] == "academic_general"
    assert template["name"] == "学术通用"
    assert template["primary_color"] == "#003366"
    assert template["preview_url"].endswith("/01_cover.svg")
    assert [page["label"] for page in template["pages"]] == ["封面", "正文"]
    assert slide_template_asset("academic_general", "01_cover.svg", root).is_file()
    with pytest.raises(FileNotFoundError):
        slide_template_asset("academic_general", "../layouts_index.json", root)


def test_webapp_serves_template_catalog_and_preview(tmp_path: Path):
    root = _easy_slides_fixture(tmp_path)
    app = NotebookWebApp(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        slides_root=root,
    )

    catalog_response = app.dispatch("GET", "/api/slides/templates")
    preview_response = app.dispatch("GET", "/api/slides/templates/academic_general/pages/01_cover.svg")
    catalog = json.loads(catalog_response.body.decode("utf-8"))

    assert catalog_response.status == 200
    assert catalog["templates"][0]["name"] == "学术通用"
    assert preview_response.status == 200
    assert preview_response.content_type.startswith("image/svg+xml")
    assert preview_response.body.startswith(b"<svg")


def test_nsfc_defense_is_the_public_id_for_the_installed_semantic_template(tmp_path: Path):
    root = _easy_slides_fixture(tmp_path)
    physical_template = _add_nsfc_template(root)

    catalog = list_slide_templates(root)
    nsfc = get_slide_template("nsfc_defense", root)
    legacy = get_slide_template("nsfc_purple_semantic", root)

    assert [item["id"] for item in catalog["templates"]] == ["academic_general", "nsfc_defense"]
    assert nsfc["name"] == "NSFC 答辩"
    assert nsfc["source_template_id"] == "nsfc_purple_semantic"
    assert nsfc["generation_mode"] == "easyslides-semantic"
    assert legacy["id"] == "nsfc_defense"
    assert resolve_slide_template_dir("nsfc_defense", root) == physical_template.resolve()
    assert slide_template_asset("nsfc_defense", "01_cover.svg", root).is_file()


def test_create_ppt_project_installs_selected_easyslides_template(tmp_path: Path, monkeypatch):
    slides_root = _easy_slides_fixture(tmp_path)
    suite_root = tmp_path / "suite"
    script = suite_root / "easyslides" / "scripts" / "project_manager.py"
    script.parent.mkdir(parents=True)
    script.write_text("# fixture", encoding="utf-8")
    monkeypatch.setenv("EASYSLIDES_ROOT", str(slides_root))
    monkeypatch.setattr(research_tools, "_SCANSCI_SUITE_ROOT", suite_root)

    def fake_run(command: list[str], *, timeout: float):
        if "init" in command:
            name = command[command.index("init") + 1]
            project_root = Path(command[command.index("--dir") + 1])
            from datetime import datetime

            project = project_root / f"{name}_ppt169_{datetime.now().strftime('%Y%m%d')}"
            for directory in ("templates", "notes", "sources"):
                (project / directory).mkdir(parents=True, exist_ok=True)
        return None

    monkeypatch.setattr(research_tools, "_run_command", fake_run)
    workspace = tmp_path / "data" / "workspace.sqlite"
    workspace.parent.mkdir()
    result = create_ppt_project(
        {"notebook_id": "research", "title": "Research", "sources": []},
        workspace=workspace,
        topic="Evidence review",
        template_id="academic_general",
    )

    project = Path(result["project_path"])
    selection = json.loads((project / "template_selection.json").read_text(encoding="utf-8"))
    plan = json.loads((project / "notes" / "deck-plan.json").read_text(encoding="utf-8"))
    assert result["template_id"] == "academic_general"
    assert (project / "templates" / "academic_general" / "01_cover.svg").is_file()
    assert selection["template_path"] == "templates/academic_general"
    assert plan["template"]["name"] == "学术通用"
