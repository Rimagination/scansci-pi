# PDF X-Ray Tiered Workflow Design

## Goal

Make `pdf-xray` fast by default without discarding the existing strict PDF semantic auditor.

## Decisions

- Keep `audit_pdf()` as the full, conservative deep auditor and retain its regression suite.
- Add CLI mode selection: `--mode auto|fast|deep`; `auto` is the default.
- In `auto`, run a lightweight preflight. Return fast results only when every page has ordinary displayed images, paths, and text without risky PDF structure. Escalate the whole document to the existing deep audit when any page has clipping, Forms, transparency/masks, inline images, shadings, unusual page coordinates, or another ambiguous feature.
- In explicit `fast` mode, do not silently guess across those risks: return `uncertain`, include escalation reasons, and recommend `deep_audit`.
- Keep geometry-rich evidence internally. Default CLI JSON exposes counts, classifications, warnings, analysis mode, and a next-step recommendation. `--verbose` retains the current full geometry contract for investigation and existing downstream callers.
- Add a `recommendation` to every page. Use `continue` for high-confidence results, `deep_audit` for fast-mode structural risks, and `render_review` for deep results that remain uncertain or contain warnings requiring visual verification.

## Fast Preflight

The fast path may use PyMuPDF displayed image information, drawings, and rendered text spans only after a pypdf resource/content scan has excluded risky features. It must reject rather than approximate pages with:

- Form XObjects, clipping, graphics-state transparency, masks, inline images, named shadings, or non-normal text rendering;
- rotated, non-default `UserUnit`, or non-trivial CropBox pages; and
- renderer-only synthetic image entries (`xref=0`).

This keeps `fast` narrowly useful and routes complex files to the previously built deep implementation.

## Compatibility and Verification

- Preserve the Python `audit_pdf()` deep-report shape.
- Move existing CLI regression helper calls to `--mode deep --verbose`, then add focused CLI tests for auto escalation, explicit fast uncertainty, compact output, and `--verbose` evidence.
- Validate the skill manifest and run the full tests plus real transformer, scan, and unused-resource fixtures.
