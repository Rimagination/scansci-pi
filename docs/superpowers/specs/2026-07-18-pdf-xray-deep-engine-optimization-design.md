# PDF X-Ray Deep Engine Optimization Design

## Goal

Reduce deep-audit cost on complex PDFs without changing the public deep report, classifications, warnings, or escalation semantics.

## Evidence

The current deep audit re-parses the same PDF content stream for Type3 reachability, Form reachability, Pattern reachability, and visible-content evidence. On the supplied paper, a full deep audit takes 104.6 seconds; pages 23 and 24 take about 25 seconds each. Profiling page 24 found four `ContentStream.operations` parses and a clipping matcher that performs millions of rectangle-containment checks.

## This iteration

- Add a private per-page content-operation cache. All deep and fast structural walkers for the same stream must reuse one parsed operation sequence.
- Use one factory for the evidence schema so deep, fast, and error reports cannot drift.
- Deduplicate equivalent clipping-path bounds before containment matching. This preserves the current existential matching semantics.
- Index remaining rendered text spans by exact text while preserving their original order. Continue to apply Form-BBox clipping and ambiguity checks before accepting a match.
- Preserve `audit_pdf()`, CLI JSON, classifications, warnings, and all public mode contracts.

## Verification

- Add a regression that observes a repeated traversal of one simple content stream and proves it is parsed once per page audit.
- Add a regression that proves duplicate clipping bounds do not multiply containment work or change retained geometry.
- Add a regression with many nonmatching spans that proves text matching does not rescan them for every text operation.
- Run the full suite, skill validator, and a before/after benchmark on the supplied PDF.

## Non-goals

- Do not alter vector/raster classification rules or claim stronger confidence.
- Do not add dependencies or change the CLI.
- Do not split the script into modules in this iteration; perform that mechanical move only after the optimized internal contracts are stable.
