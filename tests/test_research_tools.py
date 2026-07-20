from pathlib import Path

from scansci_html import research_tools


def test_search_journals_uses_scansci_origin_headers(monkeypatch):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "items": [
                {
                    "id": 1,
                    "title": "Example Journal",
                    "issn": "1234-5678",
                    "if_2023": 5.2,
                    "jcr_quartile": "Q1",
                    "cas_2025": "1区",
                }
            ]
        }

    monkeypatch.setattr(research_tools, "_request_json", fake_request)

    result = research_tools.search_journals("Example")

    assert result["items"][0]["title"] == "Example Journal"
    assert calls[0][1]["headers"]["Origin"] == "https://journal.scansci.com"


def test_paper_atlas_returns_honest_web_fallback(monkeypatch):
    def fail_request(*args, **kwargs):
        raise RuntimeError("远程服务返回 HTTP 503")

    monkeypatch.setattr(research_tools, "_request_json", fail_request)

    result = research_tools.search_paper_atlas("climate change")

    assert result["status"] == "external"
    assert result["items"] == []
    assert result["external_url"] == "https://paperatlas.scansci.com/"
    assert "503" in result["message"]


def test_capability_snapshot_marks_paper_atlas_as_web_handoff(tmp_path: Path):
    evidence = tmp_path / "evidence.sqlite"
    evidence.write_bytes(b"")

    snapshot = research_tools.capability_snapshot(workspace=tmp_path / "workspace.sqlite", evidence_db=evidence)
    atlas = next(item for item in snapshot["tools"] if item["id"] == "paper-atlas")

    assert atlas["status"] == "external"

