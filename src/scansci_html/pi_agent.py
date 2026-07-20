"""Process-isolated bridge from ScanSci's Python runtime to the Pi Agent SDK.

The Node sidecar owns model orchestration.  Every actionable tool call crosses
this JSONL boundary and is executed by a narrow ScanSci dispatcher, so Pi never
receives shell or arbitrary filesystem tools.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from uuid import uuid4

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


class PiRuntimeUnavailable(RuntimeError):
    """Raised when the bundled Pi sidecar or Node runtime cannot be found."""


class PiAgentClient:
    """Run one isolated Pi session and bridge approved ScanSci tools."""

    def __init__(self, *, workspace: str | Path, evidence_db: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.evidence_db = Path(evidence_db).resolve()

    @staticmethod
    def runtime_paths() -> tuple[Path, Path]:
        if getattr(sys, "frozen", False):
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
            node_candidates = [
                bundle_root / "pi_runtime" / "node.exe",
                Path(sys.executable).parent / "pi_runtime" / "node.exe",
            ]
            script_candidates = [
                bundle_root / "pi_runtime" / "main.mjs",
                Path(sys.executable).parent / "pi_runtime" / "main.mjs",
            ]
        else:
            project_root = Path(__file__).resolve().parents[2]
            node_on_path = shutil.which("node")
            node_candidates = [Path(node_on_path)] if node_on_path else []
            script_candidates = [project_root / "pi-runtime" / "dist" / "main.mjs"]

        node_path = next((path for path in node_candidates if path.is_file()), None)
        script_path = next((path for path in script_candidates if path.is_file()), None)
        if node_path is None:
            raise PiRuntimeUnavailable("The ScanSci Pi Node runtime is unavailable")
        if script_path is None:
            raise PiRuntimeUnavailable("The ScanSci Pi sidecar bundle is unavailable")
        return node_path, script_path

    @classmethod
    def runtime_status(cls, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
        node_path, script_path = cls.runtime_paths()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(node_path), str(script_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write('{"type":"ping"}\n')
            process.stdin.flush()
            output: Queue[str | None] = Queue()

            def read_one() -> None:
                output.put(process.stdout.readline() or None)

            threading.Thread(target=read_one, daemon=True).start()
            try:
                line = output.get(timeout=timeout_seconds)
            except Empty as error:
                raise PiRuntimeUnavailable("The ScanSci Pi sidecar did not respond") from error
            if not line:
                raise PiRuntimeUnavailable("The ScanSci Pi sidecar exited before responding")
            response = json.loads(line)
            if response.get("type") != "pong":
                raise PiRuntimeUnavailable(f"Unexpected Pi sidecar response: {response.get('type', '')}")
            return {
                "ready": True,
                "runtime": str(response.get("runtime", "pi")),
                "version": str(response.get("version", "")),
                "node": str(node_path),
                "sidecar": str(script_path),
            }
        finally:
            process.kill()
            process.wait(timeout=5)

    def stream_chat(
        self,
        *,
        provider_kind: str,
        base_url: str,
        api_key: str,
        model_id: str,
        messages: list[dict[str, Any]],
        thinking_level: str = "medium",
        task_mode: str = "general",
        timeout_seconds: float = 900.0,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized Pi events for an existing ScanSci chat request."""

        system_parts: list[str] = []
        conversation: list[str] = []
        for item in messages:
            role = str(item.get("role", "user")).strip().lower()
            content = item.get("content", "")
            if not isinstance(content, str):
                raise ValueError("Pi text bridge does not accept image message blocks")
            if role == "system":
                system_parts.append(content)
            else:
                conversation.append(f"[{role.upper()}]\n{content}")
        if not conversation:
            raise ValueError("Pi requires at least one conversational message")

        request_id = uuid4().hex
        agent_dir = self.workspace.parent / ".scansci-pi-agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        start_message = {
            "type": "run.start",
            "request_id": request_id,
            "cwd": str(self.workspace.parent),
            "agent_dir": str(agent_dir),
            "provider_kind": provider_kind,
            "base_url": base_url,
            "model_id": model_id,
            "thinking_level": thinking_level,
            "system_prompt": "\n\n".join(system_parts),
            "prompt": (
                "Continue the following ScanSci conversation. Reply to the final USER message.\n\n"
                + "\n\n".join(conversation)
            ),
            "task_mode": task_mode,
        }
        yield from self._run_process(
            start_message,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    def _run_process(
        self,
        start_message: dict[str, Any],
        *,
        api_key: str,
        timeout_seconds: float,
    ) -> Iterator[dict[str, Any]]:
        node_path, script_path = self.runtime_paths()
        environment = dict(os.environ)
        environment["SCANSCIPI_PROVIDER_KEY"] = api_key
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(node_path), str(script_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            creationflags=creation_flags,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        output: Queue[str | None] = Queue()
        errors: list[str] = []

        def drain_stdout() -> None:
            for line in process.stdout:
                output.put(line)
            output.put(None)

        def drain_stderr() -> None:
            for line in process.stderr:
                if len(errors) < 40:
                    errors.append(line.rstrip())

        threading.Thread(target=drain_stdout, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        process.stdin.write(json.dumps(start_message, ensure_ascii=False) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + timeout_seconds

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Pi Agent exceeded the request timeout")
                try:
                    line = output.get(timeout=min(1.0, remaining))
                except Empty:
                    if process.poll() is not None:
                        detail = "\n".join(errors[-8:])
                        raise RuntimeError(f"Pi Agent exited unexpectedly{': ' + detail if detail else ''}")
                    continue
                if line is None:
                    detail = "\n".join(errors[-8:])
                    raise RuntimeError(f"Pi Agent closed its output stream{': ' + detail if detail else ''}")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise RuntimeError("Pi Agent returned an invalid protocol message") from error

                event_type = str(event.get("type", ""))
                if event_type == "tool.call":
                    call_id = str(event.get("call_id", ""))
                    name = str(event.get("name", ""))
                    arguments = dict(event.get("arguments", {}) or {})
                    try:
                        result = self._execute_tool(name, arguments)
                        response = {"type": "tool.result", "call_id": call_id, "ok": True, "result": _json_safe(result)}
                        yield {"type": "tool.completed", "name": name, "result": result}
                    except Exception as error:  # noqa: BLE001 - error is returned to the model as tool output
                        response = {"type": "tool.result", "call_id": call_id, "ok": False, "error": f"{type(error).__name__}: {error}"}
                        yield {"type": "tool.failed", "name": name, "error": str(error)}
                    process.stdin.write(json.dumps(response, ensure_ascii=False) + "\n")
                    process.stdin.flush()
                    continue
                if event_type == "message.delta":
                    yield {"type": "delta", "content": str(event.get("delta", ""))}
                elif event_type == "status.update":
                    yield {
                        "type": "status",
                        "status": str(event.get("status", "")),
                        "name": str(event.get("name", "")),
                        "attempt": event.get("attempt"),
                        "error": str(event.get("error", "")),
                    }
                elif event_type == "run.completed":
                    yield {"type": "done", "stats": dict(event.get("stats", {}) or {}), "truncated": False}
                    return
                elif event_type == "run.failed":
                    raise RuntimeError(str(event.get("error", "Pi Agent failed")))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "inspect_workspace":
            return load_workspace_summary(self.workspace, notebook_id=str(arguments.get("notebook_id", "")))
        if name == "inspect_available_tools":
            return capability_snapshot(workspace=self.workspace, evidence_db=self.evidence_db)
        if name == "search_local_evidence":
            self._require_evidence_store()
            limit = _bounded_limit(arguments.get("result_limit"), default=8)
            hits = search_evidence_store(
                self.evidence_db,
                str(arguments.get("query", "")),
                limit=limit,
                context_mode="sentence",
            )
            return {
                "query": str(arguments.get("query", "")),
                "count": len(hits),
                "hits": [_compact_evidence_hit(hit) for hit in hits],
            }
        if name == "build_verified_answer":
            self._require_evidence_store()
            limit = _bounded_limit(arguments.get("result_limit"), default=12)
            return answer_question(
                self.evidence_db,
                str(arguments.get("question", "")),
                limit=limit,
                max_quotes=min(8, limit),
                adequacy_profile="manual",
                agentic_profile="custom",
                query_variants=1,
                max_followup_queries=1,
            )
        if name == "verify_doi":
            return verify_doi_metadata(
                str(arguments.get("doi", "")),
                expected_title=str(arguments.get("expected_title", "")),
            )
        if name == "discover_papers":
            return search_paper_atlas(str(arguments.get("query", "")))
        if name == "search_journal":
            return search_journals(
                str(arguments.get("query", "")),
                limit=_bounded_limit(arguments.get("result_limit"), default=8),
            )
        if name == "audit_references":
            mode = "references" if str(arguments.get("mode", "references")) == "references" else "full"
            return analyze_references(str(arguments.get("text", "")), mode=mode)
        if name == "build_presentation_outline":
            summary = load_workspace_summary(self.workspace, notebook_id=str(arguments.get("notebook_id", "")))
            notebooks = list(summary.get("notebooks", []) or [])
            if not notebooks:
                raise FileNotFoundError("The current ScanSci workspace has no usable notebook")
            return build_ppt_outline(
                dict(notebooks[0]),
                topic=str(arguments.get("topic", "")),
                template_id=str(arguments.get("template_id", "")),
            )
        raise ValueError(f"Unsupported ScanSci Pi tool: {name}")

    def _require_evidence_store(self) -> None:
        if not self.evidence_db.is_file():
            raise FileNotFoundError(f"Evidence store does not exist: {self.evidence_db}")


def _bounded_limit(value: Any, *, default: int) -> int:
    try:
        return max(1, min(20, int(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def _compact_evidence_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": str(hit.get("evidence_id", "")),
        "doc_id": str(hit.get("doc_id", "")),
        "paper": str(hit.get("paper", "")),
        "doi": str(hit.get("doi", "")),
        "section": str(hit.get("section", "")),
        "html_anchor": str(hit.get("html_anchor", "")),
        "text": " ".join(str(hit.get("text", "")).split())[:1600],
        "score": round(float(hit.get("score", 0.0) or 0.0), 6),
    }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
