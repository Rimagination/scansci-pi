from __future__ import annotations

import json

import pytest

import scansci_html.agent_reach as agent_reach
import scansci_html.pi_agent as pi_agent
from scansci_html.agent_capabilities import capability_catalog
from scansci_html.pi_agent import PiAgentClient


class _Response:
    def __init__(self, payload: object, *, content: bytes | None = None) -> None:
        self._payload = payload
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")
        self.is_redirect = False
        self.is_permanent_redirect = False
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload

    def iter_content(self, chunk_size: int = 64 * 1024) -> object:
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self) -> None:
        return None


def test_agent_reach_status_is_zero_install_and_read_only() -> None:
    result = agent_reach.agent_reach_status()

    assert result["ok"] is True
    assert result["zero_install"] is True
    assert result["security"]["read_only"] is True
    channels = {item["channel"]: item for item in result["channels"]}
    assert channels["web"]["status"] == "ready"
    assert channels["rss"]["status"] == "ready"
    assert channels["github"]["status"] == "ready"


def test_agent_reach_reads_rss_without_feedparser(monkeypatch) -> None:
    xml = b"""<?xml version='1.0'?><rss><channel><title>Science Feed</title>
    <item><title>New result</title><link>https://example.com/paper</link>
    <description>Short summary</description></item></channel></rss>"""
    monkeypatch.setattr(agent_reach.requests, "get", lambda *args, **kwargs: _Response({}, content=xml))

    result = agent_reach.run_agent_reach(
        "read",
        target="https://example.com/feed.xml",
        channel="rss",
    )

    assert result["backend"] == "stdlib XML parser"
    assert result["feed_title"] == "Science Feed"
    assert result["items"][0]["url"] == "https://example.com/paper"


