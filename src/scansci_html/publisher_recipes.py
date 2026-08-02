from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .access_flow import AccessEvidence, AccessState


@dataclass(frozen=True)
class InstitutionInputRule:
    selector: str
    requires_picker_context: bool = False


class GenericRecipe:
    name = "generic"

    def matches(self, url: str, html: str = "") -> bool:
        return True

    def inspect(self, page: object) -> AccessEvidence:
        url = _page_url(page)
        html = _page_html(page)
        text = html_to_text(html).lower()
        markers: list[str] = []

        if looks_like_security_challenge(text):
            markers.append("security-challenge")
            return AccessEvidence(AccessState.SECURITY_CHALLENGE, url, tuple(markers))
        if looks_like_fulltext(html, text):
            markers.append("article-fulltext")
            return AccessEvidence(AccessState.FULLTEXT, url, tuple(markers))
        if looks_like_subscription_preview(text):
            markers.append("subscription-preview")
            return AccessEvidence(AccessState.SUBSCRIPTION_PREVIEW, url, tuple(markers))
        if looks_like_institution_picker(url, text):
            markers.append("institution-picker")
            return AccessEvidence(AccessState.INSTITUTION_PICKER, url, tuple(markers))
        if looks_like_access_entry(text):
            markers.append("access-entry")
            return AccessEvidence(AccessState.ACCESS_ENTRY, url, tuple(markers))
        if looks_like_human_login(url, html, text):
            markers.append("human-login")
            return AccessEvidence(AccessState.HUMAN_LOGIN, url, tuple(markers))
        return AccessEvidence(AccessState.ARTICLE_PAGE if url else AccessState.UNKNOWN, url, ())

    def access_entry_selectors(self) -> tuple[str, ...]:
        return (
            "a:has-text('Access through your institution')",
            "button:has-text('Access through your institution')",
            "[role='button']:has-text('Access through your institution')",
            "a:has-text('Access through your organization')",
            "button:has-text('Access through your organization')",
            "[role='button']:has-text('Access through your organization')",
            "a:has-text('Institutional access')",
            "button:has-text('Institutional access')",
            "a:has-text('Institutional Access')",
            "button:has-text('Institutional Access')",
            "a:has-text('Institutional Sign In')",
            "button:has-text('Institutional Sign In')",
            "a:has-text('Loading institution options')",
            "button:has-text('Loading institution options')",
            "a:has-text('choose manually')",
            "button:has-text('choose manually')",
            "a:has-text('Log in through your institution')",
            "button:has-text('Log in through your institution')",
            "a:has-text('Sign in through your institution')",
            "button:has-text('Sign in through your institution')",
            "a:has-text('Access the full article')",
            "button:has-text('Access the full article')",
            "[role='button']:has-text('Access the full article')",
            "a:has-text('Read the full text')",
            "button:has-text('Read the full text')",
            "[role='button']:has-text('Read the full text')",
            "a:has-text('Check Access')",
            "button:has-text('Check Access')",
            "[role='button']:has-text('Check Access')",
            "a[href*='/action/ssostart']",
            "a[href*='action/ssostart']",
            "a[href*='institutional-login']",
            "a[href*='openathens']",
            "a[href*='shibboleth']",
            "a[href*='wayf']",
        )

    def institution_input_rules(self) -> tuple[InstitutionInputRule, ...]:
        return (
            InstitutionInputRule("input[placeholder*='institution' i]"),
            InstitutionInputRule("input[aria-label*='institution' i]"),
            InstitutionInputRule("input[placeholder*='organization' i]"),
            InstitutionInputRule("input[aria-label*='organization' i]"),
            InstitutionInputRule("input[placeholder*='university' i]"),
            InstitutionInputRule("input[aria-label*='university' i]"),
            InstitutionInputRule("[role='combobox'] input", requires_picker_context=True),
            InstitutionInputRule("[role='combobox']", requires_picker_context=True),
            InstitutionInputRule("input[type='search']", requires_picker_context=True),
            InstitutionInputRule("input[type='text']", requires_picker_context=True),
            InstitutionInputRule("input:not([type])", requires_picker_context=True),
            InstitutionInputRule("input", requires_picker_context=True),
        )

    def has_institution_picker_context(self, page: object) -> bool:
        text = html_to_text(_page_html(page)).lower()
        markers = (
            "find your institution",
            "institutional login",
            "loading institution options",
            "click to choose manually",
            "access content through your institution",
            "seamlessaccess",
        )
        return any(marker in text for marker in markers)

    def should_try_institution_input(self, rule: InstitutionInputRule, page: object) -> bool:
        return True

    def prepare_fulltext_capture(self, page: object) -> tuple[str, ...]:
        return ()


