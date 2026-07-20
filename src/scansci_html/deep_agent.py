"""Deep Agents harness for evidence-first ScanSci research sessions.

The harness deliberately exposes high-level ScanSci actions instead of a raw
shell, browser, or host filesystem.  This keeps the model useful for planning
and tool composition without granting it authority beyond the desktop app's
existing research capabilities.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agent_reasoning import native_reasoning_options, normalize_thinking_level
from .qa.agent import answer_question
from .research_tools import (
    analyze_references,
    build_ppt_outline,
    capability_snapshot,
    search_journals,
    search_paper_atlas,
    verify_doi_metadata,
)
from .retrieval import search_evidence_store
from .workspace import load_workspace_summary


AgentFactory = Callable[..., Any]


class DeepAgentsUnavailable(RuntimeError):
    """Raised when the optional Deep Agents runtime has not been installed."""


class DeepAgentsConfigurationError(ValueError):
    """Raised when an active ScanSci provider cannot run a Deep Agent."""


_SYSTEM_PROMPT = """You are ScanSci Research Agent, a scholarly task router.

First identify the requested deliverable, then choose the narrowest ScanSci
tool that can produce it. You may plan multi-step research work and combine
tool outputs, but never claim that an external action occurred unless a tool
returned success. Paper Atlas is a discovery lead, not verified evidence.

For a scientific claim about the active notebook or imported literature, call
`build_verified_answer` before delivery. Its citation payload is the only
authoritative way to deliver source-grounded conclusions. If evidence is
insufficient, state the gap rather than guessing.

For non-evidence deliverables such as discovery leads, journal/DOI metadata,
citation audits, workspace status, or a presentation outline, call the relevant
tool and then `deliver_research_result`. Do not put scientific conclusions in
that delivery: it is a status or planning artefact, not a bypass around the
evidence gate. Writing tools are intentionally not exposed here; downloads and
project creation require an explicit user-approved workflow.
"""

_EVIDENCE_ONLY_PROMPT = """
This request is explicitly evidence-only. Use local evidence and finish with
`build_verified_answer`; do not use `deliver_research_result`.
"""

_DELIVERY_TYPES = frozenset(
    {
        "research_plan",
        "discovery_report",
        "journal_report",
        "doi_report",
        "citation_audit",
        "presentation_outline",
        "workspace_report",
        "tool_status",
    }
)


def build_deep_agent_model(
    *,
    provider_id: str = "",
    provider_kind: str,
    base_url: str,
    api_key: str,
    model: str,
    thinking_level: str = "auto",
) -> Any:
    """Adapt ScanSci's existing provider settings to LangChain chat models."""

    kind = str(provider_kind or "").strip().lower()
    if not api_key:
        raise DeepAgentsConfigurationError("A provider API key is required for Deep Agents.")
    if not model:
        raise DeepAgentsConfigurationError("An active model is required for Deep Agents.")
    native_options = native_reasoning_options(
        provider_id=provider_id,
        provider_kind=kind,
        thinking_level=normalize_thinking_level(thinking_level),
    )

    if kind in {"openai", "openai-compatible"}:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as error:  # pragma: no cover - exercised in packaged installs
            raise DeepAgentsUnavailable("Install the ScanSci Deep Agents dependencies first.") from error
        options = {"model": model, "api_key": api_key, "base_url": base_url or None}
        if native_options:
            options.update(native_options)
        else:
            options["temperature"] = 0
        return ChatOpenAI(**options)
    if kind in {"anthropic", "anthropic-compatible"}:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as error:  # pragma: no cover - exercised in packaged installs
            raise DeepAgentsUnavailable("Install the ScanSci Deep Agents dependencies first.") from error
        # ScanSci's original HTTP client stored Anthropic's public endpoint as
        # ``https://api.anthropic.com/v1``.  The Anthropic SDK already appends
        # ``/v1`` internally, while compatible providers may use arbitrary
        # paths, so normalize only that known public endpoint.
        resolved_base_url = str(base_url or "").rstrip("/")
        if resolved_base_url == "https://api.anthropic.com/v1":
            resolved_base_url = "https://api.anthropic.com"
        options = {"model": model, "api_key": api_key, "base_url": resolved_base_url or None}
        if native_options:
            options.update(native_options)
        else:
            options["temperature"] = 0
        return ChatAnthropic(**options)
    raise DeepAgentsConfigurationError(f"Unsupported Deep Agents provider: {provider_kind}")


