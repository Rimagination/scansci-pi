import json
from pathlib import Path
import time
import threading
from urllib.request import Request, urlopen

import pytest

from scansci_html.annotation_layers import write_annotation_layer
from scansci_html.app_settings import save_settings
from scansci_html.evidence_store import index_evidence_library
from scansci_html.grounded_annotation import ground_draft_text
from scansci_html.webapp import NotebookWebApp, create_notebook_server, serve_notebook
from scansci_html.research_agent import (
    ResearchAgentRuntime,
    _normalize_direct_chat_output,
    _safe_good_question_fallback,
    _validate_direct_chat_output,
)
from scansci_html.research_runs import StageSpec
from scansci_html.workspace import attach_annotation_layers_to_notebook, sync_sources_from_evidence_store


def test_notebook_webapp_serves_workspace_assets_and_grounded_answer(tmp_path: Path):
    app, workspace, _evidence = _build_app(tmp_path)
    _configure_local_evidence(workspace)

    page = app.dispatch("GET", "/")
    logo = app.dispatch("GET", "/scansci-mark.png")
    male_avatar = app.dispatch("GET", "/avatar-panda-male.png")
    female_avatar = app.dispatch("GET", "/avatar-panda-female.png")
    health = _payload(app.dispatch("GET", "/api/health"))
    update = _payload(app.dispatch("GET", "/api/app/update"))
    workspace = _payload(app.dispatch("GET", "/api/workspace"))
    answer = _payload(
        app.dispatch(
            "POST",
            "/api/ask",
            json.dumps({"question": "What did Galunisertib reduce?"}).encode("utf-8"),
        )
    )

    assert page.status == 200
    assert "搜索科学".encode("utf-8") in page.body
    assert b"evidenceReaderPanel" in page.body
    assert b"citationPreview" in page.body
    assert b"data-profile-picker" in page.body
    assert logo.status == 200
    assert logo.content_type == "image/png"
    assert logo.body.startswith(b"\x89PNG")
    assert male_avatar.status == 200
    assert male_avatar.content_type == "image/png"
    assert male_avatar.body.startswith(b"\x89PNG")
    assert female_avatar.status == 200
    assert female_avatar.content_type == "image/png"
    assert female_avatar.body.startswith(b"\x89PNG")
    assert health["status"] == "ok"
    assert health["workspace_exists"] is True
    assert health["evidence_store_exists"] is True
    assert health["version"] == "0.2.0"
    assert health["build_id"] == "source"
    assert update["current_version"] == "0.2.0"
    assert update["state"] in {"idle", "current"}
    assert workspace["counts"]["sources"] == 1
    assert answer["question"] == "What did Galunisertib reduce?"
    assert answer["citation_verification"]["passed"] is True
    assert answer["reader_answer"]["citation_count"] == 1
    assert answer["reader_answer"]["citations"][0]["reader_url"].endswith("/reader") is False
    assert "/api/sources/" in answer["reader_answer"]["citations"][0]["reader_url"]


def test_review_document_ui_does_not_replay_the_user_instruction(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)
    script = app.dispatch("GET", "/app.js").body.decode("utf-8")
    styles = app.dispatch("GET", "/styles.css").body.decode("utf-8")

    assert "function reviewDisplayTitle" in script
    assert "Transformer、BERT 与 GPT-3：架构、训练与能力边界" in script
    assert 'class="review-request"' not in script
    assert 'if (model.scope) lines.push("", "> 研究范围"' not in script
    assert 'const scope = model.scope ?' not in script
    assert 'const title = ready ? "综述稿件"' in script
    assert ".review-request" not in styles
    assert "font-size: clamp(23px, 1.7vw, 28px)" in styles


def test_history_ui_exposes_archive_restore_and_delete_controls(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)
    page = app.dispatch("GET", "/").body.decode("utf-8")
    script = app.dispatch("GET", "/app.js").body.decode("utf-8")
    styles = app.dispatch("GET", "/styles.css").body.decode("utf-8")

    assert 'id="historyArchiveTrigger"' in page
    assert 'data-action="toggle-history-view"' in page
    assert "function toggleTaskMenu" in script
    assert "function archiveTask" in script
    assert "function restoreTask" in script
    assert "function deleteTask" in script
    assert 'data-action="delete-task"' in script
    assert "已经导出的 PPTX、Markdown 和下载的论文文件会保留" in script
    assert ".task-menu" in styles
    assert ".task-more:focus-visible" in styles