class NatureRecipe(GenericRecipe):
    name = "nature"

    def matches(self, url: str, html: str = "") -> bool:
        host = urlparse(url).netloc.lower()
        return "nature.com" in host or "springernature.com" in host or "springer.com" in host

    def inspect(self, page: object) -> AccessEvidence:
        evidence = super().inspect(page)
        markers = list(evidence.markers)
        url = evidence.url.lower()
        if "wayf.springernature.com" in url and "springer-nature-wayf" not in markers:
            markers.append("springer-nature-wayf")
            if evidence.state in {AccessState.ARTICLE_PAGE, AccessState.UNKNOWN, AccessState.ACCESS_ENTRY}:
                return AccessEvidence(AccessState.INSTITUTION_PICKER, evidence.url, tuple(markers))
        return AccessEvidence(evidence.state, evidence.url, tuple(markers))


class ScienceRecipe(GenericRecipe):
    name = "science"

    def matches(self, url: str, html: str = "") -> bool:
        host = urlparse(url).netloc.lower()
        return "science.org" in host or "aaas.org" in host

    def inspect(self, page: object) -> AccessEvidence:
        url = _page_url(page)
        html = _page_html(page)
        text = html_to_text(html).lower()
        markers: list[str] = []

        if looks_like_security_challenge(text):
            markers.append("science-security-challenge")
            return AccessEvidence(AccessState.SECURITY_CHALLENGE, url, tuple(markers))
        if looks_like_science_fulltext(html, text):
            markers.append("science-fulltext")
            return AccessEvidence(AccessState.FULLTEXT, url, tuple(markers))
        if looks_like_science_access_entry(url, text):
            markers.append("science-access-entry")
            return AccessEvidence(AccessState.ACCESS_ENTRY, url, tuple(markers))

        evidence = super().inspect(page)
        return AccessEvidence(evidence.state, evidence.url, tuple(markers + list(evidence.markers)))

    def access_entry_selectors(self) -> tuple[str, ...]:
        selectors = list(super().access_entry_selectors())
        check_access = "a:has-text('Check Access')"
        sso_anchor = "a[href*='/action/ssostart']"
        if check_access in selectors and sso_anchor in selectors:
            selectors.remove(check_access)
            selectors.insert(selectors.index(sso_anchor), check_access)
        return tuple(selectors)

    def prepare_fulltext_capture(self, page: object) -> tuple[str, ...]:
        if _expand_science_reference_controls(page):
            return ("browser capture action: science references expanded",)
        return ()


