---
template_id: defense_leftnav
display_name_zh: 左栏答辩
category: scenario
summary: Compact thesis-defense template with a dynamic left navigation highlight for the current section.
keywords:
  - thesis_defense
  - defense
  - left_navigation
  - active_section
  - compact_classic
primary_color: "#8B0012"
canvas_format: ppt169
replication_mode: classic
use_cases: Thesis defense, graduation defense, proposal defense, research progress reports
design_tone: Compact, formal, burgundy, left navigation, reusable
placeholders:
  01_cover: ["{{TITLE}}", "{{SUBTITLE}}", "{{PRESENTER}}", "{{ADVISOR}}", "{{DATE}}"]
  02_toc: ["{{SECTION_1}}", "{{SECTION_2}}", "{{SECTION_3}}", "{{SECTION_4}}", "{{SECTION_5}}"]
  02_chapter: ["{{SECTION_NUMBER}}", "{{PART_LABEL}}", "{{SECTION_TITLE}}", "{{SECTION_SUBTITLE}}"]
  03_content: ["{{ACTIVE_SECTION}}", "{{ACTIVE_SECTION_LABEL}}", "{{PAGE_TITLE}}", "{{KEY_MESSAGE}}", "{{CONTENT_BODY}}", "{{PAGE_NUM}}"]
  04_ending: ["{{CLOSING_TITLE}}", "{{PRESENTER}}", "{{ADVISOR}}", "{{CONTACT}}"]
---

# Defense Leftnav Template - Design Specification

`defense_leftnav` is the maintained compact thesis-defense template. It keeps the wine-red defense identity and the five-section left navigation while reducing the runtime surface to five reusable SVG shells plus small JSON sidecars for navigation and body variants.

## Template Contract

| Property | Value |
|---|---|
| Template ID | `defense_leftnav` |
| Source Template | retired full defense roster |
| Replication Mode | `classic` |
| Canvas | 1280 x 720, 16:9 |
| Primary Color | `#8B0012` |
| Navigation Accent | `#68000D` active ribbon fold |
| Built-in Palettes | `wine` default display name: Academic Red, plus `academic_blue`, `academic_purple`, `academic_green` |
| Left Navigation Width | 253.38px gray rail, with the active ribbon extending to x=291.05 |
| Content Area | x=310, y=210, width=910, height=440; machine-readable only, not visibly stroked |
| Content Safety Gap | Minimum 66px between the key-message box bottom and `CONTENT_AREA` top; minimum 32px between independent body components |
| Optional Brand Area | Content pages reserve the upper-right header area for a matched school emblem plus school name; TOC and chapter pages use upper-left emblem-only placement; cover and ending may use upper-right emblem-only placement |
| Runtime Surface | five SVG shells, no slot-guided page catalog |

Use this template for thesis defense, graduation defense, proposal defense, and research progress decks that need a compact reusable style.

## Built-In Theme Palettes

`defense_leftnav` keeps `wine` as the default palette id, displayed as Academic Red, while exposing three academic alternatives in `theme_palettes.json`:

| Palette | Primary | Dark | Soft Surface | Border | Emphasis Text |
|---|---|---|---|---|---|
| `wine` / Academic Red | `#8B0012` | `#68000D` | `#F8F2F3` | `#D9C7CA` | `#3A0008` |
| `academic_blue` | `#183A6A` | `#10284A` | `#F2F5FA` | `#C8D4E3` | `#081B33` |
| `academic_purple` | `#80308B` | `#5D2066` | `#F8F2F9` | `#D8C5DC` | `#331038` |
| `academic_green` | `#016F35` | `#014B24` | `#F1F7F4` | `#C4D8CD` | `#002B15` |

Palette switching is semantic. Replace the five theme roles as a set: `primary`, `primary_dark`, `soft_surface`, `border`, and `emphasis_text`. Do not recolor the white surfaces, black body text, muted gray inactive navigation labels, or the light gray navigation rail when applying an alternate palette.

Generated body content must use the template palette tokens. Do not use ad hoc gray fills such as `#E7E6E6` or `#F2F2F2` for cards, table headers, badges, flow blocks, or emphasis bands. Gray is reserved for immutable navigation chrome.

## Page Shells

