"""Private, local-only OpenTelemetry diagnostics for ScanSci.

Spans are written as redacted JSON Lines beside the workspace.  No network
exporter is configured and message bodies, document text, credentials, and
authorization headers are deliberately excluded.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
from threading import Lock
from typing import Any, Iterator
import zipfile


_SENSITIVE_PARTS = {"api_key", "apikey", "authorization", "credential", "password", "secret", "token"}
_PROVIDERS: dict[str, Any] = {}
_PROVIDER_LOCK = Lock()
_WRITE_LOCK = Lock()


def diagnostics_root(workspace: str | Path) -> Path:
    root = Path(workspace).resolve().parent / ".scansci-diagnostics"
    root.mkdir(parents=True, exist_ok=True)
    return root


class _JsonlSpanExporter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def export(self, spans: list[Any]) -> Any:
        try:
            from opentelemetry.sdk.trace.export import SpanExportResult

            lines = [json.dumps(_public_span(span), ensure_ascii=False, separators=(",", ":")) for span in spans]
            if lines:
                with _WRITE_LOCK:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write("\n".join(lines) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            try:
                from opentelemetry.sdk.trace.export import SpanExportResult

                return SpanExportResult.FAILURE
            except Exception:
                return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True


class _NullSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        del key, value

    def record_exception(self, error: BaseException) -> None:
        del error


def _tracer(workspace: str | Path) -> Any | None:
    key = str(Path(workspace).resolve().parent)
    with _PROVIDER_LOCK:
        cached = _PROVIDERS.get(key)
        if cached is not None:
            return cached[1]
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": "ScanSci", "service.version": "0.4"}))
            provider.add_span_processor(SimpleSpanProcessor(_JsonlSpanExporter(diagnostics_root(workspace) / "spans.jsonl")))
            tracer = provider.get_tracer("scansci.desktop")
            _PROVIDERS[key] = (provider, tracer)
            return tracer
        except Exception:
            _PROVIDERS[key] = (None, None)
            return None


@contextmanager
def diagnostic_span(
    workspace: str | Path,
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    trace_tools: bool = False,
) -> Iterator[Any]:
    """Create a local diagnostic span and record terminal errors.

    When *trace_tools* is True the span accumulates tool-call ids, skill ids,
    and planning changes that the caller reports via :func:`record_tool_call`.
    """

    tracer = _tracer(workspace)
    if tracer is None:
        yield _NullSpan()
        return
    with tracer.start_as_current_span(str(name)[:120]) as span:
        for key, value in _safe_attributes(attributes or {}).items():
            span.set_attribute(key, value)
        if trace_tools:
            span.set_attribute("scansci.trace_tools", True)
        try:
            yield span
        except BaseException as error:
            span.record_exception(error)
            span.set_attribute("scansci.ok", False)
            raise
        else:
            span.set_attribute("scansci.ok", True)


def record_tool_call(span: Any, tool_name: str, *, skills: list[str] | None = None, success: bool | None = None) -> None:
    """Record a tool call on an active diagnostic span."""
    if span is None or isinstance(span, _NullSpan):
        return
    try:
        tools: list[str] = list(getattr(span, "_scansci_tools", []) or [])
        tools.append(tool_name)
        span.set_attribute("scansci.tool_calls", ",".join(tools[-48:]))
        setattr(span, "_scansci_tools", tools)  # noqa: B010
        if success is not None:
            span.set_attribute("scansci.tool_success", success)
        if skills:
            recorded: list[str] = list(getattr(span, "_scansci_skills", []) or [])
            recorded.extend(skills)
            span.set_attribute("scansci.skills_used", ",".join(dict.fromkeys(recorded)[:32]))
            setattr(span, "_scansci_skills", recorded)  # noqa: B010
    except Exception:
        pass


def diagnostics_summary(workspace: str | Path, *, limit: int = 30) -> dict[str, Any]:
    path = diagnostics_root(workspace) / "spans.jsonl"
    records: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(200, int(limit))) :]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    errors = sum(1 for item in records if str(item.get("status", "")).upper() == "ERROR" or not item.get("ok", True))
    return {
        "enabled": _tracer(workspace) is not None,
        "local_only": True,
        "span_count": len(records),
        "error_count": errors,
        "recent": records[-10:],
    }


def export_diagnostics_bundle(workspace: str | Path) -> Path:
    root = diagnostics_root(workspace)
    target = root / "ScanSci-diagnostics.zip"
    summary = diagnostics_summary(workspace, limit=200)
    environment = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "local_only": True,
        "contains_credentials": False,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        spans = root / "spans.jsonl"
        if spans.is_file():
            archive.write(spans, "spans.jsonl")
        archive.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        archive.writestr("environment.json", json.dumps(environment, ensure_ascii=False, indent=2))
    return target


def _public_span(span: Any) -> dict[str, Any]:
    context = span.get_span_context()
    status = getattr(getattr(span, "status", None), "status_code", None)
    status_name = getattr(status, "name", str(status or "UNSET"))
    attributes = _safe_attributes(dict(getattr(span, "attributes", {}) or {}))
    return {
        "trace_id": f"{int(getattr(context, 'trace_id', 0)):032x}",
        "span_id": f"{int(getattr(context, 'span_id', 0)):016x}",
        "name": str(getattr(span, "name", ""))[:120],
        "start_time": _nanoseconds_iso(getattr(span, "start_time", 0)),
        "end_time": _nanoseconds_iso(getattr(span, "end_time", 0)),
        "duration_ms": round(max(0, int(getattr(span, "end_time", 0)) - int(getattr(span, "start_time", 0))) / 1_000_000, 2),
        "status": status_name,
        "ok": bool(attributes.get("scansci.ok", status_name != "ERROR")),
        "attributes": attributes,
    }


def _safe_attributes(values: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key)[:120]
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_PARTS):
            continue
        if raw_value is None:
            continue
        if isinstance(raw_value, bool | int | float):
            safe[key] = raw_value
        elif isinstance(raw_value, (list, tuple)):
            safe[key] = [str(item)[:120] for item in raw_value[:20]]
        else:
            safe[key] = str(raw_value)[:240]
    return safe


def _nanoseconds_iso(value: object) -> str:
    try:
        seconds = int(value) / 1_000_000_000
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
