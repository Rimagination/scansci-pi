"""Bridge ScanSci to the installed EasySlides plugin.

ScanSci owns source intake and the product workflow.  EasySlides owns semantic
template rendering, editable PPTX export, and presentation quality gates.  The
adapter deliberately uses the plugin's current deck-plan contract instead of
copying an older EasySlides workflow into ScanSci.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Iterable
from uuid import uuid4


ProgressCallback = Callable[[float, str], None]

_PIPELINE_SCRIPTS = {
    "command_hub": "easyslides.py",
    "semantic_renderer": "semantic_template_renderer.py",
    "pptx_export": "svg_to_pptx.py",
    "template_gate": "template_production_gate.py",
    "plan_contract": "deck_plan_contract.py",
    "execution_lock": "deck_execution_lock.py",
    "academic_qa": "academic_qa_gate.py",
    "classic_text_capacity": "text_capacity.py",
    "classic_text_fit": "template_text_fit_check.py",
    "visual_measure": "visual_measure_gate.py",
    "visual_review": "visual_review.py",
}
_VALID_SCENARIOS = {
    "conference_talk",
    "lab_progress",
    "multi_paper_review",
    "proposal_or_fund",
    "single_paper_report",
    "thesis_defense",
    "workshop_training",
}
def find_easyslides_root(root: str | Path | None = None) -> Path:
    """Return the newest valid EasySlides plugin installation.

    An explicit function argument or environment override is authoritative.
    Automatic discovery ranks live and cached plugin builds by the version and
    Codex build timestamp in ``plugin.json``.
    """

    explicit: list[Path] = []
    if root is not None:
        explicit.append(Path(root))
    for name in ("SCANSCI_EASYSLIDES_ROOT", "EASYSLIDES_ROOT"):
        configured = os.getenv(name, "").strip()
        if configured:
            explicit.append(Path(configured))
    for candidate in _unique_paths(explicit):
        if _is_catalog_root(candidate):
            return candidate

    candidates = [path for path in _automatic_candidates() if _is_plugin_root(path)]
    if candidates:
        return max(candidates, key=_plugin_rank)
    if explicit:
        return explicit[0]
    return (Path.home() / ".codex" / "plugins" / "easyslides").resolve()


def easyslides_plugin_status(root: str | Path | None = None) -> dict[str, Any]:
    plugin_root = find_easyslides_root(root)
    manifest = _read_json(plugin_root / ".codex-plugin" / "plugin.json")
    bundle = _read_json(plugin_root / "bundle_manifest.json")
    scripts_dir = plugin_root / "scripts"
    pipeline = {name: (scripts_dir / filename).is_file() for name, filename in _PIPELINE_SCRIPTS.items()}
    catalog_available = (plugin_root / "templates" / "layouts" / "layouts_index.json").is_file()
    latest_pipeline = all(pipeline.values())
    bundle_status = str(bundle.get("status", "unknown"))
    discovered = [path for path in _automatic_candidates() if _is_plugin_root(path)]
    version = str(manifest.get("version", ""))
    return {
        "installed": catalog_available,
        "ready": bool(catalog_available and latest_pipeline and bundle_status in {"pass", "unknown"}),
        "catalog_available": catalog_available,
        "native_generation": all(pipeline.get(name, False) for name in ("command_hub", "semantic_renderer", "pptx_export", "template_gate")),
        "latest_pipeline": latest_pipeline,
        "integration_level": "latest" if latest_pipeline else "legacy",
        "integration_contract": "easyslides.deck_plan.v1",
        "pipeline": pipeline,
        "name": str(manifest.get("interface", {}).get("displayName") or manifest.get("name") or "EasySlides"),
        "version": version,
        "version_label": version or "版本未知",
        "bundle_status": bundle_status,
        "capabilities": list(manifest.get("interface", {}).get("capabilities", []) or []),
        "root": str(plugin_root),
        "candidate_count": len(discovered),
    }


def build_semantic_deck_plan(
    outline: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    template_id: str,
) -> dict[str, Any]:
    """Translate a ScanSci outline into the current EasySlides plan contract."""

    title = _plain(outline.get("title")) or "科研汇报"
    question = _plain(outline.get("central_question")) or _plain(outline.get("story")) or "基于所选材料形成可追溯的研究汇报"
    raw_slides = [dict(item) for item in list(outline.get("slides", []) or []) if isinstance(item, dict)]
    source_map = _build_source_map(sources)
    source_names = [item["title"] for item in source_map]
    source_label = _visual_clip("来源：" + "、".join(source_names), 70)
    all_evidence = _evidence_for_sources(source_map)
    scenario = _infer_scenario(outline, sources)

    agenda = [_visual_clip(_plain(item.get("title")) or f"研究要点 {index}", 28) for index, item in enumerate(raw_slides[:4], 1)]
    agenda.extend(["来源与可追溯性", "核心结论"])
    agenda = agenda[:6] or ["研究问题", "证据与结论"]

    slides: list[dict[str, Any]] = [
        _semantic_slide(
            1,
            role="cover",
            layout_id="cover",
            content_shape="cover",
            action_title=title,
            claim=question,
            evidence_sources=all_evidence,
            rhythm="anchor",
            slot_payload={
                "TITLE": _visual_clip(title, 36),
                "SUBTITLE": _visual_clip(question, 60),
                "AUTHOR": "ScanSci",
                "DATE": datetime.now().strftime("%Y.%m"),
            },
        ),
        _semantic_slide(
            2,
            role="toc",
            layout_id="toc",
            content_shape="agenda",
            action_title="汇报按问题、证据与结论逐层展开",
            claim="先明确问题，再组织证据，最后给出可追溯结论",
            evidence_sources=all_evidence,
            rhythm="breathing",
            item_count=len(agenda),
            slot_payload={
                "PAGE_TITLE": "汇报内容",
                "SECTION": "OVERVIEW",
                "AGENDA": agenda,
                "AGENDA_COUNT": str(len(agenda)),
                "SOURCE": source_label,
                "PAGE_NUM": "02",
            },
        ),
    ]

    for index, item in enumerate(raw_slides, start=3):
        slides.append(
            _content_slide(
                index,
                item,
                source_map=source_map,
                source_label=source_label,
            )
        )

    references_index = len(slides) + 1
    slides.append(
        _semantic_slide(
            references_index,
            role="references",
            layout_id="text_focus",
            content_shape="summary",
            action_title="所有关键结论均保留可回溯的材料来源",
            claim="来源列表用于核验汇报中的论点、数据与图表",
            evidence_sources=all_evidence,
            rhythm="dense",
            item_count=min(7, len(source_names)),
            slot_payload={
                "PAGE_TITLE": "来源与可追溯性",
                "SECTION": "SOURCES",
                "KEY_MESSAGE": "每条关键结论都应能回到原始材料",
                "BODY": [_visual_clip(name, 38) for name in source_names[:7]],
                "SOURCE": source_label,
                "PAGE_NUM": f"{references_index:02d}",
            },
        )
    )

    conclusion_index = len(slides) + 1
    conclusion = _plain(raw_slides[-1].get("takeaway")) if raw_slides else ""
    conclusion = conclusion or "现有证据支持以问题—证据—结论组织后续研究"
    slides.append(
        _semantic_slide(
            conclusion_index,
            role="conclusion",
            layout_id="text_focus",
            content_shape="summary",
            action_title=conclusion,
            claim=conclusion,
            evidence_sources=all_evidence,
            rhythm="anchor",
            item_count=2,
            slot_payload={
                "PAGE_TITLE": "核心结论",
                "SECTION": "CONCLUSION",
                "KEY_MESSAGE": _visual_clip(conclusion, 42),
                "BODY": [
                    "结论由已声明来源支持",
                    "后续汇报应继续核验关键数字与适用边界",
                ],
                "SOURCE": source_label,
                "PAGE_NUM": f"{conclusion_index:02d}",
            },
        )
    )

    return {
        "schema_version": "easyslides.deck_plan.v1",
        "scenario_profile": scenario,
        "scenario_variant": "scansci_source_grounded",
        "presentation_template_id": template_id,
        "title": title,
        "central_question": question,
        "source_map": source_map,
        "source_inventory": [
            {
                "id": item["id"],
                "name": item["title"],
                "kind": item["type"],
                "path": item["path"],
                "page_count": int(sources[index].get("page_count", 0) or 0),
            }
            for index, item in enumerate(source_map)
        ],
        "slides": slides,
    }


def render_semantic_deck(
    *,
    workspace: str | Path,
    deck_path: str | Path,
    outline: dict[str, Any],
    sources: list[dict[str, Any]],
    template: dict[str, Any],
    root: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Render a native EasySlides deck through the current gated pipeline."""

    status = easyslides_plugin_status(root)
    if not status["ready"]:
        missing = [name for name, available in status.get("pipeline", {}).items() if not available]
        detail = f"缺少：{', '.join(missing)}" if missing else "插件未就绪"
        raise RuntimeError(f"EasySlides 最新工作流不可用（{detail}），请在资源配置中修复或更新插件后重试。")

    plugin_root = Path(status["root"])
    template_id = str(template.get("id", "")).strip()
    source_template_id = str(template.get("source_template_id") or template_id).strip()
    template_dir = plugin_root / "templates" / "layouts" / source_template_id
    template_status = _read_json(template_dir / "template_status.json")
    if not bool(template.get("production_eligible")) or not bool(template_status.get("production_eligible")):
        raise RuntimeError(f"模板 {template_id} 尚未通过 EasySlides 生产门禁，已阻止交付。")

    target = Path(deck_path).resolve()
    project = target.parent / "projects" / f"{target.stem}-{uuid4().hex[:8]}"
    svg_output = project / "svg_output"
    reports = project / "reports"
    notes = project / "notes"
    for directory in (project, svg_output, reports, notes):
        directory.mkdir(parents=True, exist_ok=True)

    # The product-facing template id remains stable while EasySlides receives
    # the physical template id recorded in its own installed catalog.
    plan = build_semantic_deck_plan(outline, sources, template_id=source_template_id)
    plan_path = project / "deck_plan.json"
    lock_path = project / "deck_execution_lock.json"
    _write_json(plan_path, plan)
    _write_json(notes / "source_pack.json", {"sources": plan["source_inventory"]})
    (project / "design_spec.md").write_text(
        f"# {plan['title']}\n\n- 场景：{plan['scenario_profile']}\n- 模板：{template_id}\n- EasySlides 资源：{source_template_id}\n- 页数：{len(plan['slides'])}\n",
        encoding="utf-8",
    )
    (project / "spec_lock.md").write_text(
        "# EasySlides execution contract\n\n"
        "Use named semantic slots only. Keep claims bound to declared source_map entries. "
        "Fail closed on plan, academic, render, or machine visual QA errors.\n",
        encoding="utf-8",
    )

    _progress(on_progress, 0.32, "EasySlides 正在校验新版页面计划")
    contract = _run_json(
        [
            sys.executable,
            str(plugin_root / "scripts" / "deck_plan_contract.py"),
            str(plan_path),
            "--repo-root",
            str(plugin_root),
            "--json",
        ],
        cwd=plugin_root,
        timeout=120,
        allow_nonzero=True,
    )
    _write_json(reports / "deck_plan_contract.json", contract)
    if str(contract.get("status", "")).casefold() != "pass":
        raise RuntimeError(_gate_error("EasySlides 页面计划不符合最新版契约", contract))

    academic_qa = _run_json(
        [
            sys.executable,
            str(plugin_root / "scripts" / "academic_qa_gate.py"),
            str(plan_path),
            "--repo-root",
            str(plugin_root),
            "--json",
        ],
        cwd=plugin_root,
        timeout=120,
        allow_nonzero=True,
    )
    _write_json(reports / "academic_qa.json", academic_qa)
    if str(academic_qa.get("status", "")).casefold() == "fail":
        raise RuntimeError(_gate_error("EasySlides 学术表达与证据检查未通过", academic_qa))

    _run_json(
        [
            sys.executable,
            str(plugin_root / "scripts" / "deck_execution_lock.py"),
            str(plan_path),
            "--repo-root",
            str(plugin_root),
            "--write",
            str(lock_path),
            "--json",
        ],
        cwd=plugin_root,
        timeout=120,
    )
    lock_validation = _run_json(
        [
            sys.executable,
            str(plugin_root / "scripts" / "deck_execution_lock.py"),
            str(plan_path),
            "--repo-root",
            str(plugin_root),
            "--validate",
            str(lock_path),
            "--json",
        ],
        cwd=plugin_root,
        timeout=120,
        allow_nonzero=True,
    )
    _write_json(reports / "execution_lock_validation.json", lock_validation)
    if str(lock_validation.get("status", "")).casefold() != "pass":
        raise RuntimeError(_gate_error("EasySlides 执行锁校验未通过", lock_validation))

    _progress(on_progress, 0.48, "EasySlides 正在按场景与语义槽位排版")
    render_result = _run_json(
        [
            sys.executable,
            str(plugin_root / "scripts" / "easyslides.py"),
            "semantic-render",
            str(template_dir),
            str(plan_path),
            "--out",
            str(svg_output),
            "--json",
        ],
        cwd=plugin_root,
        timeout=180,
    )

    _progress(on_progress, 0.68, "EasySlides 正在导出原生可编辑 PPTX")
    _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "svg_to_pptx.py"),
            str(project),
            "-o",
            str(target),
            "--only",
            "native",
            "-t",
            "fade",
            "-a",
            "none",
            "--no-cache",
        ],
        cwd=plugin_root,
        timeout=300,
    )
    if not target.is_file() or target.stat().st_size < 1024:
        raise RuntimeError("EasySlides 未生成有效的 PPTX 文件。")

    _progress(on_progress, 0.82, "EasySlides 正在检查模板、文本与版面")
    template_gate_path = reports / "template_gate.json"
    _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "easyslides.py"),
            "template-gate",
            str(template_dir),
            "--pptx",
            str(target),
            "--report",
            str(template_gate_path),
            "--json",
        ],
        cwd=plugin_root,
        timeout=300,
        allow_nonzero=True,
    )
    template_gate = _read_json(template_gate_path)
    if not template_gate:
        raise RuntimeError("EasySlides 没有写出模板质量报告。")
    blocking_count = int(template_gate.get("blocking_count", 0) or 0)
    template_gate_status = str(template_gate.get("status", "")).casefold()
    preapproved_review = (
        template_gate_status == "review_required"
        and blocking_count == 0
        and str(template_status.get("last_gate_status", "")).casefold() == "pass"
    )
    if template_gate_status != "pass" and not preapproved_review:
        raise RuntimeError(_gate_error("EasySlides 模板质量门禁未通过", template_gate))

    visual_measure_path = reports / "visual_measure.json"
    _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "visual_measure_gate.py"),
            "--pptx",
            str(target),
            "--skip-slot-contract",
            "--report",
            str(visual_measure_path),
            "--quiet",
        ],
        cwd=plugin_root,
        timeout=300,
        allow_nonzero=True,
    )
    visual_measure = _read_json(visual_measure_path)
    if str(visual_measure.get("status", "")).casefold() != "pass":
        raise RuntimeError(_gate_error("EasySlides 文本与版面测量未通过", visual_measure))

    _progress(on_progress, 0.93, "EasySlides 正在生成逐页视觉复核包")
    visual_review_dir = reports / "visual_review"
    review_command = _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "visual_review.py"),
            str(target),
            "--out",
            str(visual_review_dir),
            "--title",
            plan["title"],
            "--quiet",
        ],
        cwd=plugin_root,
        timeout=300,
        allow_nonzero=True,
    )
    visual_review = _read_json(visual_review_dir / "visual_review.json")
    if not visual_review:
        visual_review = {
            "status": "unavailable",
            "reason": _command_detail(review_command),
            "output_dir": str(visual_review_dir),
        }

    _progress(on_progress, 0.99, "EasySlides 最新质量链路已完成")
    return {
        "project_path": str(project),
        "plan": plan,
        "plan_path": str(plan_path),
        "execution_lock_path": str(lock_path),
        "render_manifest": render_result,
        "quality_gate": {
            "status": "pass",
            "report_path": str(visual_measure_path),
            "blocking_count": blocking_count,
            "review_count": int(template_gate.get("review_count", 0) or 0),
            "basis": "latest_machine_pipeline",
            "template_review_basis": "preapproved_template" if preapproved_review else "runtime_gate",
        },
        "contract": contract,
        "academic_qa": academic_qa,
        "execution_lock_validation": lock_validation,
        "template_gate": template_gate,
        "visual_measure": visual_measure,
        "visual_review": visual_review,
        "plugin": {
            key: status[key]
            for key in (
                "name",
                "version",
                "version_label",
                "bundle_status",
                "native_generation",
                "latest_pipeline",
                "integration_level",
                "integration_contract",
                "root",
            )
        },
    }


