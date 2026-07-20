import json
from pathlib import Path

from scansci_html import local_model_market
from scansci_html import app_settings
from scansci_html import research_agent
from scansci_html import research_tools


def test_installed_models_reads_huggingface_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SCANSCI_MODEL_ROOT", str(tmp_path))
    snapshot = tmp_path / "HuggingFace" / "hub" / "models--Qwen--Qwen2.5-1.5B-Instruct" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text(
        json.dumps({"model_type": "qwen2", "architectures": ["Qwen2ForCausalLM"]}), encoding="utf-8"
    )
    (snapshot / "model.safetensors").write_bytes(b"weights")

    rows = local_model_market.installed_models()

    assert rows == [
        {
            "id": "Qwen/Qwen2.5-1.5B-Instruct",
            "name": "Qwen/Qwen2.5-1.5B-Instruct",
            "path": str(snapshot),
            "size_bytes": (snapshot / "config.json").stat().st_size + len(b"weights"),
            "ready": True,
            "architecture": "Qwen2ForCausalLM",
            "model_type": "qwen2",
            "format": "transformers",
        }
    ]


def test_market_catalog_marks_cached_model_without_network(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SCANSCI_MODEL_ROOT", str(tmp_path))
    snapshot = tmp_path / "HuggingFace" / "hub" / "models--Qwen--Qwen2.5-1.5B-Instruct" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"weights")

    catalog = local_model_market.market_catalog()
    row = next(item for item in catalog["items"] if item["id"] == "Qwen/Qwen2.5-1.5B-Instruct")

    assert catalog["source"] == "curated"
    assert row["installed"] is True
    assert row["ready"] is True


def test_complete_chat_snapshot_is_exposed_as_local_provider(monkeypatch):
    monkeypatch.setattr(
        app_settings,
        "installed_models",
        lambda: [
            {
                "id": "Qwen/Qwen2.5-1.5B-Instruct",
                "name": "Qwen2.5 1.5B Instruct",
                "ready": True,
                "format": "transformers",
                "architecture": "Qwen2ForCausalLM",
                "model_type": "qwen2",
            },
            {
                "id": "Qwen/Qwen3-Embedding-0.6B",
                "name": "Qwen3 Embedding 0.6B",
                "ready": True,
                "format": "transformers",
                "architecture": "Qwen3Model",
                "model_type": "qwen3",
            },
        ],
    )

    settings = app_settings._normalize_settings({})
    provider = next(item for item in settings["providers"] if item["id"] == "local-huggingface")

    assert provider["kind"] == "local"
    assert provider["models"] == [
        {
            "id": "Qwen/Qwen2.5-1.5B-Instruct",
            "name": "Qwen2.5 1.5B Instruct",
            "group": "本地 Hugging Face",
            "context_window": "本机",
            "capabilities": ["reasoning", "coding"],
        }
    ]


def test_direct_chat_starts_loopback_runtime_for_huggingface_model(tmp_path: Path, monkeypatch):
    runtime = research_agent.ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    monkeypatch.setattr(
        research_agent,
        "load_settings",
        lambda _workspace: {
            "active_model": {"provider_id": "local-huggingface", "model_id": "Qwen/Qwen2.5-1.5B-Instruct"},
            "providers": [
                {
                    "id": "local-huggingface",
                    "kind": "local",
                    "enabled": True,
                    "base_url": "http://stale/v1",
                    "models": [{"id": "Qwen/Qwen2.5-1.5B-Instruct", "capabilities": ["reasoning"]}],
                }
            ],
        },
    )
    monkeypatch.setattr(research_agent, "ensure_local_transformers_runtime", lambda model_id: f"http://127.0.0.1:17863/v1/{model_id}")

    request = runtime._direct_chat_request({"messages": [{"role": "user", "content": "hello"}]})

    assert request.provider_kind == "openai-compatible"
    assert request.api_key == "local"
    assert request.base_url == "http://127.0.0.1:17863/v1/Qwen/Qwen2.5-1.5B-Instruct"


def test_paper_download_workflow_can_start_without_notebook(tmp_path: Path, monkeypatch):
    runtime = research_agent.ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    monkeypatch.setattr(runtime, "_submit", lambda _run_id: None)

    run = runtime.start({"workflow_type": "paper_download", "identifier": "10.1000/example"})

    assert run["workflow_type"] == "paper_download"
    assert run["notebook_id"] == ""


def test_paper_download_falls_back_to_public_archives_without_cli(tmp_path: Path, monkeypatch):
    destination = tmp_path / "downloads" / "paper.pdf"
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: None)
    monkeypatch.setattr(research_tools, "_public_fulltext_candidates", lambda _identifier, timeout: [{"url": "https://example.test/paper.pdf", "source": "Institutional repository"}])
    monkeypatch.setattr(research_tools, "_download_public_pdf", lambda _candidate, output_dir, identifier, timeout: destination)

    result = research_tools.download_paper("10.1000/example", workspace=tmp_path / "workspace.sqlite", strategy="gray_oa")

    assert result["source"] == "Institutional repository"
    assert result["files"] == [str(destination)]
