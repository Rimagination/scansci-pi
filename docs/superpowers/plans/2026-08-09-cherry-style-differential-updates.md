# Cherry-Style Differential Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Cherry Studio/Electron Updater-style blockmap differential downloads to the ScanSci Windows desktop updater while retaining a verified full-package fallback.

**Architecture:** Publish the existing complete ZIP plus a small JSON blockmap containing fixed-size SHA256 blocks. Keep the last downloaded complete package and its blockmap in the per-version update cache. When the current cached package matches the installed version, compare old and new blockmaps, copy unchanged ranges locally, and download only changed ranges from the complete package URL; if range support, metadata, base package, or final hash validation fails, download the complete ZIP. Continue using the existing staged PowerShell replacement and versioned runtime components.

**Tech Stack:** Python 3, `urllib.request`, SHA256, JSON blockmaps, PowerShell `Compress-Archive`, pytest, Windows HTTP Range requests.

---

### Task 1: Define blockmap format and differential plan

**Files:**
- Create: `src/scansci_html/update_blockmap.py`
- Test: `tests/test_update_blockmap.py`

- [x] **Step 1: Write failing tests** for deterministic blockmap generation, unchanged block copying, changed block planning, malformed metadata rejection, and a full-download decision when the base file is unavailable.

- [x] **Step 2: Run the focused tests** with `python -m pytest tests/test_update_blockmap.py -q` and verify they fail because the module does not exist.

- [x] **Step 3: Implement the minimal blockmap module** with a versioned JSON shape containing `schema_version`, `algorithm`, `block_size`, `size`, `sha256`, and ordered block hashes; add helpers to load/validate maps and produce copy/download operations.

- [x] **Step 4: Run the focused tests** and verify all blockmap tests pass.

### Task 2: Implement Range-based differential download with fallback

**Files:**
- Modify: `src/scansci_html/update_blockmap.py`
- Test: `tests/test_update_blockmap.py`

- [x] **Step 1: Add failing tests** using a local HTTP server that records `Range` headers, proving unchanged ranges are copied from the old package and changed ranges are requested from the new package URL.

- [x] **Step 2: Run the new focused tests** and verify they fail because the downloader is not implemented.

- [x] **Step 3: Implement coalesced changed-range requests**, requiring HTTP 206 and exact byte counts, writing to a temporary destination, and validating the target SHA256 and size before replacing the destination.

- [x] **Step 4: Add tests for server-without-Range and bad final hash** and make both paths return a clear full-download-required result without leaving a corrupt output file.

- [x] **Step 5: Run `python -m pytest tests/test_update_blockmap.py -q`** and verify the complete blockmap suite passes.

### Task 3: Integrate the updater cache and manifest selection

**Files:**
- Modify: `src/scansci_html/app_update.py`
- Modify: `tests/test_app_update.py`

- [x] **Step 1: Write failing tests** for a manifest containing `windows.blockmap`, status reporting of `update_mode` and `download_size`, use of the cached previous package, and full fallback when no matching base package exists.

- [x] **Step 2: Run the focused tests** with `python -m pytest tests/test_app_update.py -q` and verify the new assertions fail.

- [x] **Step 3: Extend manifest parsing** to accept the existing `windows.url`/`sha256` fields plus an optional `windows.blockmap` object with URL, SHA256, size, and block size; keep old manifests fully compatible.

- [x] **Step 4: Update installation preparation** to download and verify the blockmap, locate a cached package for `current_version`, attempt differential reconstruction, and fall back to downloading the full package if any precondition fails.

- [x] **Step 5: Preserve cache provenance** by writing the downloaded target archive and verified blockmap under the target version directory; the versioned directory itself identifies the installed base package for the next update.

- [x] **Step 6: Run `python -m pytest tests/test_app_update.py -q`** and verify all updater tests pass.

### Task 4: Publish blockmaps from the Windows release script

**Files:**
- Modify: `scripts/package_desktop_release.ps1`
- Modify: `tests/test_package_desktop_release.py`

- [x] **Step 1: Add a failing release test** that runs the packaging script and asserts the output directory contains `ScanSci-<version>-windows-x64.zip.blockmap`, and that `stable.json` includes the blockmap URL, SHA256, size, and block size.

- [x] **Step 2: Run `python -m pytest tests/test_package_desktop_release.py -q`** and verify the blockmap assertions fail.

- [x] **Step 3: Generate a deterministic JSON blockmap in PowerShell** after the ZIP is created, using the same block size and SHA256 algorithm as the Python downloader; add an optional `-BlockmapUrl` parameter while defaulting to `<PackageUrl>.blockmap`.

- [x] **Step 4: Add blockmap metadata to `stable.json`** while preserving the existing runtime component contract and full package fields.

- [x] **Step 5: Run the packaging test** and verify it passes.

### Task 5: Harden staged installation, documentation, and compatibility

**Files:**
- Modify: `src/scansci_html/app_update.py`
- Modify: `docs/desktop-packaging.zh.md`
- Modify: `README.md`
- Modify: `tests/test_app_update.py`

- [x] **Step 1: Add failing tests** for old manifests without blockmaps, target archive traversal validation, and preservation of the existing restart/rollback behavior.

- [x] **Step 2: Keep full ZIP as the unconditional fallback** for first install, missing cache, Range failure, blockmap mismatch, and final archive hash mismatch.

- [x] **Step 3: Document the user-visible behavior**: ordinary adjacent updates may download only changed blocks, new installations and fallback updates download the complete package, and model/runtime components remain independently versioned.

- [x] **Step 4: Run focused regression tests** covering app update, packaging, build profiles, runtime components, and existing model download behavior.

### Task 6: Final verification

**Files:**
- Verify: `src/scansci_html/update_blockmap.py`
- Verify: `src/scansci_html/app_update.py`
- Verify: `scripts/package_desktop_release.ps1`
- Verify: `tests/test_update_blockmap.py`
- Verify: `tests/test_app_update.py`
- Verify: `tests/test_package_desktop_release.py`

- [x] **Step 1: Run `git diff --check`** and confirm no whitespace errors.

- [x] **Step 2: Run the targeted pytest groups** and confirm they pass without warnings caused by this feature.

- [x] **Step 3: Run the packaging script test on Windows PowerShell** and inspect the generated ZIP, blockmap, and `stable.json` as a three-artifact set.

- [x] **Step 4: Report the exact behavior and any limitation**, especially that differential savings depend on the new ZIP retaining unchanged byte ranges and that full fallback remains supported.
