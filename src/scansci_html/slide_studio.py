"""Source-first PDF and document to editable PPTX production for ScanSci."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4
import zipfile

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from .builtin_skills import SCIENTIFIC_SLIDES_CONTRACT
from .slide_plan import build_slide_plan, safe_presentation_name, write_slide_plan
from .slides_templates import get_slide_template


class _ChatJsonClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        ...


_SUPPORTED_SUFFIXES = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".txt": "文本",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".html": "HTML",
    ".htm": "HTML",
}
_MAX_SOURCE_FILES = 3
_MAX_SOURCE_BYTES = 30 * 1024 * 1024
_MAX_EXTRACTED_CHARS = 90_000
_MAX_MODEL_CONTEXT_CHARS = 24_000
_MAX_PDF_PAGES = 80
_SAFE_NAME = re.compile(r"[^\w.-]+", flags=re.UNICODE)


def supported_slide_source_suffixes() -> tuple[str, ...]:
    return tuple(_SUPPORTED_SUFFIXES)


def persist_slide_sources(workspace: str | Path, values: object) -> list[dict[str, Any]]:
    """Copy user-selected presentation sources into a private durable area.

    Browser uploads may provide a data URL; desktop selections provide a path.
    The persisted record never exposes the original path back to the web UI.
    """

    sources = list(values or []) if isinstance(values, list) else []
    if not sources:
        raise ValueError("请先添加至少一个 PDF、Word、Markdown、TXT 或 HTML 文件")
    if len(sources) > _MAX_SOURCE_FILES:
        raise ValueError(f"一次最多可制作 {_MAX_SOURCE_FILES} 份材料的合并幻灯片")

    root = Path(workspace).resolve().parent / ".scansci-slide-sources"
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    total_bytes = 0
    for raw in sources:
        if not isinstance(raw, dict):
            raise ValueError("幻灯片来源格式无效")
        name = _safe_source_name(str(raw.get("name", "")))
        source_path = str(raw.get("path", "")).strip()
        data_url = str(raw.get("data_url", "")).strip()
        if source_path:
            candidate = Path(source_path).expanduser()
            try:
                candidate = candidate.resolve(strict=True)
            except OSError as error:
                raise ValueError("选择的演示材料已不存在") from error
            if not candidate.is_file():
                raise ValueError("选择的演示材料不是文件")
            suffix = candidate.suffix.casefold()
            name = name or _safe_source_name(candidate.name)
            payload_size = candidate.stat().st_size
            target = root / f"source-{uuid4().hex}{suffix}"
            _validate_source(name, suffix, payload_size, total_bytes)
            shutil.copy2(candidate, target)
        elif data_url:
            suffix = Path(name).suffix.casefold()
            if not suffix:
                raise ValueError("上传文件缺少可识别的扩展名")
            payload = _decode_data_url(data_url)
            payload_size = len(payload)
            _validate_source(name, suffix, payload_size, total_bytes)
            target = root / f"source-{uuid4().hex}{suffix}"
            target.write_bytes(payload)
        else:
            raise ValueError("请从本机选择演示材料")

        total_bytes += payload_size
        records.append(
            {
                "id": target.stem,
                "name": name,
                "path": str(target),
                "kind": _SUPPORTED_SUFFIXES[suffix],
                "size": payload_size,
            }
        )
    return records


def create_source_slide_deck(
    *,
    workspace: str | Path,
    sources: list[dict[str, Any]],
    topic: str = "",
    template_id: str = "",
    chat_client: _ChatJsonClient | None = None,
) -> dict[str, Any]:
    """Extract supplied material, plan a template-led deck, and export PPTX."""

    extracted = [_extract_source(source) for source in sources]
    template = get_slide_template(template_id) if str(template_id).strip() else None
    theme = _template_theme(template)
    outline, planning = _plan_deck(extracted, topic=topic, chat_client=chat_client, template=template)
    deck_path = _presentation_path(workspace, str(outline["title"]))
    slide_plan = build_slide_plan(outline, extracted)
    if template:
        slide_plan["template"] = template
        slide_plan.setdefault("theme", {})["accent"] = str(template.get("primary_color") or "#14897D")
    slide_plan_path = deck_path.with_name(f"{deck_path.stem}.slide-plan.json")
    write_slide_plan(slide_plan_path, slide_plan)
    _render_pptx(deck_path, outline, extracted, theme=theme)
    return {
        "ok": True,
        "message": "已从上传材料生成可编辑 PPTX",
        "file_path": str(deck_path),
        "pptx_path": str(deck_path),
        "download_name": deck_path.name,
        "outline": outline,
        "slide_plan": slide_plan,
        "slide_plan_path": str(slide_plan_path),
        "renderer": "python-pptx",
        "enhanced_renderer": "pptxgenjs-browser",
        "source_count": len(extracted),
        "sources": [
            {
                "name": item["name"],
                "kind": item["kind"],
                "page_count": item["page_count"],
                "warnings": item["warnings"],
            }
            for item in extracted
        ],
        "template": template,
        "template_id": str(template.get("id", "")) if template else "",
        "planning": planning,
    }


def save_browser_rendered_deck(
    workspace: str | Path,
    *,
    file_name: str,
    base64_data: str,
) -> dict[str, Any]:
    """Validate and save a browser-rendered PptxGenJS presentation."""

    encoded = str(base64_data or "").strip()
    if encoded.startswith("data:"):
        encoded = encoded.partition(",")[2]
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("PptxGenJS 导出数据无效") from error
    if not payload or len(payload) > 80 * 1024 * 1024:
        raise ValueError("PptxGenJS 导出文件为空或过大")

    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                raise ValueError("导出内容不是有效的 PPTX")
    except zipfile.BadZipFile as error:
        raise ValueError("导出内容不是有效的 PPTX") from error

    root = Path(workspace).resolve().parent / "presentations"
    root.mkdir(parents=True, exist_ok=True)
    requested = Path(str(file_name or "")).stem
    stem = safe_presentation_name(requested, fallback="scansci_slides_enhanced")
    target = root / f"{stem}.pptx"
    counter = 2
    while target.exists():
        target = root / f"{stem}-{counter}.pptx"
        counter += 1
    target.write_bytes(payload)
    return {
        "ok": True,
        "file_path": str(target),
        "download_name": target.name,
        "download_url": f"/api/presentations/{target.name}",
        "renderer": "pptxgenjs-browser",
        "bytes": len(payload),
    }


def _validate_source(name: str, suffix: str, size: int, total_bytes: int) -> None:
    if suffix not in _SUPPORTED_SUFFIXES:
        types = "、".join(item.removeprefix(".").upper() for item in _SUPPORTED_SUFFIXES)
        raise ValueError(f"暂只支持 {types} 作为幻灯片来源")
    if not name:
        raise ValueError("上传文件缺少名称")
    if size <= 0:
        raise ValueError("上传文件为空")
    if size > _MAX_SOURCE_BYTES or total_bytes + size > _MAX_SOURCE_BYTES:
        raise ValueError("制作幻灯片的源文件总大小不能超过 30 MB")


def _decode_data_url(value: str) -> bytes:
    header, separator, encoded = value.partition(",")
    if not separator or ";base64" not in header.casefold():
        raise ValueError("上传数据格式无效")
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("上传文件无法解码") from error


def _safe_source_name(value: str) -> str:
    name = Path(value).name.strip()
    return name[:180]


def _extract_source(record: dict[str, Any]) -> dict[str, Any]:
    source_path = Path(str(record["path"])).resolve()
    suffix = source_path.suffix.casefold()
    if suffix not in _SUPPORTED_SUFFIXES or not source_path.is_file():
        raise ValueError("幻灯片来源已失效，请重新添加")
    warnings: list[str] = []
    page_count = 1
    if suffix == ".pdf":
        reader = PdfReader(str(source_path))
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception as error:  # noqa: BLE001 - third-party parser boundary
                raise ValueError("受密码保护的 PDF 暂不能直接制作幻灯片") from error
            if not decrypted:
                raise ValueError("受密码保护的 PDF 暂不能直接制作幻灯片")
        page_count = len(reader.pages)
        pieces: list[str] = []
        for index, page in enumerate(reader.pages[:_MAX_PDF_PAGES]):
            text = (page.extract_text() or "").strip()
            if text:
                pieces.append(f"[第 {index + 1} 页]\n{text}")
            if sum(len(item) for item in pieces) >= _MAX_EXTRACTED_CHARS:
                warnings.append("材料较长，已截取前部文本用于生成第一版幻灯片")
                break
        if page_count > _MAX_PDF_PAGES:
            warnings.append(f"PDF 共 {page_count} 页，已先解析前 {_MAX_PDF_PAGES} 页")
        text = "\n\n".join(pieces)
    elif suffix == ".docx":
        document = Document(str(source_path))
        text = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
    elif suffix in {".html", ".htm"}:
        text = BeautifulSoup(source_path.read_text(encoding="utf-8", errors="replace"), "html.parser").get_text("\n", strip=True)
    else:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    text = _compact_text(text, limit=_MAX_EXTRACTED_CHARS)
    if not text:
        raise ValueError(f"未能从「{record.get('name', source_path.name)}」提取可用文本；扫描件请先在文档处理设置中启用 OCR 后重试")
    return {
        "id": str(record.get("id", source_path.stem)),
        "name": str(record.get("name", source_path.name)),
        "kind": _SUPPORTED_SUFFIXES[suffix],
        "page_count": page_count,
        "text": text,
        "warnings": warnings,
    }


def _plan_deck(
    sources: list[dict[str, Any]],
    *,
    topic: str,
    chat_client: _ChatJsonClient | None,
    template: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    fallback = _fallback_outline(sources, topic)
    if chat_client is None:
        return fallback, {"mode": "source-grounded", "reason": "未配置演示模型，已使用材料原文生成结构化初稿"}
    template_brief = ""
    if template:
        template_brief = (
            f"\nSelected presentation template: {template.get('name', template.get('id', ''))}. "
            f"Visual tone: {template.get('tone', '')}. "
            "Plan audience-facing presentation pages (context, question, approach, findings, implication, close). "
            "Do not make evidence chains, source verification, or generation process the visible story; put source notes in footers only.\n"
        )
    source_brief = "\n\n".join(
        f"来源：{item['name']}（{item['kind']}，{item['page_count']} 页）\n{item['text'][:_MAX_MODEL_CONTEXT_CHARS // max(1, len(sources))]}"
        for item in sources
    )
    source_brief = template_brief + source_brief
    prompt = f"""演示主题（可为空）：{topic.strip() or '请根据材料命名'}