def test_notebook_webapp_reads_and_saves_redacted_settings(tmp_path: Path):
    app, workspace, _evidence = _build_app(tmp_path)

    defaults = _payload(app.dispatch("GET", "/api/settings"))
    saved = _payload(
        app.dispatch(
            "POST",
            "/api/settings",
            json.dumps(
                {
                    "providers": [
                        {
                            "id": "local",
                            "name": "Local engine",
                            "kind": "local",
                            "models": [{"id": "retrieval", "name": "Retrieval"}],
                        }
                    ],
                    "active_model": {"provider_id": "local", "model_id": "retrieval"},
                }
            ).encode("utf-8"),
        )
    )

    assert defaults["providers"][0]["id"] == "scansci-managed"
    assert saved["active_model"] == {"provider_id": "local", "model_id": "retrieval"}
    assert saved["providers"][0]["api_key_configured"] is False
    assert (workspace.parent / ".scansci-notebook.json").exists()


def test_notebook_webapp_allows_direct_chat_without_a_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace.sqlite"
    app = NotebookWebApp(workspace=workspace, evidence_db=tmp_path / "missing-evidence.sqlite")
    monkeypatch.setattr(
        app.research_agent,
        "chat",
        lambda payload: {
            "message": {"role": "assistant", "content": f"Reply: {payload['messages'][-1]['content']}"},
            "model": {"provider_id": "scansci-managed", "model_id": "glm-4.7-flash"},
        },
    )

    response = _payload(
        app.dispatch(
            "POST",
            "/api/chat",
            json.dumps({"messages": [{"role": "user", "content": "你是什么模型？"}]}).encode("utf-8"),
        )
    )

    assert response["message"] == {"role": "assistant", "content": "Reply: 你是什么模型？"}


