from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest

import scansci_html.webapp as webapp_module
from scansci_html.webapp import NotebookWebApp


class _FakeHeaders(dict):
    def get_content_type(self) -> str:
        return str(self.get("Content-Type", "")).split(";", 1)[0].strip()


class _FakeResponse:
    def __init__(self, url: str, content_type: str, body: bytes):
        self._url = url
        self.headers = _FakeHeaders({"Content-Type": content_type})
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int = -1) -> bytes:
        return self._body


def _app(tmp_path: Path) -> NotebookWebApp:
    return NotebookWebApp(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )


def test_site_icon_resolves_html_link_and_caches_by_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_url = "https://cloud.siliconflow.cn/me/models?types=reranker"
    icon_url = "https://cloud.siliconflow.cn/assets/siliconflow.svg"
    requests: list[str] = []

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        del timeout
        url = str(getattr(request, "full_url"))
        requests.append(url)
        if url == page_url:
            return _FakeResponse(
                url,
                "text/html; charset=utf-8",
                b'<html><head><link rel="icon" href="/assets/siliconflow.svg"></head></html>',
            )
        if url == icon_url:
            return _FakeResponse(url, "image/svg+xml", b"<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>")
        raise OSError(f"unexpected request: {url}")

    monkeypatch.setattr(webapp_module, "urlopen", fake_urlopen)
    app = _app(tmp_path)
    query = f"url={quote(page_url, safe='')}"

    first = app.dispatch("GET", f"/api/site-icon?{query}")
    second = app.dispatch("GET", f"/api/site-icon?{query}")

    assert first.status == 200
    assert first.content_type == "image/svg+xml"
    assert first.body.startswith(b"<svg")
    assert first.cache_control == "public, max-age=86400"
    assert second.body == first.body
    assert requests == [page_url, icon_url]


def test_site_icon_rejects_private_urls(tmp_path: Path) -> None:
    app = _app(tmp_path)

    response = app.dispatch("GET", "/api/site-icon?url=https%3A%2F%2F127.0.0.1%2Ffavicon.ico")

    assert response.status == 400
    assert b"Private and loopback" in response.body
