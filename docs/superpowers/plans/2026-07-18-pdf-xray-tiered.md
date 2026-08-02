# PDF X-Ray Tiered Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pdf-xray` use a fast default audit, automatically upgrade risky documents to the retained deep auditor, and keep default JSON concise.

**Architecture:** Keep `audit_pdf()` as the existing complete deep engine. Add fast resource/content preflight and displayed-geometry reporting beside it, then dispatch from a new CLI-level `audit_with_mode()` function. Compact reports only at the CLI boundary so deep library callers and `--verbose` retain complete evidence.

**Tech Stack:** Python 3, pypdf, PyMuPDF, pytest.

---

### Task 1: Add fast preflight and fast page reporting

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\scripts\audit_pdf.py`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\tests\test_audit_pdf.py`

- [ ] **Step 1: Write failing behavior tests**

```python
def test_default_auto_uses_fast_mode_for_simple_raster_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "simple.pdf"
    write_pdf(pdf, "raster")
    report = run_default_cli(pdf)
    assert report["analysis_mode"] == "fast"
    assert report["pages"][0]["classification"] == "raster"
    assert report["pages"][0]["recommendation"] == "continue"

def test_explicit_fast_returns_uncertain_for_clipping(tmp_path: Path) -> None:
    pdf = tmp_path / "clipped.pdf"
    write_zero_area_clipped_rectangle_pdf(pdf)
    report = run_cli(pdf, "--mode", "fast")
    assert report["pages"][0]["classification"] == "uncertain"
    assert report["pages"][0]["recommendation"] == "deep_audit"
```

- [ ] **Step 2: Run the focused tests and verify expected RED failures**

Run: `python -m pytest tests\\test_audit_pdf.py -k "default_auto_uses_fast or explicit_fast_returns" -q`

Expected: FAIL because the CLI has no mode argument or fast report.

- [ ] **Step 3: Implement minimal preflight and fast reporting**

Add `fast_page_report()`, `fast_audit_pdf()`, and `audit_with_mode()`. Use pypdf to collect risk reasons and PyMuPDF only for normal displayed image/path/text geometry. Return `uncertain` plus `deep_audit` whenever risk reasons exist.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "default_auto_uses_fast or explicit_fast_returns" -q`

Expected: PASS.

### Task 2: Add automatic escalation and concise CLI output

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\scripts\audit_pdf.py`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\tests\test_audit_pdf.py`

- [ ] **Step 1: Write failing behavior tests**

```python
def test_auto_escalates_clipped_pdf_to_deep_mode(tmp_path: Path) -> None:
    pdf = tmp_path / "clipped.pdf"
    write_zero_area_clipped_rectangle_pdf(pdf)
    report = run_default_cli(pdf)
    assert report["analysis_mode"] == "deep"
    assert "clipping" in report["escalation_reasons"]

def test_default_cli_compacts_geometry_but_verbose_keeps_it(tmp_path: Path) -> None:
    pdf = tmp_path / "raster.pdf"
    write_pdf(pdf, "raster")
    compact = run_default_cli(pdf)
    verbose = run_cli(pdf, "--mode", "deep", "--verbose")
    assert isinstance(compact["pages"][0]["evidence"]["visible_images"], int)
    assert isinstance(verbose["pages"][0]["evidence"]["visible_images"], list)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "auto_escalates or compacts_geometry" -q`

Expected: FAIL because default mode is still the existing full JSON report.

- [ ] **Step 3: Implement dispatch, compaction, and recommendations**

Extend `build_parser()` with `--mode` and `--verbose`. Make `auto` return the fast document only when all pages are admissible; otherwise invoke `audit_pdf()` and annotate the report with `analysis_mode: "deep"` and its preflight reasons. Add a CLI-only `compact_report()` that replaces geometry arrays with counts. Add `recommendation` per page.

- [ ] **Step 4: Preserve existing deep tests**

Change the legacy `run_cli()` test helper to append `--mode deep --verbose`; this preserves the asserted evidence shape while exercising the new compatibility route.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "auto_escalates or compacts_geometry" -q`

Expected: PASS.

### Task 3: Update agent instructions and UI metadata

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\SKILL.md`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\agents\openai.yaml`

- [ ] **Step 1: Document the mode contract**

Replace the one-command imperative with: run default `auto`; follow `recommendation`; use `--mode deep --verbose` only for ambiguous results or evidence reporting; use `--mode fast` only for a deliberately non-escalating preflight.

- [ ] **Step 2: Regenerate UI metadata**

Run: `python %USERPROFILE%\.codex\skills\.system\skill-creator\scripts\generate_openai_yaml.py %USERPROFILE%\.codex\skills\pdf-xray --interface display_name="PDF X-Ray" --interface short_description="Audit PDF raster and vector evidence" --interface default_prompt="Use $pdf-xray to classify this PDF with fast automatic escalation."`

- [ ] **Step 3: Validate the package**

Run: `python %USERPROFILE%\.codex\skills\.system\skill-creator\scripts\quick_validate.py %USERPROFILE%\.codex\skills\pdf-xray`

Expected: `Skill is valid!`.

### Task 4: Complete verification and forward test

**Files:**
- Test: `%USERPROFILE%\.codex\skills\pdf-xray\tests\test_audit_pdf.py`

- [ ] **Step 1: Run the full regression suite**

Run: `python -m pytest tests\\test_audit_pdf.py -q`

Expected: all tests pass; record any external PyMuPDF deprecation warnings separately.

- [ ] **Step 2: Run fast and auto acceptance checks**

Run:

```powershell
python scripts\\audit_pdf.py "<legacy-repo>\tmp\pdf-vector-raster-lab\transformer.pdf"
python scripts\\audit_pdf.py "<legacy-repo>\tmp\pdf-vector-raster-lab\scan.pdf" --mode fast
python scripts\\audit_pdf.py "<legacy-repo>\tmp\pdf-vector-raster-lab\unused-image.pdf" --mode deep --verbose
```

Expected: ordinary pages use fast output; structurally risky documents auto-escalate; explicit fast does not overclaim; deep verbose retains full evidence.
