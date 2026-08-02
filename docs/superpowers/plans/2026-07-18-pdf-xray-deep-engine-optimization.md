# PDF X-Ray Deep Engine Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate repeated content-stream parsing and duplicate clipping comparisons while preserving the deep audit's report contract.

**Architecture:** Keep the public API and CLI unchanged. Introduce a private operation cache scoped to each page audit and route structural walkers through it. Centralize creation of the existing evidence dictionary, then deduplicate equal clipping bounds before the current conservative containment checks.

**Tech Stack:** Python 3, pypdf, PyMuPDF, pytest.

---

### Task 1: Prove and cache repeated content-stream parsing

**Files:**
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\tests\\test_audit_pdf.py`
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\audit_pdf.py`

- [ ] **Step 1: Write a failing deep-audit parse-count regression**

Create one simple vector PDF, monkeypatch the module's `ContentStream` constructor with a counting subclass, call `audit_pdf()`, and assert the page content stream is parsed once. The unoptimized code parses the same stream through Type3, Form, Pattern, and visible-content walkers, so this fails with a count greater than one.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "reuses_parsed_content_stream" -q`

Expected: FAIL because the constructor count is greater than one.

- [ ] **Step 3: Add the private cache and route walkers through it**

Add a small page-scoped cache keyed by stable stream identity. Preserve each caller's current parse-error handling; only replace direct `ContentStream(stream, reader).operations` calls with cache lookup. Instantiate a fresh cache per page in both deep and fast report construction and pass it through recursive walkers.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "reuses_parsed_content_stream" -q`

Expected: PASS.

### Task 2: Make repeated evidence and clipping work explicit

**Files:**
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\tests\\test_audit_pdf.py`
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\audit_pdf.py`

- [ ] **Step 1: Write failing factory and clipping-work regressions**

Assert that a new evidence factory returns independent lists. Create vector boxes and many identical visible clipping bounds, wrap `rectangle_contains_with_tolerance`, and assert equivalent bounds are checked only once per vector box while retained boxes are unchanged.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "empty_evidence or deduplicates_equivalent_clipping_bounds" -q`

Expected: FAIL because the helper does not exist and duplicate bounds are repeatedly compared.

- [ ] **Step 3: Add the factory and deduplicate before matching**

Replace each handwritten evidence dictionary with `empty_evidence()`. In `filter_clipped_vector_boxes`, preserve the current `visible_matches >= 1` and `any(clipped_matches)` rules but deduplicate bounds by their numeric tuple before loops.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "empty_evidence or deduplicates_equivalent_clipping_bounds" -q`

Expected: PASS.

### Task 3: Verify compatibility and measure the real workload

**Files:**
- Modify: none

- [ ] **Step 1: Run all regressions**

Run: `python -m pytest tests\\test_audit_pdf.py -q`

Expected: all tests pass.

- [ ] **Step 2: Validate the skill package**

Run: `python C:\\Users\\Liang\\.codex\\skills\\.system\\skill-creator\\scripts\\quick_validate.py C:\\Users\\Liang\\.codex\\skills\\pdf-xray`

Expected: `Skill is valid!`.

- [ ] **Step 3: Benchmark the supplied PDF**

Run the deep API on `C:\\Users\\Liang\\Downloads\\s41565-025-02080-2.pdf`, record total time and the slowest pages, and compare with the 104.6-second baseline. Report the observed change without claiming a target that was not measured.

### Task 4: Index text-span matching without changing ambiguity rules

**Files:**
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\tests\\test_audit_pdf.py`
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\audit_pdf.py`

- [ ] **Step 1: Write a failing nonmatching-span scan regression**

Pass many distinct text operations and many custom span dictionaries that count `text` lookups into `confirmed_text_operation_boxes()`. Assert each span is inspected only during index construction, not once for every candidate sequence.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "indexes_spans_by_text" -q`

Expected: FAIL because the existing nested comprehension scans every remaining span for each candidate sequence.

- [ ] **Step 3: Replace repeated list scans with ordered text buckets**

Build a mapping from span text to original indexes and retain a set of unconsumed indexes. Resolve candidate matches from the matching bucket in original order; retain the existing Form clipping, equivalent-box, and ambiguity logic.

- [ ] **Step 4: Verify GREEN and rerun the benchmark**

Run the focused regression, full suite, skill validator, and supplied-PDF benchmark. Report the measured result against the 53.3-second first-optimization baseline.
