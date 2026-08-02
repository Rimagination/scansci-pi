# PDF X-Ray Lightweight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace document-wide auto escalation with page-scoped deep escalation and add a fast vector-graphic presence goal.

**Architecture:** Preserve the existing `audit_pdf(source, region)` deep API. Extract a private deep page-subset runner, merge it with existing fast pages in `auto`, and add a fast-only `vector-presence` report that stops on qualified drawing evidence. Keep CLI compaction as the final presentation step.

**Tech Stack:** Python 3, pypdf, PyMuPDF, pytest.

---

### Task 1: Deep-audit only selected auto pages

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\scripts\audit_pdf.py`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\tests\test_audit_pdf.py`

- [ ] **Step 1: Write failing merge behavior test**

```python
def test_auto_deep_audits_only_risky_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "simple-and-clipped.pdf"
    write_simple_then_clipped_pdf(pdf)
    report = run_tiered_cli(pdf)
    assert report["analysis_mode"] == "hybrid"
    assert report["deep_pages"] == [2]
    assert report["pages"][0]["analysis_mode"] == "fast"
    assert report["pages"][1]["analysis_mode"] == "deep"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "auto_deep_audits_only_risky_pages" -q`

Expected: FAIL because current auto escalates the whole document.

- [ ] **Step 3: Implement selected deep runner and merge**

Extract the existing `audit_pdf` loop into a private runner accepting a one-based page-number set. Keep public `audit_pdf` calling it with all pages. In auto mode, pass only pages where fast result has risk signals, low confidence, or `deep_audit`; merge deep pages and safe fast pages by page number. Attach top-level `deep_pages`, page-level `analysis_mode`, and page-local escalation reasons.

- [ ] **Step 4: Verify GREEN and deep compatibility**

Run: `python -m pytest tests\\test_audit_pdf.py -k "auto_deep_audits_only_risky_pages or classifies_a_displayed_image" -q`

Expected: PASS.

### Task 2: Add the vector-presence fast goal

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\scripts\audit_pdf.py`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\tests\test_audit_pdf.py`

- [ ] **Step 1: Write failing goal tests**

```python
def test_vector_presence_confirms_safe_graphic_page(tmp_path: Path) -> None:
    pdf = tmp_path / "vector.pdf"
    write_pdf(pdf, "vector-form")
    report = run_tiered_cli(pdf, "--goal", "vector-presence")
    assert report["vector_presence"]["status"] == "confirmed"
    assert report["vector_presence"]["page"] == 1

def test_vector_presence_returns_candidate_without_deep_audit_for_risky_page(tmp_path: Path) -> None:
    pdf = tmp_path / "risky-vector.pdf"
    write_clipped_vector_graphic_pdf(pdf)
    report = run_tiered_cli(pdf, "--goal", "vector-presence")
    assert report["vector_presence"]["status"] == "candidate"
    assert report["vector_presence"]["recommendation"] == "render_review"
    assert report["analysis_mode"] == "fast"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests\\test_audit_pdf.py -k "vector_presence" -q`

Expected: FAIL because the CLI has no `--goal` argument.

- [ ] **Step 3: Implement graphic-like drawing qualification**

Add `vector_graphic_candidate(page_report, rendered_page)` that accepts a page only when fast drawing geometry has at least three boxes or one box with area at least 1% of displayed page area. Add `vector_presence_report()` that scans pages in order, stops after the first candidate, returns `confirmed` on a risk-free page and `candidate` plus risk warnings on a risky page; return `not_found` only after scanning every page.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests\\test_audit_pdf.py -k "vector_presence" -q`

Expected: PASS.

### Task 3: Document the fast intent and validate

**Files:**
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\SKILL.md`
- Modify: `%USERPROFILE%\.codex\skills\pdf-xray\agents\openai.yaml`

- [ ] **Step 1: Update instructions**

Document `--goal vector-presence` as the required first command for questions asking whether a PDF has vector graphics. Explain `confirmed`, `candidate`, and `not_found`; require deep or render review before claiming candidate figures are extractable/editable. Explain page-scoped auto escalation and `deep_pages`.

- [ ] **Step 2: Regenerate UI metadata**

Run:

```powershell
python %USERPROFILE%\.codex\skills\.system\skill-creator\scripts\generate_openai_yaml.py %USERPROFILE%\.codex\skills\pdf-xray --interface display_name="PDF X-Ray" --interface short_description="Fast PDF vector and raster evidence" --interface default_prompt="Use $pdf-xray to quickly check this PDF for vector graphics, then deepen only if needed."
```

- [ ] **Step 3: Verify all behavior**

Run:

```powershell
python -m pytest tests\\test_audit_pdf.py -q
python %USERPROFILE%\.codex\skills\.system\skill-creator\scripts\quick_validate.py %USERPROFILE%\.codex\skills\pdf-xray
```

Expected: all tests pass and `Skill is valid!`.
