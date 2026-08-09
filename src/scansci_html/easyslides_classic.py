"""Native EasySlides renderer for the five formal classic SVG templates.

The classic templates pre-date the semantic named-slot renderer, but they
already expose an explicit shell roster, slot models, and text-capacity
contracts.  This adapter keeps those SVG masters intact, fills only declared
text slots, and delegates editable PPTX export and visual QA to EasySlides.
"""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Callable, Iterable
from uuid import uuid4
from xml.etree import ElementTree as ET

from .easyslides_plugin import (
    _command_detail,
    _progress,
    _read_json,
    _run,
    _write_json,
    easyslides_plugin_status,
)


ProgressCallback = Callable[[float, str], None]

_SVG_NS = "http://www.w3.org/2000/svg"
_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_FORMAL_CLASSIC_IDS = {
    "academic_general",
    "academic_scqa",
    "defense_leftnav",
    "defense_topnav",
    "literature_minimal",
}
ET.register_namespace("", _SVG_NS)


def build_classic_deck_plan(
    outline: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    template_id: str,
    layouts: dict[str, Any] | None = None,
    text_capacity: ModuleType | None = None,
) -> dict[str, Any]:
    """Build a shell-led plan for an EasySlides classic template."""

    title = _plain(outline.get("title")) or "科研汇报"
    question = _plain(outline.get("central_question")) or _plain(outline.get("story")) or "基于已选资料形成可追溯的研究汇报"
    raw_slides = [dict(item) for item in list(outline.get("slides", []) or []) if isinstance(item, dict)]
    if not raw_slides:
        raw_slides = [
            {
                "title": "研究问题与材料范围",
                "takeaway": question,
                "bullets": ["本页内容基于已选资料整理", "关键结论需回到原始材料核验"],
                "source_pages": [],
            }
        ]
    if layouts and text_capacity:
        raw_slides = _split_overloaded_slides(raw_slides, layouts, text_capacity)

    source_names = [_plain(item.get("name")) for item in sources if _plain(item.get("name"))]
    source_label = _clip("；".join(source_names[:3]) or "已选本地资料", 30)
    section_titles = [_plain(item.get("title")) or f"研究要点 {index}" for index, item in enumerate(raw_slides, 1)]
    toc_payload = _base_payload(title, question, source_label)
    toc_payload.update({"TOC_TITLE": "汇报内容", "TOC_INTRO": "从问题、证据到结论逐层展开"})
    for index in range(1, 7):
        heading = section_titles[index - 1] if index <= len(section_titles) else ""
        toc_payload[f"TOC_ITEM_{index}_TITLE"] = heading
        toc_payload[f"TOC_ITEM_{index}_DESC"] = "基于已选资料组织论点与证据" if heading else ""
        toc_payload[f"SECTION_{index}"] = heading

    slides: list[dict[str, Any]] = []
    slides.append(
        {
            "index": 1,
            "role": "cover",
            "shell": "cover",
            "title": title,
            "slot_payload": _base_payload(title, question, source_label),
            "source_pages": [],
        }
    )
    slides.append(
        {
            "index": 2,
            "role": "toc",
            "shell": "toc",
            "title": "汇报内容",
            "slot_payload": {**toc_payload, "PAGE_NUM": "02"},
            "source_pages": [],
        }
    )
    chapter_payload = _base_payload(title, question, source_label)
    chapter_payload.update(
        {
            "CHAPTER_NUM": "01",
            "SECTION_NUMBER": "01",
            "PART_LABEL": "PART 01",
            "SCQA_LABEL": "RESEARCH",
            "CHAPTER_TITLE": "研究内容",
            "SECTION_TITLE": "研究内容",
            "CHAPTER_DESC": question,
            "SECTION_SUBTITLE": question,
            "SECTION_STATEMENT": "围绕研究问题组织证据、比较与结论",
            # Classic chapter masters use TITLE as a small running footer,
            # not as a second copy of the full cover title.
            "TITLE": _clip(title, 28),
        }
    )
    slides.append(
        {
            "index": 3,
            "role": "chapter",
            "shell": "chapter",
            "title": "研究内容",
            "slot_payload": chapter_payload,
            "source_pages": [],
        }
    )

    for item_index, item in enumerate(raw_slides, 1):
        slide_index = len(slides) + 1
        page_title = _plain(item.get("title")) or f"研究要点 {item_index}"
        takeaway = _plain(item.get("takeaway")) or question
        bullets = [_plain(value) for value in list(item.get("bullets", []) or []) if _plain(value)]
        if not bullets:
            bullets = [takeaway]
        payload = _base_payload(title, question, source_label)
        payload.update(
            {
                "SECTION_NUM": f"{item_index:02d}",
                "ACTIVE_SECTION": "研究内容",
                "ACTIVE_SECTION_LABEL": "研究内容",
                "SECTION_NAME": "研究内容",
                "CHAPTER_TITLE": "研究内容",
                "PAGE_TITLE": page_title,
                "KEY_MESSAGE": takeaway,
                "CONTENT_AREA": bullets,
                "CONTENT_BODY": bullets,
                "SOURCE": source_label,
                "PAGE_NUM": f"{slide_index:02d}",
            }
        )
        slides.append(
            {
                "index": slide_index,
                "role": "content",
                "shell": "content",
                "title": page_title,
                "slot_payload": payload,
                "source_pages": list(item.get("source_pages", []) or []),
            }
        )

    ending_index = len(slides) + 1
    ending_payload = _base_payload(title, question, source_label)
    ending_payload.update(
        {
            "THANK_YOU": "谢谢",
            "CLOSING_TITLE": "谢谢",
            "ENDING_SUBTITLE": "欢迎讨论与指正",
            "CLOSING_SUBTITLE": "欢迎讨论与指正",
            "CONTACT_INFO": "ScanSci · 本地资料研究工作台",
            "CONTACT": "基于已选资料生成",
            "EMAIL": "",
            "COPYRIGHT": "ScanSci",
            "PAGE_NUM": f"{ending_index:02d}",
        }
    )
    slides.append(
        {
            "index": ending_index,
            "role": "ending",
            "shell": "ending",
            "title": "谢谢",
            "slot_payload": ending_payload,
            "source_pages": [],
        }
    )
    return {
        "schema_version": "scansci.easyslides.classic_deck.v1",
        "presentation_template_id": template_id,
        "title": title,
        "central_question": question,
        "source_inventory": [
            {
                "id": str(item.get("id", "")),
                "name": _plain(item.get("name")),
                "kind": _plain(item.get("kind")),
                "path": _plain(item.get("path")),
                "page_count": int(item.get("page_count", 0) or 0),
            }
            for item in sources
        ],
        "slides": slides,
    }


