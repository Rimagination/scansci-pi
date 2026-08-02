# PDF X-Ray Lightweight Design

## Goal

Make ordinary classification avoid document-wide deep analysis, and make the common question “does this PDF contain vector graphics?” fast without weakening the existing strict deep auditor.

## Decisions

- Keep `audit_pdf()` and `--mode deep` unchanged as the exhaustive, evidence-rich path.
- Change `--mode auto` from document-wide escalation to page-scoped escalation. Run fast preflight for every page, deep-audit only pages whose fast result is risky or low confidence, then merge results in page order. Report `analysis_mode: hybrid` and `deep_pages` when both paths were used.
- Add `--goal classify|vector-presence`; `classify` remains the default.
- `--goal vector-presence` runs a geometry-only scan over pages and stops after the first graphic-like vector drawing candidate. It returns `confirmed` only for an ordinary, safe page; on a risky page it returns `candidate` with an explicit `render_review` recommendation, never an unqualified claim.
- Vector-presence evidence excludes text spans. It requires either three drawing boxes or a single drawing covering at least 1% of page area, so routine underlines and small decoration are not treated as a vector image.
- Keep compact CLI output and `--verbose`; add only the small presence result to the default JSON.

## Non-goals

- Do not remove the deep parser or its regression cases.
- Do not promise that vector-presence candidates are cleanly extractable or editable.
- Do not add a general page-selection CLI in this iteration; regions and deep mode already cover targeted inspection.

## Acceptance Criteria

- A mixed simple/risky document deep-audits only the risky page in auto mode.
- A vector-presence query on a risky page returns a fast `candidate` and stops without running the deep parser.
- A safe graphic-like vector page returns `confirmed`; a text-only or tiny-decoration page returns `not_found` after the fast scan.
- Existing deep API and all deep regressions remain valid.
