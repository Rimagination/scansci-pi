import json
from pathlib import Path

from scansci_html import local_model_market
from scansci_html import app_settings
from scansci_html import research_agent
from scansci_html import research_tools


def test_model_root_uses_per_user_local_app_data(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("SCANSCI_MODEL_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert local_model_market.model_root() == tmp_path / "ScanSci" / "models"
    assert local_model_market.hub_cache_root() == tmp_path / "ScanSci" / "models" / "HuggingFace" / "hub"


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


def test_arxiv_download_uses_the_authoritative_public_archive_even_when_cli_exists(tmp_path: Path, monkeypatch):
    destination = tmp_path / "downloads" / "1706.03762.pdf"
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")
    monkeypatch.setattr(
        research_tools.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("arXiv must not use the optional CLI")),
    )
    monkeypatch.setattr(
        research_tools,
        "_download_public_pdf",
        lambda _candidate, output_dir, identifier, timeout: destination,
    )

    result = research_tools.download_paper("1706.03762", workspace=tmp_path / "workspace.sqlite")

    assert result["source"] == "arXiv"
    assert result["files"] == [str(destination)]


def test_public_fulltext_candidates_prioritize_unpaywall_and_europe_pmc(monkeypatch):
    monkeypatch.setenv("SCANSCI_UNPAYWALL_EMAIL", "researcher@example.org")

    def fake_request(url, *, timeout):
        assert timeout == 12
        if "api.unpaywall.org" in url:
            return {
                "best_oa_location": {
                    "url_for_pdf": "https://repository.test/paper.pdf",
                    "host_type": "repository",
                },
                "oa_locations": [],
            }
        if "europepmc" in url:
            return {
                "resultList": {
                    "result": [
                        {
                            "pmcid": "PMC123",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {
                                        "documentStyle": "pdf",
                                        "availability": "Open access",
                                        "url": "https://europepmc.test/PMC123.pdf",
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        if "openalex.org" in url:
            return {}
        if "crossref.org" in url:
            return {"message": {}}
        raise AssertionError(url)

    monkeypatch.setattr(research_tools, "_request_json", fake_request)

    candidates = research_tools._public_fulltext_candidates("10.1000/example", timeout=12)

    assert candidates[:2] == [
        {"url": "https://repository.test/paper.pdf", "source": "Unpaywall repository"},
        {"url": "https://europepmc.test/PMC123.pdf", "source": "Europe PMC open access"},
    ]


def test_arxiv_doi_resolves_without_waiting_for_metadata_apis(monkeypatch):
    monkeypatch.setattr(
        research_tools,
        "_request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("metadata API should not run")),
    )

    candidates = research_tools._public_fulltext_candidates("10.48550/arXiv.1706.03762", timeout=12)

    assert candidates == [{"url": "https://arxiv.org/pdf/1706.03762.pdf", "source": "arXiv"}]


def test_cli_success_without_a_pdf_falls_back_to_public_archive(tmp_path: Path, monkeypatch):
    destination = tmp_path / "downloads" / "paper.pdf"
    monkeypatch.setattr(research_tools.shutil, "which", lambda _name: "scansci-pdf")
    monkeypatch.setattr(
        research_tools.subprocess,
        "run",
        lambda *_args, **_kwargs: research_tools.subprocess.CompletedProcess(
            args=["scansci-pdf"], returncode=0, stdout="FAILED: login required", stderr=""
        ),
    )
    monkeypatch.setattr(
        research_tools,
        "_public_fulltext_candidates",
        lambda _identifier, timeout: [{"url": "https://example.test/paper.pdf", "source": "Open archive"}],
    )
    monkeypatch.setattr(
        research_tools,
        "_download_public_pdf",
        lambda _candidate, output_dir, identifier, timeout: destination,
    )

    result = research_tools.download_paper("10.1000/example", workspace=tmp_path / "workspace.sqlite")

    assert result["source"] == "Open archive"
    assert result["files"] == [str(destination)]
