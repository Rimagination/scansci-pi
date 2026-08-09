# Academic SCQA Rules

Authoritative visual identity lives in `design_spec.md`; this file keeps the hard generation rules short and machine-friendly.

- Every content title must be a conclusion sentence, not a vague label. Write `title must be a conclusion sentence` into generation checks and revise titles like "Research Background" into claims.
- Use `references/academic-orchestration.md` before planning this template.
- Start with Audience-State-Transfer: audience, initial state, desired state, core tension, and transfer path.
- Follow SCQA order for default decks: Situation, Complication, Question, Answer. Repeat a phase only when the content volume requires it.
- Every content slide must create one audience-state shift and carry one defensible claim plus one main evidence shape.
- Avoid developer-facing language in visible slide text and speaker-facing plan fields: template, slot, placeholder, executor, renderer, generation, pipeline, implementation.
- Choose content body variants from `body_variants.json` by phase intent and evidence shape, not by decoration.
- Resolve `LOGO` by searching user-provided materials for a suitable real logo first. If no suitable logo is available, keep the built-in degree-cap icon fallback.
- When a real logo is inserted, replace the full `LOGO` group or hide the fallback drawing so transparent logo artwork does not overlap the fallback.
- Keep generated content inside `CONTENT_AREA`. If it cannot fit at readable size, split the slide.
- Use the palette as a set: academic blue `#0046A5`, deep blue `#0B2F6B`, sky cyan `#00A6D6`, teal `#17A889`, and ice background `#F7FAFF`.
- Use `PAGE_TITLE` for the short running title and `KEY_MESSAGE` for the fuller claim; do not duplicate the same wording.
- Prefer real research figures or generated diagrams for method/data/image slots; use icon-like assets only for workflow steps.
- Section-divider image behavior from the source is not preserved as a fixed slot. Use the chapter shell's built-in blue/teal structure unless the user explicitly requests a visual section opener.

