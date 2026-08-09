from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

import scansci_html.pi_agent as pi_agent
from scansci_html.app_settings import load_settings, save_settings
from scansci_html.pi_agent import (
    PiAgentClient,
    _ManagedGatewayAdapter,
    _bounded_tool_result_for_model,
    _compact_verified_answer_for_model,
    _parse_text_tool_intents,
    _redact_tool_value,
)
from scansci_html.research_runs import ResearchRunStore, StageSpec
from scansci_html.workspace import initialize_notebook


def test_disabling_zotero_plugin_removes_native_zotero_tools_from_pi(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    settings = load_settings(workspace)
    for plugin in settings["plugins"]:
        if plugin["id"] == "zotero":
            plugin["enabled"] = False
    save_settings(workspace, settings)
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    disabled = set(client._disabled_artifact_tools())

    assert {
        "zotero_search",
        "zotero_fulltext",
        "zotero_attachment",
        "zotero_export_bibtex",
        "zotero_citations",
    } <= disabled
    assert "zotero_status" not in disabled


def test_pi_reads_only_documents_registered_by_the_active_task(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    paper = tmp_path / "downloaded-paper.txt"
    paper.write_text(
        "Canopy photosynthesis and plant respiration jointly determine forest carbon balance.",
        encoding="utf-8",
    )
    unrelated = tmp_path / "unrelated-secret.txt"
    unrelated.write_text("This must not be returned.", encoding="utf-8")
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="",
        workflow_type="paper_download_batch",
        title="Downloaded papers",
        input_payload={"identifiers": ["10.1/example"]},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    artifact = store.create_artifact(
        run["run_id"],
        artifact_type="downloaded_paper",
        title="Downloaded papers",
        summary="Downloaded 1 paper",
        payload={
            "files": [str(paper)],
            "imported": {
                "workspace": {
                    "notebooks": [
                        {
                            "root_path": str(unrelated),
                            "metadata": {"source_file": str(unrelated)},
                        }
                    ]
                }
            },
        },
    )
    store.complete_run(run["run_id"], output_artifact_id=artifact["artifact_id"])
    client = PiAgentClient(
        workspace=workspace,
        evidence_db=tmp_path / "evidence.sqlite",
        active_run_id=run["run_id"],
    )

    result = client._execute_tool(
        "read_task_documents",
        {"path": str(unrelated), "max_files": 20, "per_file_chars": 4000},
    )

    assert result["ok"] is True
    assert result["run_id"] == run["run_id"]
    assert result["document_count"] == 1
    assert result["documents"][0]["name"] == paper.name
    assert "forest carbon balance" in result["documents"][0]["excerpt"]
    assert unrelated.name not in {item["name"] for item in result["documents"]}


def test_pi_task_document_result_stays_within_gateway_budget(tmp_path: Path, monkeypatch) -> None:
    paths = []
    for index in range(20):
        paper = tmp_path / f"paper-{index}.txt"
        paper.write_text(
            f"Paper {index} abstract and methods. " + ("Results and conclusion. " * 2_000),
            encoding="utf-8",
        )
        paths.append(paper)

    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    monkeypatch.setattr(
        client,
        "_task_run_with_documents",
        lambda _requested_run_id="": ({"run_id": "run-test", "title": "Papers", "workflow_type": "paper_download"}, paths),
    )

    result = client._read_task_documents({})
    encoded_size = len(json.dumps(result, ensure_ascii=False))

    assert result["document_count"] == 20
    assert encoded_size < 40_000
    assert "中间内容已省略" in result["documents"][0]["excerpt"]


def test_pi_workspace_inventory_is_compacted_before_model_context() -> None:
    result = {
        "workspace": "workspace.sqlite",
        "counts": {"notebooks": 1, "sources": 50_000},
        "notebooks": [
            {
                "notebook_id": "library",
                "title": "Large library",
                "description": "Evidence",
                "counts": {"sources": 50_000, "notes": 4, "layers": 2},
                "metadata": {"library_kind": "zotero"},
                "sources": [
                    {"title": f"Paper {index}", "fulltext": "large text " * 100}
                    for index in range(2_000)
                ],
            }
        ],
    }

    bounded, meta = _bounded_tool_result_for_model("inspect_workspace", result)

    assert meta["original_bytes"] > 1_000_000
    assert meta["model_bytes"] < 16_000
    assert meta["truncated"] is True
    assert meta["persist_full"] is False
    assert bounded["notebooks"][0]["counts"]["sources"] == 50_000
    assert "sources" not in bounded["notebooks"][0]


def test_pi_arbitrary_tool_result_has_a_hard_model_context_ceiling() -> None:
    bounded, meta = _bounded_tool_result_for_model(
        "mcp_result",
        {"items": [{"content": "证据" * 20_000} for _ in range(100)]},
    )

    assert meta["original_bytes"] > 1_000_000
    assert meta["model_bytes"] <= 16_000
    assert meta["truncated"] is True
    assert meta["persist_full"] is True
    assert bounded["_scansci_truncated"] is True


def test_pi_tool_results_redact_credentials_before_model_or_disk() -> None:
    secret = "sk-abcdefghijklmnop123456"
    result = _redact_tool_value(
        {
            "api_key": secret,
            "nested": {
                "authorization": f"Bearer {secret}",
                "url": f"https://example.test/data?access_token={secret}&page=1",
            },
        }
    )

    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["authorization"] == "[REDACTED]"
    assert "access_token=[REDACTED]" in result["nested"]["url"]
    assert secret not in json.dumps(result)


def test_pi_discover_papers_uses_federated_academic_search(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(query: str, **kwargs: object) -> dict[str, object]:
        captured.update({"query": query, **kwargs})
        return {"query": query, "count": 1, "items": [{"title": "A paper"}]}

    monkeypatch.setattr(pi_agent, "search_academic_papers", fake_search)
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
        embedding_provider="embedding-fixture",
        reranker="reranker-fixture",
    )

    result = client._execute_tool(
        "discover_papers",
        {
            "query": "scientific retrieval",
            "providers": ["openalex", "pubmed"],
            "year_from": 2021,
            "result_limit": 18,
            "per_source": 7,
        },
    )

    assert result["count"] == 1
    assert captured["query"] == "scientific retrieval"
    assert captured["query_variants"] == ["scientific retrieval"]
    assert captured["required_terms"] == ["scientific retrieval"]
    assert captured["provider_names"] == ["openalex", "pubmed"]
    assert captured["year_from"] == 2021
    assert captured["limit"] == 18
    assert captured["per_source"] == 7
    assert captured["embedding_provider"] == "embedding-fixture"
    assert captured["reranker"] == "reranker-fixture"
    assert result["search_plan"]["topic"] == "scientific retrieval"


def test_pi_discover_papers_keeps_full_result_off_model_and_accepts_limit_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    full_abstract = "A" * 20_000
    papers = [
        {
            "title": f"Paper {index}",
            "doi": f"10.1000/paper-{index}",
            "authors": [f"Author {author}" for author in range(10)],
            "abstract": full_abstract,
            "sources": ["openalex", "crossref"],
            "source_records": [{"source": "openalex", "payload": "B" * 4_000}],
            "score_breakdown": {"dense": 0.9, "reranker": 1.0},
            "score": 1.0 - index / 100,
            "discovery_only": True,
        }
        for index in range(10)
    ]

    def fake_search(query: str, **kwargs: object) -> dict[str, object]:
        captured.update({"query": query, **kwargs})
        return {
            "query": query,
            "count": len(papers),
            "candidate_count": 40,
            "deduplicated_count": len(papers),
            "providers_requested": ["openalex", "crossref"],
            "providers_succeeded": ["openalex", "crossref"],
            "provider_counts": {"openalex": 10, "crossref": 10},
            "provider_errors": {},
            "items": papers,
            "evidence_status": "discovery_leads",
        }

    monkeypatch.setattr(pi_agent, "search_academic_papers", fake_search)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool("discover_papers", {"query": "forest productivity", "limit": 10})

    assert captured["limit"] == 10
    assert captured["per_source"] == 8
    assert result["count"] == 8
    assert result["total_count"] == 10
    assert result["download_identifiers"] == [f"10.1000/paper-{index}" for index in range(10)]
    assert len(result["items"][0]["abstract_excerpt"]) == 600
    assert "source_records" not in result["items"][0]
    assert "score_breakdown" not in result["items"][0]
    assert len(json.dumps(result, ensure_ascii=False)) < 20_000

    full_result_path = client.agent_dir / result["full_result_reference"]
    assert full_result_path.is_file()
    persisted = json.loads(full_result_path.read_text(encoding="utf-8"))
    assert len(persisted["items"]) == 10
    assert persisted["items"][0]["abstract"] == full_abstract
    assert result["full_result_bytes"] == full_result_path.stat().st_size


def test_pi_search_local_evidence_federates_selected_knowledge_bases(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    first.touch()
    second.touch()
    calls: list[Path] = []

    def fake_search(path: str | Path, query: str, **_kwargs: object) -> list[dict[str, object]]:
        resolved = Path(path).resolve()
        calls.append(resolved)
        return [
            {
                "evidence_id": f"evidence-{resolved.stem}",
                "doc_id": f"doc-{resolved.stem}",
                "title": resolved.stem,
                "text": f"{query} from {resolved.stem}",
                "score": 0.9 if resolved == second.resolve() else 0.6,
            }
        ]

    monkeypatch.setattr(pi_agent, "search_evidence_store", fake_search)
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=first,
        additional_evidence_dbs=[second, first],
    )

    result = client._execute_tool("search_local_evidence", {"query": "shared claim", "result_limit": 8})

    assert calls == [first.resolve(), second.resolve()]
    assert result["library_count"] == 2
    assert result["count"] == 2
    assert [hit["library_index"] for hit in result["hits"]] == [1, 0]


def test_pi_build_verified_answer_federates_all_selected_evidence_stores(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    first.touch()
    second.touch()
    calls: list[Path] = []

    def fake_answer(path: str | Path, question: str, **_kwargs: object) -> dict[str, object]:
        resolved = Path(path).resolve()
        calls.append(resolved)
        label = resolved.stem
        return {
            "question": question,
            "reader_answer": {
                "text": f"Verified answer from {label}.",
                "citation_count": 1,
                "citations": [
                    {
                        "citation_id": f"citation-{label}",
                        "evidence_id": f"evidence-{label}",
                        "doc_id": f"doc-{label}",
                        "paper": f"Paper {label}",
                        "exact_quote": f"Evidence from {label}.",
                    }
                ],
            },
            "answer": {"insufficient_evidence": False, "limitations": []},
            "adequacy": {
                "is_sufficient": True,
                "quote_count": 1,
                "document_count": 1,
                "followup_reason": "",
            },
            "citation_verification": {
                "passed": True,
                "claim_count": 1,
                "supported_claim_count": 1,
                "missing_quote_ids": [],
            },
        }

    monkeypatch.setattr(pi_agent, "answer_question", fake_answer)
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=first,
        additional_evidence_dbs=[second],
    )

    result = client._execute_tool(
        "build_verified_answer",
        {"question": "What do the selected libraries show?", "result_limit": 8},
    )

    assert calls == [first.resolve(), second.resolve()]
    assert result["federated"] is True
    assert result["library_count"] == 2
    assert result["successful_library_count"] == 2
    assert result["citation_verification"]["passed"] is True
    assert {item["library_index"] for item in result["reader_answer"]["citations"]} == {0, 1}
    assert "Knowledge base 1" in result["reader_answer"]["text"]
    assert "Knowledge base 2" in result["reader_answer"]["text"]


def test_pi_download_and_index_persists_a_completed_high_level_task(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace.sqlite"
    root_evidence = tmp_path / "evidence.sqlite"
    initialize_notebook(workspace, notebook_id="library", title="Research library")
    first = tmp_path / "paper-a.pdf"
    second = tmp_path / "paper-b.pdf"
    first.write_bytes(b"%PDF-1.4 fixture a")
    second.write_bytes(b"%PDF-1.4 fixture b")
    captured: dict[str, object] = {}

    def fake_download(identifiers: list[str], **kwargs: object) -> dict[str, object]:
        captured["identifiers"] = identifiers
        captured.update(kwargs)
        return {"ok": True, "files": [str(first), str(second)], "failed": []}

    def fake_import(workspace_path: str | Path, evidence_path: str | Path, **kwargs: object) -> dict[str, object]:
        captured["workspace"] = Path(workspace_path).resolve()
        captured["evidence_db"] = Path(evidence_path).resolve()
        captured["import"] = kwargs
        return {"added_files": 2, "skipped_files": []}

    monkeypatch.setattr(pi_agent, "download_papers", fake_download)
    monkeypatch.setattr(pi_agent, "import_library_files", fake_import)
    client = PiAgentClient(
        workspace=workspace,
        evidence_db=tmp_path / "library.sqlite",
        root_evidence_db=root_evidence,
        notebook_ids=["library"],
    )

    result = client._execute_tool(
        "download_and_index",
        {"identifiers": ["10.1000/alpha", "10.1000/beta"], "strategy": "oa_first"},
    )
    persisted = ResearchRunStore(workspace).get_run(result["run_id"])

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["downloaded_file_count"] == 2
    assert result["evidence_status"] == "indexed_fulltext"
    assert persisted["status"] == "completed"
    assert persisted["output_artifact"]["payload"]["evidence_status"] == "indexed_fulltext"
    assert captured["evidence_db"] == root_evidence.resolve()
    assert captured["import"]["notebook_id"] == "library"


def test_pi_download_and_index_uses_default_library_and_ignores_missing_reported_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace.sqlite"
    paper = tmp_path / "paper.pdf"
    missing = tmp_path / "missing.pdf"
    paper.write_bytes(b"%PDF-1.4 fixture")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        pi_agent,
        "download_papers",
        lambda *_args, **_kwargs: {
            "ok": False,
            "completed": 1,
            "failed": 1,
            "files": [str(paper), str(missing)],
            "items": [
                {"identifier": "10.1000/ok", "status": "completed", "files": [str(paper)], "error": ""},
                {"identifier": "10.1000/missing", "status": "failed", "files": [], "error": "not found"},
            ],
        },
    )

    def fake_import(_workspace, _evidence_db, **kwargs):
        captured.update(kwargs)
        return {"added_files": 1, "skipped_files": []}

    monkeypatch.setattr(pi_agent, "import_library_files", fake_import)
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool(
        "download_and_index",
        {"identifiers": ["10.1000/ok", "10.1000/missing"]},
    )

    assert result["ok"] is False
    assert result["partial"] is True
    assert result["status"] == "failed"
    assert result["downloaded_file_count"] == 1
    assert result["files"] == [str(paper.resolve())]
    assert result["notebook_id"] == "pi-research-downloads"
    assert captured["notebook_id"] == "pi-research-downloads"
    assert captured["file_paths"] == [str(paper.resolve())]
    assert any(item.get("file") == str(missing) for item in result["failures"])
    summary = pi_agent.load_workspace_summary(workspace, notebook_id="pi-research-downloads")
    assert summary["notebooks"][0]["metadata"]["created_by"] == "pi-agent"


def test_failed_new_download_task_never_falls_back_to_older_documents(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace.sqlite"
    old_paper = tmp_path / "old-paper.txt"
    old_paper.write_text("Old task content must not be summarized.", encoding="utf-8")
    store = ResearchRunStore(workspace)
    old_run = store.create_run(
        notebook_id="",
        workflow_type="paper_download",
        title="Old completed task",
        input_payload={},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    artifact = store.create_artifact(
        old_run["run_id"],
        artifact_type="downloaded_paper",
        title="Old paper",
        summary="Old completed paper",
        payload={"files": [str(old_paper)]},
    )
    store.complete_run(old_run["run_id"], output_artifact_id=artifact["artifact_id"])
    monkeypatch.setattr(
        pi_agent,
        "download_papers",
        lambda identifiers, **_kwargs: {
            "ok": True,
            "files": [str(tmp_path / "missing-new-paper.pdf")],
            "items": [
                {
                    "identifier": identifiers[0],
                    "status": "completed",
                    "files": [str(tmp_path / "missing-new-paper.pdf")],
                    "error": "",
                }
            ],
        },
    )
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    with pytest.raises(RuntimeError, match="without a readable document"):
        client._execute_tool("download_and_index", {"identifiers": ["10.1000/new"]})
    read_result = client._read_task_documents({})

    assert client.active_run_id != old_run["run_id"]
    assert read_result["run_id"] == client.active_run_id
    assert read_result["document_count"] == 0
    assert old_paper.name not in json.dumps(read_result, ensure_ascii=False)


def test_pi_summarize_documents_maps_full_task_files_by_research_aspect(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    paper = tmp_path / "paper.txt"
    paper.write_text(
        "Abstract. We ask how forest productivity responds to drought.\n\n"
        "Methods. We analyzed a 20-year satellite dataset with a hierarchical model.\n\n"
        "Results. Productivity declined significantly during repeated drought events.\n\n"
        "Limitations. The observational design cannot isolate every causal mechanism.",
        encoding="utf-8",
    )
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="",
        workflow_type="paper_download",
        title="Downloaded paper",
        input_payload={"identifier": "10.1000/example"},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    artifact = store.create_artifact(
        run["run_id"],
        artifact_type="downloaded_paper",
        title="Downloaded paper",
        summary="Downloaded 1 paper",
        payload={"files": [str(paper)], "evidence_status": "indexed_fulltext"},
    )
    store.complete_run(run["run_id"], output_artifact_id=artifact["artifact_id"])
    client = PiAgentClient(
        workspace=workspace,
        evidence_db=tmp_path / "evidence.sqlite",
        active_run_id=run["run_id"],
    )

    result = client._execute_tool(
        "summarize_documents",
        {"focus": "drought productivity", "max_files": 8},
    )

    assert result["ok"] is True
    assert result["coverage"] == 1.0
    assert result["document_count"] == 1
    mapped = result["documents"][0]
    assert "forest productivity" in mapped["research_question"]
    assert "hierarchical model" in mapped["methods"]
    assert "declined significantly" in mapped["findings"]
    assert "observational design" in mapped["limitations"]


def test_pi_check_task_completion_requires_indexed_downloads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4 fixture")
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="library",
        workflow_type="paper_download",
        title="Downloaded paper",
        input_payload={"identifier": "10.1000/example"},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    store.begin_run(run["run_id"])
    store.start_stage(run["run_id"], "deliver")
    store.complete_stage(run["run_id"], "deliver", output={"files": [str(paper)]})
    artifact = store.create_artifact(
        run["run_id"],
        artifact_type="downloaded_paper",
        title="Downloaded paper",
        summary="Downloaded only",
        payload={"files": [str(paper)], "evidence_status": "downloaded_unindexed"},
    )
    store.complete_run(run["run_id"], output_artifact_id=artifact["artifact_id"])
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool("check_task_completion", {"run_id": run["run_id"]})

    assert result["complete"] is False
    assert result["checks"]["run_completed"] is True
    assert result["checks"]["fulltext_indexed"] is False
    assert result["checks"]["downloaded_files"] == 1
    assert result["blockers"] == ["fulltext_indexed"]


def test_pi_kb_search_routes_selected_zotero_library_to_native_adapter(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace.sqlite"
    initialize_notebook(
        workspace,
        notebook_id="zotero-library",
        title="Zotero 文献库",
        metadata={"library_kind": "zotero", "zotero": {"connected": True}},
    )
    captured: dict[str, object] = {}

    def fake_zotero_search(query: str, **kwargs: object) -> dict[str, object]:
        captured.update({"query": query, **kwargs})
        return {"ok": True, "count": 2, "items": [{"title": "Paper A"}, {"title": "Paper B"}]}

    monkeypatch.setattr(pi_agent, "search_zotero_library", fake_zotero_search)
    client = PiAgentClient(
        workspace=workspace,
        evidence_db=tmp_path / "evidence.sqlite",
        notebook_ids=["zotero-library"],
    )

    result = client._execute_tool("kb_search", {"query": "核心主题", "result_limit": 6})

    assert result["count"] == 2
    assert result["hits"] == []
    assert result["zotero"][0]["items"][0]["title"] == "Paper A"
    assert captured == {
        "query": "核心主题",
        "limit": 6,
        "collection_key": "",
        "include_fulltext": True,
    }


def test_pi_routes_selected_obsidian_vault_to_native_read_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Methods.md").write_text("# Methods\n\nHybrid retrieval uses embeddings and BM25.", encoding="utf-8")
    initialize_notebook(
        workspace,
        notebook_id="obsidian-vault",
        title="Research Vault",
        root_path=vault,
        metadata={"library_kind": "obsidian", "library_root": str(vault)},
    )
    client = PiAgentClient(
        workspace=workspace,
        evidence_db=tmp_path / "evidence.sqlite",
        notebook_ids=["obsidian-vault"],
    )

    status = client._execute_tool("obsidian_status", {})
    search = client._execute_tool("obsidian_search", {"query": "hybrid retrieval", "result_limit": 5})
    note = client._execute_tool("obsidian_read", {"note_path": "Methods.md"})

    assert status["vaults"][0]["read_only"] is True
    assert search["vaults"][0]["results"][0]["title"] == "Methods"
    assert "BM25" in note["content"]


def test_pi_search_web_uses_public_web_boundary(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(query: str, **kwargs: object) -> dict[str, object]:
        captured.update({"query": query, **kwargs})
        return {"query": query, "count": 1, "items": [{"title": "Market close"}]}

    monkeypatch.setattr(pi_agent, "search_public_web", fake_search)
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool("search_web", {"query": "today A-share market", "result_limit": 6})

    assert result["count"] == 1
    assert captured == {"query": "today A-share market", "limit": 6}


def test_managed_gateway_retries_transient_ssl_transport_errors(monkeypatch) -> None:
    attempts = 0

    def flaky_post(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise pi_agent.requests.exceptions.SSLError("temporary EOF")
        return SimpleNamespace(status_code=200, headers={})

    monkeypatch.setattr(pi_agent.requests, "post", flaky_post)
    monkeypatch.setattr(pi_agent.time, "sleep", lambda _delay: None)
    adapter = _ManagedGatewayAdapter(upstream_base_url="https://gateway.example/v1", api_key="fixture")
    try:
        response = adapter._post_with_transport_retry({"model": "fixture-model"})
    finally:
        adapter.close()

    assert response.status_code == 200
    assert attempts == 2


def test_managed_gateway_honors_bounded_upstream_retry_after(monkeypatch) -> None:
    attempts = 0
    waits: list[float] = []

    def rate_limited_then_ready(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return SimpleNamespace(status_code=429, headers={"Retry-After": "90"})
        return SimpleNamespace(status_code=200, headers={})

    monkeypatch.setattr(pi_agent.requests, "post", rate_limited_then_ready)
    monkeypatch.setattr(pi_agent.time, "sleep", waits.append)
    adapter = _ManagedGatewayAdapter(upstream_base_url="https://gateway.example/v1", api_key="fixture")
    try:
        response = adapter._post_with_transport_retry({"model": "fixture-model"})
    finally:
        adapter.close()

    assert response.status_code == 200
    assert attempts == 2
    assert waits == [60.0]


def test_managed_gateway_labels_input_limit_for_pi_auto_compaction(monkeypatch) -> None:
    error_text = json.dumps(
        {
            "code": "invalid_request",
            "message": "The request body is empty or exceeds the managed service input limit.",
        }
    )

    def reject_oversized(_payload: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=400,
            headers={},
            text=error_text,
            json=lambda: json.loads(error_text),
        )

    adapter = _ManagedGatewayAdapter(upstream_base_url="https://gateway.example/v1", api_key="fixture")
    monkeypatch.setattr(adapter, "_post_with_transport_retry", reject_oversized)
    try:
        response = pi_agent.requests.post(
            f"{adapter.base_url}/chat/completions",
            json={
                "model": "fixture-model",
                "messages": [{"role": "user", "content": "large context"}],
                "stream": True,
            },
            timeout=5,
        )
    finally:
        adapter.close()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"
    assert "managed service input limit" in response.json()["error"]["message"]


class _OpenAIStreamHandler(BaseHTTPRequestHandler):
    request_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(length))
        chunks = [
            {
                "id": "chatcmpl-scanscipi",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Pi bridge works"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-scanscipi",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 105,
                    "completion_tokens": 3,
                    "total_tokens": 108,
                    "prompt_tokens_details": {"cached_tokens": 100},
                },
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAIToolLoopHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        if len(type(self).request_payloads) == 1:
            chunks = [
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_workspace",
                                        "type": "function",
                                        "function": {"name": "inspect_available_tools", "arguments": "{}"},
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            ]
        else:
            chunks = [
                {
                    "id": "chatcmpl-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Tool result received"}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAIDeferredWebHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        turn = len(type(self).request_payloads)
        if turn == 1:
            chunks = [
                {
                    "id": "chatcmpl-plan",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "现在开始执行调研，请稍候。"}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl-plan",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
        elif turn == 2:
            chunks = [
                {
                    "id": "chatcmpl-search",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [{
                                "index": 0,
                                "id": "call_web",
                                "type": "function",
                                "function": {"name": "search_web", "arguments": '{"query":"today A-share market"}'},
                            }],
                        },
                        "finish_reason": None,
                    }],
                },
                {
                    "id": "chatcmpl-search",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            ]
        else:
            chunks = [
                {
                    "id": "chatcmpl-result",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "已完成检索，并根据来源给出最终市场概况。"}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl-result",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
        body = "".join(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAITerminalToolHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payloads.append(json.loads(self.rfile.read(length)))
        chunks = [
            {
                "id": "chatcmpl-terminal",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_verified",
                                    "type": "function",
                                    "function": {
                                        "name": "build_verified_answer",
                                        "arguments": '{"question":"question"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-terminal",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAIPersistentHandler(BaseHTTPRequestHandler):
    request_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).request_payloads.append(payload)
        response_text = f"turn-{len(type(self).request_payloads)}"
        chunks = [
            {
                "id": "chatcmpl-session",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": response_text}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-session",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAIHighUsageHandler(BaseHTTPRequestHandler):
    """One successful answer whose billed usage crosses the soft lease."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        chunks = [
            {
                "id": "chatcmpl-high-usage",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "completed answer"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-high-usage",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20_000, "completion_tokens": 32, "total_tokens": 20_032},
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OpenAISlowHandler(BaseHTTPRequestHandler):
    started = threading.Event()
    release = threading.Event()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        first = {
            "id": "chatcmpl-slow",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fixture-model",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "working"}, "finish_reason": None}],
        }
        self.wfile.write(f"data: {json.dumps(first)}\n\n".encode("utf-8"))
        self.wfile.flush()
        type(self).started.set()
        type(self).release.wait(timeout=15)
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_pi_sidecar_responds_to_runtime_probe() -> None:
    status = PiAgentClient.runtime_status()

    assert status["ready"] is True
    assert status["runtime"] == "pi"
    assert status["version"] == "0.80.10"
    assert status["protocol"] == 3
    assert {
        "multi_session",
        "ask_user",
        "plan_approval",
        "follow_up",
        "structured_recovery",
        "session_fork",
    }.issubset(set(status["capabilities"]))


def test_pi_stream_forwards_host_owned_task_contract(tmp_path: Path, monkeypatch) -> None:
    client = PiAgentClient(
        workspace=tmp_path / "workspace.sqlite",
        evidence_db=tmp_path / "evidence.sqlite",
    )
    captured: dict = {}

    def fake_run_request(start_message, *, api_key, timeout_seconds):
        captured.update(start_message)
        assert api_key == "secret"
        assert timeout_seconds == 30
        yield {"type": "done", "stats": {}, "truncated": False}

    monkeypatch.setattr(client, "_run_request", fake_run_request)
    events = list(
        client.stream_chat(
            provider_kind="openai-compatible",
            base_url="https://example.test/v1",
            api_key="secret",
            model_id="fixture",
            messages=[{"role": "user", "content": "search my library"}],
            task_mode="knowledge",
            task_contract={
                "contract_id": "contract-test",
                "risk_level": "read_only",
                "allowed_tools": ["kb_search"],
            },
            timeout_seconds=30,
        )
    )

    assert events[-1]["type"] == "done"
    assert captured["task_contract"]["contract_id"] == "contract-test"
    assert captured["task_contract"]["allowed_tools"] == ["kb_search"]


def test_managed_gateway_adapter_only_parses_explicit_tool_intents() -> None:
    assert _parse_text_tool_intents('[TOOL CALL]\ntool_call(name="inspect_available_tools")') == [
        ("inspect_available_tools", {})
    ]
    assert _parse_text_tool_intents('<SCANSCI_TOOL_CALL>{"name":"verify_doi","arguments":{"doi":"10.1/x"}}</SCANSCI_TOOL_CALL>') == [
        ("verify_doi", {"doi": "10.1/x"})
    ]
    assert _parse_text_tool_intents('{"name":"build_verified_answer","arguments":{"question":"q"}}') == [
        ("build_verified_answer", {"question": "q"})
    ]
    assert _parse_text_tool_intents(
        '{"name":"build_verified_answer","arguments":"{\\"question\\":\\"q\\"}"}'
    ) == [("build_verified_answer", {"question": "q"})]


def test_managed_gateway_adapter_names_the_single_mandatory_tool_exactly() -> None:
    payload = _ManagedGatewayAdapter._normalize_payload(
        {
            "messages": [{"role": "user", "content": "Continue\n\n[USER]\nquestion"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "build_verified_answer",
                        "parameters": {
                            "type": "object",
                            "properties": {"question": {"type": "string"}},
                            "required": ["question"],
                        },
                    },
                }
            ],
        }
    )

    instruction = payload["messages"][0]["content"]
    assert '"name":"build_verified_answer"' in instruction
    assert '"question":"question"' in instruction
    assert "exact JSON object" in instruction
    assert payload["max_tokens"] == 192
    assert payload["temperature"] == 0
    assert payload["thinking"] == {"type": "disabled"}


def test_managed_gateway_adapter_closes_completed_tool_loop_briefly() -> None:
    payload = _ManagedGatewayAdapter._normalize_payload(
        {
            "messages": [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "function": {"name": "build_verified_answer"}}]},
                {"role": "tool", "tool_call_id": "call-1", "content": "large verified result"},
            ],
            "tools": [{"type": "function", "function": {"name": "build_verified_answer", "parameters": {}}}],
            "tool_choice": "auto",
            "max_tokens": 16384,
        }
    )

    assert "Reply with DONE only" in payload["messages"][0]["content"]
    assert payload["max_tokens"] == 16
    assert payload["temperature"] == 0
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tools"] == []
    assert "tool_choice" not in payload


def test_managed_gateway_adapter_synthesizes_non_terminal_web_tool_result() -> None:
    payload = _ManagedGatewayAdapter._normalize_payload(
        {
            "messages": [
                {"role": "user", "content": "today's market"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call-web", "function": {"name": "search_web"}}]},
                {"role": "tool", "tool_call_id": "call-web", "content": '{"items":[{"url":"https://example.com"}]}'},
            ],
            "tools": [{"type": "function", "function": {"name": "search_web", "parameters": {}}}],
            "tool_choice": "auto",
            "max_tokens": 16384,
        }
    )

    instruction = payload["messages"][0]["content"]
    assert "Use those results to answer" in instruction
    assert "Reply with DONE only" not in instruction
    assert payload["max_tokens"] == 16384
    assert payload["tools"] == []
    assert "tool_choice" not in payload


def test_managed_gateway_orchestrates_explicit_download_index_and_summary_workflow() -> None:
    available_tools = [
        {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
        for name in ("discover_papers", "download_and_index", "summarize_documents", "check_task_completion")
    ]
    request = {
        "messages": [
            {
                "role": "user",
                "content": "搜索并下载 8 篇 Peter B. Reich 关于森林生产力的论文，完成全文索引，然后比较研究方法和主要结论。",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-discover", "function": {"name": "discover_papers"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-discover",
                "content": json.dumps(
                    {"download_identifiers": [f"10.1000/paper-{index}" for index in range(12)]}
                ),
            },
        ],
        "tools": available_tools,
    }

    download = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert download is not None
    assert download["function"]["name"] == "download_and_index"
    assert json.loads(download["function"]["arguments"]) == {
        "identifiers": [f"10.1000/paper-{index}" for index in range(8)]
    }

    default_request = json.loads(json.dumps(request))
    default_request["messages"][0]["content"] = (
        "搜索并下载 Peter B. Reich 关于森林生产力的论文，完成全文索引，然后比较主要结论。"
    )
    default_download = _ManagedGatewayAdapter._managed_followup_tool_call(default_request)
    assert default_download is not None
    assert json.loads(default_download["function"]["arguments"]) == {
        "identifiers": [f"10.1000/paper-{index}" for index in range(3)]
    }

    request["messages"].extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-download", "function": {"name": "download_and_index"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-download",
                "content": json.dumps({"ok": True, "run_id": "run-1"}),
            },
        ]
    )
    summarize = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert summarize is not None
    assert summarize["function"]["name"] == "summarize_documents"
    assert json.loads(summarize["function"]["arguments"]) == {"run_id": "run-1"}

    request["messages"].extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-summary", "function": {"name": "summarize_documents"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-summary",
                "content": json.dumps({"ok": True, "run_id": "run-1", "documents": []}),
            },
        ]
    )
    completion = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert completion is not None
    assert completion["function"]["name"] == "check_task_completion"
    assert json.loads(completion["function"]["arguments"]) == {"run_id": "run-1"}


def test_managed_gateway_downloads_an_exact_doi_without_fuzzy_discovery() -> None:
    request = {
        "messages": [
            {
                "role": "user",
                "content": "下载 DOI 10.2307/2679812，完成全文索引并写一篇综述。",
            }
        ],
        "tools": [
            {"type": "function", "function": {"name": "discover_papers", "parameters": {}}},
            {"type": "function", "function": {"name": "download_and_index", "parameters": {}}},
            {"type": "function", "function": {"name": "summarize_documents", "parameters": {}}},
        ],
    }

    call = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert call is not None
    assert call["function"]["name"] == "download_and_index"
    assert json.loads(call["function"]["arguments"]) == {"identifiers": ["10.2307/2679812"]}


def test_managed_gateway_treats_chinese_review_as_synthesis() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "下载并索引这篇论文，然后写综述。"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-download", "function": {"name": "download_and_index"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-download",
                "content": json.dumps({"ok": True, "run_id": "run-review"}),
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "download_and_index", "parameters": {}}},
            {"type": "function", "function": {"name": "summarize_documents", "parameters": {}}},
            {"type": "function", "function": {"name": "check_task_completion", "parameters": {}}},
        ],
    }

    call = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert call is not None
    assert call["function"]["name"] == "summarize_documents"
    assert json.loads(call["function"]["arguments"]) == {"run_id": "run-review"}


def test_managed_gateway_creates_a_real_presentation_after_document_mapping() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "总结当前任务文献并创建一个实际可下载的 PPTX。"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-summary", "function": {"name": "summarize_documents"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-summary",
                "content": json.dumps(
                    {
                        "ok": True,
                        "run_id": "run-slides",
                        "query": "forest productivity",
                        "zotero": [
                            {
                                "items": [
                                    {
                                        "title": "Paper A",
                                        "methods": "Field experiment",
                                        "findings": "Productivity increased",
                                        "fulltext_excerpt": "Measured plot-level productivity.",
                                    }
                                ]
                            }
                        ],
                    }
                ),
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "summarize_documents", "parameters": {}}},
            {"type": "function", "function": {"name": "create_presentation", "parameters": {}}},
        ],
    }

    call = _ManagedGatewayAdapter._managed_followup_tool_call(request)
    arguments = json.loads(call["function"]["arguments"]) if call else {}

    assert call is not None
    assert call["function"]["name"] == "create_presentation"
    assert len(arguments["slides"]) >= 3
    assert any("Field experiment" in bullet for bullet in arguments["slides"][1]["bullets"])


def test_pi_check_task_completion_rejects_partial_requested_count(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace.sqlite"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4 fixture")
    store = ResearchRunStore(workspace)
    run = store.create_run(
        notebook_id="library",
        workflow_type="paper_download_batch",
        title="Partial batch",
        input_payload={"identifiers": ["10.1000/a", "10.1000/b"]},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    store.begin_run(run["run_id"])
    store.start_stage(run["run_id"], "deliver")
    store.complete_stage(run["run_id"], "deliver", output={"files": [str(paper)]})
    artifact = store.create_artifact(
        run["run_id"],
        artifact_type="downloaded_papers",
        title="Partial batch",
        summary="One of two",
        payload={
            "files": [str(paper)],
            "evidence_status": "indexed_fulltext",
            "requested_identifiers": ["10.1000/a", "10.1000/b"],
            "requested_count": 2,
            "successful_count": 1,
            "requested_count_satisfied": False,
            "failure_records": [{"identifier": "10.1000/b", "error": "timeout"}],
        },
    )
    store.complete_run(run["run_id"], output_artifact_id=artifact["artifact_id"])
    client = PiAgentClient(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    result = client._execute_tool("check_task_completion", {"run_id": run["run_id"]})

    assert result["complete"] is False
    assert result["checks"]["requested_documents"] == 2
    assert result["checks"]["successful_documents"] == 1
    assert {"requested_count_satisfied", "download_failures"} <= set(result["blockers"])


def test_managed_gateway_does_not_download_when_user_only_asked_to_search() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "搜索 Peter B. Reich 关于森林生产力的论文。"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-discover", "function": {"name": "discover_papers"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-discover",
                "content": json.dumps({"download_identifiers": ["10.1000/paper"]}),
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "discover_papers", "parameters": {}}},
            {"type": "function", "function": {"name": "download_and_index", "parameters": {}}},
        ],
    }

    assert _ManagedGatewayAdapter._managed_followup_tool_call(request) is None


def test_managed_gateway_never_advances_a_failed_tool_result() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "下载并总结论文。"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-download", "function": {"name": "download_and_index"}}],
            },
            {
                "role": "tool",
                "tool_call_id": "call-download",
                "content": "Error: downloader reported a missing file",
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "summarize_documents", "parameters": {}}},
            {"type": "function", "function": {"name": "check_task_completion", "parameters": {}}},
        ],
    }

    assert _ManagedGatewayAdapter._managed_followup_tool_call(request) is None


def test_managed_gateway_starts_explicit_recent_task_summary_without_model_guessing() -> None:
    request = {
        "messages": [
            {
                "role": "user",
                "content": "总结刚才下载并索引的论文，只比较当前任务中的文献。",
            }
        ],
        "tools": [
            {"type": "function", "function": {"name": "read_task_documents", "parameters": {}}},
            {"type": "function", "function": {"name": "summarize_documents", "parameters": {}}},
            {"type": "function", "function": {"name": "check_task_completion", "parameters": {}}},
        ],
    }

    call = _ManagedGatewayAdapter._managed_followup_tool_call(request)

    assert call is not None
    assert call["function"]["name"] == "summarize_documents"
    assert json.loads(call["function"]["arguments"]) == {}


def test_compact_verified_answer_preserves_reader_location_fields() -> None:
    compact = _compact_verified_answer_for_model(
        {
            "question": "question",
            "reader_answer": {
                "text": "answer [1]",
                "citations": [
                    {
                        "citation_id": "1",
                        "evidence_id": "evidence-1",
                        "doc_id": "doc-1",
                        "html_anchor": "sentence-1",
                        "exact_quote": "quote",
                    }
                ],
            },
            "citation_verification": {"passed": True},
        }
    )

    citation = compact["reader_answer"]["citations"][0]
    assert citation["doc_id"] == "doc-1"
    assert citation["html_anchor"] == "sentence-1"
    assert _parse_text_tool_intents('The tool has a field named "name": "inspect_workspace".') == []


def test_pi_sdk_streams_through_the_python_bridge(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIStreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[
                    {"role": "system", "content": "Reply briefly."},
                    {"role": "user", "content": "Confirm the bridge."},
                ],
                thinking_level="off",
                task_mode="knowledge",
                timeout_seconds=30,
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "".join(str(item.get("content", "")) for item in events if item["type"] == "delta") == "Pi bridge works"
    assert events[-1]["type"] == "done"
    assert events[-1]["stats"]["tokens"]["input"] == 5
    assert events[-1]["stats"]["tokens"]["output"] == 3
    assert events[-1]["stats"]["tokens"]["cacheRead"] == 100
    assert events[-1]["stats"]["tokens"]["total"] == 8
    assert "summarize_documents" not in events[-1]["stats"]["toolInventory"]["names"]
    assert "check_task_completion" not in events[-1]["stats"]["toolInventory"]["names"]
    assert _OpenAIStreamHandler.request_payload["model"] == "fixture-model"
    assert _OpenAIStreamHandler.request_payload["stream"] is True
    assert _OpenAIStreamHandler.request_payload["tools"]
    lifecycle = {
        str(item.get("event", ""))
        for item in events
        if item.get("type") == "lifecycle"
    }
    assert {
        "started",
        "turn_started",
        "message_started",
        "message_completed",
        "turn_completed",
        "completed",
    }.issubset(lifecycle)


def test_pi_tool_call_round_trips_through_scansci_dispatcher(tmp_path: Path) -> None:
    _OpenAIToolLoopHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIToolLoopHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "Inspect the available tools."}],
                thinking_level="off",
                task_mode="knowledge",
                task_contract={
                    "contract_id": "contract-tool-loop",
                    "autonomy": "read_only",
                    "risk_level": "read_only",
                    "allowed_tools": ["inspect_available_tools"],
                    "required_tool_groups": [["inspect_available_tools"]],
                    "task_profile": {
                        "route": "tool_agent",
                        "cognitive_complexity": "low",
                        "execution_complexity": "tool",
                    },
                    "initial_tool_budget": 2,
                    "max_tool_budget": 4,
                    "recovery_budget": 2,
                },
                timeout_seconds=30,
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    completed = [item for item in events if item["type"] == "tool.completed"]
    assert completed[0]["name"] == "inspect_available_tools"
    assert completed[0]["result"]["workspace"] == str((tmp_path / "workspace.sqlite").resolve())
    assert "".join(str(item.get("content", "")) for item in events if item["type"] == "delta") == "Tool result received"
    assert len(_OpenAIToolLoopHandler.request_payloads) == 2
    advertised = {
        str(dict(tool.get("function", {}) or {}).get("name", ""))
        for tool in list(_OpenAIToolLoopHandler.request_payloads[0].get("tools", []) or [])
        if isinstance(tool, dict)
    }
    assert "inspect_available_tools" in advertised
    assert {"download_and_index", "create_document", "create_presentation"}.isdisjoint(advertised)
    system_text = "\n".join(
        str(message.get("content", ""))
        for message in list(_OpenAIToolLoopHandler.request_payloads[0].get("messages", []) or [])
        if isinstance(message, dict) and message.get("role") in {"system", "developer"}
    )
    assert "HOST-OWNED TASK CONTRACT" in system_text
    assert "risk ceiling=read_only" in system_text
    assert "Required tool groups (host authoritative): inspect_available_tools." in system_text
    second_messages = _OpenAIToolLoopHandler.request_payloads[1]["messages"]
    assert any(message.get("role") == "tool" for message in second_messages)


def test_pi_continues_after_deferred_web_plan_until_tool_backed_final(tmp_path: Path) -> None:
    _OpenAIDeferredWebHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIDeferredWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    client._execute_tool = lambda name, arguments: {  # type: ignore[method-assign]
        "query": arguments.get("query", ""),
        "count": 1,
        "evidence_level": "web-discovery",
        "items": [{"title": "Market close", "url": "https://example.com/market"}],
    }
    try:
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "$web-access 帮我看看今天大A的情况"}],
                thinking_level="off",
                task_mode="web",
                timeout_seconds=30,
                session_id="deferred-web-session",
            )
        )
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert len(_OpenAIDeferredWebHandler.request_payloads) == 3
    assert any(event.get("type") == "status" and event.get("status") == "continuing" for event in events)
    assert any(event.get("type") == "tool.completed" and event.get("name") == "search_web" for event in events)
    assert "最终市场概况" in "".join(str(event.get("content", "")) for event in events if event.get("type") == "delta")
    assert events[-1]["type"] == "done"


def test_pi_web_turn_uses_host_budget_for_large_context_and_response(tmp_path: Path) -> None:
    """The sidecar must not silently reapply its former 24K/2K web limits."""

    _OpenAIPersistentHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIPersistentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "a" * 100_000}],
                thinking_level="off",
                task_mode="web",
                task_contract={
                    "contract_id": "contract-web-budget",
                    "autonomy": "direct",
                    "risk_level": "read_only",
                    "allowed_tools": ["search_web"],
                    "required_tool_groups": [],
                    "task_profile": {
                        "route": "direct_chat",
                        "cognitive_complexity": "low",
                        "execution_complexity": "none",
                    },
                    "initial_tool_budget": 4,
                    "max_tool_budget": 8,
                    "model_token_budget": 96_000,
                    "max_model_token_budget": 384_000,
                },
                timeout_seconds=30,
                session_id="web-budget-session",
            )
        )
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert events[-1]["type"] == "done"
    assert len(_OpenAIPersistentHandler.request_payloads) == 1
    payload = _OpenAIPersistentHandler.request_payloads[0]
    assert payload.get("max_tokens", payload.get("max_completion_tokens")) == 4096


def test_pi_extends_soft_model_token_lease_instead_of_failing_sound_answer(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIHighUsageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "answer completely"}],
                thinking_level="off",
                task_mode="general",
                task_contract={
                    "contract_id": "contract-progressive-model-budget",
                    "allowed_tools": [],
                    "initial_tool_budget": 3,
                    "max_tool_budget": 6,
                    "model_token_budget": 16_000,
                    "max_model_token_budget": 64_000,
                },
                timeout_seconds=30,
                session_id="progressive-model-budget-session",
            )
        )
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert events[-1]["type"] == "done"
    extension = next(event for event in events if event.get("status") == "model_budget_extended")
    assert extension["details"]["previous_budget"] == 16_000
    assert extension["details"]["current_budget"] > 20_000
    assert events[-1]["control"]["model_tokens"] == 20_032


def test_pi_verified_answer_tool_ends_run_without_second_model_answer(tmp_path: Path) -> None:
    _OpenAITerminalToolHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAITerminalToolHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    client._execute_tool = lambda name, arguments: {"reader_answer": {"text": "verified"}}  # type: ignore[method-assign]
    try:
        events = list(
            client.stream_chat(
                provider_kind="openai-compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-key",
                model_id="fixture-model",
                messages=[{"role": "user", "content": "question"}],
                thinking_level="off",
                task_mode="verified-answer",
                timeout_seconds=30,
                session_id="terminal-tool-session",
            )
        )
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    completed = next(item for item in events if item["type"] == "tool.completed")
    assert completed["name"] == "build_verified_answer"
    assert events[-1]["type"] == "done"
    assert events[-1]["terminal_tool"] == "build_verified_answer"


def test_pi_session_survives_sidecar_restart(tmp_path: Path) -> None:
    _OpenAIPersistentHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIPersistentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        kwargs = {
            "provider_kind": "openai-compatible",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "api_key": "fixture-key",
            "model_id": "fixture-model",
            "thinking_level": "off",
            "task_mode": "knowledge",
            "timeout_seconds": 30,
            "session_id": "durable-session",
        }
        first_client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        first = list(first_client.stream_chat(messages=[{"role": "user", "content": "first question"}], **kwargs))
        session_event = next(event for event in first if event["type"] == "session")
        session_file = Path(str(session_event["session_file"]))
        first_client.close()

        second_client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
        second = list(second_client.stream_chat(messages=[{"role": "user", "content": "second question"}], **kwargs))
        second_client.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert session_file.is_file()
    assert next(event for event in second if event["type"] == "session")["resumed"] is True
    second_messages = _OpenAIPersistentHandler.request_payloads[1]["messages"]
    assert any(message.get("role") == "user" and "first question" in str(message.get("content")) for message in second_messages)
    assert any(message.get("role") == "assistant" and "turn-1" in str(message.get("content")) for message in second_messages)
    assert any(message.get("role") == "user" and "second question" in str(message.get("content")) for message in second_messages)


def test_pi_session_reuses_context_when_only_contract_identity_and_goal_change(tmp_path: Path) -> None:
    _OpenAIPersistentHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIPersistentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    common_contract = {
        "autonomy": "direct",
        "risk_level": "none",
        "allowed_tools": [],
        "initial_tool_budget": 2,
        "max_tool_budget": 4,
        "recovery_budget": 2,
        "model_token_budget": 12_000,
    }
    try:
        first = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture-key",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "first question"}],
            thinking_level="off",
            task_mode="general",
            task_contract={**common_contract, "contract_id": "turn-one", "goal": "first question"},
            timeout_seconds=30,
            session_id="same-permission-session",
        ))
        second = list(client.stream_chat(
            provider_kind="openai-compatible",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="fixture-key",
            model_id="fixture-model",
            messages=[{"role": "user", "content": "second question"}],
            thinking_level="off",
            task_mode="general",
            task_contract={**common_contract, "contract_id": "turn-two", "goal": "second question"},
            timeout_seconds=30,
            session_id="same-permission-session",
        ))
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    first_session = next(event for event in first if event["type"] == "session")
    second_session = next(event for event in second if event["type"] == "session")
    assert second_session["resumed"] is True
    assert second_session["session_file"] == first_session["session_file"]
    second_messages = _OpenAIPersistentHandler.request_payloads[1]["messages"]
    assert any(message.get("role") == "assistant" and "turn-1" in str(message.get("content")) for message in second_messages)


def test_pi_cancel_aborts_active_sdk_run_without_killing_client(tmp_path: Path) -> None:
    _OpenAISlowHandler.started = threading.Event()
    _OpenAISlowHandler.release = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAISlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    events: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            events.extend(
                client.stream_chat(
                    provider_kind="openai-compatible",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    api_key="fixture-key",
                    model_id="fixture-model",
                    messages=[{"role": "user", "content": "take a long time"}],
                    thinking_level="off",
                    task_mode="knowledge",
                    timeout_seconds=30,
                    session_id="cancel-session",
                )
            )
        except BaseException as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert _OpenAISlowHandler.started.wait(timeout=10)
        deadline = time.monotonic() + 5
        while not client.active_request_id and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.cancel() is True
        consumer.join(timeout=5)
    finally:
        _OpenAISlowHandler.release.set()
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert not consumer.is_alive()
    assert not errors
    assert events[-1]["type"] == "cancelled"


def test_pi_steer_reports_native_queue_and_control_acknowledgement(tmp_path: Path) -> None:
    _OpenAISlowHandler.started = threading.Event()
    _OpenAISlowHandler.release = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAISlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    events: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            events.extend(
                client.stream_chat(
                    provider_kind="openai-compatible",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    api_key="fixture-key",
                    model_id="fixture-model",
                    messages=[{"role": "user", "content": "take a long time"}],
                    thinking_level="off",
                    task_mode="knowledge",
                    timeout_seconds=30,
                    session_id="steer-session",
                )
            )
        except BaseException as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert _OpenAISlowHandler.started.wait(timeout=10)
        deadline = time.monotonic() + 5
        while not client.active_request_id and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.steer("focus on the requested detail") is True
        acknowledgement_deadline = time.monotonic() + 5
        while not any(
            event.get("type") == "control"
            and event.get("action") == "steer"
            and event.get("status") == "accepted"
            for event in events
        ) and time.monotonic() < acknowledgement_deadline:
            time.sleep(0.01)
        assert client.cancel() is True
        _OpenAISlowHandler.release.set()
        consumer.join(timeout=10)
    finally:
        _OpenAISlowHandler.release.set()
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert not consumer.is_alive()
    assert not errors
    assert any(
        event.get("type") == "control"
        and event.get("action") == "steer"
        and event.get("status") == "accepted"
        for event in events
    )
    assert any(
        event.get("type") == "queue"
        and "focus on the requested detail" in list(event.get("steering", []))
        for event in events
    )
    assert events[-1]["type"] == "cancelled"


def test_pi_manual_compaction_is_persisted(tmp_path: Path) -> None:
    _OpenAIPersistentHandler.request_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIPersistentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = PiAgentClient(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        common = {
            "provider_kind": "openai-compatible",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "api_key": "fixture-key",
            "model_id": "fixture-model",
            "thinking_level": "off",
            "task_mode": "knowledge",
            "timeout_seconds": 30,
            "session_id": "compact-session",
        }
        events: list[dict[str, object]] = []
        for turn in range(4):
            events = list(
                client.stream_chat(
                    messages=[{"role": "user", "content": f"turn {turn}: alpha beta gamma " + ("context " * 5000)}],
                    **common,
                )
            )
        session_file = Path(str(next(event for event in events if event["type"] == "session")["session_file"]))
        result = client.compact("compact-session", instructions="Retain the alpha beta gamma fact.", timeout_seconds=30)
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert result["summary"]
    records = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]
    assert any(record.get("type") == "compaction" for record in records)