def _content_slide(
    index: int,
    item: dict[str, Any],
    *,
    source_map: list[dict[str, Any]],
    source_label: str,
) -> dict[str, Any]:
    title = _plain(item.get("title")) or f"研究要点 {index - 2}"
    takeaway = _plain(item.get("takeaway")) or f"本页证据进一步说明：{title}"
    bullets = [_plain(value) for value in list(item.get("bullets", []) or []) if _plain(value)] or [takeaway]
    source_pages = [int(value) for value in list(item.get("source_pages", []) or []) if str(value).isdigit()]
    evidence = _evidence_for_sources(source_map, pages=source_pages)
    page_suffix = f" · p.{','.join(map(str, source_pages))}" if source_pages else ""
    footer = _visual_clip(source_label + page_suffix, 70)
    requested = _plain(item.get("layout")).casefold()
    common = {
        "PAGE_TITLE": _visual_clip(title, 26),
        "SECTION": "EVIDENCE",
        "SOURCE": footer,
        "PAGE_NUM": f"{index:02d}",
    }

    if requested == "comparison" and len(bullets) >= 2:
        split = max(1, len(bullets) // 2)
        payload = {
            **common,
            "KEY_MESSAGE": _visual_clip(takeaway, 44),
            "LEFT_BADGE": "A",
            "LEFT_TITLE": "路径 A",
            "LEFT_BODY": [_visual_clip(value, 24) for value in bullets[:split][:5]],
            "RIGHT_BADGE": "B",
            "RIGHT_TITLE": "路径 B",
            "RIGHT_BODY": [_visual_clip(value, 24) for value in bullets[split:][:5]] or [_visual_clip(takeaway, 24)],
        }
        return _semantic_slide(index, role="content", layout_id="comparison_focus", content_shape="comparison", action_title=takeaway, claim=takeaway, evidence_sources=evidence, rhythm="dense", item_count=len(bullets), slot_payload=payload)

    if requested == "branches" and len(bullets) >= 2:
        split = max(1, len(bullets) // 2)
        payload = {
            **common,
            "LEFT_TITLE": "主要发现",
            "RIGHT_TITLE": "边界与启示",
            "LEFT_BODY": [_visual_clip(value, 24) for value in bullets[:split][:7]],
            "RIGHT_BODY": [_visual_clip(value, 24) for value in bullets[split:][:7]] or [_visual_clip(takeaway, 24)],
        }
        return _semantic_slide(index, role="content", layout_id="two_column", content_shape="two_sides", action_title=takeaway, claim=takeaway, evidence_sources=evidence, rhythm="dense", item_count=len(bullets), slot_payload=payload)

    if requested == "cards" and len(bullets) >= 3:
        payload = dict(common)
        for card_index, bullet in enumerate(bullets[:3], start=1):
            heading, body = _card_parts(bullet, card_index)
            payload[f"CARD_{card_index}_TITLE"] = _visual_clip(heading, 13)
            payload[f"CARD_{card_index}_BODY"] = [_visual_clip(body, 15)]
        return _semantic_slide(index, role="content", layout_id="three_cards", content_shape="three_findings", action_title=takeaway, claim=takeaway, evidence_sources=evidence, rhythm="breathing", item_count=3, slot_payload=payload)

    if requested == "process" and len(bullets) >= 4:
        payload = dict(common)
        for step_index, bullet in enumerate(bullets[:4], start=1):
            payload[f"STEP_{step_index}_TITLE"] = f"步骤 {step_index}"
            payload[f"STEP_{step_index}_BODY"] = _visual_clip(bullet, 48)
        return _semantic_slide(index, role="content", layout_id="process", content_shape="process", action_title=takeaway, claim=takeaway, evidence_sources=evidence, rhythm="breathing", item_count=4, slot_payload=payload)

    payload = {
        **common,
        "KEY_MESSAGE": _visual_clip(takeaway, 44),
        "BODY": [_visual_clip(value, 38) for value in bullets[:7]],
    }
    return _semantic_slide(index, role="content", layout_id="text_focus", content_shape="text_focus", action_title=takeaway, claim=takeaway, evidence_sources=evidence, rhythm="dense", item_count=min(7, len(bullets)), slot_payload=payload)


def _semantic_slide(
    index: int,
    *,
    role: str,
    layout_id: str,
    content_shape: str,
    action_title: str,
    claim: str,
    evidence_sources: list[dict[str, str]],
    rhythm: str,
    slot_payload: dict[str, Any],
    item_count: int = 1,
) -> dict[str, Any]:
    slide = {
        "page": f"P{index:02d}",
        "role": role,
        "layout_id": layout_id,
        "content_shape": content_shape,
        "item_count": max(1, int(item_count or 1)),
        "action_title": _plain(action_title),
        "claim": _plain(claim),
        "evidence_sources": [dict(item) for item in evidence_sources],
        "rhythm": rhythm,
        "speaker_note": _plain(claim),
        "slot_payload": slot_payload,
    }
    return slide


def _build_source_map(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for index, source in enumerate(sources, start=1):
        source_id = f"src-{index:02d}"
        name = _plain(source.get("name")) or f"材料 {index}"
        raw_path = str(source.get("path", "")).strip()
        path = str(Path(raw_path).resolve()) if raw_path else f"scansci://source/{_plain(source.get('id')) or source_id}"
        kind = _plain(source.get("kind")).casefold()
        source_type = "paper" if kind == "pdf" else "presentation" if kind in {"ppt", "pptx", "powerpoint"} else "document"
        result.append({"id": source_id, "type": source_type, "path": path, "title": name})
    if not result:
        result.append({"id": "src-01", "type": "document", "path": "scansci://source/outline", "title": "ScanSci 汇报大纲"})
    return result


def _evidence_for_sources(source_map: list[dict[str, str]], *, pages: list[int] | None = None) -> list[dict[str, str]]:
    locator = f"p.{','.join(map(str, pages))}" if pages else "document"
    kind = "section" if pages else "source"
    return [{"source_id": item["id"], "locator": locator, "kind": kind} for item in source_map]


def _infer_scenario(outline: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    text = " ".join(
        _plain(value).casefold()
        for value in (outline.get("title"), outline.get("central_question"), outline.get("story"))
    )
    rules = (
        ("thesis_defense", ("答辩", "毕业", "defense", "thesis")),
        ("proposal_or_fund", ("基金", "申请", "开题", "proposal", "grant", "nsfc")),
        ("conference_talk", ("会议", "conference", "talk", "口头报告")),
        ("workshop_training", ("培训", "课程", "workshop", "training", "教程")),
        ("lab_progress", ("组会", "进展", "阶段汇报", "lab progress")),
    )
    for scenario, cues in rules:
        if any(cue in text for cue in cues):
            return scenario
    scenario = "multi_paper_review" if len(sources) > 1 else "single_paper_report"
    return scenario if scenario in _VALID_SCENARIOS else "single_paper_report"


def _automatic_candidates() -> list[Path]:
    home = Path.home()
    local_app_data = Path(os.getenv("LOCALAPPDATA", str(home)))
    suite_root = Path(os.getenv("SCANSCI_SUITE_ROOT", r"D:\scansci"))
    candidates = [
        home / ".codex" / "plugins" / "easyslides",
        local_app_data / "ScanSci" / "plugins" / "easyslides",
        suite_root / "easyslides",
    ]
    cache_root = home / ".codex" / "plugins" / "cache" / "local-plugins" / "easyslides"
    if cache_root.is_dir():
        candidates.extend(path for path in cache_root.iterdir() if path.is_dir())
    return _unique_paths(candidates)


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser().absolute()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _is_plugin_root(path: Path) -> bool:
    return (
        _is_catalog_root(path)
        and (path / "scripts" / "easyslides.py").is_file()
    )


def _is_catalog_root(path: Path) -> bool:
    return (path / "templates" / "layouts" / "layouts_index.json").is_file()


def _plugin_rank(path: Path) -> tuple[tuple[int, ...], int, float]:
    manifest_path = path / ".codex-plugin" / "plugin.json"
    manifest = _read_json(manifest_path)
    version = str(manifest.get("version", ""))
    match = re.search(r"^(\d+(?:\.\d+)*)(?:\+codex\.(\d+))?", version)
    semantic = tuple(int(part) for part in match.group(1).split(".")) if match else (0,)
    build = int(match.group(2) or 0) if match else 0
    try:
        modified = manifest_path.stat().st_mtime
    except OSError:
        modified = 0.0
    return semantic, build, modified


def _card_parts(value: str, index: int) -> tuple[str, str]:
    for separator in ("：", ":", "—", "-"):
        if separator in value:
            heading, body = value.split(separator, 1)
            if _plain(heading) and _plain(body):
                return _plain(heading), _plain(body)
    return f"要点 {index}", value


def _plain(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"```\w*", " ", text)
    text = text.replace("```", " ").replace("`", "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?:^|\s)#{1,6}\s*", " ", text)
    text = re.sub(r"(?:^|\s)[-*+]\s+", " ", text)
    return " ".join(text.split()).strip()


def _visual_clip(value: object, limit: float) -> str:
    text = _plain(value)
    if not text:
        return "—"
    full_cost = sum(1.0 if ord(char) > 127 else 0.55 for char in text)
    clipped_needed = full_cost > limit
    target = max(1.0, limit - 1.0) if clipped_needed else limit
    total = 0.0
    result: list[str] = []
    for char in text:
        cost = 1.0 if ord(char) > 127 else 0.55
        if total + cost > target:
            break
        result.append(char)
        total += cost
    clipped = "".join(result).rstrip(" ,，。；;:-—")
    if clipped_needed and clipped:
        return f"{clipped}…"
    return clipped or text[:1]


def _gate_error(prefix: str, report: dict[str, Any]) -> str:
    issues = report.get("issues", [])
    details = []
    if isinstance(issues, list):
        for item in issues[:3]:
            if isinstance(item, dict):
                details.append(str(item.get("message") or item.get("code") or "未知问题"))
    suffix = "；".join(details) if details else str(report.get("error") or "请查看项目 reports 目录")
    return f"{prefix}：{suffix}"


def _progress(callback: ProgressCallback | None, fraction: float, summary: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, fraction)), summary)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    allow_nonzero: bool = False,
) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        startupinfo=startupinfo,
        creationflags=creationflags,
        env=env,
    )
    if completed.returncode != 0 and not allow_nonzero:
        raise RuntimeError(f"EasySlides 执行失败：{_command_detail(completed)}")
    return completed


def _command_detail(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "命令未返回详细信息").strip()[-1200:]


def _run_json(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    allow_nonzero: bool = False,
) -> dict[str, Any]:
    completed = _run(command, cwd=cwd, timeout=timeout, allow_nonzero=allow_nonzero)
    output = completed.stdout.strip()
    candidates = [output]
    candidates.extend(line.strip() for line in reversed(output.splitlines()) if line.strip().startswith("{"))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"EasySlides 返回了无法识别的结果：{_command_detail(completed)}")
