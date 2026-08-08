from __future__ import annotations

import requests

import scansci_html.web_access as web_access
import scansci_html.pi_agent as pi_agent
from scansci_html.pi_agent import PiAgentClient


def test_browser_access_status_is_non_mutating_when_proxy_is_absent(monkeypatch) -> None:
    def fail_get(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(web_access.requests, "get", fail_get)

    result = web_access.browser_access_status()

    assert result["ok"] is True
    assert result["ready"] is False
    assert result["read_only"] is True
    assert result["requires_user_setup"] is True


def test_browser_access_reads_rendered_text_and_closes_its_tab(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_proxy(path, **kwargs):
        calls.append((path, kwargs))
        if path == "/new":
            return {"targetId": "tab-1"}
        if path == "/info":
            return {"title": "Example", "url": "https://example.com/"}
        if path == "/eval":
            return {"value": '{"title":"Example","url":"https://example.com/","ready":"complete","text":"Rendered content"}'}
        if path == "/close":
            return {"success": True}
        raise AssertionError(path)

    monkeypatch.setattr(web_access, "_ensure_proxy", lambda **kwargs: None)
    monkeypatch.setattr(web_access, "_proxy_json", fake_proxy)

    result = web_access.browser_access_read("https://example.com/article")

    assert result["backend"] == "web-access CDP proxy"
    assert result["source"] == "web-access:cdp"
    assert result["content"] == "Rendered content"
    assert result["read_only"] is True
    assert [path for path, _ in calls] == ["/new", "/info", "/eval", "/close"]


def test_browser_access_rejects_private_and_credentialed_urls() -> None:
    for target in ("http://127.0.0.1:8000/secret", "https://user:password@example.com/page"):
        try:
            web_access.browser_access_read(target)
        except web_access.WebAccessError as error:
            assert "private" in str(error) or "credentials" in str(error)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("unsafe browser target was accepted")


def test_pi_dispatches_browser_access_as_a_read_only_tool(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        pi_agent,
        "browser_access_read",
        lambda target, *, timeout: {"ok": True, "target": target, "timeout": timeout},
    )
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool(
        "browser_access",
        {"operation": "read", "target": "https://example.com", "timeout_seconds": 10},
    )

    assert result == {"ok": True, "target": "https://example.com", "timeout": 10.0}
