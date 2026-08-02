from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import pytest

from scansci_html import model_downloads
from scansci_html.model_downloads import ModelInstallManager


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
