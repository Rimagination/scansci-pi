from __future__ import annotations

from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .access_flow import AccessEvidence, AccessState, AccessStateMachine
from .browser_runtime import (
    BrowserSession,
    BrowserSessionBroker,
    CloakBrowserRuntime,
    PlaywrightBrowserRuntime,
)
from .models import FetchResponse
from .publisher_recipes import PublisherRecipeRegistry


class BrowserFetcher:
    """Visible isolated browser fetcher for legally authorized sessions.

    The fetcher only opens the article page and reads the rendered DOM. It does
    not click PDF links, save downloads, or bypass publisher/institution checks.
    It prefers CloakBrowser when available and falls back to bundled Playwright
    Chromium. The profile directory is persistent and separate from daily Chrome.
    """

    def __init__(
        self,
        *,
        profile_dir: str | Path,
        headless: bool = False,
        timeout_ms: int = 120_000,
        wait_login_seconds: int = 0,
        institution_query: str = "",
        hold_on_auth: bool = False,
        keep_pages_open: bool = False,
        security_challenge_stale_seconds: int = 75,
        security_challenge_refresh_seconds: int = 20,
        science_sso_recover_seconds: int = 15,
        browser_proxy_url: str = "",
        browser_extension_dirs: str = "",
        browser_extensions_enabled: bool = True,
        runtime: object | None = None,
        recipe_registry: PublisherRecipeRegistry | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = bool(headless)
        self.timeout_ms = max(1_000, int(timeout_ms))
        self.wait_login_seconds = max(0, int(wait_login_seconds))
        self.institution_query = institution_query.strip()
        self.hold_on_auth = bool(hold_on_auth)
        self.keep_pages_open = bool(keep_pages_open)
        self.security_challenge_stale_seconds = max(5, int(security_challenge_stale_seconds))
        self.security_challenge_refresh_seconds = max(2, int(security_challenge_refresh_seconds))
        self.science_sso_recover_seconds = max(0, int(science_sso_recover_seconds))
        self.browser_proxy_url = str(browser_proxy_url or "").strip()
        self.browser_extension_dirs = str(browser_extension_dirs or "").strip()
        self.browser_extensions_enabled = bool(browser_extensions_enabled)
        self._login_wait_consumed = False
        self._broker = BrowserSessionBroker(runtime or _BrowserFetcherRuntime(self))
        self._recipe_registry = recipe_registry or PublisherRecipeRegistry()
        self.access_events: list[AccessEvidence] = []
        self._asset_page = None
        self._asset_page_source_url = ""

    def fetch(self, url: str) -> FetchResponse:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        browser_session, page = self._broker.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            with _suppress_timeout():
                page.wait_for_load_state("networkidle", timeout=10_000)
            advanced = self._advance_if_institutional_access_page(page)
            wait_login_seconds = self._consume_login_wait_seconds()
            if wait_login_seconds:
                if not advanced:
                    self._advance_to_login_entry(page)
                print(
                    "Browser mode is waiting so you can complete any legal institution login "
                    f"or publisher challenge ({wait_login_seconds}s maximum). It will continue "
                    "early if the article full text becomes readable.",
                    file=sys.stderr,
                )
                self._wait_for_manual_login(page, wait_login_seconds, requested_url=url)
            final_evidence = self._inspect_access(page, record=True)
            if self.hold_on_auth and _requires_human_auth(final_evidence):
                final_evidence = self._hold_for_auth_completion(page, final_evidence)
            capture_warnings = self._prepare_rendered_content_for_capture(page)
            return FetchResponse(
                url=url,
                final_url=page.url,
                html=page.content(),
                status_code=None,
                source=browser_session.source,
                warnings=_access_warnings(final_evidence) + list(capture_warnings),
            )
        finally:
            if not self.keep_pages_open:
                try:
                    page.close()
                except Exception:
                    pass

    def close(self) -> None:
        self._asset_page = None
        self._asset_page_source_url = ""
        self._broker.close()

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> object:
        browser_session = self._broker.get_session()
        request_context = getattr(browser_session.context, "request", None)
        get = getattr(request_context, "get", None)
        if not callable(get):
            raise RuntimeError("browser context does not expose a request API for assets")
        response = get(
            url,
            headers=headers,
            timeout=max(1, int(float(timeout) * 1000)),
        )
        return _BrowserAssetResponse(response)

    def capture_image_asset(
        self,
        url: str,
        *,
        output_path: str | Path,
        source_url: str,
        timeout: float,
    ) -> None:
        page = self._asset_capture_page(source_url)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        timeout_ms = max(1, int(float(timeout) * 1000))
        if self._screenshot_existing_page_image(page, url, output, timeout_ms=timeout_ms):
            return
        page.evaluate(
            """
            (url) => {
              document.documentElement.style.margin = '0';
              document.body.innerHTML = '';
              document.body.style.margin = '0';
              document.body.style.background = 'white';
              const img = document.createElement('img');
              img.id = 'scansci-asset-image';
              img.alt = '';
              img.decoding = 'sync';
              img.loading = 'eager';
              img.style.display = 'block';
              img.style.margin = '0';
              img.src = url;
              document.body.appendChild(img);
            }
            """,
            url,
        )
        page.wait_for_function(
            """
            () => {
              const img = document.getElementById('scansci-asset-image');
              return img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;
            }
            """,
            timeout=timeout_ms,
        )
        dimensions = page.evaluate(
            """
            () => {
              const img = document.getElementById('scansci-asset-image');
              return {width: img.naturalWidth, height: img.naturalHeight};
            }
            """
        )
        try:
            width = max(1, min(4096, int(dimensions.get("width", 1280))))
            height = max(1, min(4096, int(dimensions.get("height", 1024))))
            page.set_viewport_size({"width": width, "height": height})
        except Exception:
            pass
        page.locator("#scansci-asset-image").screenshot(path=str(output), timeout=timeout_ms)
        self._asset_page_source_url = ""

    def __enter__(self) -> "BrowserFetcher":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _consume_login_wait_seconds(self) -> int:
        if self._login_wait_consumed:
            return 0
        self._login_wait_consumed = True
        return self.wait_login_seconds

    def _asset_capture_page(self, source_url: str) -> object:
        page = self._asset_page
        if page is None:
            _browser_session, page = self._broker.new_page()
            self._asset_page = page
            self._asset_page_source_url = ""
        if source_url and source_url != self._asset_page_source_url:
            try:
                with _suppress_timeout():
                    page.goto(source_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception:
                pass
            with _suppress_timeout():
                page.wait_for_load_state("networkidle", timeout=5_000)
            self._asset_page_source_url = source_url
        return page

    def _screenshot_existing_page_image(
        self,
        page: object,
        url: str,
        output_path: Path,
        *,
        timeout_ms: int,
    ) -> bool:
        try:
            page.wait_for_function(
                """
                (url) => {
                  const images = [...document.images];
                  const img = images.find((candidate) =>
                    candidate.src === url ||
                    candidate.currentSrc === url ||
                    candidate.getAttribute('src') === url
                  );
                  return img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;
                }
                """,
                url,
                timeout=min(timeout_ms, 10_000),
            )
            handle = page.evaluate_handle(
                """
                (url) => [...document.images].find((candidate) =>
                  candidate.src === url ||
                  candidate.currentSrc === url ||
                  candidate.getAttribute('src') === url
                ) || null
                """,
                url,
            )
            element = handle.as_element()
            if element is None:
                return False
            element.scroll_into_view_if_needed(timeout=timeout_ms)
            element.screenshot(path=str(output_path), timeout=timeout_ms)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False

    def _advance_if_institutional_access_page(self, page: object) -> bool:
        evidence = self._inspect_access(page, record=True)
        if evidence.state == AccessState.FULLTEXT:
            return False
        if evidence.state not in {AccessState.ACCESS_ENTRY, AccessState.INSTITUTION_PICKER}:
            return False
        self._advance_to_login_entry(page)
        return True

    def _page_looks_like_institutional_access(self, page: object) -> bool:
        evidence = self._inspect_access(page)
        return evidence.state in {AccessState.ACCESS_ENTRY, AccessState.INSTITUTION_PICKER}

    def _wait_for_manual_login(self, page: object, seconds: int, *, requested_url: str = "") -> None:
        deadline = time.monotonic() + max(0, seconds)
        challenge_started_at: float | None = None
        challenge_last_reload_at = 0.0
        challenge_reload_count = 0
        challenge_stale_reported = False
        unchanged_access_entry_count = 0
        last_access_entry_signature: tuple[str, tuple[str, ...]] | None = None
        unchanged_access_entry_reported = False
        last_passive_advance_at = 0.0
        passive_advance_reported = False
        human_login_reported = False
        science_sso_started_at: float | None = None
        science_sso_recovered = False
        science_individual_login_reported = False
        while True:
            now = time.monotonic()
            evidence = self._inspect_access(page, record=True)
            if evidence.state == AccessState.FULLTEXT:
                return
            if self._page_is_science_individual_login(page):
                if not science_individual_login_reported:
                    science_individual_login_reported = True
                    print(
                        "AAAS individual-login page is open; returning to the article "
                        "instead of filling the AAAS ID form.",
                        file=sys.stderr,
                    )
                if requested_url:
                    self._navigate_page(page, requested_url)
                    challenge_started_at = None
                    unchanged_access_entry_count = 0
                    last_access_entry_signature = None
                    unchanged_access_entry_reported = False
                    self._small_wait(page)
                    continue
            elif self._page_is_science_sso_transition(page):
                if science_sso_started_at is None:
                    science_sso_started_at = now
                    print(
                        "Science SSO transition page is open; waiting for the publisher "
                        "redirect to return to the article.",
                        file=sys.stderr,
                    )
                if (
                    not science_sso_recovered
                    and now - science_sso_started_at >= self.science_sso_recover_seconds
                ):
                    science_sso_recovered = True
                    target_url = requested_url or self._science_sso_redirect_target(page)
                    if target_url:
                        print(
                            "Science SSO transition did not redirect automatically; "
                            "returning to the target article in the same browser session.",
                            file=sys.stderr,
                        )
                        self._navigate_page(page, target_url)
                        science_sso_started_at = None
                        continue
                challenge_started_at = None
                unchanged_access_entry_count = 0
                last_access_entry_signature = None
                unchanged_access_entry_reported = False
            elif evidence.state == AccessState.ACCESS_ENTRY:
                signature = (evidence.url, evidence.markers)
                if signature == last_access_entry_signature:
                    unchanged_access_entry_count += 1
                else:
                    unchanged_access_entry_count = 0
                    last_access_entry_signature = signature
                self._advance_to_login_entry(page)
                challenge_started_at = None
                if unchanged_access_entry_count >= 8 and not unchanged_access_entry_reported:
                    unchanged_access_entry_reported = True
                    print(
                        "Publisher access entry is still visible after repeated automated attempts. "
                        "Please use the visible browser to complete institution access or login; "
                        "the batch will not count this page as full text unless the article body appears.",
                        file=sys.stderr,
                    )
            elif evidence.state == AccessState.INSTITUTION_PICKER:
                self._advance_to_login_entry(page)
                challenge_started_at = None
                unchanged_access_entry_count = 0
                last_access_entry_signature = None
                unchanged_access_entry_reported = False
            elif evidence.state == AccessState.SECURITY_CHALLENGE:
                if challenge_started_at is None:
                    challenge_started_at = now
                    challenge_last_reload_at = now
                    challenge_stale_reported = False
                    print(
                        "Browser mode detected a publisher security challenge. "
                        "It will retry briefly and then keep the visible browser waiting for manual verification.",
                        file=sys.stderr,
                    )
                challenge_age = now - challenge_started_at
                reload_age = now - challenge_last_reload_at
                if challenge_reload_count < 2 and reload_age >= self.security_challenge_refresh_seconds:
                    challenge_reload_count += 1
                    challenge_last_reload_at = now
                    print(
                        f"Publisher security challenge is still present; reloading attempt "
                        f"{challenge_reload_count}/2.",
                        file=sys.stderr,
                    )
                    self._reload_page(page)
                if challenge_age >= self.security_challenge_stale_seconds and not challenge_stale_reported:
                    challenge_stale_reported = True
                    print(
                        "Publisher security challenge is still visible. Please complete any visible "
                        "publisher verification in the browser; the batch will keep waiting until "
                        "the configured login window expires or full text appears.",
                        file=sys.stderr,
                    )
            elif evidence.state == AccessState.HUMAN_LOGIN:
                if not human_login_reported:
                    human_login_reported = True
                    print(
                        "Institution login page detected. Please enter your personal account, "
                        "password, and any verification code manually in the visible browser.",
                        file=sys.stderr,
                    )
            else:
                science_sso_started_at = None
                if now - last_passive_advance_at >= 3:
                    last_passive_advance_at = now
                    if self._advance_to_login_entry(page) and not passive_advance_reported:
                        passive_advance_reported = True
                        print(
                            "Browser mode clicked a visible publisher access control while waiting "
                            "for full text or institution login.",
                            file=sys.stderr,
                        )
                challenge_started_at = None
                challenge_stale_reported = False
                unchanged_access_entry_count = 0
                last_access_entry_signature = None
                unchanged_access_entry_reported = False
            remaining_ms = int((deadline - now) * 1000)
            if remaining_ms <= 0:
                return
            self._small_wait(page, milliseconds=min(1_000, remaining_ms))

    def _hold_for_auth_completion(self, page: object, evidence: AccessEvidence) -> AccessEvidence:
        print(
            "Full text is still behind publisher or institution access. Keeping the visible "
            "browser session open so you can verify/login in the same CloakBrowser profile. "
            "The batch will continue only after the article body becomes readable.",
            file=sys.stderr,
        )
        last_signature: tuple[AccessState, str, tuple[str, ...]] | None = None
        last_advance_at = 0.0
        while True:
            if evidence.state == AccessState.FULLTEXT:
                return evidence
            signature = (evidence.state, evidence.url, evidence.markers)
            if signature != last_signature:
                last_signature = signature
                print(
                    f"Waiting for access completion; current browser state is {evidence.state.value}.",
                    file=sys.stderr,
                )
            now = time.monotonic()
            if evidence.state in {AccessState.ACCESS_ENTRY, AccessState.INSTITUTION_PICKER} and (
                now - last_advance_at >= 3
            ):
                last_advance_at = now
                self._advance_to_login_entry(page)
            self._small_wait(page, milliseconds=1_000)
            evidence = self._inspect_access(page, record=True)

    def _page_looks_like_accessible_article(self, page: object) -> bool:
        evidence = self._inspect_access(page)
        return evidence.state == AccessState.FULLTEXT

    def _prepare_rendered_content_for_capture(self, page: object) -> tuple[str, ...]:
        evidence = self._inspect_access(page)
        if evidence.state != AccessState.FULLTEXT:
            return ()
        recipe = self._recipe_registry.for_page(page)
        try:
            return tuple(recipe.prepare_fulltext_capture(page))
        except Exception as exc:
            return (f"browser capture preparation failed: {type(exc).__name__}: {exc}",)

    def _inspect_access(self, page: object, *, record: bool = False) -> AccessEvidence:
        recipe = self._recipe_registry.for_page(page)
        evidence = AccessStateMachine(recipe).inspect(page)
        if record:
            self._record_access_evidence(evidence)
        return evidence

    def _record_access_evidence(self, evidence: AccessEvidence) -> None:
        if not self.access_events or self.access_events[-1] != evidence:
            self.access_events.append(evidence)

    def _advance_to_login_entry(self, page: object) -> bool:
        advanced = False
        if self._page_is_science_individual_login(page):
            return False
        self._dismiss_cookie_banners(page)
        if self._click_institutional_access_entry(page):
            advanced = True
            self._settle_page(page)
            self._dismiss_cookie_banners(page)
        if self._page_looks_like_human_login(page):
            return advanced
        if self._select_institution(page):
            advanced = True
            self._settle_page(page)
            self._click_optional_continue(page)
            self._settle_page(page)
        return advanced

    def _page_looks_like_human_login(self, page: object) -> bool:
        if self._page_is_science_individual_login(page):
            return False
        evidence = self._inspect_access(page)
        return evidence.state == AccessState.HUMAN_LOGIN

    def _click_institutional_access_entry(self, page: object) -> bool:
        if self._page_is_science_sso_transition(page):
            return False
        if self._click_institutional_access_entry_by_dom(page):
            return True
        recipe = self._recipe_registry.for_page(page)
        for selector in recipe.access_entry_selectors():
            if self._click_visible(page, selector, timeout=500):
                return True
        return False

    def _page_is_science_sso_transition(self, page: object) -> bool:
        try:
            url = str(getattr(page, "url", "") or "").lower()
        except Exception:
            return False
        return "science.org/action/ssostart" in url

    def _page_is_science_individual_login(self, page: object) -> bool:
        try:
            url = str(getattr(page, "url", "") or "").lower()
        except Exception:
            return False
        return "identity.aaas.org/u/login/identifier" in url

    def _science_sso_redirect_target(self, page: object) -> str:
        try:
            current_url = str(getattr(page, "url", "") or "")
        except Exception:
            return ""
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        values = query.get("redirectUri") or query.get("redirectURI")
        if not values:
            return ""
        return urljoin("https://www.science.org", unquote(values[0]))

    def _select_institution(self, page: object) -> bool:
        if not self.institution_query:
            return False
        if self._page_looks_like_human_login(page):
            return False

        recipe = self._recipe_registry.for_page(page)
        for rule in recipe.institution_input_rules():
            if not recipe.should_try_institution_input(rule, page):
                continue
            selector = rule.selector
            locator = self._first_visible(page, selector, timeout=2_000)
            if locator is None:
                continue
            if self._locator_looks_like_site_search(locator):
                continue
            try:
                locator.fill(self.institution_query, timeout=5_000)
            except TypeError:
                locator.fill(self.institution_query)
            except Exception:
                continue
            self._small_wait(page)
            if self._click_visible(page, f"text={self.institution_query}", timeout=5_000):
                return True
            if self._click_institution_result_by_dom(page):
                return True
            self._press_enter(locator, page)
            return True
        return False

    def _locator_looks_like_site_search(self, locator: object) -> bool:
        try:
            return bool(
                locator.evaluate(
                    """
                    (el) => {
                      const text = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('name') || '',
                        el.getAttribute('id') || '',
                        el.closest('form')?.getAttribute('action') || ''
                      ].join(' ').replace(/\\s+/g, ' ').toLowerCase();
                      const formAction = (el.closest('form')?.getAttribute('action') || '').toLowerCase();
                      if (el.closest('header,nav,[role="search"]')) return true;
                      if (formAction.includes('dosearch')) return true;
                      if (text.includes('dosearch')) return true;
                      if (text.includes('allfield')) return true;
                      if (text.includes('search within')) return true;
                      if (text.includes('search') &&
                        !text.includes('institution') &&
                        !text.includes('organization') &&
                        !text.includes('university')) {
                        return true;
                      }
                      return false;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _press_enter(self, locator: object, page: object) -> bool:
        try:
            locator.press("Enter", timeout=5_000)
            return True
        except TypeError:
            locator.press("Enter")
            return True
        except Exception:
            try:
                page.keyboard.press("Enter")
                return True
            except Exception:
                return False

    def _click_optional_continue(self, page: object) -> bool:
        selectors = (
            "button:has-text('Continue')",
            "a:has-text('Continue')",
            "button:has-text('Submit and continue')",
            "button:has-text('Submit')",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
        )
        return any(self._click_visible(page, selector, timeout=1_500) for selector in selectors)

    def _dismiss_cookie_banners(self, page: object) -> None:
        selectors = (
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('Accept cookies')",
            "button:has-text('I agree')",
            "button:has-text('Continue without accepting')",
        )
        for selector in selectors:
            self._click_visible(page, selector, timeout=800)

    def _click_visible(self, page: object, selector: str, *, timeout: int = 1_500) -> bool:
        locator = self._first_visible(page, selector, timeout=timeout)
        if locator is None:
            return False
        try:
            locator.click(timeout=10_000, no_wait_after=True)
        except TypeError:
            locator.click()
        except Exception:
            try:
                locator.click(timeout=10_000, no_wait_after=True, force=True)
            except TypeError:
                locator.click()
            except Exception:
                return False
        return True

    def _first_visible(self, page: object, selector: str, *, timeout: int = 1_500):
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=timeout):
                return locator
        except TypeError:
            locator = page.locator(selector).first
            if locator.is_visible():
                return locator
        except Exception:
            return None
        return None

    def _settle_page(self, page: object) -> None:
        self._small_wait(page, milliseconds=1_500)
        with _suppress_timeout():
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        with _suppress_timeout():
            page.wait_for_load_state("networkidle", timeout=5_000)

    def _reload_page(self, page: object) -> None:
        try:
            with _suppress_timeout():
                page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception:
            return
        self._settle_page(page)

    def _navigate_page(self, page: object, url: str) -> None:
        try:
            with _suppress_timeout():
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception:
            return
        self._settle_page(page)

    def _small_wait(self, page: object, *, milliseconds: int = 1_000) -> None:
        try:
            page.wait_for_timeout(milliseconds)
        except Exception:
            pass

    def _click_institutional_access_entry_by_dom(self, page: object) -> bool:
        try:
            return bool(
                page.evaluate(
                    """
                    () => {
                      const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                          style.visibility !== 'hidden' && style.display !== 'none';
                      };
                      const textOf = (el) => [
                        el.innerText || '',
                        el.textContent || '',
                        el.value || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('title') || '',
                        el.getAttribute('href') || ''
                      ].join(' ').replace(/\\s+/g, ' ').trim().toLowerCase();
                      const institutionalMarkers = [
                        'loading institution options',
                        'click to choose manually',
                        'choose manually',
                        'institutional login',
                        'institutional access',
                        'institutional sign in',
                        'access through your institution',
                        'access through your organization',
                        'log in through your institution',
                        'sign in through your institution',
                        'institutional-login',
                        'openathens',
                        'shibboleth',
                        'wayf'
                      ];
                      const entryMarkers = [
                        'access the full article',
                        'read the full text',
                        'check access',
                        'institutional access',
                        'institutional sign in',
                        'institutional login',
                        'institutional-login',
                        'openathens',
                        'shibboleth',
                        'wayf'
                      ];
                      const directHrefMarkers = [
                        '/action/ssostart',
                        'action/ssostart',
                        'openathens',
                        'shibboleth'
                      ];
                      const clickable = 'a,button,[role="button"],input[type="button"],input[type="submit"]';
                      for (const el of [...document.querySelectorAll(clickable)]) {
                        if (!visible(el)) continue;
                        const haystack = textOf(el);
                        if (institutionalMarkers.some((marker) => haystack.includes(marker))) {
                          el.scrollIntoView({block: 'center', inline: 'center'});
                          el.click();
                          return true;
                        }
                      }
                      for (const el of [...document.querySelectorAll(clickable)]) {
                        if (!visible(el)) continue;
                        const haystack = textOf(el);
                        if (entryMarkers.some((marker) => haystack.includes(marker))) {
                          el.scrollIntoView({block: 'center', inline: 'center'});
                          el.click();
                          return true;
                        }
                      }
                      for (const el of [...document.querySelectorAll('a[href]')]) {
                        if (!visible(el)) continue;
                        const href = (el.getAttribute('href') || '').toLowerCase();
                        if (directHrefMarkers.some((marker) => href.includes(marker))) {
                          el.scrollIntoView({block: 'center', inline: 'center'});
                          el.click();
                          return true;
                        }
                      }
                      return false;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _click_institution_result_by_dom(self, page: object) -> bool:
        if not self.institution_query:
            return False
        try:
            return bool(
                page.evaluate(
                    """
                    (query) => {
                      const needle = query.toLowerCase();
                      const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                          style.visibility !== 'hidden' && style.display !== 'none';
                      };
                      const clickable = 'a,button,[role="button"],[role="option"],li,div';
                      for (const el of [...document.querySelectorAll(clickable)]) {
                        if (!visible(el)) continue;
                        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        if (text && text.includes(needle)) {
                          const target = el.closest('a,button,[role="button"],[role="option"]') || el;
                          target.click();
                          return true;
                        }
                      }
                      return false;
                    }
                    """,
                    self.institution_query,
                )
            )
        except Exception:
            return False

    def _launch_session(self) -> "BrowserSession":
        try:
            return self._launch_cloakbrowser_context()
        except ImportError:
            return self._launch_playwright_context()

    def _launch_cloakbrowser_context(self) -> "BrowserSession":
        return CloakBrowserRuntime(
            profile_dir=self.profile_dir,
            headless=self.headless,
            browser_proxy_url=self.browser_proxy_url,
            browser_extension_dirs=self.browser_extension_dirs,
            browser_extensions_enabled=self.browser_extensions_enabled,
            institution=self.institution_query,
        ).launch()

    def _launch_playwright_context(self) -> "BrowserSession":
        return PlaywrightBrowserRuntime(profile_dir=self.profile_dir, headless=self.headless).launch()


class _BrowserFetcherRuntime:
    def __init__(self, fetcher: BrowserFetcher) -> None:
        self.fetcher = fetcher

    def launch(self) -> BrowserSession:
        return self.fetcher._launch_session()


_BrowserSession = BrowserSession


class _BrowserAssetResponse:
    def __init__(self, response: object) -> None:
        self._response = response
        self.status_code = int(getattr(response, "status", 0) or 0)
        self.headers = dict(getattr(response, "headers", {}) or {})

    @property
    def content(self) -> bytes:
        body = getattr(self._response, "body", None)
        if callable(body):
            return bytes(body() or b"")
        return bytes(body or b"")

    def raise_for_status(self) -> None:
        ok = getattr(self._response, "ok", None)
        if ok is True:
            return
        if ok is False or self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _access_warnings(evidence: AccessEvidence) -> list[str]:
    warnings = [f"browser access state: {evidence.state.value}"]
    warnings.extend(f"browser access marker: {marker}" for marker in evidence.markers)
    if evidence.url:
        warnings.append(f"browser final url: {evidence.url}")
    return warnings


def _requires_human_auth(evidence: AccessEvidence) -> bool:
    return evidence.state in {
        AccessState.ACCESS_ENTRY,
        AccessState.INSTITUTION_PICKER,
        AccessState.HUMAN_LOGIN,
        AccessState.SECURITY_CHALLENGE,
    }


class _suppress_timeout:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            return False
        return "TimeoutError" in getattr(exc_type, "__name__", "")
