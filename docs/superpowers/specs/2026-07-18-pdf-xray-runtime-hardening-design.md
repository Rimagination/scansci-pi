# PDF X-Ray Runtime Hardening Design

## Goal

Make the deep audit easier to evolve and bounded on hostile PDFs while preserving its current evidence and classification semantics.

## Scope

- Move page-scoped runtime state into `scripts/pdf_xray_runtime.py`: audit limits, telemetry, resource-limit exception, and the cached content-stream parser.
- Add an explicit page traversal context in the deep walker so shared evidence, warnings, page geometry, cache, and limits are no longer passed as independent values.
- Add conservative default limits for Form nesting and parsed operations. A limit breach returns `uncertain` and a review recommendation instead of continuing an incomplete audit.
- Add CLI-only `--diagnostics`; normal reports remain unchanged. Diagnostics expose parsed-stream count, cache hits, total operations, maximum Form depth, and limit reasons.

## Compatibility

- Keep `audit_pdf(source, region)` and all existing JSON fields valid.
- Do not alter classifications for documents that stay within default limits.
- Do not change normal CLI output unless `--diagnostics` is supplied.

## Verification

- Add failing tests for diagnostics visibility, a depth-limited Form chain, and a low operation limit through the internal API.
- Preserve existing Type3, Pattern, clipping, and Form tests.
- Run the complete suite, validate the skill, and benchmark the supplied PDF against the 41.679-second deep-audit baseline.

## Deferred

- Move geometry and reporting helpers into their own modules only after this runtime boundary has stabilized.
- Build a distributable real-PDF corpus only with user-approved source files; continue using the supplied paper as a local, non-distributed benchmark.