def test_agent_reach_reads_public_github_repository_via_api(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response({"full_name": "Panniantong/Agent-Reach", "description": "internet capability"})

    monkeypatch.setattr(agent_reach.requests, "get", fake_get)
    result = agent_reach.agent_reach_read("https://github.com/Panniantong/Agent-Reach")

    assert result["channel"] == "github"
    assert result["data"]["full_name"] == "Panniantong/Agent-Reach"
    assert calls[0][0] == "https://api.github.com/repos/Panniantong/Agent-Reach"


def test_agent_reach_searches_bilibili_public_api(monkeypatch) -> None:
    payload = {
        "data": {
            "result": [
                {
                    "title": "<em class=\"keyword\">AI</em> tutorial",
                    "arcurl": "https://www.bilibili.com/video/BV1",
                    "author": "demo",
                }
            ]
        }
    }
    monkeypatch.setattr(agent_reach.requests, "get", lambda *args, **kwargs: _Response(payload))

    result = agent_reach.agent_reach_search("AI", channel="bilibili")

    assert result["channel"] == "bilibili"
    assert result["items"][0]["title"] == "AI tutorial"


def test_agent_reach_public_url_boundary_rejects_private_targets() -> None:
    with pytest.raises(agent_reach.AgentReachError, match="private"):
        agent_reach.agent_reach_read("http://127.0.0.1:8000/private")

    with pytest.raises(agent_reach.AgentReachError, match="credentials"):
        agent_reach.agent_reach_read("https://user:password@example.com/page")


def test_agent_reach_is_in_capability_catalog(tmp_path) -> None:
    catalog = capability_catalog(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        plugins=[],
    )

    item = next(item for item in catalog["capabilities"] if item["id"] == "agent_reach")
    assert item["status"] == "ready"
    assert item["risk_level"] == "read_only"
    assert item["source"].startswith("Panniantong/Agent-Reach")


def test_pi_dispatches_agent_reach_as_a_native_read_only_tool(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        pi_agent,
        "run_agent_reach",
        lambda operation, **kwargs: {"ok": True, "operation": operation, "channel": kwargs["channel"]},
    )
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool(
        "agent_reach",
        {"operation": "status", "channel": "auto", "limit": 8},
    )

    assert result == {"ok": True, "operation": "status", "channel": "auto"}


def test_agent_reach_rejects_redirect_to_private_address(monkeypatch) -> None:
    def redirecting_get(url, **kwargs):
        response = _Response({})
        response.is_redirect = True
        response.is_permanent_redirect = False
        response.headers = {"Location": "http://127.0.0.1:11434/"}
        return response

    monkeypatch.setattr(agent_reach.requests, "get", redirecting_get)
    with pytest.raises(agent_reach.AgentReachError, match="private"):
        agent_reach.agent_reach_read("https://public.example/page")


def test_agent_reach_dns_rebinding_names_resolve_to_private(monkeypatch) -> None:
    # 127.0.0.1.nip.io has a public-looking hostname but resolves locally.
    monkeypatch.setattr(
        agent_reach.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    assert agent_reach._is_private_host("127.0.0.1.nip.io") is True


def test_agent_reach_search_routes_bare_issue_word_to_web_search(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response({})

    monkeypatch.setattr(agent_reach.requests, "get", fake_get)
    monkeypatch.setattr(agent_reach, "search_public_web", lambda *args, **kwargs: {"items": []})
    result = agent_reach.agent_reach_search("climate change issues in cities")
    assert result["channel"] == "web"
    assert "api.github.com" not in calls


def test_agent_reach_jina_reader_url_keeps_target_query() -> None:
    url = agent_reach._normalize_public_url("https://example.com/search?q=foo&page=2")
    assert agent_reach._read_web.__globals__["quote"](url, safe="") == (
        "https%3A%2F%2Fexample.com%2Fsearch%3Fq%3Dfoo%26page%3D2"
    )


def test_agent_reach_reads_public_json_api_directly_without_jina(monkeypatch) -> None:
    calls: list[str] = []
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "title": "A real scholarly result",
                "doi": "https://doi.org/10.1000/example",
            }
        ]
    }

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.startswith("https://r.jina.ai/"):
            raise AssertionError("healthy public JSON endpoints must not be sent through Jina")
        return _Response(payload)

    monkeypatch.setattr(agent_reach.requests, "get", fake_get)
    result = agent_reach.agent_reach_read(
        "https://api.openalex.org/works?search=climate%20change&per-page=1"
    )

    assert result["backend"] == "direct public HTTP"
    assert result["content_type"] == "application/json"
    assert result["data"]["results"][0]["id"] == "https://openalex.org/W123"
    assert calls == ["https://api.openalex.org/works?search=climate%20change&per-page=1"]


def test_agent_reach_extracts_readable_text_from_direct_html(monkeypatch) -> None:
    html = b"""<!doctype html><html><head><title>Paper page</title>
    <style>.hidden { display:none }</style><script>secret()</script></head>
    <body><main><h1>Evidence title</h1><p>Evidence paragraph.</p></main></body></html>"""
    monkeypatch.setattr(agent_reach.requests, "get", lambda *args, **kwargs: _Response({}, content=html))

    result = agent_reach.agent_reach_read("https://example.com/paper")

    assert result["backend"] == "direct public HTTP"
    assert result["title"] == "Paper page"
    assert "Evidence paragraph." in result["content"]
    assert "secret()" not in result["content"]


def test_agent_reach_retries_transient_direct_connection_failure(monkeypatch) -> None:
    calls: list[str] = []

    def flaky_get(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise agent_reach.requests.ConnectionError("connection reset")
        return _Response({"title": "Recovered public response"})

    monkeypatch.setattr(agent_reach.requests, "get", flaky_get)
    result = agent_reach.agent_reach_read("https://api.example.com/works/1")

    assert result["backend"] == "direct public HTTP"
    assert result["data"]["title"] == "Recovered public response"
    assert calls == [
        "https://api.example.com/works/1",
        "https://api.example.com/works/1",
        "https://api.example.com/works/1",
    ]