| SVG | Role | Main Slots |
|---|---|---|
| `01_cover.svg` | cover | `TITLE`, `SUBTITLE`, `PRESENTER`, `ADVISOR`, `DATE` |
| `02_toc.svg` | table of contents | `SECTION_1` through `SECTION_5` |
| `02_chapter.svg` | section opener | `SECTION_NUMBER`, `PART_LABEL`, `SECTION_TITLE`, `SECTION_SUBTITLE` |
| `03_content.svg` | reusable content page | `ACTIVE_SECTION`, `ACTIVE_SECTION_LABEL`, `PAGE_TITLE`, `KEY_MESSAGE`, `CONTENT_AREA`, `CONTENT_BODY`, `PAGE_NUM` |
| `04_ending.svg` | closing | `CLOSING_TITLE`, `PRESENTER`, `ADVISOR`, `CONTACT` |

Do not add routine content variants as new SVG files. Add reusable composition guidance to `body_variants.json` and visual primitives to `component_styles.json`.

## Dynamic Left Navigation

The main implementation feature is the active-section highlight on `03_content.svg`. In the distilled template, the left navigation is not five duplicated SVG pages. It is one shape-preserving navigation component with five explicit variants.

### Five Navigation Variants

The five variants are defined in `navigation_states.json` as `navigation_variants`. Each variant uses the same base shell, `03_content.svg`, and changes only the active-state elements.

| Variant | Active Section | Use For |
|---|---|---|
| `D01-NAV-01` | 研究背景 | Content pages in section 1 |
| `D01-NAV-02` | 目的及意义 | Content pages in section 2 |
| `D01-NAV-03` | 材料与方法 | Content pages in section 3 |
| `D01-NAV-04` | 结果与分析 | Content pages in section 4 |
| `D01-NAV-05` | 结论与讨论 | Content pages in section 5 |

Shape invariants:

- Keep `nav-surface` and all `nav-inactive-items` fixed.
- Keep the wine-red ribbon, dark fold, icon, and label shapes visually identical to the reference PPT.
- Keep active and inactive labels on the same left text edge: `x=72.54` with `text-anchor="start"`. The active highlight changes the row state, not the label alignment model.
- Keep the active label's editable PPT text box vertically centered inside the wine-red ribbon: `data-pptx-box-y` equals the active band y, `data-pptx-box-h=65.42`, and `data-pptx-valign="middle"`.
- Do not create five separate content SVG shells for the five navigation states.
- Do not resize, recolor, or replace the inactive navigation icon set when switching variants.

Allowed mutable elements:

- `nav-active-band`
- `nav-active-fold`
- `nav-active-pointer`
- `nav-active-icon`
- `nav-active-label`

`03_content.svg` ships with section 1 highlighted. For every generated content slide, the generator must:

1. Select one `navigation_variants` entry using `ACTIVE_SECTION`.
2. Set `ACTIVE_SECTION` to the section index.
3. Set `ACTIVE_SECTION_LABEL` to the selected section title.
4. Resolve that variant's `section_ref` into the matching `sections` entry.
5. Update `nav-active-band` with the selected `active_band` position and fill.
6. Leave `nav-active-fold` untransformed and update `nav-active-pointer` with the selected pre-flattened fold points and fill.
7. Update `nav-active-icon` using the selected section `icon_id` and the active fill from `component_styles.json`.
8. Update `nav-active-label` text, y-position, and `data-pptx-box-y` from `active_label`, while keeping `active_label.x` and `active_label.anchor` equal to the inactive label's left-aligned values.
9. Update `data-active-index` and `data-active-icon` to the selected section values.

The left rail style is abstracted in `component_styles.json` under `navigation_styles.left_navigation`; `navigation_states.json` only stores the state-specific row geometry. The inactive labels and icons remain fixed muted-gray elements under the active ribbon, and the white `ACTIVE_SECTION_LABEL` becomes the visible current chapter label. Both active and inactive labels use the same left-aligned x-coordinate so the highlighted chapter does not drift horizontally.

Default section order:

1. 研究背景
2. 目的及意义
3. 材料与方法
4. 结果与分析
5. 结论与讨论

## Content Body Variants

`03_content.svg` intentionally contains only one body region. Choose one body model from `body_variants.json` after deciding the slide's claim and evidence shape:

- `body_text` for background, motivation, literature context, and discussion.
- `figure_with_takeaway` for one dominant figure and one conclusion.
- `figure_with_callouts` for annotated evidence.
- `two_column_compare` for contrastive arguments.
- `card_grid` for three or four parallel findings.
- `process_steps` for method or workflow sequences.
- `table_or_matrix` for compact structured evidence.