def test_notebook_server_streams_direct_chat_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_self, _payload):
        yield {"type": "delta", "content": "Hel"}
        yield {
            "type": "done",
            "message": {"role": "assistant", "content": "Hello", "usage": {"total_tokens": 7}},
            "model": {"provider_id": "scansci-managed", "model_id": "glm-4.7-flash"},
        }

    monkeypatch.setattr("scansci_html.webapp.ResearchAgentRuntime.chat_stream", fake_stream)
    server = create_notebook_server(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/chat/stream",
            data=json.dumps({"messages": [{"role": "user", "content": "hello"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            body = response.read().decode("utf-8")
            assert response.headers.get_content_type() == "text/event-stream"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "event: ready" in body
    assert 'event: delta\ndata: {"content":"Hel"}' in body
    assert 'event: done\ndata: {"message":{"role":"assistant","content":"Hello","usage":{"total_tokens":7}},"model":{"provider_id":"scansci-managed","model_id":"glm-4.7-flash"}}' in body


def test_direct_chat_emits_canonical_terminal_run_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_model_stream(*_args, **_kwargs):
        yield {"type": "delta", "content": "你"}
        yield {"type": "delta", "content": "好"}
        yield {"type": "done", "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}}

    monkeypatch.setattr("scansci_html.research_agent.stream_chat_text", fake_model_stream)
    runtime = ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    events = list(runtime.chat_stream({"messages": [{"role": "user", "content": "你好"}]}))

    event_types = [event["type"] for event in events]
    assert event_types[0] == "RUN_STARTED"
    assert event_types[-1] == "RUN_FINISHED"
    assert event_types.count("TEXT_MESSAGE_CONTENT") == 2
    assert event_types.count("CUSTOM") == 3
    assert any(event.get("name") == "process_trace" for event in events)
    assert events[-1]["result"]["message"]["content"] == "你好"
    assert events[-1]["result"]["message"]["usage"]["total_tokens"] == 4
    assert events[-1]["result"]["message"]["trace"][-1]["title"] == "完成回答"


def test_direct_chat_knows_scansci_identity_and_loads_an_explicit_skill(tmp_path: Path):
    runtime = ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")

    chat_request = runtime._direct_chat_request({
        "chat_mode": "writing",
        "skills": ["good-question"],
        "messages": [{"role": "user", "content": "$good-question 帮我收束研究问题"}],
    })

    system = chat_request.messages[0]["content"]
    assert "ScanSci Pi | 搜索科学" in system
    assert "当前底层模型为 glm-4.7-flash" in system
    assert "写作模式" in system
    assert '<selected_skill id="good-question">' in system
    assert "## 好问题卡" in system
    assert "分别写 H1、H2、H3" in system
    assert "必须能在 14 天内完成" in system
    assert "一年、季度或完整项目" in system
    assert "不要写回归公式" in system
    assert "可观察数据图形或结果模式" in system
    assert "零效应、混杂、反向关系或测量偏差" in system
    assert "观察性数据不得被写成已识别的因果效应" in system
    assert "不得只靠 p 值" in system
    assert "references/platt-strong-inference.md" not in system
    assert len(system) < 8_000
    assert chat_request.chat_mode == "writing"
    assert [item["id"] for item in chat_request.selected_skills] == ["good-question"]


def test_good_question_output_is_cleaned_and_must_be_a_complete_card():
    selected = [{"id": "good-question"}]
    complete = "\n".join(
        [
            "## 好问题卡",
            "**暂定题目：** 城市树冠降温阈值",
            "**核心研究问题：** 树冠覆盖率与地表温度是否存在线性线性关系？",
            "**为什么值得做：** 基于用户信息的暂定判断：该结果可改变绿化配置。",
            "**它挑战了什么默认假设：** 覆盖越多总是越冷。",
            "**竞争性解释：** H1 阈值；H2 线性；H3 无关联。",
            "**关键判别证据或实验：** 比较分段模型、线性模型与零效应模型。",
            "**什么结果会推翻它：** 各城市斜率方向不一致且效应小于预设门槛。",
            "**两周内可做的 pilot：** 14 天分析 5 个城市；3 城出现同向效应则继续，否则停止。",
            "**所需数据与资源：** 已有城市数据和统计环境。",
            "**最强评审质疑：** 空间混杂；以匹配对照应对。",
            "**下一步：** 固定纳入标准。",
            "补充说明：三个解释分别对应不同预测，试验以预注册门槛作出继续或停止决定。" * 3,
        ]
    )

    cleaned = _normalize_direct_chat_output(complete, selected)
    assert "线性线性" not in cleaned
    _validate_direct_chat_output(cleaned, selected)

    with pytest.raises(RuntimeError, match="未通过完整性校验"):
        _validate_direct_chat_output("## 好问题卡", selected)

    with pytest.raises(RuntimeError, match="未审定公式"):
        _validate_direct_chat_output(complete + "\n判别模型：LST = a + b * CC", selected)


def test_good_question_unsafe_model_notation_gets_a_safe_actionable_fallback(tmp_path: Path):
    runtime = ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    chat_request = runtime._direct_chat_request({
        "chat_mode": "writing",
        "skills": ["good-question"],
        "messages": [{"role": "user", "content": "$good-question 我有城市树冠与地表温度数据。"}],
    })
    draft = """## 好问题卡
**暂定题目：** 城市树冠降温

**核心研究问题：** 树冠覆盖与地表温度的关系能否在留出城市中复现？

**为什么值得做：** 临时草稿。

判别模型：LST = a + b * CC
"""

    fallback = _safe_good_question_fallback(chat_request, draft)

    _validate_direct_chat_output(fallback, chat_request.selected_skills)
    assert "城市树冠降温" in fallback
    assert "留出城市中复现" in fallback
    assert "LST =" not in fallback
    assert "至少70%的预设样本层方向一致" in fallback
    assert "观察性数据只解释为关联" in fallback


def test_runtime_answers_version_and_capabilities_without_model_guessing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def model_must_not_run(*_args, **_kwargs):
        raise AssertionError("runtime facts must not be delegated to a language model")
        yield  # pragma: no cover

    monkeypatch.setattr("scansci_html.research_agent.stream_chat_text", model_must_not_run)
    runtime = ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    events = list(runtime.chat_stream({
        "messages": [{"role": "user", "content": "你是谁？当前是什么模型、版本，有哪些 Skill？"}],
    }))

    assert events[-1]["type"] == "RUN_FINISHED"
    message = events[-1]["result"]["message"]
    assert "ScanSci Pi" in message["content"]
    assert "glm-4.7-flash" in message["content"]
    assert "$good-question" in message["content"]
    assert any(item["title"] == "读取运行时事实" for item in message["trace"])


def test_direct_chat_failure_emits_run_error_instead_of_hanging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def failed_model_stream(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr("scansci_html.research_agent.stream_chat_text", failed_model_stream)
    runtime = ResearchAgentRuntime(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    events = list(runtime.chat_stream({"messages": [{"role": "user", "content": "你好"}]}))

    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "chat_failed"


def test_notebook_webapp_stores_document_service_keys_via_dedicated_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, _workspace, _evidence = _build_app(tmp_path)
    captured: dict[str, str] = {}

    def save_key(workspace: Path, service_id: str, value: str) -> dict[str, object]:
        captured.update({"workspace": str(workspace), "service_id": service_id, "value": value})
        return {"document_processing": {"mineru": {"api_key_configured": True}}}

    monkeypatch.setattr("scansci_html.webapp.set_document_service_api_key", save_key)
    saved = _payload(
        app.dispatch(
            "POST",
            "/api/settings/document-processing/mineru/api-key",
            json.dumps({"api_key": "secret-value"}).encode("utf-8"),
        )
    )

    assert captured["service_id"] == "mineru"
    assert captured["value"] == "secret-value"
    assert saved["document_processing"]["mineru"]["api_key_configured"] is True


def test_notebook_webapp_installs_local_skills_and_exposes_extension_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, workspace, _evidence = _build_app(tmp_path)
    source = tmp_path / "skills" / "study-design"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: Study Design\ndescription: Plan a transparent study.\n---\n", encoding="utf-8")
    monkeypatch.setattr(
        "scansci_html.webapp.marketplace_skills",
        lambda: {"items": [{"id": "example/skills/study-design", "name": "Study Design"}], "offline": False, "provider": "skills.sh"},
    )

    before = _payload(app.dispatch("GET", "/api/skills"))
    market = _payload(app.dispatch("GET", "/api/skills/market"))
    installed = _payload(
        app.dispatch(
            "POST",
            "/api/skills/install",
            json.dumps({"source_type": "local", "source": str(source)}).encode("utf-8"),
        )
    )

    assert len(before["skills"]) >= 2
    assert market["items"][0]["id"] == "example/skills/study-design"
    assert installed["installed"][0]["name"] == "Study Design"
    assert installed["settings"]["skills"][-1]["source_type"] == "local"
    assert Path(installed["installed"][0]["path"]).is_dir()


def test_notebook_webapp_exposes_and_registers_official_mcp_marketplace_records(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)

    marketplace = _payload(app.dispatch("GET", "/api/mcp/marketplace"))
    pubmed = next(item for item in marketplace["items"] if item["id"] == "io.github.cyanheads/pubmed-mcp-server")
    installed = _payload(
        app.dispatch(
            "POST",
            "/api/mcp/marketplace/install",
            json.dumps({"id": pubmed["id"]}).encode("utf-8"),
        )
    )

    assert marketplace["source"]["api_version"] == "v0.1"
    assert any(item["id"] == "life" for item in marketplace["disciplines"])
    assert installed["created"] is True
    assert installed["record"]["catalog_id"] == pubmed["id"]
    assert installed["settings"]["mcp_servers"][0]["enabled"] is True


def test_notebook_webapp_exposes_presets_capabilities_and_ppt_outline(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)

    presets = _payload(app.dispatch("GET", "/api/settings/presets"))
    capabilities = _payload(app.dispatch("GET", "/api/capabilities"))
    outline = _payload(
        app.dispatch(
            "POST",
            "/api/studio/ppt/outline",
            json.dumps({"notebook_id": "immunotherapy", "topic": "免疫治疗证据汇报"}).encode("utf-8"),
        )
    )

    assert any(item["id"] == "openai" for item in presets["providers"])
    assert any(item["runtime"] == "ollama" for item in presets["local_models"])
    assert {item["id"] for item in capabilities["tools"]} >= {"paper-download", "journal-scout", "citation-lab", "paper-atlas", "ppt-studio"}
    assert outline["title"] == "免疫治疗证据汇报"
    assert outline["evidence_linked"] is True
    assert outline["slides"][-1]["title"] == "参考文献"


def test_notebook_webapp_fetches_models_through_a_redacted_provider_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, workspace, _evidence = _build_app(tmp_path)
    captured: dict[str, object] = {}

    def fetch_models(*, workspace: Path, provider: dict[str, object]) -> dict[str, object]:
        captured.update({"workspace": workspace, "provider": provider})
        return {"provider": "OpenAI", "count": 1, "models": [{"id": "demo-model", "name": "Demo model", "context_window": "32K"}]}

    monkeypatch.setattr("scansci_html.webapp.fetch_provider_models", fetch_models)
    result = _payload(app.dispatch("POST", "/api/settings/providers/openai/models", b"{}"))

    assert captured["workspace"] == workspace
    assert captured["provider"]["id"] == "openai"
    assert result["models"][0]["id"] == "demo-model"


def test_notebook_webapp_runs_persistent_evidence_workflow(tmp_path: Path):
    app, workspace, _evidence = _build_app(tmp_path)
    _configure_local_evidence(workspace)

    created = _payload(
        app.dispatch(
            "POST",
            "/api/runs",
            json.dumps(
                {
                    "workflow_type": "ask",
                    "notebook_id": "immunotherapy",
                    "question": "What did Galunisertib reduce?",
                    "thinking_level": "high",
                }
            ).encode("utf-8"),
        )
    )
    run_id = created["run_id"]
    completed = created
    for _ in range(100):
        completed = _payload(app.dispatch("GET", f"/api/runs/{run_id}"))
        if completed["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)

    listing = _payload(app.dispatch("GET", "/api/runs"))
    catalog = _payload(app.dispatch("GET", "/api/runs/catalog"))

    assert completed["status"] == "completed"
    assert completed["progress"] == 1
    assert [stage["status"] for stage in completed["stages"]] == ["completed"] * 4
    assert completed["output_artifact"]["artifact_type"] == "evidence_answer"
    assert completed["output_artifact"]["evidence_links"][0]["evidence_id"]
    assert completed["tool_calls"][0]["tool_name"] == "scansci.evidence.ask"
    assert completed["input"]["thinking_level"] == "high"
    assert completed["metadata"]["thinking_level"] == "high"
    assert completed["metadata"]["evidence_budget"] == 14
    assert listing["runs"][0]["run_id"] == run_id
    assert any(item["id"] == "literature_review" for item in catalog["workflows"])


def test_notebook_webapp_archives_restores_and_deletes_conversations(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)
    run = app.research_agent.store.create_run(
        notebook_id="",
        workflow_type="ask",
        title="Archive from the sidebar",
        input_payload={"question": "Archive this"},
        stages=[StageSpec("deliver", "Deliver", "delivery")],
    )
    app.research_agent.store.complete_run(run["run_id"])

    archived = _payload(app.dispatch("POST", f"/api/runs/{run['run_id']}/archive", b"{}"))
    assert archived["archived"] is True
    assert _payload(app.dispatch("GET", "/api/runs"))["runs"] == []
    archived_listing = _payload(app.dispatch("GET", "/api/runs?view=archived&limit=200"))
    assert archived_listing["runs"][0]["run_id"] == run["run_id"]

    restored = _payload(app.dispatch("POST", f"/api/runs/{run['run_id']}/restore", b"{}"))
    assert restored["archived"] is False

    deleted = _payload(app.dispatch("POST", f"/api/runs/{run['run_id']}/delete", b"{}"))
    assert deleted["deleted"] is True
    assert app.dispatch("GET", f"/api/runs/{run['run_id']}").status == 404


def test_notebook_webapp_writes_notes_audits_and_serves_source_anchors(tmp_path: Path):
    app, workspace, _evidence = _build_app(tmp_path, with_layer=True)
    notebook_id = "immunotherapy"
    notebook = _payload(app.dispatch("GET", f"/api/notebooks/{notebook_id}"))
    citation = notebook["citations"][0]
    source = notebook["sources"][0]

    source_reader = app.dispatch("GET", f"/api/sources/{source['doc_id']}/reader")
    note_payload = _payload(
        app.dispatch(
            "POST",
            f"/api/notebooks/{notebook_id}/notes",
            json.dumps({"title": "Follow-up", "body": "Check the study population before synthesis."}).encode("utf-8"),
        )
    )
    audit_payload = _payload(
        app.dispatch(
            "POST",
            f"/api/citations/{citation['citation_record_id']}/audits",
            json.dumps({"verdict": "supported", "reasoning": "Directly stated in the quoted result.", "confidence": 0.94}).encode("utf-8"),
        )
    )
    refreshed = _payload(app.dispatch("GET", f"/api/notebooks/{notebook_id}"))

    assert source_reader.status == 200
    assert b"data-evidence-id" in source_reader.body
    assert note_payload["note"]["title"] == "Follow-up"
    assert audit_payload["audit"]["provider"] == "human-notebook-review"
    assert refreshed["counts"]["notes"] == 1
    assert refreshed["counts"]["citation_audits"] == 1
    assert workspace.exists()


def test_notebook_webapp_rejects_unsafe_or_invalid_requests(tmp_path: Path):
    app, _workspace, _evidence = _build_app(tmp_path)

    missing_question = _payload(app.dispatch("POST", "/api/ask", b"{}"))
    traversal = _payload(app.dispatch("GET", "/api/sources/10.1234_gal/files/%2E%2E/workspace.sqlite"))

    assert missing_question["error"]["code"] == "invalid_request"
    assert traversal["error"]["code"] in {"invalid_request", "not_found"}
    with pytest.raises(ValueError, match="loopback"):
        serve_notebook(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite", host="0.0.0.0")

    server = create_notebook_server(workspace=tmp_path / "workspace.sqlite", evidence_db=tmp_path / "evidence.sqlite")
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_port > 0
    finally:
        server.server_close()


def _build_app(tmp_path: Path, *, with_layer: bool = False) -> tuple[NotebookWebApp, Path, Path]:
    library = tmp_path / "library"
    library.mkdir()
    (library / "paper.html").write_text(
        """
        <article class="paper" data-doi="10.1234/gal">
          <h1>Galunisertib Immunotherapy Paper</h1>
          <h2>Results</h2>
          <p id="results-p1">Galunisertib reduced regulatory T cells after treatment. IL-15 activated dendritic cells improved survival in lymphoma models.</p>
        </article>
        """,
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.sqlite"
    index_evidence_library(library, db_path=evidence, inject_evidence_html=True, min_sentence_length=10)
    workspace = tmp_path / "workspace.sqlite"
    sync_sources_from_evidence_store(workspace, evidence, notebook_id="immunotherapy")
    if with_layer:
        layer_db = tmp_path / "layers.sqlite"
        payload = ground_draft_text(evidence, "Galunisertib reduced regulatory T cells.", limit=1)
        write_annotation_layer(layer_db, payload, layer_id="tregs", name="Tregs result", replace=True)
        attach_annotation_layers_to_notebook(workspace, layer_db, notebook_id="immunotherapy", layer_ids=["tregs"])
    return NotebookWebApp(workspace=workspace, evidence_db=evidence), workspace, evidence


def _configure_local_evidence(workspace: Path) -> None:
    save_settings(
        workspace,
        {
            "active_model": {"provider_id": "local-evidence", "model_id": "evidence-retrieval"},
            "providers": [{
                "id": "local-evidence",
                "name": "Local evidence engine",
                "kind": "local",
                "models": [{"id": "evidence-retrieval", "name": "Evidence retrieval"}],
            }],
            "model_roles": {
                "reasoning": "provider:local-evidence:evidence-retrieval",
                "writing": "provider:local-evidence:evidence-retrieval",
                "retrieval": "local:builtin-evidence",
                "embedding": "local:builtin-evidence",
                "reranking": "local:builtin-evidence",
                "vision": "",
                "slides": "provider:local-evidence:evidence-retrieval",
            },
        },
    )


def _payload(response) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))
