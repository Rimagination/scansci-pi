"""Discover and safely expose the active local EasySlides template library."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from .easyslides_plugin import easyslides_plugin_status, find_easyslides_root


_SAFE_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_FORMAL_TEMPLATE_SOURCES = (
    ("academic_general", "academic_general"),
    ("academic_scqa", "academic_scqa"),
    ("defense_leftnav", "defense_leftnav"),
    ("defense_topnav", "defense_topnav"),
    ("literature_minimal", "literature_minimal"),
    ("nsfc_defense", "nsfc_purple_semantic"),
)
_LEGACY_TEMPLATE_IDS = {
    "nsfc_purple_semantic": "nsfc_defense",
    "nsfc_semantic": "nsfc_defense",
    "nsfc_purple": "nsfc_defense",
}
_TEMPLATE_NAMES = {
    "nsfc_defense": "NSFC 答辩",
}
_PAGE_LABELS = {
    "cover": "封面",
    "toc": "目录",
    "chapter": "章节",
    "content": "正文",
    "ending": "结束页",
}
_TEMPLATE_LOCALIZATION = {
    "academic_general": {
        "description": "通用科研汇报，适合研究报告、课程汇报与进展复盘。",
        "tone": "专业、严谨、层级清晰",
    },
    "academic_scqa": {
        "description": "蓝青学术论证版式，适合技术报告、项目评审与结构化表达。",
        "tone": "正式、数据导向、强调论证",
    },
    "defense_leftnav": {
        "description": "酒红左栏导航，适合论文答辩、开题与阶段汇报。",
        "tone": "紧凑、正式、章节感明确",
    },
    "defense_topnav": {
        "description": "蓝白顶栏导航，适合正式答辩、开题与研究进展汇报。",
        "tone": "沉稳、清晰、结构化",
    },
    "literature_minimal": {
        "description": "克制的蓝白版式，适合文献阅读、综述与论文解读。",
        "tone": "极简、留白充足、学术感",
    },
    "nsfc_defense": {
        "description": "紫色科研项目答辩版式，适合基金汇报、项目评审与正式答辩。",
        "tone": "专业、克制、结构明确",
    },
}


def easyslides_root(root: str | Path | None = None) -> Path:
    """Return the configured EasySlides repository root."""

    return find_easyslides_root(root)


def list_slide_templates(root: str | Path | None = None) -> dict[str, Any]:
    """Return active EasySlides academic templates and SVG preview pages."""

    repository = easyslides_root(root)
    plugin = easyslides_plugin_status(repository)
    public_plugin = {key: value for key, value in plugin.items() if key != "root"}
    layouts_root = repository / "templates" / "layouts"
    index_path = layouts_root / "layouts_index.json"
    if not index_path.is_file():
        return {
            "available": False,
            "provider": "EasySlides",
            "templates": [],
            "message": "未找到 EasySlides 模板库",
            "plugin": public_plugin,
        }
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("EasySlides 模板索引不是有效 JSON") from error
    if not isinstance(index, dict):
        raise ValueError("EasySlides 模板索引必须是对象")

    templates = []
    for template_id, source_template_id in _FORMAL_TEMPLATE_SOURCES:
        if not _SAFE_TEMPLATE_ID.fullmatch(template_id) or not _SAFE_TEMPLATE_ID.fullmatch(source_template_id):
            continue
        index_record = index.get(source_template_id)
        if not isinstance(index_record, dict):
            continue
        template_dir = layouts_root / source_template_id
        if not template_dir.is_dir():
            continue
        record = _template_record(template_id, source_template_id, template_dir, dict(index_record))
        if record["pages"]:
            templates.append(record)
    return {
        "available": bool(templates),
        "provider": "EasySlides",
        "templates": templates,
        "count": len(templates),
        "plugin": public_plugin,
    }


def get_slide_template(template_id: str, root: str | Path | None = None) -> dict[str, Any]:
    normalized = str(template_id or "").strip()
    normalized = _LEGACY_TEMPLATE_IDS.get(normalized, normalized)
    catalog = list_slide_templates(root)
    template = next((item for item in catalog["templates"] if item["id"] == normalized), None)
    if template is None:
        raise FileNotFoundError(f"EasySlides 模板不存在或未启用：{normalized}")
    return dict(template)


def resolve_slide_template_dir(template_id: str, root: str | Path | None = None) -> Path:
    template = get_slide_template(template_id, root)
    directory = easyslides_root(root) / "templates" / "layouts" / str(template["source_template_id"])
    if not directory.is_dir():
        raise FileNotFoundError(f"EasySlides 模板目录不存在：{template_id}")
    return directory.resolve()


def slide_template_asset(
    template_id: str,
    page_name: str,
    root: str | Path | None = None,
) -> Path:
    template = get_slide_template(template_id, root)
    allowed = {str(page["file"]) for page in template["pages"]}
    normalized_page = str(page_name or "").strip()
    if normalized_page not in allowed:
        raise FileNotFoundError(f"模板预览页不存在：{normalized_page}")
    directory = resolve_slide_template_dir(template_id, root)
    asset = (directory / normalized_page).resolve()
    try:
        asset.relative_to(directory)
    except ValueError as error:
        raise ValueError("模板预览路径越出了模板目录") from error
    if not asset.is_file():
        raise FileNotFoundError(f"模板预览页不存在：{normalized_page}")
    return asset


def _template_record(
    template_id: str,
    source_template_id: str,
    template_dir: Path,
    index_record: dict[str, Any],
) -> dict[str, Any]:
    metadata = _read_front_matter(template_dir / "design_spec.md")
    localized = _TEMPLATE_LOCALIZATION.get(template_id, {})
    status = _read_json(template_dir / "template_status.json")
    template_pack = _read_json(template_dir / "template.json")
    layout_pack = _read_json(template_dir / "layouts.json")
    layout_by_file = {
        str(row.get("svg", "")): dict(row)
        for row in list(layout_pack.get("layouts", []) or [])
        if isinstance(row, dict) and row.get("svg")
    }
    pages = []
    for index, path in enumerate(sorted(template_dir.glob("*.svg")), start=1):
        layout = layout_by_file.get(path.name, {})
        role = str(layout.get("role") or _page_role(path.stem))
        layout_id = str(layout.get("layout_id") or path.stem)
        pages.append(
            {
                "index": index,
                "file": path.name,
                "role": role,
                "layout_id": layout_id,
                "label": _layout_label(layout_id, role, index),
                "preview_url": _preview_url(template_id, path.name),
            }
        )
    summary = str(metadata.get("summary") or index_record.get("summary") or "").strip()
    use_cases = str(metadata.get("use_cases") or "").strip()
    semantic_eligible = bool(status.get("production_eligible")) and str(status.get("status", "")) == "production"
    classic_eligible = _classic_template_eligible(layout_pack)
    route = str(template_pack.get("recommended_template_route") or "compatibility")
    output_contract = str(template_pack.get("output_contract") or "editable-pptx")
    if semantic_eligible and route == "semantic_named_slots":
        generation_mode = "easyslides-semantic"
    elif classic_eligible:
        generation_mode = "easyslides-classic"
    else:
        generation_mode = "compatibility"
    production_eligible = bool(semantic_eligible or classic_eligible)
    return {
        "id": template_id,
        "source_template_id": source_template_id,
        "resource_path": f"templates/layouts/{source_template_id}",
        "name": str(_TEMPLATE_NAMES.get(template_id) or metadata.get("display_name_zh") or template_pack.get("display_name") or template_id.replace("_", " ").title()),
        "category": str(metadata.get("category") or "academic"),
        "summary": summary,
        "description": str(localized.get("description") or summary),
        "use_cases": use_cases,
        "tone": str(localized.get("tone") or metadata.get("design_tone") or "").strip(),
        "primary_color": str(metadata.get("primary_color") or "#334155"),
        "format": str(metadata.get("canvas_format") or "ppt169"),
        "replication_mode": str(metadata.get("replication_mode") or "classic"),
        "status": str(status.get("status") or "compatibility"),
        "production_eligible": production_eligible,
        "generation_mode": generation_mode,
        "renderer_label": "EasySlides 原生" if production_eligible else "兼容模板",
        "quality_label": (
            "已通过生产门禁"
            if generation_mode == "easyslides-semantic"
            else "母版槽位与容量检查"
            if generation_mode == "easyslides-classic"
            else "兼容模式"
        ),
        "template_route": route,
        "output_contract": output_contract,
        "keywords": list(index_record.get("keywords", []) or []),
        "pages": pages,
        "preview_url": pages[0]["preview_url"] if pages else "",
    }


def _read_front_matter(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t", "-")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            values[key.strip()] = cleaned
    return values


def _classic_template_eligible(layout_pack: dict[str, Any]) -> bool:
    if str(layout_pack.get("replication_mode", "")).casefold() != "classic":
        return False
    shells = {
        str(item.get("role") or item.get("page_id") or "").casefold()
        for item in list(layout_pack.get("shells", []) or [])
        if isinstance(item, dict)
    }
    models = layout_pack.get("slot_models")
    policy = layout_pack.get("text_fit_policy")
    required = {"cover", "toc", "chapter", "content", "ending"}
    return required <= shells and isinstance(models, dict) and all(
        isinstance(models.get(role), list) and bool(models.get(role)) for role in required
    ) and isinstance(policy, dict)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _layout_label(layout_id: str, role: str, index: int) -> str:
    labels = {
        "text_focus": "重点正文",
        "figure_left": "左图右文",
        "figure_right": "左文右图",
        "two_column": "双栏",
        "comparison_focus": "对比",
        "three_cards": "三卡片",
        "process": "流程",
        "result": "结果",
    }
    return labels.get(layout_id, _PAGE_LABELS.get(role, f"页面 {index}"))


def _page_role(stem: str) -> str:
    lowered = stem.casefold()
    for role in ("cover", "toc", "chapter", "content", "ending"):
        if role in lowered:
            return role
    return "page"


def _preview_url(template_id: str, page_name: str) -> str:
    return f"/api/slides/templates/{quote(template_id, safe='')}/pages/{quote(page_name, safe='')}"