All generated components must stay inside `CONTENT_AREA` unless the selected shell is cover, TOC, chapter, or ending. `CONTENT_AREA` is an invisible machine-readable boundary; do not render it as a dashed or solid outline in the slide.

Independent body components must keep at least 32px of visual gap from each other. Treat each card, text panel, image frame, table, matrix block, or flow-step block as one body component. Internal parts that form a single component, such as a card title strip, number badge, table header, table cells, figure caption, or grouped callout inside one variant, may touch or overlap according to the component style.

## Hard Generation Rules

This section is the authoritative generation contract for `defense_leftnav`. Keep `rules.md` as a short compatibility entry point only.

- Keep the template shell roster small: `01_cover.svg`, `02_toc.svg`, `02_chapter.svg`, `03_content.svg`, and `04_ending.svg`.
- Do not create new SVG shell files for routine content changes such as one image plus one text box, one image plus callouts, card grids, or dashed hypothesis boxes.
- Select a `body_variants.json` entry for each content slide, then apply `component_styles.json` inside `CONTENT_AREA`.
- Enforce `CONTENT_AREA` as hard geometry: `x=310`, `y=210`, `width=910`, `height=440`. Body content must not start in the header/key-message zone.
- Enforce a minimum `32px` gap between independent body components. Only sub-parts of one grouped component may touch or overlap.
- Flatten directional marker geometry before export. Do not rely on group-level rotation transforms for title or TOC triangles, because editable-native PPTX conversion may not preserve the visual direction.
- Keep the content-page header on a fixed grid: the right-pointing title triangle and `PAGE_TITLE` text box must share the same vertical center, the title text x-position must be at least 28px to the right of the triangle's rightmost point, and `PAGE_TITLE` must use middle vertical alignment.
- Reserve the right side of the content-page title row for optional institutional branding. When a school is known and a logo asset is available, place a 34px emblem at x=1052, y=38 and the school name to its right; keep the `PAGE_TITLE` editable box no wider than 620px so the brand slot cannot collide with the title.
- Add a visible primary-color `header-separator` line below the title row before the key-message band.
- Keep at least 16px vertical gap between the `header-separator` bottom and the key-message band top; the key-message text box must use middle vertical alignment.
- Keep gray fills out of generated body content; only the fixed left navigation rail may use the template gray.
- Keep `PAGE_NUM` centered in the red page-number square. Its editable PPT text box must match the square's x, y, width, and height, use `text-anchor="middle"`, and set `data-pptx-valign="middle"` so two-digit page numbers remain fully visible.
- Institutional branding is optional and source-driven. Match the school from the source document, prefer `references/assets/university_emblems`, and use no logo when the school is unknown. If the school is known but absent locally, a transparent web asset may be used only with its source recorded in the project asset lock.
- A specific school logo must never be baked into the template; the same template must be able to generate a logo-free deck or a deck branded for any matched source institution.
- On TOC and chapter transition pages, put optional institutional branding in the upper-left area; keep other non-content page brand placements unchanged, so cover and ending page branding remains in the upper-right area. On content pages, use emblem plus Chinese/English school name in the upper-right header slot.
- Cover and ending metadata footers use exactly three evenly distributed groups with centers around x=260, x=640, and x=1020. Use icons from `templates/icons`, keep at least 12px visual gap between each icon and its label, and keep each editable text box inside its own column so adjacent labels cannot overlap.
- Treat the left navigation as five semantic variants, not five duplicated SVG shells: `D01-NAV-01` through `D01-NAV-05` in `navigation_states.json`.
- For each content slide, choose exactly one navigation variant by `ACTIVE_SECTION`, resolve its `section_ref`, and update only `nav-active-band`, `nav-active-fold`, `nav-active-pointer`, `nav-active-icon`, and `nav-active-label`.
- Keep `nav-active-fold` free of `transform`; `nav-active-pointer.points` in `navigation_states.json` are pre-flattened final coordinates so editable-native PPTX export keeps the fold attached to the active band.
- Keep active and inactive navigation labels left-aligned to the same x-coordinate (`72.54`) with `text-anchor="start"`; switching chapters must move only the active row state vertically.
- Built-in palette switching lives in `theme_palettes.json`. Apply `primary`, `primary_dark`, `soft_surface`, `border`, and `emphasis_text` as one semantic color family.
- Do not recolor immutable white surfaces, black body text, muted gray inactive navigation, or the light gray navigation rail when switching palettes.
- Keep `PAGE_TITLE` as the short running title and `KEY_MESSAGE` as the more detailed one-sentence claim; they must not repeat the same wording.
- Use formal thesis-defense wording, not presentation-internal writing process language.
- Do not use meta-slide labels such as `本页落点`, `本页小结`, `本页重点`, `这一页想说明`, `这一页主要讲`, or `核心 takeaway`.
- If a highlighted label is necessary, make it a content label from the research itself, such as `关键判断`, `机制解释`, `研究贡献`, `方法依据`, or `结果启示`; otherwise omit the label and state the claim directly.
- For closing-page wording on the closing page, do not use `感谢聆听`, `谢谢聆听`, `感谢各位老师聆听`, or any Chinese wording containing `聆听`; use defense-appropriate wording such as `敬请各位老师批评指正`, `感谢各位老师指导`, or a concise `谢谢`.
- Keep `CONTENT_AREA` as an invisible machine-readable boundary. Do not render a dashed or solid content-region outline on generated content slides.
- Do not add a routine citation/source footer to `03_content.svg`; put necessary sources inside the selected body variant, speaker notes, or a dedicated references slide.
- If the content cannot fit inside `CONTENT_AREA` at readable sizes, split the slide instead of shrinking text or adding extra panels outside the content region.
- `defense_leftnav` has a compact body width. When porting content from a larger template or source deck, do a text-capacity pass before export; shorten process-step and card bodies at the source content layer, use punctuation-aware Chinese wrapping, and inspect dense cards, process pages, tables, reference pages, and ported pages at full-size render.
- If speaker notes are embedded, the exported PPTX must pass package validation with a real `ppt/notesMasters/notesMaster1.xml`, a presentation-level `notesMaster` relationship, and one `notesSlide` per slide. Treat missing notes master or broken notesSlide relationships as a blocking defect.

