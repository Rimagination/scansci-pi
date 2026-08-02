from __future__ import annotations

import argparse
import base64
import csv
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright

from scansci_html.cleaner import CleanHtmlRenderer
from scansci_html.service import _output_path


DEFAULT_CDP = "http://127.0.0.1:9224"
DEFAULT_INSTITUTION = "Tsinghua University"


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    doi_list = _read_dois(Path(args.input_file))
    selected = doi_list[args.start : args.start + args.limit if args.limit else None]
    if args.overwrite_jsonl and args.manifest_jsonl:
        Path(args.manifest_jsonl).unlink(missing_ok=True)

    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        if not browser.contexts:
            raise RuntimeError("No live browser context is exposed by the CDP endpoint.")
        context = browser.contexts[0]
        for index, doi in enumerate(selected, start=args.start + 1):
            result = _capture_one(
                context,
                doi,
                output_dir=output_dir,
                institution=args.institution,
                min_text_length=args.min_text_length,
            )
            result["index"] = index
            results.append(result)
            _append_jsonl(Path(args.manifest_jsonl), result) if args.manifest_jsonl else None
            print(json.dumps(_progress_payload(result), ensure_ascii=False), flush=True)

    if args.manifest_json:
        _write_json_manifest(Path(args.manifest_json), output_dir=output_dir)
    if args.manifest_tsv:
        _write_tsv_manifest(Path(args.manifest_tsv), output_dir=output_dir)
    return 0 if all(row.get("status") == "success" for row in results) else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture Science article clean HTML after expanding all references."
    )
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cdp", default=DEFAULT_CDP)
    parser.add_argument("--institution", default=DEFAULT_INSTITUTION)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--manifest-jsonl", default="")
    parser.add_argument("--manifest-json", default="")
    parser.add_argument("--manifest-tsv", default="")
    parser.add_argument("--overwrite-jsonl", action="store_true")
    parser.add_argument("--min-text-length", type=int, default=1000)
    return parser.parse_args()