class ScanSciDeepAgent:
    """Run one routed research task through the bounded Deep Agents harness."""

    def __init__(
        self,
        *,
        evidence_db: str | Path,
        workspace: str | Path | None = None,
        model: Any,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.evidence_db = Path(evidence_db).resolve()
        self.workspace = Path(workspace).resolve() if workspace else None
        self.model = model
        self.agent_factory = agent_factory or _create_deep_agent

    def answer(
        self,
        question: str,
        *,
        limit: int = 8,
        thread_id: str = "",
        task_mode: str = "auto",
    ) -> dict[str, Any]:
        """Run a research task with an evidence gate for scientific claims.

        ``auto`` lets the Agent return a bounded non-writing research artefact.
        ``evidence`` retains the original strict evidence-answer contract. If a
        model fails to deliver either contract, ScanSci falls back to the
        deterministic evidence verifier rather than returning uncited prose.
        """

        clean_question = str(question or "").strip()
        if not clean_question:
            raise ValueError("question is required")
        normalized_mode = _normalize_task_mode(task_mode)
        if normalized_mode == "evidence" and not self.evidence_db.is_file():
            raise FileNotFoundError(f"Evidence store does not exist: {self.evidence_db}")
        bounded_limit = max(1, min(20, int(limit)))
        audit: list[dict[str, Any]] = []
        finalized: list[dict[str, Any]] = []
        deliveries: list[dict[str, Any]] = []
        agent = self.agent_factory(
            model=self.model,
            tools=self._tools(
                limit=bounded_limit,
                audit=audit,
                finalized=finalized,
                deliveries=deliveries,
                task_mode=normalized_mode,
            ),
            system_prompt=_system_prompt(normalized_mode),
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": clean_question}]},
            config={"configurable": {"thread_id": thread_id or f"scansci-{id(self)}"}},
        )
        if finalized:
            response = dict(finalized[-1])
            finalization = "tool"
        elif deliveries:
            response = _research_delivery_response(clean_question, deliveries[-1])
            finalization = "research_delivery"
        elif not self.evidence_db.is_file():
            raise RuntimeError(
                "The Agent did not produce a research delivery, and no evidence store is available for a safe fallback."
            )
        else:
            response = self._verified_answer(clean_question, bounded_limit)
            finalization = "safety_fallback"
        response["deep_agent"] = {
            "harness": "deepagents",
            "task_mode": normalized_mode,
            "finalization": finalization,
            "tool_calls": audit,
            "model_output": _final_message_text(result),
        }
        return response

    def _tools(
        self,
        *,
        limit: int,
        audit: list[dict[str, Any]],
        finalized: list[dict[str, Any]],
        deliveries: list[dict[str, Any]],
        task_mode: str,
    ) -> list[Callable[..., dict[str, Any]]]:
        evidence_db = self.evidence_db
        workspace = self.workspace

        def search_local_evidence(query: str, result_limit: int = 8) -> dict[str, Any]:
            """Search sentence-level evidence in the active ScanSci notebook.

            Returns compact source snippets with stable evidence IDs and HTML
            anchors. Use this before drawing a scientific conclusion.
            """

            if not evidence_db.is_file():
                raise FileNotFoundError(f"Evidence store does not exist: {evidence_db}")
            requested_limit = max(1, min(20, int(result_limit)))
            hits = search_evidence_store(evidence_db, query, limit=requested_limit, context_mode="sentence")
            payload = {
                "query": str(query),
                "hits": [_compact_evidence_hit(hit) for hit in hits],
                "count": len(hits),
            }
            _record_tool(
                audit,
                "search_local_evidence",
                {
                    "query": str(query),
                    "count": len(hits),
                    "evidence_ids": [str(hit.get("evidence_id", "")) for hit in hits],
                },
            )
            return payload

        def build_verified_answer(question: str, result_limit: int = limit) -> dict[str, Any]:
            """Create the final citation-verified answer from the active notebook.

            This is mandatory before final delivery for notebook-grounded
            questions. It returns inline citations, exact source quotes, and a
            verifier result.
            """

            payload = self._verified_answer(question, max(1, min(20, int(result_limit))))
            finalized.append(payload)
            _record_tool(audit, "build_verified_answer", _answer_summary(payload))
            return payload

        def verify_doi(doi: str, expected_title: str = "") -> dict[str, Any]:
            """Verify DOI metadata against Crossref; use for bibliographic checks."""

            payload = verify_doi_metadata(doi, expected_title=expected_title)
            _record_tool(audit, "verify_doi", {"doi": payload.get("doi", ""), "status": payload.get("status", "")})
            return payload

        def discover_papers(query: str) -> dict[str, Any]:
            """Find related papers through ScanSci Paper Atlas for discovery only."""

            payload = search_paper_atlas(query)
            _record_tool(audit, "discover_papers", {"query": payload.get("query", ""), "status": payload.get("status", "")})
            return payload

        def search_journal(query: str, result_limit: int = 8) -> dict[str, Any]:
            """Look up journal metadata, impact indicators, and warning flags."""

            payload = search_journals(query, limit=max(1, min(20, int(result_limit))))
            _record_tool(audit, "search_journal", {"query": payload.get("query", ""), "count": len(payload.get("items", []))})
            return payload

        def audit_references(text: str, mode: str = "references") -> dict[str, Any]:
            """Audit supplied references or manuscript text through Citation Lab."""

            payload = analyze_references(text, mode="references" if mode == "references" else "full")
            _record_tool(audit, "audit_references", {"mode": mode})
            return payload

        def inspect_workspace(notebook_id: str = "") -> dict[str, Any]:
            """Inspect the current ScanSci workspace without changing it."""

            if workspace is None:
                payload = {"status": "unavailable", "reason": "No workspace was configured for this Agent run."}
            else:
                summary = load_workspace_summary(workspace, notebook_id=str(notebook_id or ""))
                payload = _compact_workspace_summary(summary)
            _record_tool(
                audit,
                "inspect_workspace",
                {"notebook_id": str(notebook_id or ""), "status": payload.get("status", "ready")},
            )
            return payload

        def inspect_available_tools() -> dict[str, Any]:
            """List enabled ScanSci research capabilities without executing them."""

            if workspace is None:
                payload = {"status": "unavailable", "reason": "No workspace was configured for this Agent run."}
            else:
                snapshot = capability_snapshot(workspace=workspace, evidence_db=evidence_db)
                payload = {
                    "status": "ready",
                    "evidence_store_ready": bool(snapshot.get("evidence_store_ready")),
                    "tools": [
                        {
                            "id": str(item.get("id", "")),
                            "name": str(item.get("name", "")),
                            "status": str(item.get("status", "")),
                        }
                        for item in list(snapshot.get("tools", []) or [])
                        if isinstance(item, dict)
                    ],
                }
            _record_tool(audit, "inspect_available_tools", {"status": payload.get("status", "ready")})
            return payload

        def build_presentation_outline(
            topic: str = "",
            notebook_id: str = "",
            template_id: str = "",
        ) -> dict[str, Any]:
            """Create a source-linked presentation outline without writing a project to disk."""

            if workspace is None:
                raise ValueError("A workspace is required to build a presentation outline.")
            summary = load_workspace_summary(workspace, notebook_id=str(notebook_id or ""))
            notebooks = list(summary.get("notebooks", []) or [])
            if not notebooks:
                raise FileNotFoundError("The current workspace has no usable notebook.")
            payload = build_ppt_outline(
                dict(notebooks[0]),
                topic=str(topic or ""),
                template_id=str(template_id or ""),
            )
            _record_tool(
                audit,
                "build_presentation_outline",
                {
                    "notebook_id": str(notebooks[0].get("notebook_id", "")),
                    "slide_count": int(payload.get("slide_count", 0) or 0),
                },
            )
            return payload

        def deliver_research_result(
            delivery_type: str,
            summary: str,
            next_steps: list[str] | None = None,
        ) -> dict[str, Any]:
            """Deliver a non-evidence research artefact based on tool results.

            This tool is for planning, discovery, metadata, audit, workspace,
            capability, and presentation-outline reports. It must not be used to
            deliver scientific conclusions; call build_verified_answer for those.
            """

            normalized_type = str(delivery_type or "").strip().lower()
            if normalized_type not in _DELIVERY_TYPES:
                allowed = ", ".join(sorted(_DELIVERY_TYPES))
                raise ValueError(f"Unsupported research delivery type: {delivery_type}. Allowed: {allowed}")
            if not audit:
                raise ValueError("A research delivery must follow at least one ScanSci tool result.")
            clean_summary = " ".join(str(summary or "").split())
            if not clean_summary:
                raise ValueError("summary is required")
            payload = {
                "delivery_type": normalized_type,
                "summary": clean_summary[:2400],
                "next_steps": [
                    " ".join(str(item).split())[:300]
                    for item in list(next_steps or [])
                    if str(item).strip()
                ][:8],
                "evidence_required": False,
            }
            deliveries.append(payload)
            _record_tool(audit, "deliver_research_result", {"delivery_type": normalized_type})
            return payload

        tools: list[Callable[..., dict[str, Any]]] = [
            search_local_evidence,
            build_verified_answer,
            verify_doi,
            discover_papers,
            search_journal,
            audit_references,
            inspect_workspace,
            inspect_available_tools,
            build_presentation_outline,
        ]
        if task_mode != "evidence":
            tools.append(deliver_research_result)
        return tools

    def _verified_answer(self, question: str, limit: int) -> dict[str, Any]:
        return answer_question(
            self.evidence_db,
            question,
            limit=limit,
            max_quotes=min(8, limit),
            adequacy_profile="manual",
            agentic_profile="custom",
            query_variants=1,
            max_followup_queries=1,
        )


def _create_deep_agent(**kwargs: Any) -> Any:
    try:
        from deepagents import create_deep_agent
    except ImportError as error:  # pragma: no cover - exercised in packaged installs
        raise DeepAgentsUnavailable("Install the ScanSci Deep Agents dependencies first.") from error
    return create_deep_agent(**kwargs)


def _compact_evidence_hit(hit: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(hit.get("text", "")).split())
    return {
        "evidence_id": str(hit.get("evidence_id", "")),
        "doc_id": str(hit.get("doc_id", "")),
        "paper": str(hit.get("paper", "")),
        "doi": str(hit.get("doi", "")),
        "section": str(hit.get("section", "")),
        "html_anchor": str(hit.get("html_anchor", "")),
        "text": text[:1600],
        "score": round(float(hit.get("score", 0.0) or 0.0), 6),
    }


def _record_tool(audit: list[dict[str, Any]], name: str, payload: dict[str, Any]) -> None:
    audit.append({"name": name, "summary": payload})


def _answer_summary(payload: dict[str, Any]) -> dict[str, Any]:
    reader_answer = dict(payload.get("reader_answer", {}) or {})
    verification = dict(payload.get("citation_verification", {}) or {})
    return {
        "citation_count": int(reader_answer.get("citation_count", 0) or 0),
        "verification_passed": bool(verification.get("passed", False)),
    }


def _normalize_task_mode(task_mode: str) -> str:
    normalized = str(task_mode or "auto").strip().lower()
    if normalized not in {"auto", "evidence"}:
        raise ValueError("task_mode must be 'auto' or 'evidence'")
    return normalized


def _system_prompt(task_mode: str) -> str:
    return _SYSTEM_PROMPT + (_EVIDENCE_ONLY_PROMPT if task_mode == "evidence" else "")


def _compact_workspace_summary(summary: dict[str, Any]) -> dict[str, Any]:
    notebooks = []
    for item in list(summary.get("notebooks", []) or [])[:12]:
        if not isinstance(item, dict):
            continue
        counts = dict(item.get("counts", {}) or {})
        notebooks.append(
            {
                "notebook_id": str(item.get("notebook_id", "")),
                "title": str(item.get("title", "")),
                "description": str(item.get("description", ""))[:400],
                "counts": {
                    "sources": int(counts.get("sources", 0) or 0),
                    "notes": int(counts.get("notes", 0) or 0),
                    "layers": int(counts.get("layers", 0) or 0),
                },
            }
        )
    return {
        "status": "ready",
        "counts": dict(summary.get("counts", {}) or {}),
        "notebooks": notebooks,
    }


def _research_delivery_response(question: str, delivery: dict[str, Any]) -> dict[str, Any]:
    """Return a truthful non-evidence delivery without presenting it as cited QA."""

    summary = str(delivery.get("summary", "")).strip()
    return {
        "question": question,
        "evidence_status": "not_required",
        "agent_delivery": dict(delivery),
        "reader_answer": {
            "text": summary,
            "citations": [],
            "citation_count": 0,
        },
        "citation_verification": {
            "passed": True,
            "required": False,
            "status": "not_required",
            "reason": "This is a non-evidence research artefact, not a scientific conclusion.",
        },
    }


def _final_message_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    messages = list(result.get("messages", []) or [])
    for message in reversed(messages):
        message_type = str(getattr(message, "type", "") or "").strip().lower()
        if message_type in {"tool", "human", "system"}:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "").strip().lower()
            if role in {"tool", "user", "human", "system"}:
                continue
            text = message.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""