以下是用户提供的材料。材料可能不完整或含有局限；不得补充材料外的事实。

{source_brief}
"""
    try:
        candidate = chat_client.complete_json(
            [{"role": "system", "content": SCIENTIFIC_SLIDES_CONTRACT}, {"role": "user", "content": prompt}],
            schema_name="scansci_scientific_slides",
        )
        outline = _normalise_model_outline(candidate, fallback=fallback, sources=sources)
        return outline, {"mode": "skill-aware-model", "reason": "已应用好问题、好故事与科研幻灯片内置技能"}
    except Exception as error:  # noqa: BLE001 - deck creation remains available offline
        return fallback, {"mode": "source-grounded", "reason": f"演示规划模型暂不可用，已改用材料原文生成初稿：{str(error)[:180]}"}


def _normalise_model_outline(candidate: Any, *, fallback: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("演示模型没有返回结构化大纲")
    raw_slides = candidate.get("slides")
    if not isinstance(raw_slides, list) or len(raw_slides) < 3:
        raise ValueError("演示模型返回的大纲页数不足")
    max_pages = max(item["page_count"] for item in sources)
    slides: list[dict[str, Any]] = []
    for raw in raw_slides[:8]:
        if not isinstance(raw, dict):
            continue
        title = _short_text(raw.get("title"), 72)
        takeaway = _short_text(raw.get("takeaway"), 120)
        bullets = [_short_text(item, 150) for item in list(raw.get("bullets", []) or []) if _short_text(item, 150)][:5]
        pages = [int(item) for item in list(raw.get("source_pages", []) or []) if str(item).isdigit() and 1 <= int(item) <= max_pages][:6]
        if title and (takeaway or bullets):
            slides.append({"title": title, "takeaway": takeaway, "bullets": bullets, "source_pages": pages})
    if len(slides) < 3:
        raise ValueError("演示模型返回的页面内容不完整")
    return {
        "title": _short_text(candidate.get("title"), 96) or str(fallback["title"]),
        "central_question": _short_text(candidate.get("central_question"), 300) or str(fallback["central_question"]),
        "story": _short_text(candidate.get("story"), 260) or str(fallback["story"]),
        "slides": slides,
        "evidence_linked": True,
        "source_first": True,
    }


def _fallback_outline(sources: list[dict[str, Any]], topic: str) -> dict[str, Any]:
    title = _short_text(topic, 96) or Path(str(sources[0]["name"])).stem.replace("_", " ") or "研究材料汇报"
    sentences = _sentences("\n".join(item["text"] for item in sources))
    if not sentences:
        sentences = ["材料已成功导入，但正文可提炼句子较少。"]
    pages = list(range(1, min(4, max(item["page_count"] for item in sources)) + 1))
    first = sentences[:5]
    middle = sentences[5:10] or first[1:]
    later = sentences[10:15] or middle[:3]
    source_names = [item["name"] for item in sources]
    slides = [
        {"title": title, "takeaway": "基于用户提供材料生成的第一版研究汇报", "bullets": source_names, "source_pages": []},
        {"title": "这份材料要回答什么问题？", "takeaway": "先明确材料中的研究对象、目标与边界", "bullets": first[:4], "source_pages": pages[:2]},
        {"title": "核心信息集中在哪里", "takeaway": "把材料中的关键事实、数据与观点组织成听众易理解的内容", "bullets": middle[:5], "source_pages": pages},
        {"title": "方法、过程与核心发现", "takeaway": "用清晰的结构呈现材料中的过程、结果与适用范围", "bullets": later[:5], "source_pages": pages},
        {"title": "结论、启示与下一步", "takeaway": "概括可用于汇报和讨论的结论，并明确下一步工作", "bullets": ["请在使用前复核原文中的关键数字、因果表述和结论范围。", "如需正式汇报，可补充图表、方法细节与外部文献交叉验证。"], "source_pages": []},
        {"title": "来源材料", "takeaway": "本演示仅基于本次上传内容", "bullets": source_names, "source_pages": []},
    ]
    presentation_titles = [
        title,
        "研究问题与演示目标",
        "关键信息与核心发现",
        "方法、过程与逻辑",
        "结论、启示与下一步",
        "来源材料",
    ]
    presentation_takeaways = [
        "围绕材料的核心主题，建立清晰的汇报主线。",
        "先说明这份材料试图回答的问题，以及汇报希望达成的判断。",
        "把最重要的信息组织成便于理解与讨论的关键结论。",
        "用清晰的过程、关系或比较解释内容如何展开。",
        "收束可得出的结论，并明确下一步需要讨论或补充的内容。",
        "本演示基于本次上传材料整理。",
    ]
    for index, slide in enumerate(slides):
        if index < len(presentation_titles):
            slide["title"] = presentation_titles[index]
            slide["takeaway"] = presentation_takeaways[index]
    return {
        "title": title,
        "central_question": "这份材料希望帮助听众理解和判断的核心问题是什么？",
        "story": "从研究对象与问题出发，依次呈现关键信息、方法或过程、核心发现，以及可讨论的结论与下一步。",
        "slides": slides,
        "evidence_linked": True,
        "source_first": True,
    }


def _render_pptx(path: Path, outline: dict[str, Any], sources: list[dict[str, Any]], *, theme: dict[str, Any]) -> None:
    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    slides = list(outline.get("slides", []) or [])
    if not slides:
        raise ValueError("幻灯片大纲为空")
    for index, slide_data in enumerate(slides, start=1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        if index == 1:
            _render_cover(slide, outline, sources, theme=theme)
        else:
            _render_content_slide(slide, slide_data, index=index, total=len(slides), sources=sources, theme=theme)
    path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(path))


def _render_cover(slide: Any, outline: dict[str, Any], sources: list[dict[str, Any]], *, theme: dict[str, Any]) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(*theme["cover_bg"])
    title = str(outline.get("title", "研究汇报"))
    title_size, title_height, question_top = _cover_title_metrics(title)
    _add_text(slide, title, 0.9, 1.35, 11.4, title_height, size=title_size, color=theme["cover_text"], bold=True)
    central_question = str(outline.get("central_question", ""))
    _add_text(
        slide,
        central_question,
        0.94,
        question_top,
        10.8,
        1.55,
        size=16 if len(central_question) > 150 else 18 if len(central_question) > 110 else 21,
        color=theme["cover_muted"],
    )
    _add_text(slide, "基于上传材料自动生成 · 生成前请复核原文中的关键结论与数据", 0.94, 5.95, 10.7, 0.35, size=12, color=(167, 190, 199))
    _add_text(slide, " / ".join(item["name"] for item in sources), 0.94, 6.35, 10.8, 0.38, size=12, color=(207, 232, 230))
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(0.88), Inches(1.65), Inches(0.08))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor(*theme["accent"])
    bar.line.fill.background()


def _render_content_slide(
    slide: Any,
    data: dict[str, Any],
    *,
    index: int,
    total: int,
    sources: list[dict[str, Any]],
    theme: dict[str, Any],
) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(*theme["background"])
    _render_template_chrome(slide, theme=theme, index=index, total=total)
    content_left = float(theme.get("content_left", 1.02))
    content_width = 12.15 - content_left
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(content_left - 0.28), Inches(0.55), Inches(0.11), Inches(0.78))
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(*theme["accent"])
    accent.line.fill.background()
    title = str(data.get("title", "研究要点"))
    title_size, title_height = _content_title_metrics(title)
    _add_text(slide, title, content_left, 0.62, content_width, title_height, size=title_size, color=theme["heading"], bold=True)
    takeaway = str(data.get("takeaway", "")).strip()
    takeaway_top = 0.72 + title_height
    takeaway_height = 0.76 if len(takeaway) > 100 else 0.52
    if takeaway:
        _add_text(slide, takeaway, content_left, takeaway_top, content_width - 0.2, takeaway_height, size=17, color=theme["body"])
    bullets = list(data.get("bullets", []) or [])[:5]
    _render_content_modules(
        slide,
        bullets,
        index=index,
        theme=theme,
        left=content_left,
        width=content_width - 0.2,
        top=takeaway_top + takeaway_height + 0.25,
    )
    pages = [str(item) for item in list(data.get("source_pages", []) or []) if str(item).strip()]
    source_label = "本次上传材料"
    if pages:
        source_label += f" · 原文第 {', '.join(pages)} 页"
    _add_text(slide, source_label, content_left, 6.72, content_width - 1.0, 0.25, size=11, color=theme["muted"])


def _template_theme(template: dict[str, Any] | None) -> dict[str, Any]:
    """Translate an EasySlides template into editable PPTX design tokens."""

    template_id = str((template or {}).get("id", "academic_general"))
    themes: dict[str, dict[str, Any]] = {
        "academic_general": {
            "cover_bg": (0, 51, 102), "cover_text": (255, 255, 255), "cover_muted": (232, 244, 252),
            "background": (255, 255, 255), "heading": (51, 51, 51), "body": (51, 51, 51),
            "muted": (102, 102, 102), "primary": (0, 51, 102), "accent": (0, 102, 204),
            "emphasis": (204, 0, 0), "surface": (245, 247, 250), "border": (208, 215, 224),
            "chrome": "header", "content_left": 1.02,
        },
        "academic_scqa": {
            "cover_bg": (11, 47, 107), "cover_text": (255, 255, 255), "cover_muted": (207, 240, 250),
            "background": (247, 250, 255), "heading": (11, 47, 107), "body": (42, 68, 105),
            "muted": (103, 124, 150), "primary": (11, 47, 107), "accent": (0, 166, 214),
            "emphasis": (0, 137, 123), "surface": (241, 246, 255), "border": (188, 213, 239),
            "chrome": "header", "content_left": 1.02,
        },
        "defense_leftnav": {
            "cover_bg": (139, 0, 18), "cover_text": (255, 255, 255), "cover_muted": (250, 228, 232),
            "background": (255, 255, 255), "heading": (61, 23, 31), "body": (51, 51, 51),
            "muted": (112, 112, 112), "primary": (139, 0, 18), "accent": (139, 0, 18),
            "emphasis": (104, 0, 13), "surface": (253, 245, 246), "border": (228, 205, 209),
            "chrome": "leftnav", "content_left": 3.15,
        },
        "defense_topnav": {
            "cover_bg": (24, 58, 106), "cover_text": (255, 255, 255), "cover_muted": (226, 234, 245),
            "background": (255, 255, 255), "heading": (24, 58, 106), "body": (45, 55, 72),
            "muted": (110, 117, 128), "primary": (24, 58, 106), "accent": (24, 58, 106),
            "emphasis": (92, 115, 145), "surface": (231, 230, 230), "border": (210, 214, 220),
            "chrome": "topnav", "content_left": 0.92,
        },
        "literature_minimal": {
            "cover_bg": (255, 255, 255), "cover_text": (14, 40, 65), "cover_muted": (83, 111, 139),
            "background": (255, 255, 255), "heading": (14, 40, 65), "body": (35, 48, 61),
            "muted": (113, 126, 139), "primary": (13, 93, 190), "accent": (13, 93, 190),
            "emphasis": (13, 93, 190), "surface": (246, 250, 255), "border": (211, 224, 239),
            "chrome": "minimal", "content_left": 0.92,
        },
    }
    return dict(themes.get(template_id, themes["academic_general"]))


def _render_template_chrome(slide: Any, *, theme: dict[str, Any], index: int, total: int) -> None:
    primary = RGBColor(*theme["primary"])
    accent = RGBColor(*theme["accent"])
    chrome = str(theme.get("chrome", "header"))
    if chrome == "leftnav":
        rail = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(2.55), Inches(7.5))
        rail.fill.solid(); rail.fill.fore_color.rgb = RGBColor(241, 241, 241); rail.line.fill.background()
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(1.35 + ((index - 2) % 5) * 0.66), Inches(2.72), Inches(0.54))
        band.fill.solid(); band.fill.fore_color.rgb = primary; band.line.fill.background()
        labels = ["研究背景", "研究目标", "材料与方法", "结果与分析", "结论与讨论"]
        for position, label in enumerate(labels):
            _add_text(slide, label, 0.36, 1.49 + position * 0.66, 1.9, 0.24, size=12, color=(255, 255, 255) if position == (index - 2) % 5 else (99, 99, 99), bold=position == (index - 2) % 5)
    elif chrome == "topnav":
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.48))
        bar.fill.solid(); bar.fill.fore_color.rgb = primary; bar.line.fill.background()
        labels = ["背景", "目标", "方法", "结果", "结论"]
        active = (index - 2) % len(labels)
        for position, label in enumerate(labels):
            x = 3.1 + position * 1.45
            if position == active:
                tab = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x - 0.08), Inches(0.08), Inches(1.22), Inches(0.34))
                tab.fill.solid(); tab.fill.fore_color.rgb = RGBColor(255, 255, 255); tab.line.fill.background()
            _add_text(slide, label, x, 0.14, 1.05, 0.16, size=10, color=theme["primary"] if position == active else (231, 237, 245), alignment=PP_ALIGN.CENTER)
    elif chrome == "minimal":
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.48), Inches(0.38), Inches(12.36), Inches(0.04))
        line.fill.solid(); line.fill.fore_color.rgb = accent; line.line.fill.background()
        footer = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(7.24), Inches(13.333), Inches(0.26))
        footer.fill.solid(); footer.fill.fore_color.rgb = accent; footer.line.fill.background()
    else:
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.46))
        header.fill.solid(); header.fill.fore_color.rgb = primary; header.line.fill.background()
        key = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(1.55), Inches(13.333), Inches(0.08))
        key.fill.solid(); key.fill.fore_color.rgb = accent; key.line.fill.background()
    _add_text(slide, f"{index}/{total}", 12.1, 7.0, 0.55, 0.2, size=10, color=theme["muted"], alignment=PP_ALIGN.RIGHT)


def _render_content_modules(
    slide: Any,
    bullets: list[str],
    *,
    index: int,
    theme: dict[str, Any],
    left: float,
    width: float,
    top: float,
) -> None:
    items = bullets or ["根据材料提炼本页要点"]
    kind = (index - 2) % 3
    gap = 0.22
    surface = RGBColor(*theme["surface"])
    border = RGBColor(*theme["border"])
    accent = RGBColor(*theme["accent"])
    if kind == 0:
        count = min(3, len(items))
        card_width = (width - gap * (count - 1)) / count
        for position, item in enumerate(items[:count]):
            x = left + position * (card_width + gap)
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top), Inches(card_width), Inches(2.35))
            card.fill.solid(); card.fill.fore_color.rgb = surface; card.line.color.rgb = border
            marker = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.22), Inches(top + 0.24), Inches(0.42), Inches(0.42))
            marker.fill.solid(); marker.fill.fore_color.rgb = accent; marker.line.fill.background()
            _add_text(slide, str(position + 1), x + 0.22, top + 0.29, 0.42, 0.14, size=10, color=(255, 255, 255), bold=True, alignment=PP_ALIGN.CENTER)
            _add_text(slide, item, x + 0.22, top + 0.82, card_width - 0.44, 1.15, size=16, color=theme["body"])
    elif kind == 1:
        midpoint = left + (width - gap) / 2
        for position, item in enumerate(items[:2] or items):
            x = left if position == 0 else midpoint + gap
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top), Inches((width - gap) / 2), Inches(2.55))
            card.fill.solid(); card.fill.fore_color.rgb = surface; card.line.color.rgb = border
            _add_text(slide, "要点" if position == 0 else "解读", x + 0.28, top + 0.28, 1.0, 0.28, size=13, color=theme["accent"], bold=True)
            _add_text(slide, item, x + 0.28, top + 0.82, (width - gap) / 2 - 0.55, 1.3, size=17, color=theme["body"])
    else:
        count = min(4, len(items))
        node_width = min(2.0, (width - 0.4) / count)
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left + 0.55), Inches(top + 1.18), Inches(max(0.5, node_width * (count - 1))), Inches(0.05))
        line.fill.solid(); line.fill.fore_color.rgb = accent; line.line.fill.background()
        for position, item in enumerate(items[:count]):
            x = left + position * node_width
            node = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.38), Inches(top + 0.88), Inches(0.62), Inches(0.62))
            node.fill.solid(); node.fill.fore_color.rgb = accent; node.line.fill.background()
            _add_text(slide, str(position + 1), x + 0.38, top + 1.08, 0.62, 0.16, size=11, color=(255, 255, 255), bold=True, alignment=PP_ALIGN.CENTER)
            _add_text(slide, item, x, top + 1.78, node_width - 0.12, 1.15, size=15, color=theme["body"], alignment=PP_ALIGN.CENTER)


def _add_text(
    slide: Any,
    text: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: int,
    color: tuple[int, int, int],
    bold: bool = False,
    alignment: Any | None = None,
) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = _short_text(text, 900)
    if alignment is not None:
        paragraph.alignment = alignment
    run = paragraph.runs[0]
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*color)
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0


def _add_bullets(slide: Any, bullets: list[str], left: float, top: float, width: float, height: float) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(0.04)
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    for index, value in enumerate(bullets or ["材料中尚未提炼出足够的要点。"]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = _short_text(value, 155)
        paragraph.level = 0
        paragraph.space_after = Pt(14)
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(20)
        paragraph.font.color.rgb = RGBColor(30, 54, 69)
        paragraph.font.bold = False


def _cover_title_metrics(title: str) -> tuple[int, float, float]:
    """Reserve vertical space for long scientific titles before rendering."""

    length = len(title.strip())
    if length > 78:
        return 30, 2.2, 3.85
    if length > 48:
        return 34, 1.75, 3.45
    return 42, 1.35, 3.05


def _content_title_metrics(title: str) -> tuple[int, float]:
    """Keep claim titles distinct from the takeaway instead of letting them overlap."""

    length = len(title.strip())
    if length > 68:
        return 24, 1.22
    if length > 34:
        return 28, 1.02
    return 30, 0.72


def _presentation_path(workspace: str | Path, title: str) -> Path:
    root = Path(workspace).resolve().parent / "presentations"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = _SAFE_NAME.sub("_", title).strip("._ ")[:70] or "scansci_slides"
    return root / f"{stem}_{stamp}.pptx"


def _sentences(value: str) -> list[str]:
    chunks = re.split(r"(?<=[。！？.!?])\s+|\n+", value)
    rows: list[str] = []
    for chunk in chunks:
        candidate = _compact_text(chunk, limit=190)
        if len(candidate) >= 24 and candidate not in rows:
            rows.append(candidate)
    return rows


def _compact_text(value: str, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _short_text(value: Any, limit: int) -> str:
    return _compact_text(str(value or ""), limit=limit)
