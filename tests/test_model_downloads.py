from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import threading
import time

import pytest

from scansci_html import model_downloads
from scansci_html.model_downloads import ModelInstallManager


class _FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, status: int, headers: dict[str, str]):
        super().__init__(payload)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _file_record(source: Path, relative: str) -> dict[str, object]:
    payload = source.read_bytes()
    return {
        "path": relative,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "url": source.as_uri(),
    }


def test_install_manifest_builds_verified_huggingface_cache_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    config = source / "config.json"
    weights = source / "model.safetensors"
    config.write_text('{"model_type":"qwen3"}', encoding="utf-8")
    weights.write_bytes(b"verified-weights")
    events: list[dict[str, object]] = []

    installed = model_downloads._install_manifest(
        {
            "repo_id": "Qwen/Qwen3-Test",
            "source": "modelscope",
            "revision": "commit-123",
            "files": [
                _file_record(config, "config.json"),
                _file_record(weights, "model.safetensors"),
            ],
        },
        cache_root=tmp_path / "cache",
        progress_callback=events.append,
    )

    assert installed == tmp_path / "cache" / "models--Qwen--Qwen3-Test" / "snapshots" / "commit-123"
    assert (installed / "config.json").read_text(encoding="utf-8") == '{"model_type":"qwen3"}'
    assert (installed / "model.safetensors").read_bytes() == b"verified-weights"
    assert (installed / ".scansci-model.json").is_file()
    assert events[-1]["state"] == "ready"
    assert not list(installed.parent.glob(".*.partial"))


def test_auto_source_falls_back_from_modelscope_to_huggingface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "config.json"
    source.write_text("{}", encoding="utf-8")

    def unavailable(_repo_id: str) -> dict[str, object]:
        raise model_downloads.ModelSourceUnavailable("domestic route unavailable")

    monkeypatch.setattr(model_downloads, "_modelscope_manifest", unavailable)
    monkeypatch.setattr(
        model_downloads,
        "_huggingface_manifest",
        lambda repo_id: {
            "repo_id": repo_id,
            "source": "huggingface",
            "revision": "hf-commit",
            "files": [_file_record(source, "config.json")],
        },
    )

    result = model_downloads.download_snapshot(
        "Qwen/Qwen3-Test",
        cache_root=tmp_path / "cache",
    )

    assert result["source"] == "huggingface"
    assert result["fallback_used"] is True
    assert "modelscope:" in result["source_failures"][0]


def test_binary_download_rejects_small_html_error_without_writing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<html>mirror access denied</html>"
    monkeypatch.setattr(
        model_downloads.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            payload,
            status=200,
            headers={"Content-Type": "text/html", "Content-Length": str(len(payload))},
        ),
    )
    destination = tmp_path / "model.safetensors"

    with pytest.raises(model_downloads.InvalidModelResponse, match="错误页"):
        model_downloads._download_file(
            "https://modelscope.example/model.safetensors",
            destination,
            expected_size=1024 * 1024,
            expected_sha256="",
            progress_callback=None,
        )

    assert not destination.exists()
    assert not (tmp_path / "model.safetensors.download").exists()


def test_http_model_download_uses_verified_ranges_and_discards_legacy_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified-model-bytes"
    ranges: list[str] = []
    monkeypatch.setattr(model_downloads, "_HTTP_RANGE_BYTES", 5)
    partial = tmp_path / "model.safetensors.download"
    partial.write_bytes(b"<bad legacy response>")

    def urlopen(request_object, **_kwargs):
        header = request_object.get_header("Range")
        ranges.append(header)
        match = model_downloads.re.fullmatch(r"bytes=(\d+)-(\d+)", header)
        assert match is not None
        start, end = int(match.group(1)), int(match.group(2))
        chunk = payload[start:end + 1]
        return _FakeResponse(
            chunk,
            status=206,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{len(payload)}",
            },
        )

    monkeypatch.setattr(model_downloads.request, "urlopen", urlopen)
    destination = tmp_path / "model.safetensors"

    size = model_downloads._download_file(
        "https://modelscope.example/model.safetensors",
        destination,
        expected_size=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        progress_callback=None,
    )

    assert size == len(payload)
    assert destination.read_bytes() == payload
    assert ranges[0] == "bytes=0-4"
    assert ranges[-1] == f"bytes=15-{len(payload) - 1}"
    assert not (tmp_path / "model.safetensors.download.json").exists()


def test_install_manager_reports_background_progress_and_completion(tmp_path: Path) -> None:
    ready: set[str] = set()

    def download(repo_id: str, *, cache_root: Path, source: str, progress_callback):
        assert cache_root == tmp_path
        assert source == "auto"
        progress_callback(
            {
                "source": "modelscope",
                "completed_bytes": 50,
                "total_bytes": 100,
                "progress": 0.5,
            }
        )
        ready.add(repo_id)
        return {"source": "modelscope"}

    manager = ModelInstallManager(
        cache_root=tmp_path,
        ready_checker=lambda model_id: model_id in ready,
        downloader=download,
    )
    started = manager.start(["Qwen/Embedding", "Qwen/Reranker"], job_id="retrieval-core")
    assert started["state"] == "queued"

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = manager.status("retrieval-core")
        if status["state"] == "ready":
            break
        time.sleep(0.01)

    assert status["state"] == "ready"
    assert status["progress"] == 1.0
    assert status["completed_models"] == ["Qwen/Embedding", "Qwen/Reranker"]
    assert manager.status()["active"] is None


