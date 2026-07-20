"""Discover and safely expose the active local EasySlides template library."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote


_SAFE_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
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
}


def easyslides_root(root: str | Path | None = None) -> Path:
    """Return the configured EasySlides repository root."""

    if root is not None:
        return Path(root).expanduser().resolve()
    configured = os.getenv("EASYSLIDES_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    suite_root = Path(os.getenv("SCANSCI_SUITE_ROOT", r"D:\scansci"))
    return (suite_root / "easyslides").resolve()


def list_slide_templates(root: str | Path | None = None) -> dict[str, Any]:
    """Return active EasySlides academic templates and SVG preview pages."""

    repository = easyslides_root(root)
    layouts_root = repository / "templates" / "layouts"
    index_path = layouts_root / "layouts_index.json"
    if not index_path.is_file():
        return {
            "available": False,
            "provider": "EasySlides",
            "templates": [],
            "message": "未找到 EasySlides 模板库",
        }
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("EasySlides 模板索引不是有效 JSON") from error
    if not isinstance(index, dict):
        raise ValueError("EasySlides 模板索引必须是对象")

    templates = []
    for template_id, index_record in index.items():
        if not _SAFE_TEMPLATE_ID.fullmatch(str(template_id)):
            continue
        template_dir = layouts_root / str(template_id)
        if not template_dir.is_dir():
            continue
        record = _template_record(str(template_id), template_dir, dict(index_record or {}))
        if record["pages"]:
            templates.append(record)
    return {
        "available": bool(templates),
        "provider": "EasySlides",
        "templates": templates,
        "count": len(templates),
    }


def get_slide_template(template_id: str, root: str | Path | None = None) -> dict[str, Any]:
    normalized = str(template_id or "").strip()
    catalog = list_slide_templates(root)
    template = next((item for item in catalog["templates"] if item["id"] == normalized), None)
    if template is None:
        raise FileNotFoundError(f"EasySlides 模板不存在或未启用：{normalized}")
    return dict(template)


def resolve_slide_template_dir(template_id: str, root: str | Path | None = None) -> Path:
    template = get_slide_template(template_id, root)
    directory = easyslides_root(root) / "templates" / "layouts" / str(template["id"])
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


def _template_record(template_id: str, template_dir: Path, index_record: dict[str, Any]) -> dict[str, Any]:
    metadata = _read_front_matter(template_dir / "design_spec.md")
    localized = _TEMPLATE_LOCALIZATION.get(template_id, {})
    pages = []
    for index, path in enumerate(sorted(template_dir.glob("*.svg")), start=1):
        role = _page_role(path.stem)
        pages.append(
            {
                "index": index,
                "file": path.name,
                "role": role,
                "label": _PAGE_LABELS.get(role, f"页面 {index}"),
                "preview_url": _preview_url(template_id, path.name),
            }
        )
    summary = str(metadata.get("summary") or index_record.get("summary") or "").strip()
    use_cases = str(metadata.get("use_cases") or "").strip()
    return {
        "id": template_id,
        "name": str(metadata.get("display_name_zh") or template_id.replace("_", " ").title()),
        "category": str(metadata.get("category") or "academic"),
        "summary": summary,
        "description": str(localized.get("description") or summary),
        "use_cases": use_cases,
        "tone": str(localized.get("tone") or metadata.get("design_tone") or "").strip(),
        "primary_color": str(metadata.get("primary_color") or "#334155"),
        "format": str(metadata.get("canvas_format") or "ppt169"),
        "replication_mode": str(metadata.get("replication_mode") or "classic"),
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


def _page_role(stem: str) -> str:
    lowered = stem.casefold()
    for role in ("cover", "toc", "chapter", "content", "ending"):
        if role in lowered:
            return role
    return "page"


def _preview_url(template_id: str, page_name: str) -> str:
    return f"/api/slides/templates/{quote(template_id, safe='')}/pages/{quote(page_name, safe='')}"
