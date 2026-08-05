---
name: academic-research-suite
description: End-to-end academic research orchestration from question formation and literature search through evidence review, statistics, figures, manuscript writing, peer-review response, data availability, and paper-to-PPT delivery. Use when a task spans multiple research stages.
---

# Academic Research Suite

Route a multi-stage research request through the smallest set of built-in skills.

1. Start with `scientific-brainstorming` or `good-question` when the question is not yet testable.
2. Use `nature-academic-search` to discover and verify sources, then `literature-review` to build an evidence map.
3. Use `nature-statistics` for numerical claims and analysis reporting, and `scientific-visualization` or `nature-figure` for figures.
4. Use `nature-writing` for drafting, `nature-polishing` for language and claim-drift checks, and `nature-reviewer` before submission.
5. Use `nature-response` for revision letters, `nature-data` for data-availability materials, and `nature-paper2ppt` for a presentation artifact.
6. At every handoff, carry forward source IDs, exact quotes, analysis inputs, figure provenance, and unresolved issues.

Do not run every skill by default. Ask for missing inputs when they change the conclusion. Keep planning, discovery leads, verified evidence, analysis output, and final prose as distinct artifacts. This suite is a ScanSci composition layer; it does not replace the individual skill contracts.