class WileyRecipe(GenericRecipe):
    name = "wiley"

    def matches(self, url: str, html: str = "") -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith("onlinelibrary.wiley.com")

    def inspect(self, page: object) -> AccessEvidence:
        url = _page_url(page)
        html = _page_html(page)
        text = html_to_text(html).lower()
        markers: list[str] = []

        if looks_like_security_challenge(text):
            markers.append("wiley-security-challenge")
            return AccessEvidence(AccessState.SECURITY_CHALLENGE, url, tuple(markers))
        if _is_wiley_abstract_url(url):
            markers.append("wiley-abstract-page")
            return AccessEvidence(AccessState.SUBSCRIPTION_PREVIEW, url, tuple(markers))
        if looks_like_wiley_fulltext(html, text, url=url):
            markers.append("wiley-fulltext")
            return AccessEvidence(AccessState.FULLTEXT, url, tuple(markers))
        if looks_like_wiley_access_entry(text):
            markers.append("wiley-access-entry")
            return AccessEvidence(AccessState.ACCESS_ENTRY, url, tuple(markers))
        if looks_like_subscription_preview(text):
            markers.append("subscription-preview")
            return AccessEvidence(AccessState.SUBSCRIPTION_PREVIEW, url, tuple(markers))
        if looks_like_institution_picker(url, text):
            markers.append("institution-picker")
            return AccessEvidence(AccessState.INSTITUTION_PICKER, url, tuple(markers))
        if looks_like_access_entry(text):
            markers.append("access-entry")
            return AccessEvidence(AccessState.ACCESS_ENTRY, url, tuple(markers))
        if looks_like_human_login(url, html, text):
            markers.append("human-login")
            return AccessEvidence(AccessState.HUMAN_LOGIN, url, tuple(markers))
        return AccessEvidence(AccessState.ARTICLE_PAGE if url else AccessState.UNKNOWN, url, ())

    def should_try_institution_input(self, rule: InstitutionInputRule, page: object) -> bool:
        if not rule.requires_picker_context:
            return True
        if not _is_wiley_article_page(_page_url(page)):
            return True
        return self.has_institution_picker_context(page)


class PublisherRecipeRegistry:
    def __init__(self, recipes: tuple[GenericRecipe, ...] | None = None) -> None:
        self.recipes = recipes or (NatureRecipe(), ScienceRecipe(), WileyRecipe(), GenericRecipe())

    def for_page(self, page: object) -> GenericRecipe:
        url = _page_url(page)
        html = _page_html(page)
        for recipe in self.recipes:
            if recipe.matches(url, html):
                return recipe
        return GenericRecipe()


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _page_url(page: object) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:
        return ""


def _page_html(page: object) -> str:
    try:
        return page.content()
    except Exception:
        return ""


def _expand_science_reference_controls(page: object) -> bool:
    expanded = False
    for _attempt in range(6):
        try:
            clicked = bool(
                page.evaluate(
                    """
                    () => {
                      const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                          style.visibility !== 'hidden' &&
                          style.display !== 'none' &&
                          Number(style.opacity || 1) > 0.01;
                      };
                      const textOf = (el) => [
                        el.innerText || '',
                        el.textContent || '',
                        el.value || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('title') || ''
                      ].join(' ').replace(/\\s+/g, ' ').trim();
                      const isReferenceExpander = (text) => {
                        const normalized = text.toLowerCase();
                        if (normalized.includes('go to reference')) return false;
                        return /(?:^|\\b)(show|see)\\s+all\\s+references(?:\\b|$)/.test(normalized) ||
                          /(?:^|\\b)(show|see)\\s+more\\s+references(?:\\b|$)/.test(normalized);
                      };
                      const clickable = 'button,a,[role="button"],input[type="button"],input[type="submit"]';
                      for (const el of [...document.querySelectorAll(clickable)]) {
                        if (!visible(el)) continue;
                        if (!isReferenceExpander(textOf(el))) continue;
                        el.scrollIntoView({block: 'center', inline: 'center'});
                        el.click();
                        return true;
                      }
                      return false;
                    }
                    """
                )
            )
        except Exception:
            return expanded
        if not clicked:
            return expanded
        expanded = True
        _wait_for_page_settle(page)
    return expanded


def _wait_for_page_settle(page: object) -> None:
    try:
        page.wait_for_timeout(700)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass


def html_to_text(html: str) -> str:
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