def test_install_manager_keeps_failure_retryable(tmp_path: Path) -> None:
    attempts = 0
    ready = False

    def download(repo_id: str, **_kwargs):
        nonlocal attempts, ready
        attempts += 1
        if attempts == 1:
            raise OSError("temporary network failure")
        ready = True
        return {"source": "modelscope", "id": repo_id}

    manager = ModelInstallManager(
        cache_root=tmp_path,
        ready_checker=lambda _model_id: ready,
        downloader=download,
    )
    manager.start(["Qwen/Embedding"], job_id="retrieval-core")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("retrieval-core")["state"] != "failed":
        time.sleep(0.01)
    assert manager.status("retrieval-core")["state"] == "failed"

    manager.start(["Qwen/Embedding"], job_id="retrieval-core")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("retrieval-core")["state"] != "ready":
        time.sleep(0.01)
    assert manager.status("retrieval-core")["state"] == "ready"
    assert attempts == 2


def test_install_manager_restores_interrupted_job_and_keeps_it_retryable(tmp_path: Path) -> None:
    state_path = tmp_path / "jobs.json"
    state_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_id": "retrieval-core",
                        "state": "downloading",
                        "models": ["Qwen/Embedding"],
                        "completed_models": [],
                        "total_models": 1,
                        "completed_bytes": 25,
                        "total_bytes": 100,
                        "progress": 0.25,
                        "updated_at": int(time.time()) - 30,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ready = False

    def download(repo_id: str, **_kwargs):
        nonlocal ready
        ready = True
        return {"source": "modelscope", "id": repo_id}

    manager = ModelInstallManager(
        cache_root=tmp_path / "cache",
        state_path=state_path,
        ready_checker=lambda _model_id: ready,
        downloader=download,
    )

    restored = manager.status("retrieval-core")
    assert restored["state"] == "interrupted"
    assert "续传" in restored["message"]

    manager.start(["Qwen/Embedding"], job_id="retrieval-core")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("retrieval-core")["state"] != "ready":
        time.sleep(0.01)
    assert manager.status("retrieval-core")["state"] == "ready"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["state"] == "ready"


def test_install_manager_reports_stalled_active_download(tmp_path: Path) -> None:
    manager = ModelInstallManager(cache_root=tmp_path, ready_checker=lambda _model_id: False)
    with manager._lock:
        manager._jobs["slow"] = {
            "job_id": "slow",
            "state": "downloading",
            "models": ["Qwen/Embedding"],
            "updated_at": int(time.time()) - 120,
        }

    status = manager.status("slow")

    assert status["stalled"] is True
    assert status["last_update_seconds"] >= 90


def test_install_manager_pause_resume_cancel_and_retry_are_persistent_controls(tmp_path: Path) -> None:
    ready: set[str] = set()
    entered: dict[str, threading.Event] = {}
    attempts: dict[str, int] = {}

    def download(repo_id: str, *, progress_callback, **_kwargs):
        attempts[repo_id] = attempts.get(repo_id, 0) + 1
        signal = entered.setdefault(repo_id, threading.Event())
        signal.set()
        for index in range(20):
            progress_callback(
                {
                    "source": "modelscope",
                    "completed_bytes": index,
                    "total_bytes": 20,
                    "progress": index / 20,
                }
            )
            time.sleep(0.01)
        ready.add(repo_id)
        return {"source": "modelscope", "id": repo_id}

    manager = ModelInstallManager(
        cache_root=tmp_path,
        ready_checker=lambda model_id: model_id in ready,
        downloader=download,
    )

    entered["Qwen/Pause"] = threading.Event()
    manager.start(["Qwen/Pause"], job_id="pause-job")
    assert entered["Qwen/Pause"].wait(1)
    requested = manager.pause("pause-job")
    assert requested["state"] in {"pausing", "paused"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("pause-job")["state"] != "paused":
        time.sleep(0.01)
    assert manager.status("pause-job")["state"] == "paused"
    resumed = manager.resume("pause-job")
    assert resumed["state"] in {"queued", "downloading"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("pause-job")["state"] != "ready":
        time.sleep(0.01)
    assert manager.status("pause-job")["state"] == "ready"
    assert attempts["Qwen/Pause"] == 2

    entered["Qwen/Cancel"] = threading.Event()
    manager.start(["Qwen/Cancel"], job_id="cancel-job")
    assert entered["Qwen/Cancel"].wait(1)
    requested = manager.cancel("cancel-job")
    assert requested["state"] in {"cancelling", "cancelled"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("cancel-job")["state"] != "cancelled":
        time.sleep(0.01)
    assert manager.status("cancel-job")["state"] == "cancelled"
    assert "临时文件" in manager.status("cancel-job")["message"]
    retried = manager.retry("cancel-job")
    assert retried["state"] in {"queued", "downloading"}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and manager.status("cancel-job")["state"] != "ready":
        time.sleep(0.01)
    assert manager.status("cancel-job")["state"] == "ready"
    assert attempts["Qwen/Cancel"] == 2