def render_classic_deck(
    *,
    workspace: str | Path,
    deck_path: str | Path,
    outline: dict[str, Any],
    sources: list[dict[str, Any]],
    template: dict[str, Any],
    root: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fill a classic EasySlides shell set and export an editable PPTX."""

    status = easyslides_plugin_status(root)
    if not status.get("ready"):
        raise RuntimeError("EasySlides 原生模板运行组件未就绪，请先在插件和技能页修复或更新插件。")

    plugin_root = Path(str(status["root"]))
    template_id = str(template.get("id", "")).strip()
    source_template_id = str(template.get("source_template_id") or template_id).strip()
    if template_id not in _FORMAL_CLASSIC_IDS:
        raise RuntimeError(f"模板 {template_id} 不是 ScanSci 正式经典模板。")
    template_dir = plugin_root / "templates" / "layouts" / source_template_id
    layouts = _read_json(template_dir / "layouts.json")
    if not _is_complete_classic_contract(layouts):
        raise RuntimeError(f"模板 {template_id} 缺少完整的经典母版、槽位或容量契约。")

    text_capacity = _load_text_capacity(plugin_root)
    plan = build_classic_deck_plan(
        outline,
        sources,
        template_id=source_template_id,
        layouts=layouts,
        text_capacity=text_capacity,
    )
    target = Path(deck_path).resolve()
    project = target.parent / "projects" / f"{target.stem}-{uuid4().hex[:8]}"
    svg_output = project / "svg_output"
    reports = project / "reports"
    notes = project / "notes"
    for directory in (project, svg_output, reports, notes):
        directory.mkdir(parents=True, exist_ok=True)

    plan_path = project / "deck_plan.json"
    _write_json(plan_path, plan)
    _write_json(notes / "source_pack.json", {"sources": plan["source_inventory"]})
    (project / "design_spec.md").write_text(
        f"# {plan['title']}\n\n- 模板：{template_id}\n- EasySlides 资源：{source_template_id}\n- 页数：{len(plan['slides'])}\n",
        encoding="utf-8",
    )
    (project / "spec_lock.md").write_text(
        "# EasySlides classic template contract\n\n"
        "Keep the source SVG masters unchanged except for declared text slots. "
        "Apply the installed slot capacity rules before native PPTX export.\n",
        encoding="utf-8",
    )

    _progress(on_progress, 0.34, "EasySlides 正在校验经典母版与文字容量")
    text_fit_check = _run(
        [sys.executable, str(plugin_root / "scripts" / "template_text_fit_check.py"), str(template_dir)],
        cwd=plugin_root,
        timeout=120,
        allow_nonzero=True,
    )
    _write_json(
        reports / "template_text_fit_preflight.json",
        {
            "status": "pass" if text_fit_check.returncode == 0 else "fail",
            "stdout": text_fit_check.stdout[-4000:],
            "stderr": text_fit_check.stderr[-4000:],
        },
    )
    if text_fit_check.returncode != 0:
        raise RuntimeError(f"EasySlides 模板容量契约未通过：{_command_detail(text_fit_check)}")

    shells = _shell_map(layouts)
    capacity_checks: list[dict[str, Any]] = []
    _progress(on_progress, 0.48, "EasySlides 正在填充正式模板母版")
    for slide in list(plan.get("slides", []) or []):
        role = str(slide.get("shell") or slide.get("role") or "content")
        shell = shells.get(role)
        if not shell:
            raise RuntimeError(f"模板 {template_id} 缺少 {role} 母版。")
        source_svg = _resolve_shell_svg(plugin_root, template_dir, shell)
        output_name = f"{int(slide['index']):02d}_{role}.svg"
        checks = _fill_svg(
            source_svg,
            svg_output / output_name,
            payload=dict(slide.get("slot_payload", {}) or {}),
            model_id=str(shell.get("page_id") or role),
            layouts=layouts,
            text_capacity=text_capacity,
        )
        for check in checks:
            check.update({"slide_index": int(slide["index"]), "slide_role": role, "file": output_name})
        capacity_checks.extend(checks)
        _write_slide_notes(notes / f"{Path(output_name).stem}.md", slide)

    placeholders = _scan_placeholders(svg_output)
    capacity_report = {
        "status": "pass" if not any(row.get("output_overflow") for row in capacity_checks) else "fail",
        "template_id": template_id,
        "slide_count": len(plan["slides"]),
        "checks": capacity_checks,
        "input_over_capacity_count": sum(bool(row.get("input_over_capacity")) for row in capacity_checks),
        "output_overflow_count": sum(bool(row.get("output_overflow")) for row in capacity_checks),
    }
    _write_json(reports / "classic_text_fit.json", capacity_report)
    _write_json(
        reports / "placeholder_scan.json",
        {"status": "pass" if not placeholders else "fail", "placeholders": placeholders},
    )
    if capacity_report["status"] != "pass" or placeholders:
        raise RuntimeError("EasySlides 经典模板填充后仍有文字溢出或未替换槽位，已阻止交付。")

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

    _progress(on_progress, 0.84, "EasySlides 正在检查 PPTX 文本与版面")
    visual_measure_path = reports / "visual_measure.json"
    _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "visual_measure_gate.py"),
            "--pptx",
            str(target),
            "--skip-template-svg",
            "--skip-template-pptx",
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
    accepted_baseline_issues = _accepted_template_baseline_issues(visual_measure)
    if str(visual_measure.get("status", "")).casefold() != "pass" and not accepted_baseline_issues:
        raise RuntimeError("EasySlides 原生 PPTX 文本与版面测量未通过，已阻止交付。")

    _progress(on_progress, 0.94, "EasySlides 正在生成逐页视觉复核包")
    visual_review_dir = reports / "visual_review"
    review_command = _run(
        [
            sys.executable,
            str(plugin_root / "scripts" / "visual_review.py"),
            str(target),
            "--out",
            str(visual_review_dir),
            "--title",
            str(plan["title"]),
            "--quiet",
        ],
        cwd=plugin_root,
        timeout=300,
        allow_nonzero=True,
    )
    visual_review = _read_json(visual_review_dir / "visual_review.json") or {
        "status": "unavailable",
        "reason": _command_detail(review_command),
        "output_dir": str(visual_review_dir),
    }
    _progress(on_progress, 0.99, "EasySlides 经典模板原生质量链路已完成")
    return {
        "project_path": str(project),
        "plan": plan,
        "plan_path": str(plan_path),
        "render_manifest": {
            "renderer": "easyslides-classic-shells",
            "template_id": template_id,
            "source_template_id": source_template_id,
            "svg_output": str(svg_output),
            "slide_count": len(plan["slides"]),
        },
        "quality_gate": {
            "status": "pass",
            "report_path": str(visual_measure_path),
            "blocking_count": 0,
            "review_count": len(accepted_baseline_issues) + (0 if str(visual_review.get("status", "")).casefold() == "pass" else 1),
            "basis": "classic_slots_capacity_and_pptx_measurement",
            "accepted_template_baseline_issues": accepted_baseline_issues,
        },
        "classic_text_fit": capacity_report,
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


def _base_payload(title: str, question: str, source_label: str) -> dict[str, Any]:
    date = datetime.now().strftime("%Y.%m")
    return {
        "LOGO": "ScanSci",
        "LOGO_IMAGE": "",
        "TITLE": title,
        "SUBTITLE": question,
        "AUTHOR": "ScanSci",
        "PRESENTER": "ScanSci",
        "ADVISOR": "—",
        "INSTITUTION": "本地资料研究汇报",
        "AFFILIATION": "本地资料研究汇报",
        "DATE": date,
        "FOOTER": source_label,
    }


def _plain(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _clip(value: str, limit: int) -> str:
    text = _plain(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _is_complete_classic_contract(layouts: dict[str, Any]) -> bool:
    if str(layouts.get("replication_mode", "")).casefold() != "classic":
        return False
    shells = _shell_map(layouts)
    models = layouts.get("slot_models")
    return set(shells) >= {"cover", "toc", "chapter", "content", "ending"} and isinstance(models, dict) and all(
        isinstance(models.get(role), list) and models.get(role) for role in ("cover", "toc", "chapter", "content", "ending")
    ) and isinstance(layouts.get("text_fit_policy"), dict)


def _shell_map(layouts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in list(layouts.get("shells", []) or []):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or raw.get("page_id") or "").casefold()
        if role:
            result[role] = dict(raw)
    return result


def _resolve_shell_svg(plugin_root: Path, template_dir: Path, shell: dict[str, Any]) -> Path:
    raw = Path(str(shell.get("svg_path") or ""))
    candidates = [template_dir / raw.name, plugin_root / raw]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"EasySlides 母版文件不存在：{raw}")


def _load_text_capacity(plugin_root: Path) -> ModuleType:
    path = plugin_root / "scripts" / "text_capacity.py"
    if not path.is_file():
        raise RuntimeError("EasySlides 缺少 text_capacity.py，无法安全填充正式模板。")
    module_name = f"scansci_easyslides_text_capacity_{abs(hash(str(path.resolve())))}"
    cached = sys.modules.get(module_name)
    if isinstance(cached, ModuleType):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 EasySlides 文字容量组件。")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _split_overloaded_slides(
    raw_slides: list[dict[str, Any]],
    layouts: dict[str, Any],
    text_capacity: ModuleType,
) -> list[dict[str, Any]]:
    models = layouts.get("slot_models", {})
    content_slots = [row for row in list(models.get("content", []) or []) if isinstance(row, dict)]
    body_slot = next((row for row in content_slots if str(row.get("slot_id")) == "CONTENT_BODY"), None)
    body_slot = body_slot or next((row for row in content_slots if str(row.get("slot_id")) == "CONTENT_AREA"), None)
    if not body_slot:
        return raw_slides
    capacity = text_capacity.resolve_slot_capacity(layouts, body_slot)
    expanded: list[dict[str, Any]] = []
    for item in raw_slides:
        bullets = [_plain(value) for value in list(item.get("bullets", []) or []) if _plain(value)]
        if not bullets:
            expanded.append(item)
            continue
        groups: list[list[str]] = []
        group: list[str] = []
        used_lines = 0
        for bullet in bullets:
            fit = text_capacity.fit_text_to_capacity(bullet, capacity)
            estimated = max(1, int(fit.raw_line_count))
            if group and used_lines + estimated > int(capacity.max_lines):
                groups.append(group)
                group = []
                used_lines = 0
            group.append(bullet)
            used_lines += estimated
        if group:
            groups.append(group)
        for group_index, values in enumerate(groups, 1):
            clone = dict(item)
            clone["bullets"] = values
            if group_index > 1:
                clone["title"] = f"{_plain(item.get('title')) or '研究要点'}（续）"
            expanded.append(clone)
    return expanded


def _fill_svg(
    source: Path,
    target: Path,
    *,
    payload: dict[str, Any],
    model_id: str,
    layouts: dict[str, Any],
    text_capacity: ModuleType,
) -> list[dict[str, Any]]:
    tree = ET.parse(source)
    root = tree.getroot()
    model_rows = [row for row in list((layouts.get("slot_models") or {}).get(model_id, []) or []) if isinstance(row, dict)]
    slots = {str(row.get("slot_id")): row for row in model_rows if row.get("slot_id")}
    checks: list[dict[str, Any]] = []
    for element in root.iter():
        if element.tag.split("}", 1)[-1] != "text":
            continue
        element_slots = _element_slots(element)
        if not element_slots:
            continue
        capacity_slot_id = _preferred_capacity_slot(element_slots, slots)
        slot = slots.get(capacity_slot_id)
        if not slot:
            continue
        element.set("data-slot", capacity_slot_id)
        _repair_declared_slot_geometry(root, element, model_id=model_id, slot_id=capacity_slot_id)
        capacity = text_capacity.resolve_slot_capacity(layouts, slot)
        role = str(slot.get("role") or "body")
        if role == "logo" and _is_hidden_logo_anchor(element):
            _clear_children(element)
            element.text = ""
            checks.append(
                {
                    "slot_id": capacity_slot_id,
                    "role": role,
                    "capacity_chars": int(capacity.capacity_chars),
                    "max_lines": int(capacity.max_lines),
                    "max_chars_per_line_zh": int(capacity.max_chars_per_line_zh),
                    "input_chars": 0,
                    "rendered_chars": 0,
                    "raw_lines": 0,
                    "rendered_lines": 0,
                    "input_over_capacity": False,
                    "output_overflow": False,
                    "action": "preserve_graphic_logo_fallback",
                }
            )
            continue
        if role == "body":
            _prepare_body_textbox(element, capacity)
            raw_value = payload.get(capacity_slot_id, [])
            lines, report = _fit_body_lines(raw_value, capacity, text_capacity)
        else:
            raw_text = _element_text(element).strip()
            rendered = raw_text
            for slot_id in element_slots:
                value = payload.get(slot_id, "")
                value_text = " · ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
                rendered = rendered.replace(f"{{{{{slot_id}}}}}", value_text)
            if not _PLACEHOLDER.search(raw_text) and element.get("data-slot"):
                value = payload.get(str(element.get("data-slot")), "")
                rendered = " · ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
            rendered = _PLACEHOLDER.sub("", rendered).strip()
            fit = text_capacity.fit_text_to_capacity(rendered, capacity)
            lines = list(fit.lines)
            report = {
                "input_chars": int(fit.input_chars),
                "rendered_chars": int(fit.rendered_chars),
                "raw_lines": int(fit.raw_line_count),
                "rendered_lines": len(fit.lines),
                "input_over_capacity": bool(fit.input_over_capacity),
                "output_overflow": bool(fit.output_overflow),
                "action": str(fit.action),
            }
        if _single_line_master_slot(model_id, capacity_slot_id) and lines:
            lines = [" ".join(line.strip() for line in lines if line.strip())]
            report["rendered_lines"] = 1
            report["action"] = "fit_single_line_master_slot"
        if role != "body" and (len(lines) > 1 or bool(report.get("input_over_capacity")) or len(element_slots) > 1):
            element.set("font-size", str(float(capacity.min_font_size_px)).rstrip("0").rstrip("."))
        _set_text_lines(element, lines)
        checks.append(
            {
                "slot_id": capacity_slot_id,
                "role": role,
                "capacity_chars": int(capacity.capacity_chars),
                "max_lines": int(capacity.max_lines),
                "max_chars_per_line_zh": int(capacity.max_chars_per_line_zh),
                **report,
            }
        )
    if model_id == "content":
        _remove_unbound_content_guides(root)
        _normalize_dynamic_navigation(root)
    _replace_remaining_placeholders(root, payload)
    _normalize_icon_placeholders(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return checks


def _fit_body_lines(raw_value: Any, capacity: Any, text_capacity: ModuleType) -> tuple[list[str], dict[str, Any]]:
    values = [str(item).strip() for item in raw_value if str(item).strip()] if isinstance(raw_value, list) else [str(raw_value or "").strip()]
    values = [value for value in values if value]
    rendered: list[str] = []
    raw_line_count = 0
    input_chars = sum(len(value) for value in values)
    input_over_capacity = False
    for value in values:
        fit = text_capacity.fit_text_to_capacity(value, capacity)
        raw_line_count += int(fit.raw_line_count)
        input_over_capacity = input_over_capacity or bool(fit.input_over_capacity)
        for index, line in enumerate(fit.lines):
            prefix = "• " if index == 0 else "  "
            rendered.append(f"{prefix}{line}")
    if len(rendered) > int(capacity.max_lines):
        input_over_capacity = True
        rendered = rendered[: int(capacity.max_lines)]
    output_overflow = len(rendered) > int(capacity.max_lines) or any(
        len(line.removeprefix("• ").removeprefix("  ")) > int(capacity.max_chars_per_line_zh) for line in rendered
    )
    return rendered, {
        "input_chars": input_chars,
        "rendered_chars": sum(len(line) for line in rendered),
        "raw_lines": raw_line_count,
        "rendered_lines": len(rendered),
        "input_over_capacity": input_over_capacity,
        "output_overflow": output_overflow,
        "action": "split_or_compressed_before_render" if input_over_capacity else "within_capacity",
    }


def _element_slots(element: ET.Element) -> list[str]:
    slots: list[str] = []
    declared = str(element.get("data-slot") or "").strip()
    if declared:
        slots.append(declared)
    for match in _PLACEHOLDER.findall(_element_text(element)):
        if match not in slots:
            slots.append(match)
    token = str(element.get("data-slot-token") or "")
    match = _PLACEHOLDER.fullmatch(token)
    if match and match.group(1) not in slots:
        slots.append(match.group(1))
    return slots


def _preferred_capacity_slot(element_slots: list[str], slots: dict[str, dict[str, Any]]) -> str:
    for preferred in ("CONTENT_BODY", "CONTENT_AREA", "PAGE_TITLE", "TITLE", "KEY_MESSAGE"):
        if preferred in element_slots and preferred in slots:
            return preferred
    return next((slot_id for slot_id in element_slots if slot_id in slots), element_slots[0])


def _element_text(element: ET.Element) -> str:
    return "".join(element.itertext())


def _local_name(element: ET.Element) -> str:
    return element.tag.split("}", 1)[-1]


def _remove_unbound_content_guides(root: ET.Element) -> None:
    """Drop template authoring hints, while preserving all declared chrome."""

    for parent in root.iter():
        for child in list(parent):
            if _local_name(child) != "text" or _element_slots(child):
                continue
            if child.get("fill") in {"#CBD5E1", "#94A3B8"}:
                parent.remove(child)


def _repair_declared_slot_geometry(
    root: ET.Element,
    element: ET.Element,
    *,
    model_id: str,
    slot_id: str,
) -> None:
    """Repair obvious textbox-width typos without altering visible master chrome."""

    if model_id != "content" or slot_id != "PAGE_TITLE":
        return
    try:
        canvas_width = float(root.get("width") or root.get("viewBox", "0 0 1280 720").split()[2])
        box_x = float(element.get("data-pptx-box-x") or element.get("x") or 0)
        box_width = float(element.get("data-pptx-box-w") or 0)
    except (ValueError, IndexError):
        return
    # A page-title box narrower than one third of the canvas is an authoring
    # metadata typo in the classic masters (for example 110 instead of 1100).
    if box_width and box_width < canvas_width / 3:
        repaired_width = max(box_width, canvas_width - box_x - 40)
        element.set("data-pptx-box-w", str(round(repaired_width, 2)).rstrip("0").rstrip("."))


def _single_line_master_slot(model_id: str, slot_id: str) -> bool:
    return (model_id, slot_id) in {("chapter", "TITLE"), ("content", "PAGE_TITLE")}


def _prepare_body_textbox(element: ET.Element, capacity: Any) -> None:
    """Turn a classic authoring guide slot into readable production body copy."""

    element.set("fill", "#1F2937")
    element.attrib.pop("fill-opacity", None)
    element.set("font-size", str(float(capacity.font_size_px)).rstrip("0").rstrip("."))
    element.set("data-pptx-valign", "top")
    box_x = element.get("data-pptx-box-x")
    box_w = element.get("data-pptx-box-w")
    if box_x is None or box_w is None:
        return
    try:
        x = float(box_x)
        width = float(box_w)
    except ValueError:
        return
    padding = min(34.0, max(width / 12, 0.0))
    text_x = x + padding
    text_width = max(width - padding * 2, 1.0)
    value_x = str(round(text_x, 2)).rstrip("0").rstrip(".")
    value_width = str(round(text_width, 2)).rstrip("0").rstrip(".")
    element.set("x", value_x)
    element.set("text-anchor", "start")
    element.set("data-pptx-box-x", value_x)
    element.set("data-pptx-box-w", value_width)


def _is_hidden_logo_anchor(element: ET.Element) -> bool:
    try:
        font_size = float(element.get("font-size") or 0)
        fill_opacity = float(element.get("fill-opacity") or 1)
    except ValueError:
        return False
    return font_size < 8 or fill_opacity <= 0.01


def _replace_remaining_placeholders(root: ET.Element, payload: dict[str, Any]) -> None:
    def replace(value: str | None) -> str | None:
        if value is None or "{{" not in value:
            return value

        def resolve(match: re.Match[str]) -> str:
            raw = payload.get(match.group(1), "")
            if isinstance(raw, list):
                return " · ".join(str(item) for item in raw)
            return str(raw or "")

        return _PLACEHOLDER.sub(resolve, value)

    for element in root.iter():
        element.text = replace(element.text)
        element.tail = replace(element.tail)
        for key, value in list(element.attrib.items()):
            element.set(key, replace(value) or "")


def _normalize_icon_placeholders(root: ET.Element) -> None:
    """Map unavailable master icon aliases to editable installed icons.

    The classic ``defense_leftnav`` ending master historically referenced
    ``tabler-filled/mail``, while the bundled EasySlides icon set provides
    the equivalent editable icon as ``chunk-filled/mailbox``.  Normalizing the output
    SVG keeps the official master untouched and lets the native converter
    expand the placeholder into DrawingML primitives.
    """

    aliases = {"tabler-filled/mail": "chunk-filled/mailbox"}
    for element in root.iter():
        if _local_name(element) != "use":
            continue
        icon_id = str(element.get("data-icon") or "")
        replacement = aliases.get(icon_id)
        if replacement:
            element.set("data-icon", replacement)


def _normalize_dynamic_navigation(root: ET.Element) -> None:
    """Hide the inactive navigation row covered by the active state.

    ``defense_leftnav`` keeps one complete inactive menu plus a movable active
    band in the master.  When the band is rendered, the inactive label at the
    same index must be removed; otherwise both editable text boxes occupy the
    same coordinates in PowerPoint.
    """

    active_indexes = {
        str(element.get("data-active-index") or "").strip()
        for element in root.iter()
        if element.get("data-active-index")
    }
    active_indexes.discard("")
    if not active_indexes:
        return
    for parent in root.iter():
        for child in list(parent):
            child_id = str(child.get("id") or "")
            nav_index = str(child.get("data-nav-index") or "").strip()
            if child_id.startswith("nav-inactive-item-") and nav_index in active_indexes:
                parent.remove(child)


def _accepted_template_baseline_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept only unchanged numeric control alignment advisories from masters."""

    issues = [item for item in list(report.get("issues", []) or []) if isinstance(item, dict)]
    blocking = [item for item in issues if str(item.get("severity", "")).casefold() == "blocking"]
    accepted: list[dict[str, Any]] = []
    for item in blocking:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        preview = str(details.get("text_preview") or "").strip()
        if str(item.get("code")) == "CONTROL-TEXT-VERTICAL-MISALIGN" and preview.isdigit():
            accepted.append(item)
            continue
        return []
    return accepted if accepted and len(accepted) == len(blocking) else []


def _clear_children(element: ET.Element) -> None:
    element.text = None
    for child in list(element):
        element.remove(child)


def _set_text_lines(element: ET.Element, lines: list[str]) -> None:
    _clear_children(element)
    if not lines:
        element.text = ""
        return
    x = element.get("x") or element.get("data-pptx-box-x") or "0"
    try:
        font_size = float(element.get("font-size") or "18")
    except ValueError:
        font_size = 18.0
    line_step = round(font_size * 1.25, 2)
    box_y = element.get("data-pptx-box-y")
    box_h = element.get("data-pptx-box-h")
    if box_y is not None and box_h is not None:
        try:
            top = float(box_y)
            height = float(box_h)
            total_height = font_size + line_step * (len(lines) - 1)
            valign = element.get("data-pptx-valign")
            if valign == "middle":
                baseline = top + max(font_size, (height - total_height) / 2 + font_size * 0.85)
            elif valign == "bottom":
                baseline = top + max(font_size, height - total_height + font_size * 0.85)
            else:
                baseline = top + font_size * 0.85
            element.set("y", str(round(baseline, 2)).rstrip("0").rstrip("."))
            element.attrib.pop("dominant-baseline", None)
        except ValueError:
            pass
    for index, line in enumerate(lines):
        tspan = ET.SubElement(element, f"{{{_SVG_NS}}}tspan")
        tspan.text = line
        tspan.set("x", x)
        if index > 0:
            tspan.set("dy", str(line_step).rstrip("0").rstrip("."))


def _scan_placeholders(svg_output: Path) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path in sorted(svg_output.glob("*.svg")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for placeholder in sorted(set(_PLACEHOLDER.findall(text))):
            found.append({"file": path.name, "placeholder": placeholder})
    return found


def _write_slide_notes(path: Path, slide: dict[str, Any]) -> None:
    payload = dict(slide.get("slot_payload", {}) or {})
    body = payload.get("CONTENT_BODY") or payload.get("CONTENT_AREA") or []
    rows = list(body) if isinstance(body, list) else [body]
    lines = [f"# {slide.get('title') or slide.get('role')}", ""]
    lines.extend(f"- {value}" for value in rows if _plain(value))
    source_pages = list(slide.get("source_pages", []) or [])
    if source_pages:
        lines.extend(["", f"来源页：{', '.join(str(value) for value in source_pages)}"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def formal_classic_template_ids() -> tuple[str, ...]:
    return tuple(sorted(_FORMAL_CLASSIC_IDS))
