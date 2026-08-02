from pathlib import Path

from scansci_html.browser import BrowserFetcher, _BrowserSession


def test_browser_fetcher_consumes_manual_login_wait_only_once(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, wait_login_seconds=300)

    assert fetcher._consume_login_wait_seconds() == 300
    assert fetcher._consume_login_wait_seconds() == 0


def test_browser_fetcher_clicks_institutional_access_entry(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path)
    page = FakePage(
        visible_selectors={
            "a:has-text('Access through your institution')",
        }
    )

    assert fetcher._click_institutional_access_entry(page) is True
    assert page.clicked_selectors == ["a:has-text('Access through your institution')"]


def test_browser_fetcher_prioritizes_visible_check_access_over_science_sso_anchor(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path)
    page = FakePage(
        visible_selectors={
            "a[href*='/action/ssostart']",
            "a:has-text('Check Access')",
        }
    )

    assert fetcher._click_institutional_access_entry(page) is True
    assert page.clicked_selectors == ["a:has-text('Check Access')"]


def test_browser_fetcher_does_not_reclick_science_sso_while_already_in_sso(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path)
    page = FakePage(
        visible_selectors={
            "a[href*='/action/ssostart']",
            "a:has-text('Check Access')",
        }
    )
    page.url = "https://www.science.org/action/ssostart?redirectUri=%2Fdoi%2F10.1126%2Fscience.aed5051"

    assert fetcher._click_institutional_access_entry(page) is False
    assert page.clicked_selectors == []


