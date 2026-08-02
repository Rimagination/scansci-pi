# PDF X-Ray Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract page-scoped audit runtime state and expose safe operational diagnostics without changing ordinary audit reports.

**Architecture:** `pdf_xray_runtime.py` owns operation caching, limits, and counters. `audit_pdf.py` creates one runtime per page, passes a traversal context through recursive Form walks, and serializes counters only when `--diagnostics` is requested.

**Tech Stack:** Python 3, dataclasses, pypdf, PyMuPDF, pytest.

---

### Task 1: Lock diagnostics and limits with failing tests

**Files:**
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\tests\\test_audit_pdf.py`

- [ ] **Step 1: Write failing diagnostics test**

Run the deep CLI with `--diagnostics` on a simple vector PDF. Assert normal evidence remains present and diagnostics contains `content_streams_parsed`, `content_stream_cache_hits`, `content_operations`, `max_form_depth`, and `resource_limits`.

- [ ] **Step 2: Write failing depth-limit test**

Create a chain of nested Form XObjects, call the internal deep runner with `AuditLimits(max_form_depth=1)`, and assert `classification == "uncertain"`, the warning names `max_form_depth`, and diagnostics records the reason.

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "diagnostics or form_depth_limit" -q`

Expected: FAIL because the CLI option and runtime types do not exist.

### Task 2: Extract runtime ownership and thread traversal state

**Files:**
- Create: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\pdf_xray_runtime.py`
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\audit_pdf.py`

- [ ] **Step 1: Add runtime primitives**

Implement immutable `AuditLimits`, mutable `AuditTelemetry`, `ResourceLimitExceeded`, and `ContentOperationCache`. Cache parsed operations per page; count cache hits and operations; raise the resource-limit exception once a configured stream limit is exceeded.

- [ ] **Step 2: Add a page traversal context**

Replace the deep walker’s independent cache/evidence/warning/page-bound arguments with a context object. Track Form depth centrally and mark the context limited before recursion proceeds beyond the configured depth.

- [ ] **Step 3: Preserve normal behavior**

When no resource limit is hit, keep existing warnings, evidence, classifications, public deep API shape, and CLI output unchanged.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "diagnostics or form_depth_limit or type3 or clipping" -q`

Expected: PASS.

### Task 3: Add opt-in diagnostics and complete verification

**Files:**
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\scripts\\audit_pdf.py`
- Modify: `C:\\Users\\Liang\\.codex\\skills\\pdf-xray\\SKILL.md`

- [ ] **Step 1: Add `--diagnostics`**

Emit `diagnostics` only when explicitly requested. Pass the option through deep, fast, and auto paths; do not include diagnostics in default compact reports.

- [ ] **Step 2: Document diagnostics and limit behavior**

Explain that diagnostics are for performance investigation and that resource-limit results are intentionally uncertain and require review.

- [ ] **Step 3: Verify all behavior**

Run the complete pytest suite, skill validator, a standard deep audit, `--diagnostics`, and the supplied-PDF timing benchmark. Compare the result with the 41.679-second baseline.
