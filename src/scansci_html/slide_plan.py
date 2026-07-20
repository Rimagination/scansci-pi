"""Versioned renderer-neutral slide plans for ScanSci presentations."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


SLIDE_PLAN_SCHEMA = "scansci.slide-plan.v1"


def build_slide_plan(outline: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    slides = []
    for index, raw in enumerate(list(outline.get("slides", []) or []), start=1):
        data = dict(raw or {})
        bullets = [_compact(item, 240) for item in list(data.get("bullets", []) or []) if _compact(item, 240)][:6]
        slides.append(
            {
                "id": f"slide-{index:02d}",
                "layout": "cover" if index == 1 else "claim-with-points",
                "title": _compact(data.get("title") or (outline.get("title") if index == 1 else "研究要点"), 180),
                "takeaway": _compact(data.get("takeaway", ""), 320),
                "blocks": [{"type": "bullets", "items": bullets}] if bullets else [],
                "source_pages": [int(page) for page in list(data.get("source_pages", []) or []) if str(page).isdigit()],
                "source_names": [str(item.get("name", "")) for item in sources if item.get("name")],
            }
        )
    plan = {
        "schema": SLIDE_PLAN_SCHEMA,
        "title": _compact(outline.get("title", "科研汇报"), 180),
        "central_question": _compact(outline.get("central_question", ""), 420),
        "story": _compact(outline.get("story", ""), 900),
        "aspect_ratio": "16:9",
        "theme": {
            "font_head": "Microsoft YaHei",
            "font_body": "Microsoft YaHei",
            "background": "F7F8F7",
            "ink": "132431",
            "muted": "667781",
            "accent": "14897D",
            "cover": "091B2A",
        },
        "slides": slides,
        "sources": [
            {
                "name": str(item.get("name", "")),
                "kind": str(item.get("kind", "")),
                "page_count": int(item.get("page_count", 0) or 0),
            }
            for item in sources
        ],
    }
    validate_slide_plan(plan)
    return plan


def validate_slide_plan(plan: object) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != SLIDE_PLAN_SCHEMA:
        raise ValueError("Unsupported slide plan schema")
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("A slide plan requires at least one slide")
    if len(slides) > 80:
        raise ValueError("A slide plan cannot exceed 80 slides")
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict) or not str(slide.get("title", "")).strip():
            raise ValueError(f"Slide {index} requires a title")
        blocks = slide.get("blocks", [])
        if not isinstance(blocks, list):
            raise ValueError(f"Slide {index} blocks must be a list")
    return plan


def write_slide_plan(path: str | Path, plan: dict[str, Any]) -> Path:
    validate_slide_plan(plan)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def safe_presentation_name(value: object, *, fallback: str = "scansci_slides") -> str:
    normalized = re.sub(r"[^\w.-]+", "_", str(value or "")).strip("._ ")[:70]
    return normalized or fallback


def _compact(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()