def test_browser_fetcher_selects_configured_institution(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Example University")
    page = FakePage(
        visible_selectors={
            "input[placeholder*='institution' i]",
            "text=Example University",
        }
    )

    assert fetcher._select_institution(page) is True
    assert page.filled == [("input[placeholder*='institution' i]", "Example University")]
    assert page.clicked_selectors == ["text=Example University"]


def test_browser_fetcher_selects_plain_text_institution_input(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Tsinghua university")
    page = FakePage(
        visible_selectors={
            "input[type='text']",
            "text=Tsinghua university",
        }
    )

    assert fetcher._select_institution(page) is True
    assert page.filled == [("input[type='text']", "Tsinghua university")]
    assert page.clicked_selectors == ["text=Tsinghua university"]


def test_browser_fetcher_submits_plain_text_institution_input_with_enter(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Tsinghua University")
    page = FakePage(
        visible_selectors={
            "input[type='text']",
        }
    )

    assert fetcher._select_institution(page) is True
    assert page.filled == [("input[type='text']", "Tsinghua University")]
    assert page.pressed == [("input[type='text']", "Enter")]


def test_browser_fetcher_does_not_fill_wiley_article_site_search(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Tsinghua University")
    page = FakePage(
        visible_selectors={
            "input[type='search']",
        }
    )
    page.url = "https://onlinelibrary.wiley.com/doi/full/10.1111/gcb.70943"

    assert fetcher._select_institution(page) is False
    assert page.filled == []


def test_browser_fetcher_does_not_fill_institution_on_human_login_page(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Tsinghua University")
    page = FakeHumanLoginPage(
        visible_selectors={
            "input[type='text']",
        }
    )

    assert fetcher._select_institution(page) is False
    assert page.filled == []


def test_browser_fetcher_does_not_fill_science_individual_login_page(tmp_path: Path):
    fetcher = BrowserFetcher(profile_dir=tmp_path, institution_query="Tsinghua University")
    page = FakeScienceIndividualLoginPage(
        visible_selectors={
            "input[type='text']",
            "button:has-text('Log in')",
        }
    )

    assert fetcher._advance_to_login_entry(page) is False
    assert page.filled == []
    assert page.clicked_selectors == []


def test_browser_fetcher_reuses_live_context_until_explicit_close(tmp_path: Path):
    fetcher = ReusableSessionBrowserFetcher(profile_dir=tmp_path)

    first = fetcher.fetch("https://publisher.example/first")
    second = fetcher.fetch("https://publisher.example/second")

    assert fetcher.launches == 1
    assert first.source == "cloakbrowser"
    assert second.source == "cloakbrowser"
    assert [page.url for page in fetcher.contexts[0].pages] == [
        "https://publisher.example/first",
        "https://publisher.example/second",
    ]
    assert [page.closed for page in fetcher.contexts[0].pages] == [True, True]
    assert fetcher.contexts[0].close_count == 0

    fetcher.close()
    fetcher.close()

    assert fetcher.contexts[0].close_count == 1


def test_browser_fetcher_can_keep_pages_open_for_session_continuity(tmp_path: Path):
    fetcher = ReusableSessionBrowserFetcher(profile_dir=tmp_path, keep_pages_open=True)

    fetcher.fetch("https://publisher.example/first")

    page = fetcher.contexts[0].pages[0]
    assert page.closed is False


def test_browser_fetcher_manual_login_wait_ends_when_article_is_already_accessible(tmp_path: Path):
    fetcher = EarlyContinueBrowserFetcher(profile_dir=tmp_path, wait_login_seconds=300)

    response = fetcher.fetch("https://publisher.example/authorized")

    page = fetcher.contexts[0].pages[0]
    assert "Full text body" in response.html
    assert page.timeouts == []


def test_browser_fetcher_auto_advances_wayf_page_without_manual_wait(tmp_path: Path):
    fetcher = WayfAdvanceBrowserFetcher(
        profile_dir=tmp_path,
        institution_query="Tsinghua University",
    )

    response = fetcher.fetch("https://wayf.springernature.com/?redirect_uri=https%3A%2F%2Fwww.nature.com%2Farticles%2Fs1")

    assert fetcher.advance_count == 1
    assert "Full text after institutional login" in response.html


def test_browser_fetcher_attaches_security_challenge_evidence(tmp_path: Path):
    fetcher = ChallengeBrowserFetcher(profile_dir=tmp_path)

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    assert "Please wait" in response.html
    assert "browser access state: security_challenge" in response.warnings
    assert "browser access marker: science-security-challenge" in response.warnings


def test_browser_fetcher_reports_access_entry_when_no_manual_wait_is_configured(tmp_path: Path):
    fetcher = StuckAccessEntryBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=0,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Check Access" in response.html
    assert "browser access state: access_entry" in response.warnings
    assert page.timeouts == []
    assert fetcher.advance_count == 1


def test_browser_fetcher_manual_login_wait_does_not_abandon_stable_access_entry(tmp_path: Path):
    fetcher = DelayedAccessEntryBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=300,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Delayed Full Text" in response.html
    assert len(page.timeouts) >= 10
    assert fetcher.advance_count >= 8


def test_browser_fetcher_clicks_visible_access_control_even_when_state_is_article_page(tmp_path: Path):
    fetcher = PassiveAccessControlBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=300,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Passive Access Full Text" in response.html
    assert page.clicked_selectors == ["button:has-text('Check Access')"]


def test_browser_fetcher_hold_on_auth_waits_until_fulltext_is_visible(tmp_path: Path):
    fetcher = HoldUntilAuthorizedBrowserFetcher(
        profile_dir=tmp_path,
        hold_on_auth=True,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Hold Mode Full Text" in response.html
    assert page.closed is True
    assert page.timeouts
    assert fetcher.advance_count >= 1


def test_browser_fetcher_recovers_from_stuck_science_sso_transition(tmp_path: Path):
    fetcher = SsoTransitionRecoveryBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=30,
        science_sso_recover_seconds=0,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Recovered Science Full Text" in response.html
    assert page.navigations == [
        "https://www.science.org/doi/10.1126/science.aed5051",
        "https://www.science.org/doi/10.1126/science.aed5051",
    ]


def test_browser_fetcher_prefers_requested_article_when_sso_redirect_points_home(tmp_path: Path):
    fetcher = SsoHomeRedirectRecoveryBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=30,
        science_sso_recover_seconds=0,
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Recovered Science Full Text" in response.html
    assert page.navigations == [
        "https://www.science.org/doi/10.1126/science.aed5051",
        "https://www.science.org/doi/10.1126/science.aed5051",
    ]


def test_browser_fetcher_recovers_from_science_individual_login_branch(tmp_path: Path):
    fetcher = ScienceIndividualLoginRecoveryBrowserFetcher(
        profile_dir=tmp_path,
        wait_login_seconds=30,
        institution_query="Tsinghua University",
    )

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed5051")

    page = fetcher.contexts[0].pages[0]
    assert "Recovered From AAAS Individual Login" in response.html
    assert page.filled == []
    assert page.clicked_selectors == []
    assert page.navigations == [
        "https://www.science.org/doi/10.1126/science.aed5051",
        "https://www.science.org/doi/10.1126/science.aed5051",
    ]


def test_browser_fetcher_expands_science_references_before_capture(tmp_path: Path):
    fetcher = ScienceCollapsedReferencesBrowserFetcher(profile_dir=tmp_path)

    response = fetcher.fetch("https://www.science.org/doi/10.1126/science.aed8630")

    page = fetcher.contexts[0].pages[0]
    assert page.reference_expand_clicks == 1
    assert "Reference 5 after expansion" in response.html
    assert "SHOW ALL REFERENCES" not in response.html
    assert "browser capture action: science references expanded" in response.warnings


class FakePage:
    def __init__(self, *, visible_selectors: set[str]):
        self.visible_selectors = visible_selectors
        self.clicked_selectors: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.pressed: list[tuple[str, str]] = []
        self.url = ""

    def locator(self, selector: str):
        return FakeLocator(self, selector)

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, *_args, **_kwargs):
        return None

    def content(self):
        return "<main></main>"


class FakeHumanLoginPage(FakePage):
    def __init__(self, *, visible_selectors: set[str]):
        super().__init__(visible_selectors=visible_selectors)
        self.url = "https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/example"

    def content(self):
        return """
        <main>
          <h1>清华大学用户电子身份服务系统</h1>
          <label>用户名</label><input type="text" />
          <label>密码</label><input type="password" />
        </main>
        """


class FakeScienceIndividualLoginPage(FakePage):
    def __init__(self, *, visible_selectors: set[str]):
        super().__init__(visible_selectors=visible_selectors)
        self.url = "https://identity.aaas.org/u/login/identifier?state=abc"

    def content(self):
        return """
        <main>
          <h1>LOG IN</h1>
          <label>AAAS ID (EMAIL ADDRESS)*</label><input type="text" />
          <button>LOGIN</button>
        </main>
        """


class FakeLocator:
    def __init__(self, page: FakePage, selector: str):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, **_kwargs):
        return self.selector in self.page.visible_selectors

    def click(self, **_kwargs):
        self.page.clicked_selectors.append(self.selector)

    def fill(self, value: str, **_kwargs):
        self.page.filled.append((self.selector, value))

    def press(self, key: str, **_kwargs):
        self.page.pressed.append((self.selector, key))


class ReusableSessionBrowserFetcher(BrowserFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.launches = 0
        self.contexts: list[FetchContext] = []

    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = FetchContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class FetchContext:
    def __init__(self):
        self.pages: list[FetchPage] = []
        self.close_count = 0

    def new_page(self):
        page = FetchPage()
        self.pages.append(page)
        return page

    def close(self):
        self.close_count += 1


class FetchPage:
    def __init__(self):
        self.url = ""
        self.closed = False
        self.timeouts: list[int] = []
        self.html = "<article><h1>Fetched Article</h1><p>Rendered HTML</p></article>"

    def goto(self, url: str, **_kwargs):
        self.url = url

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, *_args, **_kwargs):
        if _args:
            self.timeouts.append(_args[0])
        return None

    def content(self):
        return self.html

    def close(self):
        self.closed = True


class EarlyContinueBrowserFetcher(ReusableSessionBrowserFetcher):
    def _advance_to_login_entry(self, page: object) -> None:
        page.html = """
        <article>
          <h1>Authorized Article</h1>
          <section><h2>Results</h2><p>Full text body is visible now.</p></section>
          <section><h2>Methods</h2><p>The institution session is already active.</p></section>
          <section><h2>References</h2><p>Reference list is available.</p></section>
        </article>
        """


class WayfAdvanceBrowserFetcher(BrowserFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.advance_count = 0

    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        return _BrowserSession(context=WayfContext(), source="cloakbrowser")

    def _advance_to_login_entry(self, page: object) -> None:
        self.advance_count += 1
        page.url = "https://www.nature.com/articles/s1"
        page.html = """
        <article class="c-article">
          <h1>Authorized Article</h1>
          <section><h2>Results</h2><p>Full text after institutional login.</p></section>
          <section><h2>Methods</h2><p>Authorized methods are visible.</p></section>
          <section><h2>References</h2><p>Reference list is visible.</p></section>
        </article>
        """


class WayfContext:
    def new_page(self):
        return WayfPage()

    def close(self):
        return None


class WayfPage(FetchPage):
    def goto(self, url: str, **_kwargs):
        self.url = url
        self.html = """
        <main>
          <h1>Access through your institution</h1>
          <p>Access subscription content by using your institution's login system.</p>
          <label>Find your institution:</label>
          <input type="text" />
        </main>
        """


class ChallengeBrowserFetcher(ReusableSessionBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = ChallengeContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class ChallengeContext(FetchContext):
    def new_page(self):
        page = ChallengePage()
        self.pages.append(page)
        return page


class ChallengePage(FetchPage):
    def goto(self, url: str, **_kwargs):
        self.url = url
        self.html = """
        <main>
          <h1>Please wait...</h1>
          <p>Checking if the site connection is secure</p>
          <p>This website is using a security service to protect itself from online attacks.</p>
        </main>
        """


class StuckAccessEntryBrowserFetcher(ReusableSessionBrowserFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.advance_count = 0

    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = StuckAccessEntryContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")

    def _advance_to_login_entry(self, page: object) -> None:
        self.advance_count += 1


class StuckAccessEntryContext(FetchContext):
    def new_page(self):
        page = StuckAccessEntryPage()
        self.pages.append(page)
        return page


class StuckAccessEntryPage(FetchPage):
    def goto(self, url: str, **_kwargs):
        self.url = url
        self.html = """
        <main class="article__body">
          <h1>Fast cell wall softening causes Venus flytrap closure</h1>
          <h2>Editor’s summary</h2><p>Public summary only.</p>
          <h2>Abstract</h2><p>The abstract is visible.</p>
          <h2>Access the full article</h2>
          <button>Check Access</button>
          <h2>References and Notes</h2>
        </main>
        """


class DelayedAccessEntryBrowserFetcher(StuckAccessEntryBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = DelayedAccessEntryContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class DelayedAccessEntryContext(FetchContext):
    def new_page(self):
        page = DelayedAccessEntryPage()
        self.pages.append(page)
        return page


class DelayedAccessEntryPage(StuckAccessEntryPage):
    def content(self):
        if len(self.timeouts) >= 10:
            return """
            <article>
              <h1>Delayed Full Text</h1>
              <section><h2>Abstract</h2><p>The abstract is visible.</p></section>
              <section><h2>Results</h2><p>The full article body appears after verification.</p></section>
              <section><h2>Methods</h2><p>Methods are visible after login.</p></section>
              <section><h2>References</h2><p>References are visible after login.</p></section>
            </article>
            """
        return self.html


class HoldUntilAuthorizedBrowserFetcher(ReusableSessionBrowserFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.advance_count = 0

    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = HoldUntilAuthorizedContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")

    def _advance_to_login_entry(self, page: object) -> None:
        self.advance_count += 1


class HoldUntilAuthorizedContext(FetchContext):
    def new_page(self):
        page = HoldUntilAuthorizedPage()
        self.pages.append(page)
        return page


class HoldUntilAuthorizedPage(StuckAccessEntryPage):
    def content(self):
        if len(self.timeouts) >= 2:
            return """
            <article>
              <h1>Hold Mode Full Text</h1>
              <section><h2>Abstract</h2><p>The abstract is visible.</p></section>
              <section><h2>Results</h2><p>The hold loop waited for full text.</p></section>
              <section><h2>Discussion</h2><p>The article body is now readable.</p></section>
              <section><h2>References</h2><p>Reference list is visible.</p></section>
            </article>
            """
        return self.html


class PassiveAccessControlBrowserFetcher(ReusableSessionBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = PassiveAccessControlContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class PassiveAccessControlContext(FetchContext):
    def new_page(self):
        page = PassiveAccessControlPage()
        self.pages.append(page)
        return page


class PassiveAccessControlPage(FetchPage):
    def __init__(self):
        super().__init__()
        self.clicked_selectors: list[str] = []
        self.html = """
        <main>
          <h1>Science Article Shell</h1>
          <p>The visible toolbar has an access control, but the text is outside page.content.</p>
        </main>
        """

    def locator(self, selector: str):
        return PassiveAccessControlLocator(self, selector)


class PassiveAccessControlLocator:
    def __init__(self, page: PassiveAccessControlPage, selector: str):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, **_kwargs):
        return self.selector == "button:has-text('Check Access')" and not self.page.clicked_selectors

    def click(self, **_kwargs):
        self.page.clicked_selectors.append(self.selector)
        self.page.html = """
        <article>
          <h1>Passive Access Full Text</h1>
          <section><h2>Abstract</h2><p>The abstract is visible.</p></section>
          <section><h2>Results</h2><p>The access control moved to the full text page.</p></section>
          <section><h2>Discussion</h2><p>The article body is visible.</p></section>
          <section><h2>References</h2><p>References are visible.</p></section>
        </article>
        """


class SsoTransitionRecoveryBrowserFetcher(ReusableSessionBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = SsoTransitionRecoveryContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class SsoTransitionRecoveryContext(FetchContext):
    def new_page(self):
        page = SsoTransitionRecoveryPage()
        self.pages.append(page)
        return page


class SsoTransitionRecoveryPage(FetchPage):
    def __init__(self):
        super().__init__()
        self.navigations: list[str] = []

    def goto(self, url: str, **_kwargs):
        self.navigations.append(url)
        if len(self.navigations) == 1:
            self.url = (
                "https://www.science.org/action/ssostart?"
                "redirectUri=%2Fdoi%2F10.1126%2Fscience.aed5051"
            )
            self.html = "<html><head><title>Login | Science | AAAS</title></head><body></body></html>"
            return
        self.url = url
        self.html = """
        <article class="article__body">
          <h1>Recovered Science Full Text</h1>
          <section><h2>Abstract</h2><p>The article is visible after SSO recovery.</p></section>
          <section><h2>Results</h2><p>The full article body appears after redirect recovery.</p></section>
          <section><h2>Discussion</h2><p>The browser session is authorized.</p></section>
          <section><h2>References and Notes</h2><p>References are visible.</p></section>
        </article>
        """


class SsoHomeRedirectRecoveryBrowserFetcher(SsoTransitionRecoveryBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = SsoHomeRedirectRecoveryContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class SsoHomeRedirectRecoveryContext(FetchContext):
    def new_page(self):
        page = SsoHomeRedirectRecoveryPage()
        self.pages.append(page)
        return page


class SsoHomeRedirectRecoveryPage(SsoTransitionRecoveryPage):
    def goto(self, url: str, **_kwargs):
        self.navigations.append(url)
        if len(self.navigations) == 1:
            self.url = "https://www.science.org/action/ssostart?redirectUri=%2F"
            self.html = "<html><head><title>Login | Science | AAAS</title></head><body></body></html>"
            return
        self.url = url
        self.html = """
        <article class="article__body">
          <h1>Recovered Science Full Text</h1>
          <section><h2>Abstract</h2><p>The article is visible after SSO recovery.</p></section>
          <section><h2>Results</h2><p>The full article body appears after redirect recovery.</p></section>
          <section><h2>Discussion</h2><p>The browser session is authorized.</p></section>
          <section><h2>References and Notes</h2><p>References are visible.</p></section>
        </article>
        """


class ScienceIndividualLoginRecoveryBrowserFetcher(ReusableSessionBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = ScienceIndividualLoginRecoveryContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class ScienceIndividualLoginRecoveryContext(FetchContext):
    def new_page(self):
        page = ScienceIndividualLoginRecoveryPage()
        self.pages.append(page)
        return page


class ScienceIndividualLoginRecoveryPage(FetchPage):
    def __init__(self):
        super().__init__()
        self.navigations: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.clicked_selectors: list[str] = []

    def goto(self, url: str, **_kwargs):
        self.navigations.append(url)
        if len(self.navigations) == 1:
            self.url = "https://identity.aaas.org/u/login/identifier?state=abc"
            self.html = """
            <main>
              <h1>LOG IN</h1>
              <label>AAAS ID (EMAIL ADDRESS)*</label><input type="text" />
              <button>LOGIN</button>
            </main>
            """
            return
        self.url = url
        self.html = """
        <article class="article__body">
          <h1>Recovered From AAAS Individual Login</h1>
          <section><h2>Abstract</h2><p>The article is visible after returning.</p></section>
          <section><h2>Results</h2><p>The full body is now visible.</p></section>
          <section><h2>Discussion</h2><p>No individual-login fields were filled.</p></section>
          <section><h2>References and Notes</h2><p>References are visible.</p></section>
        </article>
        """


class ScienceCollapsedReferencesBrowserFetcher(ReusableSessionBrowserFetcher):
    def _launch_cloakbrowser_context(self) -> _BrowserSession:
        self.launches += 1
        context = ScienceCollapsedReferencesContext()
        self.contexts.append(context)
        return _BrowserSession(context=context, source="cloakbrowser")


class ScienceCollapsedReferencesContext(FetchContext):
    def new_page(self):
        page = ScienceCollapsedReferencesPage()
        self.pages.append(page)
        return page


class ScienceCollapsedReferencesPage(FetchPage):
    def __init__(self):
        super().__init__()
        self.reference_expand_clicks = 0

    def goto(self, url: str, **_kwargs):
        self.url = url
        self.html = """
        <article class="article__body">
          <h1>Science With Collapsed References</h1>
          <section><h2>Abstract</h2><p>The article is visible.</p></section>
          <section><h2>Results</h2><p>The full article body is visible.</p></section>
          <section><h2>Discussion</h2><p>The authorized article continues.</p></section>
          <section id="bibliography">
            <h2>References and Notes</h2>
            <ol>
              <li>Reference 1</li>
              <li>Reference 2</li>
              <li>Reference 3</li>
              <li>Reference 4</li>
            </ol>
            <button>SHOW ALL REFERENCES</button>
          </section>
        </article>
        """

    def evaluate(self, _script: str, *_args):
        if "SHOW ALL REFERENCES" not in self.html:
            return False
        self.reference_expand_clicks += 1
        self.html = """
        <article class="article__body">
          <h1>Science With Collapsed References</h1>
          <section><h2>Abstract</h2><p>The article is visible.</p></section>
          <section><h2>Results</h2><p>The full article body is visible.</p></section>
          <section><h2>Discussion</h2><p>The authorized article continues.</p></section>
          <section id="bibliography">
            <h2>References and Notes</h2>
            <ol>
              <li>Reference 1</li>
              <li>Reference 2</li>
              <li>Reference 3</li>
              <li>Reference 4</li>
              <li>Reference 5 after expansion</li>
              <li>Reference 6 after expansion</li>
            </ol>
          </section>
        </article>
        """
        return True
