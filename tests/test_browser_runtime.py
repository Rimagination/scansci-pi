from pathlib import Path

from scansci_html.browser_runtime import (
    BrowserSession,
    BrowserSessionBroker,
    _stable_cloakbrowser_fingerprint,
    _stable_cloakbrowser_args,
)


def test_session_broker_reuses_live_context_until_close():
    runtime = FakeRuntime()
    broker = BrowserSessionBroker(runtime)

    first_session, first_page = broker.new_page()
    second_session, second_page = broker.new_page()

    assert runtime.launches == 1
    assert first_session is second_session
    assert [page.name for page in runtime.contexts[0].pages] == ["page-1", "page-2"]
    assert first_page.name == "page-1"
    assert second_page.name == "page-2"
    assert runtime.contexts[0].close_count == 0

    broker.close()
    broker.close()

    assert runtime.contexts[0].close_count == 1


def test_cloakbrowser_fingerprint_is_stable_per_profile(tmp_path: Path):
    first_profile = tmp_path / "profile-a"
    second_profile = tmp_path / "profile-b"

    first = _stable_cloakbrowser_fingerprint(first_profile)
    again = _stable_cloakbrowser_fingerprint(first_profile)
    second = _stable_cloakbrowser_fingerprint(second_profile)

    assert first == again
    assert first != second
    assert 10_000 <= first <= 99_999


def test_cloakbrowser_args_include_stable_fingerprint(tmp_path: Path):
    fingerprint = _stable_cloakbrowser_fingerprint(tmp_path)

    args = _stable_cloakbrowser_args(tmp_path)

    assert f"--fingerprint={fingerprint}" in args
    assert "--disable-features=CrossOriginOpenerPolicy" in args


class FakeRuntime:
    def __init__(self):
        self.launches = 0
        self.contexts: list[FakeContext] = []

    def launch(self):
        self.launches += 1
        context = FakeContext()
        self.contexts.append(context)
        return BrowserSession(context=context, source="cloakbrowser")


class FakeContext:
    def __init__(self):
        self.pages: list[FakeRuntimePage] = []
        self.close_count = 0

    def new_page(self):
        page = FakeRuntimePage(f"page-{len(self.pages) + 1}")
        self.pages.append(page)
        return page

    def close(self):
        self.close_count += 1


class FakeRuntimePage:
    def __init__(self, name: str):
        self.name = name
