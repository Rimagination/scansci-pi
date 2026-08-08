from pathlib import Path

from scansci_html import ollama_runtime


def test_ollama_status_recognizes_the_exact_minicpm_tag(monkeypatch):
    def fake_request(_base, path, **_kwargs):
        if path == "/api/version":
            return {"version": "0.11.0"}
        return {"models": [{"name": "minicpm-v4.6:latest"}]}

    monkeypatch.setattr(ollama_runtime, "_request_json", fake_request)
    status = ollama_runtime.ollama_status()

    assert status["reachable"] is True
    assert status["model_ready"] is True
    assert status["model_id"] == "minicpm-v4.6"


def test_ollama_install_manager_reuses_an_already_pulled_model(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        ollama_runtime,
        "ollama_status",
        lambda _base: {"reachable": True, "model_ready": True, "error": ""},
    )
    completed = []
    manager = ollama_runtime.OllamaInstallManager(state_path=tmp_path / "jobs.json")
    job = manager.start(on_complete=completed.append)

    assert job["state"] == "ready"
    assert job["progress"] == 1.0
    assert completed and completed[0]["current_model"] == "minicpm-v4.6"


def test_ollama_install_manager_marks_previous_stream_as_interrupted(tmp_path: Path):
    state_path = tmp_path / "jobs.json"
    state_path.write_text(
        '{"jobs":[{"job_id":"ollama:minicpm-v4.6","state":"downloading","progress":0.4}]}'
    )

    manager = ollama_runtime.OllamaInstallManager(state_path=state_path)

    job = manager.status("ollama:minicpm-v4.6")
    assert job["state"] == "interrupted"
    assert "继续下载" in job["message"]
