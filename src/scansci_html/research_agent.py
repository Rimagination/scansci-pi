"""Research workflow runtime for the ScanSci desktop application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import quote

from .agent_context import build_agent_system_context, runtime_self_description, selected_skill_ids
from .agent_reasoning import evidence_budget_for_thinking, managed_glm_thinking_mode, normalize_thinking_level
from .app_settings import get_provider_api_key, load_settings
from .deep_agent import ScanSciDeepAgent, build_deep_agent_model
from .image_attachments import persist_image_attachments, vision_image_blocks
from .ingestion import ingest_sources, ingestion_context
from .library_manager import notebook_evidence_db
from .literature_review import retrieve_review_evidence, synthesize_literature_review
from .llm import CascadingChatJsonClient, analyze_vision_images, build_chat_json_client, complete_chat_text, managed_gateway_session, stream_chat_text
from .local_transformers_runtime import ensure_local_transformers_runtime
from .pi_agent import PiAgentClient
from .qa.agent import answer_question
from .research_runs import ResearchRunStore, StageSpec
from .run_events import (
    CUSTOM,
    RUN_ERROR,
    RUN_FINISHED,
    RUN_STARTED,
    STEP_FINISHED,
    STEP_STARTED,
    TEXT_MESSAGE_CONTENT,
    TEXT_MESSAGE_END,
    TEXT_MESSAGE_START,
    event as run_event,
    new_message_id,
    new_run_id,
)
from .research_tools import (
    analyze_references,
    build_ppt_outline,
    create_ppt_project,
    download_paper,
    search_journals,
    search_paper_atlas,
    verify_doi_metadata,
)
from .slide_studio import create_source_slide_deck, persist_slide_sources
from .workspace import load_workspace_summary


_WORKFLOWS: dict[str, dict[str, Any]] = {
    "ask": {
        "label": "证据问答",
        "artifact_type": "evidence_answer",
        "stages": [
            StageSpec("plan", "理解问题", "planner"),
            StageSpec("research", "检索与综合", "tool", "scansci.evidence.ask"),
            StageSpec("verify", "证据核验", "verification", "scansci.evidence.verify"),
            StageSpec("deliver", "交付回答", "delivery"),
        ],
    },
    "literature_review": {
        "label": "文献综述",
        "artifact_type": "literature_review",
        "stages": [
            StageSpec("plan", "确定综述边界", "planner"),
            StageSpec("research", "按章节检索证据", "tool", "scansci.review.retrieve"),
            StageSpec("synthesize", "跨论文比较与写作", "tool", "scansci.review.write"),
            StageSpec("verify", "核验段落引用", "verification", "scansci.evidence.verify"),
            StageSpec("deliver", "生成综述产物", "delivery"),
        ],
    },
    "journal_search": {
        "label": "期刊查询",
        "artifact_type": "journal_search_result",
        "stages": [
            StageSpec("plan", "识别期刊查询", "planner"),
            StageSpec("execute", "查询分区与指标", "tool", "scansci.journal.search"),
            StageSpec("deliver", "整理期刊结果", "delivery"),
        ],
    },
    "citation_analysis": {
        "label": "参考文献核验",
        "artifact_type": "citation_audit",
        "stages": [
            StageSpec("plan", "解析参考文献", "planner"),
            StageSpec("execute", "核验引用与元数据", "tool", "scansci.citation.analyze"),
            StageSpec("deliver", "生成核验报告", "delivery"),
        ],
    },
    "doi_verification": {
        "label": "DOI 核验",
        "artifact_type": "doi_verification",
        "stages": [
            StageSpec("plan", "识别 DOI 与题名", "planner"),
            StageSpec("execute", "查询权威元数据", "tool", "scansci.citation.verify_doi"),
            StageSpec("deliver", "生成 DOI 结论", "delivery"),
        ],
    },
    "paper_atlas": {
        "label": "Paper Atlas",
        "artifact_type": "paper_atlas_result",
        "stages": [
            StageSpec("plan", "确定图谱种子", "planner"),
            StageSpec("execute", "检索论文关系", "tool", "scansci.paper_atlas.search"),
            StageSpec("deliver", "生成图谱入口", "delivery"),
        ],
    },
    "paper_download": {
        "label": "文献下载",
        "artifact_type": "downloaded_paper",
        "stages": [
            StageSpec("plan", "解析论文标识", "planner"),
            StageSpec("execute", "查找合法全文", "tool", "scansci.paper.download"),
            StageSpec("deliver", "登记下载产物", "delivery"),
        ],
    },
    "ppt_outline": {
        "label": "PPT 大纲",
        "artifact_type": "slide_outline",
        "stages": [
            StageSpec("plan", "规划汇报叙事", "planner"),
            StageSpec("execute", "生成证据化大纲", "tool", "scansci.ppt.outline"),
            StageSpec("deliver", "交付演示大纲", "delivery"),
        ],
    },
    "ppt_project": {
        "label": "PPT 项目",
        "artifact_type": "slide_deck_project",
        "stages": [
            StageSpec("plan", "规划演示项目", "planner"),
            StageSpec("execute", "创建 EasySlides 项目", "tool", "scansci.ppt.create_project"),
            StageSpec("deliver", "登记演示产物", "delivery"),
        ],
    },
    "pdf_to_ppt": {
        "label": "PDF 制作幻灯片",
        "artifact_type": "presentation_deck",
        "stages": [
            StageSpec("plan", "解析材料与演示主线", "planner"),
            StageSpec("execute", "生成可编辑 PPTX", "tool", "scansci.ppt.from_source"),
            StageSpec("deliver", "交付演示文稿", "delivery"),
        ],
    },
}


@dataclass(frozen=True)
class _DirectChatRequest:
    messages: list[dict[str, Any]]
    provider_id: str
    provider_name: str
    provider_kind: str
    base_url: str
    api_key: str
    model_id: str
    thinking_mode: str | None
    session: Any | None
    chat_mode: str
    thinking_level: str
    selected_skills: list[dict[str, Any]]


class ResearchAgentRuntime:
    """Run ScanSci tools behind a persistent, resumable research contract."""

    def __init__(self, *, workspace: str | Path, evidence_db: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.evidence_db = Path(evidence_db).resolve()
        self.store = ResearchRunStore(self.workspace)
        self.store.recover_interrupted_runs()
        self._threads: dict[str, threading.Thread] = {}
        self._thread_lock = threading.Lock()
        self._managed_writing_clients: dict[tuple[str, str, str], Any] = {}

    def workflow_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": workflow_id,
                "label": spec["label"],
                "artifact_type": spec["artifact_type"],
                "stages": [stage.title for stage in spec["stages"]],
            }
            for workflow_id, spec in _WORKFLOWS.items()
        ]

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_type = str(payload.get("workflow_type", "ask")).strip()
        spec = _WORKFLOWS.get(workflow_type)
        if spec is None:
            raise ValueError(f"Unsupported research workflow: {workflow_type}")
        notebook = {"notebook_id": ""} if workflow_type in {"pdf_to_ppt", "paper_download"} else self._requested_notebook(payload)
        normalized = self._normalize_input(workflow_type, payload)
        thinking_level = normalize_thinking_level(normalized.get("thinking_level"))
        normalized["thinking_level"] = thinking_level
        if normalized.get("images"):
            if workflow_type != "ask":
                raise ValueError("图片提问目前仅支持“通用”模式")
            normalized["images"] = persist_image_attachments(self.workspace, normalized["images"])
        if workflow_type == "pdf_to_ppt":
            normalized["source_files"] = persist_slide_sources(self.workspace, normalized.get("source_files"))
        settings = load_settings(self.workspace)
        active = dict(settings.get("active_model", {}) or {})
        if workflow_type == "literature_review":
            provider_id, model_id = self._role_identity(settings, "writing")
        elif workflow_type == "pdf_to_ppt":
            provider_id, model_id = self._role_identity(settings, "slides")
        else:
            provider_id, model_id = str(active.get("provider_id", "")), str(active.get("model_id", ""))
        run = self.store.create_run(
            notebook_id=str(notebook["notebook_id"]),
            workflow_type=workflow_type,
            title=self._run_title(workflow_type, normalized),
            input_payload=normalized,
            stages=spec["stages"],
            model_provider_id=provider_id,
            model_id=model_id,
            metadata={
                "artifact_contract": spec["artifact_type"],
                "runtime": "scansci-research-agent.v1",
                "thinking_level": thinking_level,
                "evidence_budget": evidence_budget_for_thinking(thinking_level),
            },
        )
        self._submit(str(run["run_id"]))
        return self.store.get_run(str(run["run_id"]))

    def resume(self, run_id: str) -> dict[str, Any]:
        run = self.store.prepare_resume(run_id)
        self._submit(run_id)
        return run

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self.store.request_cancel(run_id)
        if run["status"] in {"queued", "paused"}:
            return self.store.mark_cancelled(run_id)
        return run

    def answer_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise ValueError("question is required")
        notebook = self._requested_notebook(payload)
        evidence_db = self._evidence_db_for_notebook(notebook)
        thinking_level = normalize_thinking_level(payload.get("thinking_level"))
        try:
            requested_limit = payload.get("limit", evidence_budget_for_thinking(thinking_level))
            limit = min(20, max(1, int(requested_limit)))
        except (TypeError, ValueError) as error:
            raise ValueError("limit must be an integer") from error
        settings = load_settings(self.workspace)
        active = dict(settings.get("active_model", {}) or {})
        provider = next(
            (item for item in settings.get("providers", []) if item.get("id") == active.get("provider_id")),
            None,
        )
        answer_options: dict[str, Any] = {}
        result: dict[str, Any] | None = None
        agent_harness = "local-evidence"
        agent_fallback_error = ""
        image_attachments = list(payload.get("images", []) or [])
        if image_attachments and (provider is None or provider.get("kind") == "local"):
            raise ValueError("图片提问需要选择一个已配置的视觉模型")
        image_analysis: dict[str, Any] | None = None
        if provider is not None and provider.get("kind") != "local":
            managed = str(provider.get("auth_mode", "")) == "managed"
            api_key = "scansci-managed-gateway" if managed else get_provider_api_key(self.workspace, str(provider.get("id", "")))
            if not api_key:
                raise ValueError("当前生成模型尚未配置 API Key")
            if image_attachments:
                model_record = next(
                    (item for item in provider.get("models", []) if str(item.get("id", "")) == str(active.get("model_id", ""))),
                    {},
                )
                if "vision" not in set(model_record.get("capabilities", []) or []):
                    raise ValueError("当前模型未启用视觉能力，请在对话框模型菜单选择带“视觉”标签的模型")
                image_analysis = {
                    "text": analyze_vision_images(
                        str(provider.get("kind", "")),
                        base_url=str(provider.get("base_url", "")),
                        api_key=api_key,
                        model=str(active.get("model_id", "")),
                        question=question,
                        images=vision_image_blocks(self.workspace, image_attachments),
                    ),
                    "image_count": len(image_attachments),
                    "model": str(active.get("model_id", "")),
                }
            else:
                harness = str(payload.get("agent_harness", "pi")).strip().lower()
                tool_calls: list[dict[str, Any]] = []
                # ScanSci's managed gateway intentionally exposes the portable
                # chat-completions subset.  Tool-call wire formats vary between
                # providers, so managed models use the same provider-neutral
                # pattern as OpenCode: the application executes typed tools and
                # sends their normalized text results back to the model.
                use_native_tool_loop = harness not in {"legacy", "fixed-workflow"} and not managed
                if harness in {"deep", "deep-agent", "deep-agents"}:
                    try:
                        model = build_deep_agent_model(
                            provider_id=str(provider.get("id", "")),
                            provider_kind=str(provider.get("kind", "")),
                            base_url=str(provider.get("base_url", "")),
                            api_key=api_key,
                            model=str(active.get("model_id", "")),
                            thinking_level=thinking_level,
                        )
                        result = ScanSciDeepAgent(
                            evidence_db=evidence_db,
                            workspace=self.workspace,
                            model=model,
                        ).answer(
                            question,
                            limit=limit,
                            thread_id=str(payload.get("thread_id", "")),
                            task_mode=str(payload.get("task_mode", "auto")),
                        )
                        agent_harness = "deep-agents"
                    except Exception as error:  # optional compatibility harness
                        agent_fallback_error = f"{type(error).__name__}: {error}"
                elif use_native_tool_loop:
                    task_mode = str(payload.get("task_mode", "evidence")).strip().lower() or "evidence"
                    try:
                        pi_events = PiAgentClient(workspace=self.workspace, evidence_db=evidence_db).stream_chat(
                            provider_kind=str(provider.get("kind", "")),
                            base_url=str(provider.get("base_url", "")),
                            api_key=api_key,
                            model_id=str(active.get("model_id", "")),
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are ScanSci Pi. This endpoint requires a source-grounded answer. "
                                        "Call build_verified_answer and use its verified result for delivery."
                                    ),
                                },
                                {"role": "user", "content": question},
                            ],
                            thinking_level=thinking_level,
                            task_mode="knowledge" if task_mode in {"auto", "evidence"} else task_mode,
                        )
                        for pi_event in pi_events:
                            if pi_event.get("type") == "tool.completed":
                                tool_name = str(pi_event.get("name", ""))
                                tool_calls.append({"name": tool_name, "status": "completed"})
                                if tool_name == "build_verified_answer":
                                    result = dict(pi_event.get("result", {}) or {})
                        agent_harness = "pi-agent-sdk"
                        if result is None:
                            agent_fallback_error = "Pi Agent did not finalize through build_verified_answer"
                    except Exception as error:  # provider tool compatibility boundary
                        # Do not fail the user's evidence task merely because a
                        # nominally OpenAI-compatible endpoint implements a
                        # different tool/message schema.  The fixed workflow
                        # below retains the same retrieval and citation gates.
                        agent_fallback_error = f"{type(error).__name__}: {error}"
                if result is None:
                    rag_client = build_chat_json_client(
                        str(provider.get("kind", "")),
                        base_url=str(provider.get("base_url", "")),
                        api_key=api_key,
                        model=str(active.get("model_id", "")),
                        session=managed_gateway_session() if managed else None,
                        thinking_mode="disabled" if managed else None,
                    )
                    answer_options = {
                        "answer_provider": "llm",
                        "verification_provider": "llm",
                        "query_rewrite_provider": "llm",
                        "chat_client": rag_client,
                    }
                    agent_harness = "provider-neutral-workflow"
        if result is None:
            if not evidence_db.exists():
                raise FileNotFoundError(f"Evidence store does not exist: {evidence_db}")
            result = answer_question(
                evidence_db,
                question,
                limit=limit,
                max_quotes=min(8, limit),
                adequacy_profile="manual",
                agentic_profile="custom",
                query_variants=2,
                max_followup_queries=1,
                **answer_options,
            )
            steps = list(dict(result.get("agentic_trace", {}) or {}).get("steps", []) or [])
            result["pi_agent"] = {
                "harness": agent_harness,
                "task_mode": str(payload.get("task_mode", "evidence") or "evidence"),
                "finalization": "verified-workflow",
                "tool_calls": _provider_neutral_tool_calls(result, steps=steps),
                "compatibility_fallback": bool(agent_fallback_error),
                "compatibility_error": agent_fallback_error[:500],
            }
        else:
            result["pi_agent"] = {
                "harness": agent_harness,
                "task_mode": str(payload.get("task_mode", "evidence") or "evidence"),
                "finalization": "build_verified_answer",
                "tool_calls": tool_calls,
                "compatibility_fallback": False,
                "compatibility_error": "",
            }
        reader_answer = dict(result.get("reader_answer", {}) or {})
        citations = []
        for citation in list(reader_answer.get("citations", []) or []):
            item = dict(citation)
            doc_id = str(item.get("doc_id", ""))
            anchor = str(item.get("html_anchor", ""))
            item["reader_url"] = self._reader_url(doc_id, anchor) if doc_id else ""
            item["original_url"] = self._original_url(doc_id) if doc_id else ""
            citations.append(item)
        reader_answer["citations"] = citations
        result["reader_answer"] = reader_answer
        if image_analysis is not None:
            result["image_analysis"] = image_analysis
        runtime_meta = dict(result.get("agent_runtime", {}) or {})
        runtime_meta["thinking_level"] = thinking_level
        runtime_meta["evidence_budget"] = limit
        result["agent_runtime"] = runtime_meta
        return result

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a normal model conversation without requiring imported evidence."""

        ingestion = self._ingest_direct_attachments(payload)
        attachment_context = ingestion_context(self.workspace, str(ingestion["job_id"])) if ingestion else ""
        chat_request = self._direct_chat_request(payload, attachment_context=attachment_context)
        local_facts = self._runtime_fact_answer(payload, chat_request)
        if local_facts:
            text, usage = local_facts, {}
        else:
            completion = complete_chat_text(
                chat_request.provider_kind,
                base_url=chat_request.base_url,
                api_key=chat_request.api_key,
                model=chat_request.model_id,
                messages=chat_request.messages,
                thinking_mode=chat_request.thinking_mode,
                session=chat_request.session,
                include_usage=True,
            )
            if isinstance(completion, tuple):
                text, usage = completion
            else:
                text, usage = completion, {}
        trace = self._direct_process_trace(chat_request, had_attachments=bool(ingestion))
        if local_facts:
            trace[-1] = {"title": "读取运行时事实", "detail": "已从当前安装状态读取版本、模型、模式与 Skill，避免模型猜测。"}
        trace.append({"title": "完成回答", "detail": "模型已返回完整内容并完成响应收束。"})
        message: dict[str, Any] = {
            "role": "assistant",
            "content": text,
            "mode": chat_request.chat_mode,
            "trace": trace,
        }
        if usage:
            message["usage"] = usage
        result = {
            "message": message,
            "model": {"provider_id": chat_request.provider_id, "model_id": chat_request.model_id},
        }
        if ingestion:
            result["ingestion"] = ingestion
            message["sources"] = list(ingestion.get("sources", []) or [])
        return result

    def continue_run_conversation(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Answer a follow-up without breaking it out into a new chat thread."""

        run = self.store.get_run(run_id)
        question = str(payload.get("content", payload.get("question", ""))).strip()
        if not question:
            raise ValueError("Follow-up message is required")
        if len(question) > 12_000:
            raise ValueError("Follow-up message is too long")

        # Persist the request first.  If the model is temporarily unavailable,
        # the user's work is still visible when they reopen the task.
        self.store.append_message(run_id, role="user", content=question)
        prior_messages = list(self.store.get_run(run_id).get("messages", []) or [])[-14:]
        messages = [
            {"role": "system", "content": self._run_conversation_context(run)},
            *[
                {"role": str(item["role"]), "content": str(item["content"])}
                for item in prior_messages
                if item.get("role") in {"user", "assistant"} and item.get("content")
            ],
        ]
        chat_request = self._direct_chat_request(
            {"messages": messages, "thinking_level": payload.get("thinking_level", "auto")}
        )
        started_at = time.monotonic()
        try:
            completion = complete_chat_text(
                chat_request.provider_kind,
                base_url=chat_request.base_url,
                api_key=chat_request.api_key,
                model=chat_request.model_id,
                messages=chat_request.messages,
                thinking_mode=chat_request.thinking_mode,
                session=chat_request.session,
                include_usage=True,
            )
            if isinstance(completion, tuple):
                text, usage = completion
            else:
                text, usage = completion, {}
            text = str(text).strip()
            if not text:
                raise RuntimeError("The model returned an empty response")
            message = self.store.append_message(
                run_id,
                role="assistant",
                content=text,
                usage=usage,
                processing_ms=round((time.monotonic() - started_at) * 1000),
            )
        except Exception:
            # The user turn is deliberately retained; no fabricated assistant
            # turn is written when a network/model request fails.
            raise
        return {
            "run": self.store.get_run(run_id),
            "message": message,
            "model": {"provider_id": chat_request.provider_id, "model_id": chat_request.model_id},
        }

    @staticmethod
    def _run_conversation_context(run: dict[str, Any]) -> str:
        """Build concise, durable context for a task follow-up."""

        artifact = dict(run.get("output_artifact") or {})
        payload = dict(artifact.get("payload") or {})
        outline = dict(payload.get("outline") or payload)
        slide_titles = [
            str(item.get("title", "")).strip()
            for item in list(outline.get("slides", []) or [])[:12]
            if isinstance(item, dict) and item.get("title")
        ]
        source_names = [
            str(item.get("name", "")).strip()
            for item in list(payload.get("sources", []) or [])[:8]
            if isinstance(item, dict) and item.get("name")
        ]
        input_payload = dict(run.get("input") or {})
        source_names.extend(
            str(item.get("name", "")).strip()
            for item in list(input_payload.get("source_files", []) or [])[:8]
            if isinstance(item, dict) and item.get("name")
        )
        source_summary = "、".join(dict.fromkeys(name for name in source_names if name)) or "未提供可读源文件名称"
        slide_summary = "；".join(slide_titles) or "尚未生成逐页标题"
        return (
            "You are continuing an existing ScanSci task, not starting a new conversation. "
            "Keep the answer tied to this task and its generated deliverable. Be clear about limits: "
            "do not claim the PPTX was edited, regenerated, or downloaded unless a tool actually did that. "
            "If the user asks for revisions, explain the proposed changes and tell them when a new export is needed.\n\n"
            f"Task type: {run.get('workflow_type', 'research')}\n"
            f"Task title: {run.get('title', '')}\n"
            f"Original request: {input_payload.get('question', '')}\n"
            f"Source files: {source_summary}\n"
            f"Generated slide titles: {slide_summary}"
        )

    def chat_stream(self, payload: dict[str, Any]):
        """Yield an AG-UI-compatible direct-chat event stream."""

        run_id = new_run_id()
        message_id = new_message_id()
        yield run_event(
            RUN_STARTED,
            run_id=run_id,
            threadId="direct-chat",
            input={
                "attachmentCount": len(list(payload.get("source_files", []) or [])),
                "imageCount": len(list(payload.get("images", []) or [])),
            },
        )
        try:
            ingestion = None
            attachment_context = ""
            if payload.get("source_files"):
                yield run_event(STEP_STARTED, run_id=run_id, stepName="ingest_attachments")
                ingestion = self._ingest_direct_attachments(payload)
                attachment_context = ingestion_context(self.workspace, str(ingestion["job_id"]))
                yield run_event(
                    STEP_FINISHED,
                    run_id=run_id,
                    stepName="ingest_attachments",
                    result=ingestion,
                )

            chat_request = self._direct_chat_request(payload, attachment_context=attachment_context)
            local_facts = self._runtime_fact_answer(payload, chat_request)
            pi_eligible = (
                not local_facts
                and chat_request.provider_kind != "local"
                and chat_request.session is None
                and all(isinstance(item.get("content"), str) for item in chat_request.messages)
            )
            trace = self._direct_process_trace(chat_request, had_attachments=bool(ingestion))
            if local_facts:
                trace[-1] = {"title": "读取运行时事实", "detail": "已从当前安装状态读取版本、模型、模式与 Skill，避免模型猜测。"}
            elif pi_eligible:
                trace.append({"title": "启动 Pi Agent", "detail": "本轮由 Pi AgentSession 负责模型会话与工具循环。"})
            else:
                trace.append({"title": "使用兼容传输", "detail": "托管网关、本地引擎或视觉消息保留直接传输，避免不兼容的工具协议。"})
            yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
            yield run_event(TEXT_MESSAGE_START, run_id=run_id, messageId=message_id, role="assistant")
            fragments: list[str] = []
            usage: dict[str, int] = {}
            truncated = False
            if local_facts:
                model_events = [{"type": "delta", "content": local_facts}, {"type": "done", "truncated": False}]
            elif pi_eligible:
                model_events = PiAgentClient(workspace=self.workspace, evidence_db=self.evidence_db).stream_chat(
                    provider_kind=chat_request.provider_kind,
                    base_url=chat_request.base_url,
                    api_key=chat_request.api_key,
                    model_id=chat_request.model_id,
                    messages=chat_request.messages,
                    thinking_level=chat_request.thinking_level,
                    task_mode=chat_request.chat_mode,
                )
            else:
                # Managed-gateway, local-only, and vision requests retain the
                # proven direct transport until their provider wire formats
                # can preserve Pi's tool-call contract.
                model_events = stream_chat_text(
                    chat_request.provider_kind,
                    base_url=chat_request.base_url,
                    api_key=chat_request.api_key,
                    model=chat_request.model_id,
                    messages=chat_request.messages,
                    thinking_mode=chat_request.thinking_mode,
                    session=chat_request.session,
                )
            for model_event in model_events:
                if model_event.get("type") == "delta":
                    content = str(model_event.get("content", ""))
                    if content:
                        fragments.append(content)
                        yield run_event(
                            TEXT_MESSAGE_CONTENT,
                            run_id=run_id,
                            messageId=message_id,
                            delta=content,
                        )
                elif model_event.get("type") == "done":
                    received_usage = model_event.get("usage")
                    if not isinstance(received_usage, dict):
                        received_usage = dict(model_event.get("stats", {}) or {}).get("tokens")
                    if isinstance(received_usage, dict):
                        usage = {str(key): value for key, value in received_usage.items() if isinstance(value, int)}
                    truncated = bool(model_event.get("truncated"))
                elif model_event.get("type") == "status":
                    status = str(model_event.get("status", ""))
                    tool_name = str(model_event.get("name", ""))
                    if status == "tool_started" and tool_name:
                        trace.append({"title": "Pi Agent 调用工具", "detail": f"正在执行 ScanSci 工具：{tool_name}"})
                        yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
                elif model_event.get("type") == "tool.completed":
                    tool_name = str(model_event.get("name", ""))
                    trace.append({"title": "ScanSci 工具完成", "detail": f"{tool_name} 已返回结构化结果。"})
                    yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
                elif model_event.get("type") == "tool.failed":
                    tool_name = str(model_event.get("name", ""))
                    trace.append({"title": "ScanSci 工具未完成", "detail": f"{tool_name}：{model_event.get('error', '')}"})
                    yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
                elif model_event.get("type") == "continuation":
                    trace.append(
                        {
                            "title": "自动续写",
                            "detail": "检测到模型达到单次输出上限，已从断点继续生成，避免答案被截断。",
                        }
                    )
                    yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
                elif model_event.get("type") == "retry":
                    delay = int(float(model_event.get("delay_seconds", 0) or 0))
                    reason = "服务繁忙" if model_event.get("reason") == "rate_limit" else "上游暂时不可用"
                    trace.append(
                        {
                            "title": "自动重试",
                            "detail": f"检测到{reason}，将在约 {delay} 秒后继续，本轮内容不会丢失。",
                        }
                    )
                    yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)

            text = "".join(fragments).strip()
            if not text:
                raise RuntimeError("The model returned an empty response")
            if truncated:
                raise RuntimeError("模型连续达到输出上限，ScanSci 没有把不完整内容标记为完成；请缩小问题范围后重试。")
            trace.append({"title": "完成回答", "detail": "模型已返回完整内容并完成响应收束。"})
            yield run_event(CUSTOM, run_id=run_id, name="process_trace", value=trace)
            message: dict[str, Any] = {
                "role": "assistant",
                "content": text,
                "message_id": message_id,
                "mode": chat_request.chat_mode,
                "trace": trace,
            }
            if usage:
                message["usage"] = usage
                yield run_event(CUSTOM, run_id=run_id, name="usage", value=usage)
            if ingestion:
                message["sources"] = list(ingestion.get("sources", []) or [])
            yield run_event(TEXT_MESSAGE_END, run_id=run_id, messageId=message_id)
            yield run_event(
                RUN_FINISHED,
                run_id=run_id,
                threadId="direct-chat",
                result={
                    "message": message,
                    "model": {"provider_id": chat_request.provider_id, "model_id": chat_request.model_id},
                    **({"ingestion": ingestion} if ingestion else {}),
                },
            )
        except Exception as error:  # terminal events prevent a permanently spinning UI
            yield run_event(RUN_ERROR, run_id=run_id, message=str(error), code="chat_failed")

    def _runtime_fact_answer(self, payload: dict[str, Any], chat_request: _DirectChatRequest) -> str:
        raw_messages = [item for item in list(payload.get("messages", []) or []) if isinstance(item, dict)]
        question = next(
            (str(item.get("content", "")) for item in reversed(raw_messages) if item.get("role") == "user"),
            "",
        )
        return runtime_self_description(
            self.workspace,
            question=question,
            model_id=chat_request.model_id,
            provider_name=chat_request.provider_name,
            chat_mode=chat_request.chat_mode,
        )

    def _ingest_direct_attachments(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        source_files = payload.get("source_files")
        if not source_files:
            return None
        return ingest_sources(
            self.workspace,
            source_files,
            parser=str(payload.get("attachment_parser", "auto")),
        )

    def _direct_chat_request(self, payload: dict[str, Any], *, attachment_context: str = "") -> _DirectChatRequest:
        raw_messages = list(payload.get("messages", []) or [])
        messages: list[dict[str, Any]] = []
        for item in raw_messages[-16:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role in {"system", "user", "assistant"} and content:
                messages.append({"role": role, "content": content[:12000]})
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("messages must end with a user message")

        if attachment_context:
            messages.insert(
                max(0, len(messages) - 1),
                {
                    "role": "system",
                    "content": (
                        "The user attached the following local material. Answer from it when relevant, "
                        "name the attachment and preserve any page labels. Do not invent missing facts.\n\n"
                        + attachment_context[:80_000]
                    ),
                },
            )

        settings = load_settings(self.workspace)
        active = dict(settings.get("active_model", {}) or {})
        provider = next(
            (item for item in settings.get("providers", []) if item.get("id") == active.get("provider_id")),
            None,
        )
        if provider is None or not provider.get("enabled", True):
            raise ValueError("当前没有可用的对话模型")

        provider_id = str(provider.get("id", ""))
        provider_kind = str(provider.get("kind", ""))
        managed = str(provider.get("auth_mode", "")) == "managed"
        if managed:
            api_key = "scansci-managed-gateway"
        elif provider_kind == "local":
            api_key = str(provider.get("api_key", "")) or "local"
        else:
            api_key = get_provider_api_key(self.workspace, provider_id)
        if not api_key:
            raise ValueError("当前对话模型尚未配置 API Key")

        model_id = str(active.get("model_id", "")).strip()
        chat_mode = str(payload.get("chat_mode", "general") or "general").strip().lower()
        if chat_mode not in {"general", "writing", "knowledge", "slides"}:
            chat_mode = "general"
        skill_ids = selected_skill_ids(payload, messages)
        system_context, selected_skills = build_agent_system_context(
            self.workspace,
            model_id=model_id,
            provider_name=str(provider.get("name", provider_id)),
            chat_mode=chat_mode,
            selected_ids=skill_ids,
        )
        messages.insert(0, {"role": "system", "content": system_context})
        if provider_id == "local-huggingface":
            # Registering the selected snapshot starts only a loopback server;
            # weights are loaded lazily by the first completion request so the
            # normal desktop startup remains quick.
            provider_kind = "openai-compatible"
            provider = dict(provider)
            provider["base_url"] = ensure_local_transformers_runtime(model_id)
        raw_images = list(payload.get("images", []) or [])
        if raw_images:
            model_record = next(
                (item for item in provider.get("models", []) if str(item.get("id", "")) == model_id),
                {},
            )
            if "vision" not in set(model_record.get("capabilities", []) or []):
                raise ValueError("当前模型不支持图片，请选择带有视觉能力的模型")
            attachments = persist_image_attachments(self.workspace, raw_images)
            blocks = vision_image_blocks(self.workspace, attachments)
            text = str(messages[-1].get("content", ""))
            if provider_kind in {"anthropic-compatible", "anthropic"}:
                content: list[dict[str, Any]] = [{"type": "text", "text": text}]
                content.extend(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": block["mime_type"], "data": block["data"]},
                    }
                    for block in blocks
                )
            else:
                content = [{"type": "text", "text": text}]
                content.extend(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{block['mime_type']};base64,{block['data']}"},
                    }
                    for block in blocks
                )
            messages[-1]["content"] = content
        thinking_mode = (
            managed_glm_thinking_mode(
                thinking_level=payload.get("thinking_level"),
                messages=messages,
            )
            if provider_id == "scansci-managed" and model_id == "glm-4.7-flash"
            else None
        )
        return _DirectChatRequest(
            messages=messages,
            provider_id=provider_id,
            provider_name=str(provider.get("name", provider_id)),
            provider_kind=provider_kind,
            base_url=str(provider.get("base_url", "")),
            api_key=api_key,
            model_id=model_id,
            thinking_mode=thinking_mode,
            session=managed_gateway_session() if managed else None,
            chat_mode=chat_mode,
            thinking_level=normalize_thinking_level(payload.get("thinking_level")),
            selected_skills=selected_skills,
        )

    @staticmethod
    def _direct_process_trace(
        chat_request: _DirectChatRequest,
        *,
        had_attachments: bool,
    ) -> list[dict[str, str]]:
        """Return a safe activity log, never hidden chain-of-thought."""

        trace = [
            {"title": "解析请求", "detail": f"已按“{chat_request.chat_mode}”模式组织本轮任务。"},
            {
                "title": "加载 ScanSci 能力",
                "detail": f"已注入 ScanSci 身份、版本、模式边界与当前模型 {chat_request.model_id}。",
            },
        ]
        if had_attachments:
            trace.append({"title": "读取附件", "detail": "已将本轮添加的本地材料解析为可引用上下文。"})
        if chat_request.selected_skills:
            names = "、".join(str(item.get("id", "")) for item in chat_request.selected_skills)
            trace.append({"title": "加载 Skill", "detail": f"已应用用户显式选择的 Skill：{names}。"})
        trace.append({"title": "生成回答", "detail": "正在通过流式接口生成，并监控输出上限与结束原因。"})
        return trace

    def _submit(self, run_id: str) -> None:
        with self._thread_lock:
            existing = self._threads.get(run_id)
            if existing is not None and existing.is_alive():
                return
            thread = threading.Thread(target=self._execute_run, args=(run_id,), daemon=True, name=f"scansci-{run_id}")
            self._threads[run_id] = thread
            thread.start()

    def _execute_run(self, run_id: str) -> None:
        try:
            self.store.begin_run(run_id)
            run = self.store.get_run(run_id)
            output_artifact_id = str(run.get("output_artifact_id", ""))
            for stage in run["stages"]:
                if stage["status"] == "completed":
                    output_artifact_id = str(stage.get("output", {}).get("artifact_id", output_artifact_id))
                    continue
                if self.store.cancel_requested(run_id):
                    self.store.mark_cancelled(run_id)
                    return
                stage_key = str(stage["key"])
                self.store.start_stage(run_id, stage_key)
                try:
                    if stage["kind"] == "planner":
                        output = self._plan(self.store.get_run(run_id))
                        summary = str(output["summary"])
                    elif stage["kind"] == "tool":
                        output = self._run_tool(self.store.get_run(run_id), stage)
                        summary = self._tool_summary(self.store.get_run(run_id), output)
                    elif stage["kind"] == "verification":
                        output = self._verify(self.store.get_run(run_id))
                        summary = "证据与引用核验通过" if output.get("passed") else "已标记证据不足或待人工核验"
                    else:
                        artifact = self._deliver(self.store.get_run(run_id))
                        output_artifact_id = str(artifact["artifact_id"])
                        output = {"artifact_id": output_artifact_id, "artifact_type": artifact["artifact_type"]}
                        summary = str(artifact["summary"] or "研究产物已保存")
                    self.store.complete_stage(run_id, stage_key, summary=summary, output=output)
                except Exception as error:  # noqa: BLE001 - persisted for resume and UI inspection
                    self.store.fail_stage(run_id, stage_key, error)
                    return
                if self.store.cancel_requested(run_id):
                    self.store.mark_cancelled(run_id)
                    return
            self.store.complete_run(run_id, output_artifact_id=output_artifact_id)
        except Exception as error:  # noqa: BLE001 - last-resort worker boundary
            try:
                current = self.store.get_run(run_id).get("current_stage", "")
                if current:
                    self.store.fail_stage(run_id, str(current), error)
            except Exception:
                return

    def _run_tool(self, run: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
        payload = dict(run["input"])
        if run.get("notebook_id"):
            payload["notebook_id"] = str(run["notebook_id"])
        workflow_type = str(run["workflow_type"])
        tool_name = str(stage.get("tool_name", ""))
        call_id = self.store.begin_tool_call(
            str(run["run_id"]), str(stage["key"]), tool_name=tool_name, input_payload=payload
        )
        try:
            if workflow_type == "ask":
                output = self.answer_sync(payload)
            elif workflow_type == "literature_review" and str(stage.get("key", "")) == "research":
                notebook = self._notebook(str(run["notebook_id"]))
                output = retrieve_review_evidence(
                    self._evidence_db_for_notebook(notebook),
                    str(payload["question"]),
                    chat_client=self._writing_chat_client(),
                    limit=int(payload.get("limit", 14) or 14),
                )
            elif workflow_type == "literature_review" and str(stage.get("key", "")) == "synthesize":
                research = self._stage_output(run, "research")
                output = synthesize_literature_review(
                    research,
                    chat_client=self._writing_chat_client(),
                    reader_url_builder=self._reader_url,
                )
            elif workflow_type == "journal_search":
                output = search_journals(str(payload["query"]), limit=int(payload.get("limit", 8)))
            elif workflow_type == "citation_analysis":
                output = analyze_references(str(payload["text"]), mode=str(payload.get("mode", "full")))
            elif workflow_type == "doi_verification":
                output = verify_doi_metadata(str(payload["doi"]), expected_title=str(payload.get("title", "")))
            elif workflow_type == "paper_atlas":
                output = search_paper_atlas(str(payload["query"]))
            elif workflow_type == "paper_download":
                output = download_paper(
                    str(payload["identifier"]),
                    workspace=self.workspace,
                    strategy=str(payload.get("strategy", "legal_only")),
                )
            elif workflow_type == "ppt_outline":
                output = build_ppt_outline(
                    self._notebook(str(run["notebook_id"])),
                    topic=str(payload.get("topic", "")),
                    template_id=str(payload.get("template_id", "")),
                )
            elif workflow_type == "ppt_project":
                output = create_ppt_project(
                    self._notebook(str(run["notebook_id"])),
                    workspace=self.workspace,
                    topic=str(payload.get("topic", "")),
                    template_id=str(payload.get("template_id", "")),
                )
            elif workflow_type == "pdf_to_ppt":
                try:
                    slide_client = self._slides_chat_client()
                except ValueError:
                    # Source-first generation remains useful while a user is
                    # offline or has not configured a dedicated slide model.
                    slide_client = None
                output = create_source_slide_deck(
                    workspace=self.workspace,
                    sources=list(payload.get("source_files", []) or []),
                    topic=str(payload.get("topic", "")),
                    template_id=str(payload.get("template_id", "")),
                    chat_client=slide_client,
                )
            else:
                raise ValueError(f"No tool executor for workflow: {workflow_type}")
        except Exception as error:
            self.store.fail_tool_call(call_id, error)
            raise
        self.store.complete_tool_call(call_id, output)
        return output

    @staticmethod
    def _plan(run: dict[str, Any]) -> dict[str, Any]:
        spec = _WORKFLOWS[str(run["workflow_type"])]
        source_scope = "当前资料库" if run["notebook_id"] else "当前工作区"
        return {
            "summary": f"已确定 {spec['label']} 的输入、{source_scope}与交付格式",
            "workflow_type": run["workflow_type"],
            "artifact_contract": spec["artifact_type"],
            "stages": [stage.title for stage in spec["stages"]],
        }

    def _verify(self, run: dict[str, Any]) -> dict[str, Any]:
        result = self._tool_output(run)
        verification = dict(result.get("citation_verification", {}) or {})
        reader = dict(result.get("reader_answer", {}) or {})
        return {
            "passed": bool(verification.get("passed", False)),
            "citation_count": int(reader.get("citation_count", 0) or 0),
            "evidence_status": str(result.get("evidence_status", "")),
            "details": verification,
        }

    def _deliver(self, run: dict[str, Any]) -> dict[str, Any]:
        spec = _WORKFLOWS[str(run["workflow_type"])]
        result = self._tool_output(run)
        summary = self._artifact_summary(run, result)
        evidence_links: list[dict[str, Any]] = []
        if run["workflow_type"] in {"ask", "literature_review"}:
            evidence_links = [
                {
                    **dict(item),
                    "relationship": "supports",
                }
                for item in list(dict(result.get("reader_answer", {}) or {}).get("citations", []) or [])
            ]
        file_path = str(
            result.get("file_path", "")
            or result.get("output_path", "")
            or result.get("project_path", "")
            or result.get("path", "")
        )
        return self.store.create_artifact(
            str(run["run_id"]),
            artifact_type=str(spec["artifact_type"]),
            title=str(run["title"]),
            summary=summary,
            payload=result,
            evidence_links=evidence_links,
            file_path=file_path,
        )

    @staticmethod
    def _tool_output(run: dict[str, Any]) -> dict[str, Any]:
        tool_stages = [stage for stage in run["stages"] if stage["kind"] == "tool" and stage["status"] == "completed"]
        if not tool_stages:
            raise RuntimeError("工具阶段尚未产生可交付结果")
        return dict(tool_stages[-1].get("output", {}) or {})

    @staticmethod
    def _stage_output(run: dict[str, Any], stage_key: str) -> dict[str, Any]:
        stage = next(
            (
                item
                for item in list(run.get("stages", []) or [])
                if str(item.get("key", "")) == stage_key and item.get("status") == "completed"
            ),
            None,
        )
        if stage is None:
            raise RuntimeError(f"前置阶段尚未完成：{stage_key}")
        return dict(stage.get("output", {}) or {})

    @staticmethod
    def _tool_summary(run: dict[str, Any], result: dict[str, Any]) -> str:
        workflow = str(run["workflow_type"])
        if workflow == "pdf_to_ppt":
            slides = list(dict(result.get("outline", {}) or {}).get("slides", []) or [])
            slide_count = int(result.get("slide_count", 0) or 0) or len(slides) + 1
            return f"已从 {int(result.get('source_count', 0) or 0)} 份材料生成 {slide_count} 页可编辑 PPTX"
        if workflow == "literature_review" and result.get("phase") == "retrieval":
            summary = dict(result.get("retrieval_summary", {}) or {})
            return (
                f"已完成 {int(summary.get('section_count', 0) or 0)} 个章节的检索，"
                f"汇集 {int(summary.get('document_count', 0) or 0)} 篇文献、"
                f"{int(summary.get('evidence_count', 0) or 0)} 条证据"
            )
        if workflow in {"ask", "literature_review"}:
            reader = dict(result.get("reader_answer", {}) or {})
            return f"已综合 {int(reader.get('citation_count', 0) or 0)} 条可回跳引用"
        count = result.get("count") or result.get("total") or len(result.get("results", []) or [])
        if count:
            return f"工具执行完成，返回 {count} 条结果"
        return "工具执行完成"

    @staticmethod
    def _artifact_summary(run: dict[str, Any], result: dict[str, Any]) -> str:
        if run["workflow_type"] == "pdf_to_ppt":
            return str(result.get("message", "已生成可编辑 PPTX"))
        if run["workflow_type"] == "literature_review":
            abstract = dict(dict(result.get("review_document", {}) or {}).get("abstract", {}) or {})
            text = str(abstract.get("text", "")).strip()
            return text[:220] + ("…" if len(text) > 220 else "")
        if run["workflow_type"] == "ask":
            text = str(dict(result.get("reader_answer", {}) or {}).get("text", "")).strip()
            return text[:220] + ("…" if len(text) > 220 else "")
        if result.get("message"):
            return str(result["message"])
        count = result.get("count") or result.get("total") or len(result.get("results", []) or [])
        return f"已保存 {count} 条结构化结果" if count else "结构化研究产物已保存"

    def _requested_notebook(self, payload: dict[str, Any]) -> dict[str, Any]:
        notebook_id = str(payload.get("notebook_id", "")).strip()
        if notebook_id:
            return self._notebook(notebook_id)
        summary = load_workspace_summary(self.workspace)
        notebooks = list(summary.get("notebooks", []) or [])
        if not notebooks:
            # Legacy callers and one-off evidence jobs may provide a concrete
            # evidence database without first creating a notebook record.
            if self.evidence_db.is_file():
                return {"notebook_id": "", "sources": []}
            raise FileNotFoundError("当前工作区没有可用资料库")
        return dict(notebooks[0])

    def _notebook(self, notebook_id: str) -> dict[str, Any]:
        summary = load_workspace_summary(self.workspace, notebook_id=notebook_id)
        notebooks = list(summary.get("notebooks", []) or [])
        if not notebooks:
            raise FileNotFoundError(f"Notebook does not exist: {notebook_id}")
        return dict(notebooks[0])

    def _evidence_db_for_notebook(self, notebook: dict[str, Any]) -> Path:
        """Resolve the notebook's own index, with a legacy single-index fallback."""

        for source in list(notebook.get("sources", []) or []):
            candidate = Path(str(dict(source).get("evidence_db_path", "") or ""))
            if candidate.is_file():
                return candidate.resolve()
        isolated = notebook_evidence_db(self.evidence_db, str(notebook.get("notebook_id", "")))
        if isolated.is_file():
            return isolated
        return self.evidence_db

    @staticmethod
    def _normalize_input(workflow_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {str(key): value for key, value in payload.items() if key not in {"workflow_type", "notebook_id"}}
        required = {
            "ask": "question",
            "literature_review": "question",
            "journal_search": "query",
            "citation_analysis": "text",
            "doi_verification": "doi",
            "paper_atlas": "query",
            "paper_download": "identifier",
        }.get(workflow_type)
        if required and not str(normalized.get(required, "")).strip():
            raise ValueError(f"{required} is required")
        if workflow_type == "pdf_to_ppt":
            sources = normalized.get("source_files")
            if not isinstance(sources, list) or not sources:
                raise ValueError("source_files is required for PDF-to-PPT")
        return normalized

    @staticmethod
    def _run_title(workflow_type: str, payload: dict[str, Any]) -> str:
        source = (
            payload.get("question")
            or payload.get("query")
            or payload.get("doi")
            or payload.get("identifier")
            or payload.get("topic")
            or _WORKFLOWS[workflow_type]["label"]
        )
        title = " ".join(str(source).split())
        return title[:96] + ("…" if len(title) > 96 else "")

    @staticmethod
    def _reader_url(doc_id: str, anchor: str) -> str:
        suffix = f"#{anchor}" if anchor else ""
        return f"/api/sources/{quote(doc_id, safe='')}/reader{suffix}"

    @staticmethod
    def _original_url(doc_id: str) -> str:
        return f"/api/sources/{quote(doc_id, safe='')}/original"

    def _writing_chat_client(self) -> Any:
        settings = load_settings(self.workspace)
        reference = self._role_reference(settings, "writing")
        if reference.startswith("provider:"):
            remainder = reference.removeprefix("provider:")
            provider_id, separator, model_id = remainder.partition(":")
            if not separator or not provider_id or not model_id:
                raise ValueError("写作模型配置无效，请在“设置 → 模型服务 → 功能分工”中重新选择")
            provider = next(
                (item for item in settings.get("providers", []) if str(item.get("id", "")) == provider_id),
                None,
            )
            if provider is None or not provider.get("enabled", True):
                raise ValueError("指定的写作模型提供商不存在或已停用")
            if str(provider.get("kind", "")) == "local":
                raise ValueError(
                    "真正的文献综述需要生成模型。请在“设置 → 模型服务”添加云端模型服务或本地 Ollama/LM Studio，"
                    "并把“写作”分工指向该模型。"
                )
            api_key = "scansci-managed-gateway" if str(provider.get("auth_mode", "")) == "managed" else get_provider_api_key(self.workspace, provider_id)
            if not api_key:
                raise ValueError(f"写作模型 {provider.get('name', provider_id)} 尚未配置 API Key")
            managed = str(provider.get("auth_mode", "")) == "managed"
            cache_key = (provider_id, model_id, str(provider.get("base_url", "")))
            if managed and cache_key in self._managed_writing_clients:
                return self._managed_writing_clients[cache_key]
            primary_client = build_chat_json_client(
                str(provider.get("kind", "")),
                base_url=str(provider.get("base_url", "")),
                api_key=api_key,
                model=model_id,
                timeout=20.0 if managed else 60.0,
                session=managed_gateway_session() if managed else None,
                thinking_mode="disabled" if managed else None,
            )
            if not managed:
                return primary_client
            fallback_model = next(
                (
                    str(item.get("id", ""))
                    for item in list(provider.get("models", []) or [])
                    if str(item.get("id", "")) and str(item.get("id", "")) != model_id
                ),
                "",
            )
            if not fallback_model:
                self._managed_writing_clients[cache_key] = primary_client
                return primary_client
            fallback_client = build_chat_json_client(
                str(provider.get("kind", "")),
                base_url=str(provider.get("base_url", "")),
                api_key=api_key,
                model=fallback_model,
                timeout=35.0,
                session=managed_gateway_session(),
                thinking_mode="disabled",
            )
            client = CascadingChatJsonClient([primary_client, fallback_client])
            self._managed_writing_clients[cache_key] = client
            return client
        if reference.startswith("local:"):
            local_id = reference.removeprefix("local:")
            local_model = next(
                (item for item in settings.get("local_models", []) if str(item.get("id", "")) == local_id),
                None,
            )
            if local_model is None or not local_model.get("enabled", False):
                raise ValueError("指定的本地写作模型不存在或未启用")
            if str(local_model.get("runtime", "")) == "builtin":
                raise ValueError(
                    "本地证据引擎只负责检索，不能冒充综述作者。请为“写作”分工选择 Ollama、LM Studio 或 API 模型。"
                )
            base_url = str(local_model.get("base_url", "")).strip()
            model_id = str(local_model.get("model_id", "")).strip()
            if not base_url or not model_id:
                raise ValueError("本地写作模型需要配置 Base URL 和模型 ID")
            return build_chat_json_client(
                "openai-compatible",
                base_url=base_url,
                api_key="scansci-local-runtime",
                model=model_id,
            )
        raise ValueError("尚未指定写作模型，请在“设置 → 模型服务 → 功能分工”中选择")

    def _slides_chat_client(self) -> Any:
        """Return the model dedicated to presentation planning, when configured."""

        settings = load_settings(self.workspace)
        reference = self._role_reference(settings, "slides")
        if reference.startswith("provider:"):
            provider_id, separator, model_id = reference.removeprefix("provider:").partition(":")
            if not separator or not provider_id or not model_id:
                raise ValueError("演示模型配置无效")
            provider = next(
                (item for item in settings.get("providers", []) if str(item.get("id", "")) == provider_id),
                None,
            )
            if provider is None or not provider.get("enabled", True):
                raise ValueError("指定的演示模型不存在或已停用")
            if str(provider.get("kind", "")) == "local":
                raise ValueError("内置检索引擎不能用于生成演示文稿")
            api_key = "scansci-managed-gateway" if str(provider.get("auth_mode", "")) == "managed" else get_provider_api_key(self.workspace, provider_id)
            if not api_key:
                raise ValueError("演示模型尚未配置 API Key")
            return build_chat_json_client(
                str(provider.get("kind", "")),
                base_url=str(provider.get("base_url", "")),
                api_key=api_key,
                model=model_id,
                session=managed_gateway_session() if str(provider.get("auth_mode", "")) == "managed" else None,
                # Planning a compact JSON deck should not wait for a long
                # hidden chain of thought. This is supported by the managed
                # GLM gateway; other providers keep their own default.
                thinking_mode="disabled" if str(provider.get("auth_mode", "")) == "managed" else None,
            )
        if reference.startswith("local:"):
            local_id = reference.removeprefix("local:")
            local_model = next(
                (item for item in settings.get("local_models", []) if str(item.get("id", "")) == local_id),
                None,
            )
            if local_model is None or not local_model.get("enabled", False):
                raise ValueError("指定的本地演示模型不存在或未启用")
            if str(local_model.get("runtime", "")) == "builtin":
                raise ValueError("内置检索引擎不能用于生成演示文稿")
            base_url = str(local_model.get("base_url", "")).strip()
            model_id = str(local_model.get("model_id", "")).strip()
            if not base_url or not model_id:
                raise ValueError("本地演示模型需要配置 Base URL 和模型 ID")
            return build_chat_json_client(
                "openai-compatible",
                base_url=base_url,
                api_key="scansci-local-runtime",
                model=model_id,
            )
        raise ValueError("尚未指定演示模型")

    @staticmethod
    def _role_reference(settings: dict[str, Any], role: str) -> str:
        reference = str(dict(settings.get("model_roles", {}) or {}).get(role, "")).strip()
        active = dict(settings.get("active_model", {}) or {})
        active_provider_id = str(active.get("provider_id", ""))
        active_model_id = str(active.get("model_id", ""))
        active_provider = next(
            (item for item in settings.get("providers", []) if str(item.get("id", "")) == active_provider_id),
            None,
        )
        if (
            role == "writing"
            and reference == "provider:local-evidence:evidence-retrieval"
            and active_provider is not None
            and str(active_provider.get("kind", "")) != "local"
        ):
            return f"provider:{active_provider_id}:{active_model_id}"
        return reference

    @classmethod
    def _role_identity(cls, settings: dict[str, Any], role: str) -> tuple[str, str]:
        reference = cls._role_reference(settings, role)
        if reference.startswith("provider:"):
            provider_id, _separator, model_id = reference.removeprefix("provider:").partition(":")
            return provider_id, model_id
        if reference.startswith("local:"):
            local_id = reference.removeprefix("local:")
            local_model = next(
                (item for item in settings.get("local_models", []) if str(item.get("id", "")) == local_id),
                {},
            )
            return f"local:{local_id}", str(local_model.get("model_id", ""))
        return "", ""


def _provider_neutral_tool_calls(result: dict[str, Any], *, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe real application-side actions without inventing model calls.

    Provider-compatible chat endpoints are not required to serialize native
    tool-call messages.  The records below are derived solely from completed
    ScanSci workflow output and are therefore safe to show in the process
    trace and persist in a research run.
    """

    calls: list[dict[str, Any]] = []
    query_plan = dict(result.get("query_plan", {}) or {})
    if query_plan:
        calls.append({"name": "plan_query", "status": "completed", "output": {"question_type": query_plan.get("question_type", "")}})
    retrieval_queries = [str(item) for item in list(result.get("retrieval_queries", []) or []) if str(item).strip()]
    hits = list(result.get("hits", []) or [])
    if retrieval_queries or hits:
        calls.append(
            {
                "name": "search_local_evidence",
                "status": "completed",
                "output": {"queries": retrieval_queries, "hit_count": len(hits)},
            }
        )
    if steps:
        calls.append({"name": "assess_evidence", "status": "completed", "output": {"steps": len(steps)}})
    verification = dict(result.get("citation_verification", {}) or {})
    calls.append(
        {
            "name": "build_verified_answer",
            "status": "completed",
            "output": {
                "passed": bool(verification.get("passed")),
                "cited_quote_count": int(verification.get("cited_quote_count", 0) or 0),
            },
        }
    )
    return calls