## Visual Rules

- Keep the palette white, light gray, selected theme color, and black.
- Use the selected palette's `primary` color for active surfaces, page number square, key message rule, title accents, and primary strokes.
- Use the selected palette's `primary_dark` color for the active navigation fold only.
- Use `theme_palettes.json` as the source of truth for alternate theme color families.

## Required QA

- Run `scripts/svg_quality_checker.py` before export; all 29-style page SVGs must pass with zero errors.
- Export a native editable PPTX and then run an OpenXML package validation round-trip with `scripts/office/unpack.py` and `scripts/office/pack.py --original`.
- When speaker notes are present, confirm the package contains `ppt/notesMasters/notesMaster1.xml`, `ppt/notesSlides/notesSlide*.xml`, and a presentation-level notes master relationship. Broken notes relationships are a blocking defect even when the slides visually render.
- Render the exported PPTX itself to preview images. Contact sheets are useful for rhythm, but full-size preview inspection is required for dense cards, process pages, tables, figures with captions, and reference pages.
- If `pdftoppm` is unavailable, use LibreOffice to export PDF and PyMuPDF to render PNG previews; do not skip PPTX-rendered visual QA just because one renderer is missing from `PATH`.

## SVG Technical Constraints

1. Every SVG uses `width="1280"`, `height="720"`, and `viewBox="0 0 1280 720"`.
2. Use inline SVG attributes. Do not use `<style>`, `class`, `foreignObject`, `script`, animation tags, or external assets.
3. Use `{{PLACEHOLDER}}` text tokens inside `<text>` / `<tspan>`, except compact chrome text such as the active navigation label and page number may render the default value and carry `data-slot-token` so long tokens do not break the shell preview.
4. Text intended to become editable PowerPoint text should carry `data-pptx-textbox="true"` and box metadata when bounded.
5. The active navigation state is semantic, not decorative. It must match the slide chapter.

## Sidecars

| File | Purpose |
|---|---|
| `layouts.json` | Declares the five-shell classic template surface and slot lists. |
| `navigation_states.json` | Machine-readable active-section row geometry, pre-flattened fold points, and icon ids. |
| `body_variants.json` | Reusable content compositions inside `CONTENT_AREA`. |
| `component_styles.json` | Shared navigation, card, figure, callout, and caption styling primitives. |
| `theme_palettes.json` | Built-in semantic color families for wine, academic blue, academic purple, and academic green. |
| `rules.md` | Short compatibility entry point that redirects to `design_spec.md#hard-generation-rules`. |
