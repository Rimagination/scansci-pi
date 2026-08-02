# pdf-xray design

## Goal

Create a globally discoverable Codex skill that classifies PDF pages or explicitly supplied figure regions as `vector`, `raster`, `mixed`, or `uncertain`, with auditable structural evidence.

## Scope

- Install under `%USERPROFILE%\.codex\skills\pdf-xray`.
- Inspect image XObjects, masks, nested Form XObjects, and path paint operations recursively.
- Use raw PDF structure for classification evidence.
- Use PyMuPDF only to obtain displayed image and vector-drawing bounding boxes for spatial association, and to render a page for visual verification when needed.
- Report page-level classifications by default. Report region-level classifications only when a reliable region is supplied.
- Treat clipping paths as an ambiguity boundary: suppress automatic visible geometry on affected pages and require rendered verification rather than guessing clip geometry.

## Non-goals

- Do not infer semantic figures from captions in the first version.
- Do not treat every path operator as visible vector art.
- Do not force a binary raster/vector conclusion when the available evidence cannot prove an object is displayed.
- Do not attempt full clipping-path geometry or coordinate-transform evaluation in the first version.
- Do not claim a page-level label is a label for every figure on that page.
- Do not bundle a large PDF corpus or add a general-purpose document-processing workflow.

## Components

| Component | Responsibility |
|---|---|
| `SKILL.md` | Trigger conditions, workflow, tool boundaries, reporting rules, and ambiguity handling. |
| `scripts/audit_pdf.py` | Deterministically collect page-level structural evidence and produce JSON. |
| `agents/openai.yaml` | Skill UI metadata generated from the final skill content. |

## Data flow

1. Read each page's resource dictionary and recursively resolve XObjects.
2. Record image dimensions, masks, Form nesting, and content-stream operators.
3. Count only paint operators as visible vector evidence; retain clipping/transform operations as context, not proof.
4. Query PyMuPDF for displayed-image and vector-drawing bounding boxes, when available, without treating its high-level inventory as the sole structural proof.
5. If a clipping path occurs in used content, suppress automatic geometry evidence and add a render-verification warning.
6. Classify a page from visible image and vector-paint evidence. Preserve `uncertain` for malformed, encrypted, clipped, or structurally ambiguous PDFs.
7. If the caller supplies a region, classify evidence overlapping that region; otherwise return only page-level results.

## Output contract

Return JSON with a per-page `classification`, `confidence`, `evidence`, and `warnings`. Evidence includes image objects, masks, nested forms, paint-operation counts, clipping-operation counts, and displayed-image bounding boxes. Warnings state why a conclusion is page-level or uncertain.

## Validation

Before publishing the skill, run independent baseline and forward tests against requests covering a scanned page, a mixed page, and vector content embedded in nested Form XObjects. Validate the script syntax and its JSON output against available public samples.
