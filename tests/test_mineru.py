from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

from scansci_html import mineru


class _Response:
    def __init__(self, *, status_code: int = 200, payload: object | None = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\nfixture")
    return path


def test_agent_api_upload_poll_and_download_returns_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _pdf(tmp_path / "paper.pdf")
    calls: list[tuple[str, str]] = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/parse/file"):
            return _Response(payload={"code": 0, "data": {"task_id": "task-1", "file_url": "https://upload.test/file"}})
        assert url.endswith("/parse/task-1")
        return _Response(payload={"code": 0, "data": {"state": "done", "markdown_url": "https://result.test/paper.md"}})

    monkeypatch.setattr(mineru.requests, "request", request)
    monkeypatch.setattr(mineru.requests, "put", lambda *args, **kwargs: _Response(status_code=200))
    monkeypatch.setattr(mineru.requests, "get", lambda *args, **kwargs: _Response(content=b"# Clean paper\n\nResults"))
    monkeypatch.setattr(mineru.time, "sleep", lambda _seconds: None)

    result = mineru.mineru_convert(source, api_key="secret", timeout=2, poll_interval=0)

    assert result == "# Clean paper\n\nResults"
    assert calls == [
        ("POST", "https://mineru.net/api/v1/agent/parse/file"),
        ("GET", "https://mineru.net/api/v1/agent/parse/task-1"),
    ]


def test_precision_api_extracts_markdown_from_safe_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _pdf(tmp_path / "large-paper.pdf")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("large-paper/full.md", "# Precision paper\n\nTable")
    archive_content = archive_buffer.getvalue()
    calls: list[str] = []

    def request(method, url, **kwargs):
        calls.append(url)
        if url.endswith("/file-urls/batch"):
            return _Response(payload={"code": 0, "data": {"batch_id": "batch-1", "file_urls": ["https://upload.test/file"]}})
        assert url.endswith("/extract-results/batch/batch-1")
        return _Response(payload={"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": "https://result.test/archive.zip"}]}})

    monkeypatch.setattr(mineru.requests, "request", request)
    monkeypatch.setattr(mineru.requests, "put", lambda *args, **kwargs: _Response(status_code=200))
    monkeypatch.setattr(mineru.requests, "get", lambda *args, **kwargs: _Response(content=archive_content))
    monkeypatch.setattr(mineru.time, "sleep", lambda _seconds: None)

    result = mineru.mineru_convert(source, api_key="secret", api_mode="precision", timeout=2, poll_interval=0)

    assert result == "# Precision paper\n\nTable"
    assert calls == [
        "https://mineru.net/api/v4/file-urls/batch",
        "https://mineru.net/api/v4/extract-results/batch/batch-1",
    ]


def test_auto_mode_falls_back_to_precision_on_agent_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _pdf(tmp_path / "paper.pdf")
    calls: list[str] = []

    def request(method, url, **kwargs):
        calls.append(url)
        if "/api/v1/agent/" in url:
            return _Response(status_code=429, content=b"rate limited")
        if url.endswith("/file-urls/batch"):
            return _Response(payload={"code": 0, "data": {"batch_id": "batch-2", "file_urls": ["https://upload.test/file"]}})
        return _Response(payload={"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": "https://result.test/archive.zip"}]}})

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("full.md", "fallback")
    monkeypatch.setattr(mineru.requests, "request", request)
    monkeypatch.setattr(mineru.requests, "put", lambda *args, **kwargs: _Response(status_code=200))
    monkeypatch.setattr(mineru.requests, "get", lambda *args, **kwargs: _Response(content=archive_buffer.getvalue()))
    monkeypatch.setattr(mineru.time, "sleep", lambda _seconds: None)

    assert mineru.mineru_convert(source, api_key="secret", timeout=2, poll_interval=0) == "fallback"
    assert calls[0].endswith("/api/v1/agent/parse/file")
    assert calls[1].endswith("/api/v4/file-urls/batch")


def test_result_zip_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _pdf(tmp_path / "paper.pdf")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../../outside.md", "bad")
    with pytest.raises(mineru.MinerUError, match="不安全路径"):
        mineru._safe_extract(zipfile.ZipFile(io.BytesIO(archive_buffer.getvalue())), tmp_path / "out")

