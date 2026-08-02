from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scansci_html.easyslides_classic import build_classic_deck_plan, formal_classic_template_ids
from scansci_html.easyslides_plugin import (
    build_semantic_deck_plan,
    easyslides_plugin_status,
    find_easyslides_root,
)


def _outline() -> dict[str, object]:
    return {
        "title": "Evidence-oriented review",
        "central_question": "Which conclusions are supported by the supplied sources?",
        "slides": [
            {
                "title": "Research context",
                "takeaway": "The scope is explicitly bounded by the supplied evidence.",
                "layout": "comparison",
                "bullets": ["Supported finding", "Open limitation"],
                "source_pages": [1, 2],
            }
        ],
    }


def test_scansci_builds_the_current_easyslides_plan_contract() -> None:
    plan = build_semantic_deck_plan(
        _outline(),
        [
            {"id": "paper-a", "name": "Paper A", "kind": "pdf", "path": "paper-a.pdf"},
            {"id": "notes-b", "name": "Notes B", "kind": "markdown", "path": "notes-b.md"},
        ],
        template_id="nsfc_purple_semantic",
    )

    assert plan["schema_version"] == "easyslides.deck_plan.v1"
    assert plan["scenario_profile"] == "multi_paper_review"
    assert plan["presentation_template_id"] == "nsfc_purple_semantic"
    assert "template_id" not in plan
    assert len(plan["source_map"]) == 2
    assert all({"id", "type", "path", "title"} <= set(source) for source in plan["source_map"])
    assert plan["slides"][-2]["role"] == "references"
    assert plan["slides"][-1]["role"] == "conclusion"
    assert {slide["rhythm"] for slide in plan["slides"]} <= {"anchor", "dense", "breathing"}
    assert all("template_id" not in slide for slide in plan["slides"])
    assert all(
        {"source_id", "locator", "kind"} <= set(evidence)
        for slide in plan["slides"]
        for evidence in slide["evidence_sources"]
    )


def test_plugin_status_reports_the_latest_pipeline_when_all_scripts_exist(tmp_path: Path) -> None:
    root = tmp_path / "easyslides"
    (root / "templates" / "layouts").mkdir(parents=True)
    (root / "templates" / "layouts" / "layouts_index.json").write_text("{}", encoding="utf-8")
    (root / ".codex-plugin").mkdir()
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "easyslides", "version": "1.2.3+codex.20260801010101"}),
        encoding="utf-8",
    )
    (root / "bundle_manifest.json").write_text('{"status":"pass"}', encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    for script in (
        "easyslides.py",
        "semantic_template_renderer.py",
        "svg_to_pptx.py",
        "template_production_gate.py",
        "deck_plan_contract.py",
        "deck_execution_lock.py",
        "academic_qa_gate.py",
        "visual_measure_gate.py",
        "visual_review.py",
        "text_capacity.py",
        "template_text_fit_check.py",
    ):
        (scripts / script).write_text("# fixture\n", encoding="utf-8")

    status = easyslides_plugin_status(root)

    assert find_easyslides_root(root) == root.resolve()
    assert status["ready"] is True
    assert status["latest_pipeline"] is True
    assert status["integration_level"] == "latest"
    assert status["version"] == "1.2.3+codex.20260801010101"


def test_formal_classic_templates_share_the_native_shell_plan_contract() -> None:
    plan = build_classic_deck_plan(
        {
            "title": "可追溯科研证据工作流",
            "central_question": "如何把资料组织成可核验的研究证据？",
            "slides": [
                {
                    "title": "文档结构与证据片段",
                    "takeaway": "保留文档、章节、页码与原文证据之间的关系。",
                    "bullets": ["先生成文件摘要", "再执行片段级检索"],
                    "source_pages": [1, 2],
                }
            ],
        },
        [{"id": "paper-a", "name": "Paper A", "kind": "pdf", "path": "paper-a.pdf"}],
        template_id="academic_general",
    )

    assert formal_classic_template_ids() == (
        "academic_general",
        "academic_scqa",
        "defense_leftnav",
        "defense_topnav",
        "literature_minimal",
    )
    assert [slide["role"] for slide in plan["slides"]] == ["cover", "toc", "chapter", "content", "ending"]
    assert plan["slides"][3]["slot_payload"]["CONTENT_BODY"] == ["先生成文件摘要", "再执行片段级检索"]
    assert plan["slides"][3]["source_pages"] == [1, 2]


def test_installed_easyslides_accepts_the_scansci_plan(tmp_path: Path) -> None:
    status = easyslides_plugin_status()
    if not status.get("ready"):
        pytest.skip("EasySlides latest pipeline is not installed")

    root = Path(str(status["root"]))
    plan_path = tmp_path / "deck_plan.json"
    plan_path.write_text(
        json.dumps(
            build_semantic_deck_plan(
                _outline(),
                [{"id": "paper-a", "name": "Paper A", "kind": "pdf", "path": "paper-a.pdf"}],
                template_id="nsfc_purple_semantic",
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for script in ("deck_plan_contract.py", "academic_qa_gate.py"):
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / script),
                str(plan_path),
                "--repo-root",
                str(root),
                "--json",
            ],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        report = json.loads(completed.stdout)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert report["status"] == "pass"