def looks_like_fulltext(html: str, text: str | None = None) -> bool:
    text = text if text is not None else html_to_text(html).lower()
    if looks_like_subscription_preview(text):
        return False
    body_markers = (
        "main",
        "introduction",
        "results",
        "discussion",
        "methods",
        "data availability",
    )
    end_markers = (
        "references",
        "acknowledgements",
        "author information",
        "ethics declarations",
    )
    has_article_shell = "<article" in html.lower() or "c-article" in html.lower()
    has_body = any(marker in text for marker in body_markers)
    has_endmatter = any(marker in text for marker in end_markers)
    return has_article_shell and has_body and has_endmatter and len(text) >= 120


def looks_like_science_fulltext(html: str, text: str | None = None) -> bool:
    text = text if text is not None else html_to_text(html).lower()
    if looks_like_subscription_preview(text) or looks_like_security_challenge(text):
        return False
    html_lower = html.lower()
    shell_markers = (
        "<article",
        "article__body",
        "article-body",
        "core-container",
        "hlflvt-main",
    )
    end_markers = (
        "references and notes",
        "references",
        "acknowledgments",
        "supplementary materials",
    )
    has_shell = any(marker in html_lower for marker in shell_markers)
    has_body = bool(science_body_headings_after_abstract(html))
    has_endmatter = any(marker in text for marker in end_markers)
    return has_shell and has_body and has_endmatter and len(text) >= 120


def looks_like_wiley_fulltext(html: str, text: str | None = None, *, url: str = "") -> bool:
    if _is_wiley_abstract_url(url):
        return False
    text = text if text is not None else html_to_text(html).lower()
    if looks_like_subscription_preview(text) or looks_like_security_challenge(text):
        return False
    html_lower = html.lower()
    has_shell = any(
        marker in html_lower
        for marker in (
            "<article",
            "article__body",
            "article-body",
            "hlflvt-main",
            "fulltext",
        )
    )
    body_headings = wiley_body_headings_before_backmatter(html)
    has_body = any(not _is_wiley_frontmatter_heading(heading) for heading in body_headings)
    has_endmatter = "references" in text
    return has_shell and has_body and has_endmatter and len(text) >= 500


def looks_like_wiley_access_entry(text: str) -> bool:
    markers = (
        "get access to the full version of this article",
        "view access options below",
        "institutional login",
        "loading institution options",
        "click to choose manually",
        "purchase instant access",
        "read the full text",
    )
    return any(marker in text for marker in markers)


def wiley_body_headings_before_backmatter(html: str) -> tuple[str, ...]:
    try:
        soup = BeautifulSoup(html or "", "lxml")
        headings = [
            _normalize_heading_text(heading.get_text(" ", strip=True))
            for heading in soup.find_all(["h2", "h3"])
        ]
    except Exception:
        headings = []

    body: list[str] = []
    for heading in headings:
        if not heading:
            continue
        if body and _is_wiley_backmatter_heading(heading):
            break
        if _is_wiley_body_heading(heading):
            body.append(heading)
    return tuple(body)


def _is_wiley_body_heading(heading: str) -> bool:
    normalized = re.sub(r"^(?:[ivxlcdm]+|\d+(?:\.\d+)*)\s*[.)]?\s+", "", heading).strip()
    body_markers = (
        "abstract",
        "summary",
        "introduction",
        "background",
        "materials",
        "methods",
        "method",
        "results",
        "discussion",
        "conclusion",
        "conclusions",
        "development",
    )
    return any(normalized == marker or normalized.startswith(marker + " ") for marker in body_markers)


def _is_wiley_frontmatter_heading(heading: str) -> bool:
    normalized = re.sub(r"^(?:[ivxlcdm]+|\d+(?:\.\d+)*)\s*[.)]?\s+", "", heading).strip()
    return normalized in {"abstract", "summary", "keywords"}


def _is_wiley_backmatter_heading(heading: str) -> bool:
    backmatter = (
        "supporting information",
        "references",
        "citing literature",
        "author contributions",
        "acknowledgements",
        "acknowledgments",
        "funding",
        "conflicts of interest",
        "data availability statement",
        "information",
        "figures",
    )
    return any(heading == marker or heading.startswith(marker + " ") for marker in backmatter)


