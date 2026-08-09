---
template_id: academic_scqa
display_name_zh: 学术论证
category: scenario
summary: Blue-cyan academic and technical report template with Audience-State-Transfer and SCQA body-variant guidance.
keywords:
  - academic_report
  - technical_report
  - academic_blue
  - Audience-State-Transfer
  - SCQA
  - slot_distilled
primary_color: "#0046A5"
canvas_format: ppt169
replication_mode: classic
use_cases: Academic reports, laboratory technical briefings, research progress reviews, project reviews
design_tone: Formal, institutional, data-driven, audience-facing, AST/SCQA-structured
placeholders:
  01_cover: ["{{LOGO}}", "{{TITLE}}", "{{SUBTITLE}}", "{{PRESENTER}}", "{{AFFILIATION}}", "{{DATE}}"]
  02_toc: ["{{LOGO}}", "{{TOC_ITEM_1_TITLE}}", "{{TOC_ITEM_2_TITLE}}", "{{TOC_ITEM_3_TITLE}}", "{{TOC_ITEM_4_TITLE}}", "{{TOC_ITEM_5_TITLE}}"]
  02_chapter: ["{{LOGO}}", "{{CHAPTER_NUM}}", "{{CHAPTER_TITLE}}", "{{CHAPTER_DESC}}"]
  03_content: ["{{LOGO}}", "{{PAGE_TITLE}}", "{{KEY_MESSAGE}}", "{{CONTENT_AREA}}", "{{CONTENT_BODY}}", "{{SOURCE}}", "{{PAGE_NUM}}"]
  04_ending: ["{{LOGO}}", "{{THANK_YOU}}", "{{CONTACT_INFO}}"]
---

# Academic SCQA - Design Specification

## I. Template Overview

`academic_scqa` distills an academic report HTML slot-template pattern into the EasySlides layout library. The source style is not a PPTX master, so this template keeps the academic storytelling rules and body-variant taxonomy while rebuilding the runtime surface as clean SVG shells.

Use it for academic reports, lab technology briefings, project reviews, and research progress decks that need a formal blue-white identity with bright cyan emphasis and teal evidence accents.

## I-A. Academic Orchestration Contract

Read `references/academic-orchestration.md` before planning with this template.
`academic_scqa` is the structured argument variant of the general academic family:

- Start with **Audience-State-Transfer**: audience, initial state, desired
  state, core tension, and transfer path.
- Use **SCQA** as the visible planning spine for structured reports:
  Situation, Complication, Question, Answer.
- Every content slide should create one audience-state shift and support one
  defensible claim with a main evidence shape.
- Keep visible slide language audience-facing. Do not leak developer-facing
  language such as template, slot, placeholder, executor, renderer, generation,
  pipeline, or implementation into slide copy or speaker-facing plans.

## II. Color Scheme

| Role | Color | Usage |
|---|---|---|
| Academic blue | `#0046A5` | Title bands, chapter surfaces, section labels, key statements |
| Deep blue | `#0B2F6B` | Chapter depth, dark support surfaces, high-contrast accents |
| Sky cyan | `#00A6D6` | Top rule, underlines, key emphasis, section markers |
| Teal evidence | `#17A889` | Evidence bars, TOC ticks, workflow connectors, secondary highlights |
| Ice background | `#F7FAFF` | Cover and calm content background |
| Subtle surface | `#F1F6FF` | Data cards, figure wells, method panels |
| Border gray | `#D6E4F5` | Soft dividers and card borders |
| Body text | `#475569` | Main text |

## III. Typography

Use `Microsoft YaHei, Arial, sans-serif`. Titles are compact and declarative; body copy should be short enough to preserve the formal lab-report rhythm.

## IV. Signature Design Elements

- Thin sky-cyan top rule.
- Academic-blue statement bands for cover, chapter, and content headers.
- Teal vertical or horizontal evidence bars for SCQA progression and data emphasis.
- Reusable `LOGO` image slot. When building a PPT, first search user-provided materials for a suitable institution or project logo; if no suitable logo is found, keep the built-in degree-cap icon fallback.
- One-slide-one-claim convention: `PAGE_TITLE` is the short running title, while `KEY_MESSAGE` is the conclusion sentence.

## V. Page Roster

| SVG | Role | Description |
|---|---|---|
| `01_cover.svg` | cover | Ice-blue cover with cyan top rule, `LOGO` slot, and an academic-blue title band carrying title/subtitle. |
| `02_toc.svg` | toc | Two-column agenda with `LOGO` slot, academic-blue numbering, and teal ticks for up to five SCQA or report sections. |
| `02_chapter.svg` | chapter | Deep-blue section opener with `LOGO` slot, large chapter number, cyan underline, teal keyword rail, and concise section claim. |
| `03_content.svg` | content | Reusable content shell with `LOGO` slot, academic-blue header, cyan underline, soft key-message bar, invisible `CONTENT_AREA`, and source/page footer. |
| `04_ending.svg` | ending | Ice-blue closing page with `LOGO` slot, academic-blue thanks band, teal divider, presenter/contact block, and footer. |

## VI. Logo Slot Policy

All five shells expose a single `LOGO` image slot instead of fixed report text or separate organization-name fields. The generator should resolve it in this order:

1. Search user-provided materials for a suitable institutional, laboratory, project, or paper-source logo.
2. Prefer a real logo image with transparent or clean background and preserve its aspect ratio inside the declared slot box.
3. If no suitable logo is available, keep the SVG degree-cap icon fallback.

When a real logo is inserted, replace the full `LOGO` group or hide the fallback drawing so transparent logo artwork does not overlap the fallback icon.

## VII. Sidecars

| File | Purpose |
|---|---|
| `template.json` | Template package metadata and source attribution. |
| `layouts.json` | Declares the five classic shells and placeholder slots. |
| `body_variants.json` | Distills the source HTML page roles into reusable body layouts. |
| `story_structure.json` | Encodes the SCQA narrative order and phase-to-layout preferences. |
| `rules.md` | Hard generation rules: conclusion titles, SCQA mapping, text fit, and image-slot policy. |

## VIII. Distillation Notes

The source repository contains 12 HTML templates: cover, contents, intro-policy, section-divider, 4-workflow, 3-workflow, research-method, comparison, image-grid, key-finding, thank-you, and data-stats. EasySlides keeps five reusable SVG shells and moves the specialized HTML pages into `body_variants.json`, because the active template library favors stable shell surfaces plus machine-readable composition rules over one SVG per content variant.

