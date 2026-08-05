"""Durable, redacted manifest for one Agent harness run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping
import re
from typing import Any
from uuid import uuid4

from .prefix_diagnostics import cache_metrics, prefix_change_reason
from .telemetry import diagnostics_root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


@dataclass
class RunManifest:
    workspace: Path
    harness: str
    provider: str
    model: str
    api_surface: str
    run_id: str = field(default_factory=lambda: f"run-{uuid4().hex}")
    session_id: str = ""
    prompt_version: str = ""
    tool_set_version: str = ""
    prefix_shape: dict[str, Any] = field(default_factory=dict)
    task_contract: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    max_turns: int = 0
    timeout_seconds: float = 0.0
    max_requests: int = 0
    status: str = "running"
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(
        cls,
        workspace: str | Path,
        *,
        harness: str,
        provider: str,
        model: str,
        api_surface: str,
        session_id: str = "",
        prompt: str = "",
        tool_set: object = "",
        max_turns: int = 0,
        timeout_seconds: float = 0.0,
        max_requests: int = 0,
        prefix_shape: Mapping[str, Any] | None = None,
        task_contract: Mapping[str, Any] | None = None,
        context_policy: Mapping[str, Any] | None = None,
    ) -> "RunManifest":
        manifest = cls(
            workspace=Path(workspace).resolve(),
            harness=str(harness),
            provider=str(provider),
            model=str(model),
            api_surface=str(api_surface),
            session_id=str(session_id or ""),
            prompt_version=_hash(prompt) if prompt else "",
            tool_set_version=_hash(json.dumps(tool_set, sort_keys=True, default=str)) if tool_set else "",
            max_turns=max(0, int(max_turns)),
            timeout_seconds=max(0.0, float(timeout_seconds)),
            max_requests=max(0, int(max_requests)),
            prefix_shape=dict(prefix_shape or {}),
            task_contract=dict(task_contract or {}),
            context_policy=dict(context_policy or {}),
        )
        manifest.record("run.started")
        manifest.persist()
        return manifest

    @property
    def path(self) -> Path:
        return diagnostics_root(self.workspace) / "runs" / f"{self.run_id}.json"

    def record(self, event_type: str, **payload: Any) -> None:
        safe_payload = _safe_payload(payload)
        self.events.append({"type": str(event_type), "timestamp": _now(), **safe_payload})
        self.persist()

    def metric(self, name: str, value: Any) -> None:
        self.metrics[str(name)] = _safe_payload({"value": value})["value"]
        self.persist()

    def record_context_stats(
        self,
        stats: Mapping[str, Any] | None,
        *,
        prefix_shape: Mapping[str, Any] | None = None,
    ) -> None:
        """Persist cache counters and context-shape diagnostics without payloads."""

        normalized = cache_metrics(stats)
        self.metrics.update(_safe_payload(normalized))
        if prefix_shape:
            current = dict(prefix_shape)
            self.metrics["prefix_shape_hash"] = str(current.get("hash", ""))
            self.metrics["prefix_change_reason"] = prefix_change_reason(self.prefix_shape, current)
            self.prefix_shape = current
        if isinstance(stats, Mapping):
            breakdown = stats.get("contextBreakdown")
            if isinstance(breakdown, Mapping):
                self.metrics["context_breakdown"] = _safe_payload(dict(breakdown))
            cache_diagnostics = stats.get("cacheDiagnostics")
            if isinstance(cache_diagnostics, Mapping):
                self.metrics["cache_diagnostics"] = _safe_payload(dict(cache_diagnostics))
        self.persist()

    def finish(self, *, status: str = "completed", **metrics: Any) -> dict[str, Any]:
        self.status = str(status)
        self.finished_at = _now()
        self.metrics.update(_safe_payload(metrics))
        self.record("run.finished", status=self.status)
        self.persist()
        return self.to_dict()

    def fail(self, error: BaseException | str, *, retryable: bool = False) -> dict[str, Any]:
        self.status = "failed"
        self.finished_at = _now()
        self.error = {
            "type": type(error).__name__ if isinstance(error, BaseException) else "RuntimeError",
            "message": _redact_text(str(error))[:500],
            "retryable": bool(retryable),
        }
        self.record("run.failed", error=self.error)
        self.persist()
        return self.to_dict()

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "api_surface": self.api_surface,
            "session_id": self.session_id,
            "prompt_version": self.prompt_version,
            "tool_set_version": self.tool_set_version,
            "prefix_shape": dict(self.prefix_shape),
            "task_contract": dict(self.task_contract),
            "context_policy": dict(self.context_policy),
            "max_turns": self.max_turns,
            "timeout_seconds": self.timeout_seconds,
            "max_requests": self.max_requests,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "events": list(self.events),
            "metrics": dict(self.metrics),
            "error": dict(self.error),
        }


def _safe_payload(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe_payload(item) for key, item in value.items() if not _sensitive(str(key))}
    if isinstance(value, list | tuple):
        return [_safe_payload(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)[:500] if isinstance(value, str) else value
    return str(value)[:500]

def _sensitive(key: str) -> bool:
    lowered = key.lower()
    if lowered in {
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    }:
        return False
    return any(
        part in lowered
        for part in (
            "api_key",
            "apikey",
            "authorization",
            "credential",
            "password",
            "secret",
            "access_token",
            "refresh_token",
        )
    )


def _redact_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|secret|password)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["RunManifest", "load_manifest"]