def _is_wiley_abstract_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.lower().endswith("onlinelibrary.wiley.com") and "/doi/abs/" in parsed.path.lower()


def _is_wiley_article_page(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.lower().endswith("onlinelibrary.wiley.com") and "/doi/" in parsed.path.lower()


def science_body_headings_after_abstract(html: str) -> tuple[str, ...]:
    try:
        soup = BeautifulSoup(html or "", "lxml")
        headings = [
            _normalize_heading_text(heading.get_text(" ", strip=True))
            for heading in soup.find_all(["h2", "h3"])
        ]
    except Exception:
        headings = []
    if not headings:
        return ()

    abstract_indexes = [index for index, heading in enumerate(headings) if heading == "abstract"]
    start = abstract_indexes[-1] + 1 if abstract_indexes else 0
    body: list[str] = []
    for heading in headings[start:]:
        if not heading:
            continue
        if _is_science_gate_or_backmatter_heading(heading):
            break
        if heading in {"editor's summary", "editor’s summary", "structured abstract"}:
            continue
        body.append(heading)
    return tuple(body)


def _is_science_gate_or_backmatter_heading(heading: str) -> bool:
    gate_or_backmatter = (
        "access the full article",
        "check access",
        "supplementary materials",
        "references and notes",
        "references",
        "eletters",
        "recommended articles",
        "information",
        "authors",
    )
    return any(heading == marker or heading.startswith(marker + " ") for marker in gate_or_backmatter)


def _normalize_heading_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip(" .:;-")


def looks_like_subscription_preview(text: str) -> bool:
    markers = (
        "this is a preview of subscription content",
        "are you a librarian?",
        "get full access",
        "subscribe to journal",
    )
    return any(marker in text for marker in markers)


def looks_like_security_challenge(text: str) -> bool:
    text = text.lower()
    markers = (
        "checking if the site connection is secure",
        "checking your browser",
        "please wait while we verify",
        "please wait...",
        "just a moment",
        "security service to protect itself",
        "verify you are human",
        "human verification",
        "ray id",
        "\u6b63\u5728\u8fdb\u884c\u5b89\u5168",
        "\u5b89\u5168\u68c0\u67e5",
        "\u8bf7\u7a0d\u5019",
    )
    return any(marker in text for marker in markers)


def looks_like_human_login(url: str, html: str, text: str) -> bool:
    url = url.lower()
    html = html.lower()
    url_markers = (
        "/auth/login",
        "idp",
        "sso",
        "id.tsinghua.edu.cn",
        "login.",
    )
    form_markers = (
        "type='password'",
        'type="password"',
        "captcha",
        "one-time",
        "verification code",
        "二次验证",
        "统一身份",
        "电子身份",
    )
    text_markers = (
        "password",
        "验证码",
        "清华大学用户电子身份服务系统",
    )
    return (
        any(marker in url for marker in url_markers)
        or any(marker in html for marker in form_markers)
        or any(marker.lower() in text for marker in text_markers)
    )


def looks_like_institution_picker(url: str, text: str) -> bool:
    url = url.lower()
    url_markers = (
        "wayf.",
        "openathens",
        "shibboleth",
        "institutional-login",
    )
    text_markers = (
        "find your institution",
        "institution's login system",
    )
    return any(marker in url for marker in url_markers) or any(marker in text for marker in text_markers)


def looks_like_access_entry(text: str) -> bool:
    text_markers = (
        "access through your institution",
        "access through your organization",
        "institutional access",
        "institutional sign in",
        "log in through your institution",
        "sign in through your institution",
    )
    return any(marker in text for marker in text_markers)


def looks_like_science_access_entry(url: str, text: str) -> bool:
    text_markers = (
        "access the full article",
        "check access",
        "institutional sign in",
        "sign in through your institution",
        "log in through your institution",
        "access through your institution",
        "access through your organization",
        "find your institution",
    )
    return any(marker in text for marker in text_markers)