def _read_dois(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _capture_one(
    context: object,
    doi: str,
    *,
    output_dir: Path,
    institution: str,
    min_text_length: int,
) -> dict[str, object]:
    url = f"https://www.science.org/doi/{doi}"
    page, created_page = _page_for_doi(context, doi)
    errors: list[str] = []
    try:
        _navigate(page, url, errors)
        state = _ensure_science_access(page, doi, institution=institution, errors=errors)
        if not state.get("has_fulltext"):
            return _failed_result(doi, state, errors)

        _load_lazy_content(page)
        reference_expand_clicks = _expand_science_references(page)
        page_reference_state = _reference_state(page)
        if int(page_reference_state.get("hidden", 0)) > 0:
            _force_unhide_bibliography(page)
            page_reference_state = _reference_state(page)
        _load_lazy_content(page)

        html = page.content()
        document = CleanHtmlRenderer(min_text_length=min_text_length).render(
            html,
            source_url=page.url,
            doi=doi,
        )
        soup = BeautifulSoup(document.html, "lxml")
        _ensure_h1(soup, document.title)
        _remove_eletters_and_recommendations(soup)
        local_image_count, missing_images = _localize_images(soup, page, output_dir, doi, document.title)

        reference_count = _clean_reference_count(soup)
        if reference_count < int(page_reference_state.get("total", 0)):
            errors.append(
                f"clean reference count {reference_count} is lower than page reference count "
                f"{page_reference_state.get('total')}"
            )
        gate_reason = _gate_reason_from_clean_html(soup)
        if gate_reason:
            errors.append(gate_reason)
        if not document.has_fulltext:
            errors.extend(document.warnings)

        output_path = _output_path(output_dir, doi, document.title)
        output_path.write_text(str(soup), encoding="utf-8")
        status = "success" if not errors else "failed"
        return {
            "doi": doi,
            "status": status,
            "path": str(output_path) if status == "success" else str(output_path),
            "title": document.title,
            "final_url": page.url,
            "text_length": document.text_length,
            "reference_count": reference_count,
            "page_reference_count": page_reference_state.get("total", 0),
            "hidden_reference_count": page_reference_state.get("hidden", 0),
            "reference_expand_clicks": reference_expand_clicks,
            "image_count": len(soup.find_all("img")),
            "local_image_count": local_image_count,
            "missing_local_images": missing_images,
            "warnings": document.warnings,
            "errors": errors,
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        state = _inspect_science_page(page)
        return _failed_result(doi, state, errors)
    finally:
        if created_page:
            try:
                page.close()
            except Exception:
                pass


def _page_for_doi(context: object, doi: str) -> tuple[object, bool]:
    for page in getattr(context, "pages", []):
        try:
            if doi in str(page.url):
                return page, False
        except Exception:
            continue
    return context.new_page(), True


def _navigate(page: object, url: str, errors: list[str]) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    except Exception as exc:
        # Science sometimes closes the navigation stream after the document has
        # already committed. Continue and inspect the DOM before treating it as a failure.
        errors.append(f"navigation warning: {type(exc).__name__}: {exc}")
    _settle(page, milliseconds=1_500)


def _ensure_science_access(
    page: object,
    doi: str,
    *,
    institution: str,
    errors: list[str],
) -> dict[str, object]:
    article_url = f"https://www.science.org/doi/{doi}"
    returned_from_individual_login = False
    wait_page_reloads = 0
    for _attempt in range(8):
        state = _inspect_science_page(page)
        if state.get("has_fulltext"):
            return state
        if state.get("is_wait_page"):
            _settle(page, milliseconds=4_000)
            if wait_page_reloads < 2:
                wait_page_reloads += 1
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60_000)
                except Exception as exc:
                    errors.append(f"wait-page reload warning: {type(exc).__name__}: {exc}")
                _settle(page, milliseconds=2_000)
            continue
        if state.get("is_tsinghua_login"):
            errors.append("Tsinghua human login page is open; waiting for manual credentials is required.")
            return state
        if state.get("is_aaas_individual_login"):
            errors.append("AAAS individual login appeared; returned to the article instead.")
            if returned_from_individual_login:
                return state
            returned_from_individual_login = True
            _navigate(page, article_url, errors)
            continue
        if _click_by_text(page, [r"^\s*check access\s*$", r"^\s*access the full article\s*$"]):
            _settle(page)
            continue
        if _click_by_text(
            page,
            [
                r"access through your institution",
                r"access content through your institution",
                r"institutional access",
                r"sign in through your institution",
                r"log in through your institution",
            ],
            deny=[r"^\s*log in\s*$", r"create an account", r"aaas id"],
        ):
            _settle(page)
            continue
        if state.get("is_institution_picker"):
            _select_institution(page, institution)
            _settle(page, milliseconds=2_000)
            continue
        if _click_by_text(page, [r"action/ssostart", r"openathens", r"shibboleth"]):
            _settle(page)
            continue
        errors.append(_access_failure_reason(state))
        return state
    state = _inspect_science_page(page)
    if not state.get("has_fulltext"):
        errors.append(_access_failure_reason(state))
    return state


def _inspect_science_page(page: object) -> dict[str, object]:
    return page.evaluate(
        r"""
        () => {
          const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim();
          const lower = text.toLowerCase();
          const controls = [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')]
            .map(el => [el.innerText || '', el.textContent || '', el.value || '', el.getAttribute('aria-label') || '', el.getAttribute('title') || ''].join(' ').replace(/\s+/g, ' ').trim())
            .filter(Boolean);
          const exact = (want) => controls.some(text => text.toLowerCase() === want);
          const root = document.querySelector('#bodymatter') || document.querySelector('article') || document.body;
          const bodyTextLength = root ? (root.innerText || root.textContent || '').replace(/\s+/g, ' ').trim().length : 0;
          const refRoot = document.querySelector('#bibliography') || document;
          const refIds = [...refRoot.querySelectorAll('[id]')].map(el => el.id).filter(id => /^R\d+$/.test(id));
          const hasGate = exact('check access') || lower.includes('access the full article');
          const isAAASLogin = location.href.includes('identity.aaas.org/u/login/identifier');
          const isTsinghuaLogin = lower.includes('清华大学用户电子身份服务系统') || lower.includes('清华大学联邦认证系统');
          const isInstitutionPicker = lower.includes('access content through your institution') ||
            lower.includes('find your institution') ||
            lower.includes('type the name of your institution');
          const isWaitPage = /请稍候|please wait|just a moment/i.test(document.title) ||
            /请稍候|please wait|just a moment/i.test(text.slice(0, 1000));
          return {
            url: location.href,
            title: document.title,
            text_length: text.length,
            body_text_length: bodyTextLength,
            has_check_access: exact('check access'),
            has_access_full_article: lower.includes('access the full article'),
            is_aaas_individual_login: isAAASLogin,
            is_tsinghua_login: isTsinghuaLogin,
            is_institution_picker: isInstitutionPicker,
            is_wait_page: isWaitPage,
            reference_count: Array.from(new Set(refIds)).length,
            has_fulltext: !isAAASLogin && !isTsinghuaLogin && !isInstitutionPicker && !hasGate && bodyTextLength >= 6000,
          };
        }
        """
    )


def _click_by_text(page: object, patterns: list[str], deny: list[str] | None = None) -> bool:
    return bool(
        page.evaluate(
            r"""
            ({patterns, deny}) => {
              const regs = patterns.map(pattern => new RegExp(pattern, 'i'));
              const denyRegs = (deny || []).map(pattern => new RegExp(pattern, 'i'));
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                  style.visibility !== 'hidden' && style.display !== 'none' &&
                  Number(style.opacity || 1) > 0.01;
              };
              const textOf = (el) => [
                el.innerText || '',
                el.textContent || '',
                el.value || '',
                el.getAttribute('aria-label') || '',
                el.getAttribute('title') || '',
                el.getAttribute('href') || ''
              ].join(' ').replace(/\s+/g, ' ').trim();
              for (const el of [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')]) {
                if (!visible(el)) continue;
                const text = textOf(el);
                if (denyRegs.some(reg => reg.test(text))) continue;
                if (regs.some(reg => reg.test(text))) {
                  el.scrollIntoView({block: 'center', inline: 'center'});
                  el.click();
                  return true;
                }
              }
              return false;
            }
            """,
            {"patterns": patterns, "deny": deny or []},
        )
    )


def _select_institution(page: object, institution: str) -> None:
    page.evaluate(
        r"""
        ({institution}) => {
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 &&
              style.visibility !== 'hidden' && style.display !== 'none';
          };
          const input = [...document.querySelectorAll('input,[role="combobox"]')]
            .find(el => visible(el) && !/password/i.test(el.getAttribute('type') || ''));
          if (input) {
            input.focus();
            if ('value' in input) input.value = '';
            input.dispatchEvent(new Event('input', {bubbles: true}));
          }
        }
        """,
        {"institution": institution},
    )
    try:
        page.keyboard.type(institution, delay=20)
    except Exception:
        return
    page.wait_for_timeout(900)
    clicked = page.evaluate(
        r"""
        ({institution}) => {
          const needle = institution.toLowerCase();
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 &&
              style.visibility !== 'hidden' && style.display !== 'none';
          };
          for (const el of [...document.querySelectorAll('a,button,[role="button"],[role="option"],li,div')]) {
            if (!visible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (!text.includes(needle)) continue;
            const target = el.closest('a,button,[role="button"],[role="option"]') || el;
            target.click();
            return true;
          }
          return false;
        }
        """,
        {"institution": institution},
    )
    if not clicked:
        page.keyboard.press("Enter")


def _load_lazy_content(page: object) -> None:
    page.evaluate(
        r"""
        async () => {
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          for (const img of [...document.images]) {
            img.loading = 'eager';
            const dataSrc = img.getAttribute('data-src') || img.getAttribute('data-original');
            if (dataSrc && !img.getAttribute('src')) img.setAttribute('src', dataSrc);
          }
          const height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
          const step = Math.max(600, Math.floor(window.innerHeight * 0.8));
          for (let y = 0; y <= height; y += step) {
            window.scrollTo(0, y);
            await sleep(120);
          }
          window.scrollTo(0, 0);
          await sleep(250);
        }
        """
    )
    _settle(page, milliseconds=600)


def _expand_science_references(page: object) -> int:
    page.evaluate(
        r"""
        () => {
          const root = document.querySelector('#bibliography') ||
            [...document.querySelectorAll('section,div')].find(el => /references and notes/i.test((el.querySelector('h2,h3') || {}).innerText || ''));
          if (root) root.scrollIntoView({block: 'center'});
        }
        """
    )
    page.wait_for_timeout(400)
    clicks = 0
    for _ in range(12):
        clicked = page.evaluate(
            r"""
            () => {
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                  style.visibility !== 'hidden' && style.display !== 'none' &&
                  Number(style.opacity || 1) > 0.01;
              };
              const textOf = (el) => [
                el.innerText || '',
                el.textContent || '',
                el.value || '',
                el.getAttribute('aria-label') || '',
                el.getAttribute('title') || ''
              ].join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
              const isExpander = (text) => {
                if (text.includes('go to reference')) return false;
                return /(^|\b)(show|see)\s+all\s+references(\b|$)/.test(text) ||
                  /(^|\b)(show|see)\s+more\s+references(\b|$)/.test(text);
              };
              const seen = new Set();
              for (const root of [document.querySelector('#bibliography'), document].filter(Boolean)) {
                for (const el of [...root.querySelectorAll('button,a,[role="button"],input[type="button"],input[type="submit"]')]) {
                  if (seen.has(el)) continue;
                  seen.add(el);
                  if (!visible(el)) continue;
                  if (!isExpander(textOf(el))) continue;
                  el.scrollIntoView({block: 'center', inline: 'center'});
                  el.click();
                  return true;
                }
              }
              return false;
            }
            """
        )
        if not clicked:
            return clicks
        clicks += 1
        _settle(page, milliseconds=1_200)
    return clicks


def _reference_state(page: object) -> dict[str, int]:
    return page.evaluate(
        r"""
        () => {
          const root = document.querySelector('#bibliography') || document;
          const refs = [...root.querySelectorAll('[id]')].filter(el => /^R\d+$/.test(el.id));
          const ids = new Set(refs.map(el => el.id));
          const hidden = refs.filter(el => !!el.closest('[hidden],[aria-hidden="true"]')).length;
          return {total: ids.size, hidden};
        }
        """
    )


def _force_unhide_bibliography(page: object) -> None:
    page.evaluate(
        r"""
        () => {
          const root = document.querySelector('#bibliography');
          if (!root) return;
          for (const el of [...root.querySelectorAll('[hidden]')]) {
            el.hidden = false;
            el.removeAttribute('hidden');
          }
          for (const el of [...root.querySelectorAll('[aria-hidden="true"]')]) {
            el.removeAttribute('aria-hidden');
          }
        }
        """
    )
    page.wait_for_timeout(300)


def _ensure_h1(soup: BeautifulSoup, title: str) -> None:
    article = soup.find("article")
    if not isinstance(article, Tag) or article.find("h1"):
        return
    heading = soup.new_tag("h1")
    heading.string = title
    article.insert(0, heading)


def _remove_eletters_and_recommendations(soup: BeautifulSoup) -> None:
    article = soup.find("article")
    if not isinstance(article, Tag):
        return
    marker = _first_backmatter_marker(article)
    if marker is None:
        return
    parent = marker.parent
    if not isinstance(parent, Tag):
        marker.decompose()
        return
    siblings = list(parent.contents)
    try:
        start = siblings.index(marker)
    except ValueError:
        marker.decompose()
        return
    for child in siblings[start:]:
        if isinstance(child, Tag):
            child.decompose()
        else:
            child.extract()


def _first_backmatter_marker(article: Tag) -> Tag | None:
    for tag in article.find_all(True):
        identity = " ".join(
            str(value)
            for value in [
                tag.get("id", ""),
                " ".join(tag.get("class", [])),
                tag.get("aria-label", ""),
            ]
        ).lower()
        heading = ""
        if tag.name in {"section", "div"}:
            header = tag.find(["h2", "h3"], recursive=False)
            heading = header.get_text(" ", strip=True).lower() if header else ""
        if "eletter" in identity or heading.startswith("eletters"):
            return tag
        if "trendmd" in identity or heading.startswith("recommended articles"):
            return tag
    return None


def _localize_images(
    soup: BeautifulSoup,
    page: object,
    output_dir: Path,
    doi: str,
    title: str,
) -> tuple[int, list[str]]:
    output_path = _output_path(output_dir, doi, title)
    files_dir = output_path.with_suffix("").parent / f"{output_path.stem}_files"
    local_count = 0
    missing: list[str] = []
    seen_urls: dict[str, str] = {}
    for index, img in enumerate(soup.find_all("img"), start=1):
        if not isinstance(img, Tag):
            continue
        src = str(img.get("src") or "").strip()
        if not src or src.startswith("data:") or not src.lower().startswith(("http://", "https://")):
            continue
        absolute = urljoin(str(page.url), src)
        if absolute in seen_urls:
            img["src"] = seen_urls[absolute]
            local_count += 1
            continue
        try:
            payload = _fetch_binary_as_base64(page, absolute)
            suffix = _suffix_for_image(absolute, str(payload.get("contentType") or ""))
            files_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{index:02d}_{_safe_filename(Path(urlparse(absolute).path).name or 'image')}"
            if not filename.lower().endswith(suffix):
                filename = f"{Path(filename).stem}{suffix}"
            target = files_dir / filename
            target.write_bytes(base64.b64decode(str(payload["data"])))
            relative = f"{files_dir.name}/{target.name}"
            img["src"] = relative
            seen_urls[absolute] = relative
            local_count += 1
        except Exception as exc:
            missing.append(f"{absolute} ({type(exc).__name__}: {exc})")
    return local_count, missing


def _fetch_binary_as_base64(page: object, url: str) -> dict[str, str]:
    return page.evaluate(
        r"""
        async ({url}) => {
          const response = await fetch(url, {credentials: 'include'});
          if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
          const blob = await response.blob();
          const bytes = new Uint8Array(await blob.arrayBuffer());
          let binary = '';
          const chunkSize = 0x8000;
          for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
          }
          return {contentType: blob.type || response.headers.get('content-type') || '', data: btoa(binary)};
        }
        """,
        {"url": url},
    )


def _suffix_for_image(url: str, content_type: str) -> str:
    suffix = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else ""
    if suffix:
        return ".jpg" if suffix == ".jpe" else suffix
    path_suffix = Path(urlparse(url).path).suffix.lower()
    return path_suffix if path_suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"} else ".img"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "image"


def _clean_reference_count(soup: BeautifulSoup) -> int:
    root = soup.select_one("#bibliography")
    if root is None:
        return 0
    return len({tag.get("id") for tag in root.select("[id]") if re.match(r"^R\d+$", tag.get("id", ""))})


def _gate_reason_from_clean_html(soup: BeautifulSoup) -> str:
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()
    gate_markers = (
        "check access",
        "access the full article",
        "access content through your institution",
        "aaas id (email address)",
    )
    return "access gate marker remains in cleaned HTML" if any(marker in text for marker in gate_markers) else ""


def _settle(page: object, *, milliseconds: int = 1_000) -> None:
    try:
        page.wait_for_timeout(milliseconds)
    except Exception:
        return
    try:
        page.wait_for_load_state("networkidle", timeout=6_000)
    except Exception:
        pass


def _failed_result(doi: str, state: dict[str, object], errors: list[str]) -> dict[str, object]:
    if not errors:
        errors = [_access_failure_reason(state)]
    return {
        "doi": doi,
        "status": "failed",
        "path": "",
        "title": state.get("title", ""),
        "final_url": state.get("url", ""),
        "text_length": state.get("text_length", 0),
        "reference_count": state.get("reference_count", 0),
        "page_reference_count": state.get("reference_count", 0),
        "hidden_reference_count": 0,
        "reference_expand_clicks": 0,
        "image_count": 0,
        "local_image_count": 0,
        "missing_local_images": [],
        "warnings": [],
        "errors": errors,
    }


def _access_failure_reason(state: dict[str, object]) -> str:
    if state.get("is_wait_page"):
        return "publisher wait/security transition page remained visible"
    if state.get("is_aaas_individual_login"):
        return "AAAS individual login page remained visible"
    if state.get("is_tsinghua_login"):
        return "Tsinghua human login page remained visible"
    if state.get("is_institution_picker"):
        return "institution picker remained visible"
    if state.get("has_check_access") or state.get("has_access_full_article"):
        return "Science access gate remained visible"
    return (
        f"full text was not detected "
        f"(body_text_length={state.get('body_text_length', 0)}, url={state.get('url', '')})"
    )


def _progress_payload(result: dict[str, object]) -> dict[str, object]:
    return {
        "index": result.get("index"),
        "doi": result.get("doi"),
        "status": result.get("status"),
        "title": result.get("title"),
        "reference_count": result.get("reference_count"),
        "page_reference_count": result.get("page_reference_count"),
        "local_image_count": result.get("local_image_count"),
        "errors": result.get("errors"),
    }


def _append_jsonl(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _manifest_rows(output_dir: Path) -> list[dict[str, object]]:
    jsonl_path = output_dir / "science-2026-clean-html-expandedrefs-results.jsonl"
    rows: list[dict[str, object]] = []
    if jsonl_path.exists():
        raw_rows = [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        deduped: dict[str, dict[str, object]] = {}
        for row in raw_rows:
            key = str(row.get("doi") or row.get("index") or len(deduped))
            deduped[key] = row
        rows = list(deduped.values())
    rows.sort(key=lambda row: int(row.get("index", 0)))
    return rows


def _write_json_manifest(path: Path, *, output_dir: Path) -> None:
    rows = _manifest_rows(output_dir)
    payload = {
        "total": len(rows),
        "success": sum(1 for row in rows if row.get("status") == "success"),
        "failed": sum(1 for row in rows if row.get("status") != "success"),
        "results": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_tsv_manifest(path: Path, *, output_dir: Path) -> None:
    rows = _manifest_rows(output_dir)
    fieldnames = [
        "index",
        "doi",
        "status",
        "title",
        "path",
        "final_url",
        "text_length",
        "reference_count",
        "page_reference_count",
        "hidden_reference_count",
        "reference_expand_clicks",
        "image_count",
        "local_image_count",
        "errors",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), ensure_ascii=False)
                    if key == "errors"
                    else row.get(key, "")
                    for key in fieldnames
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
