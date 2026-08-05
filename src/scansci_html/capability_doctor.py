"""Read-only diagnostics for the installed Agent harness surface."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from .agent_capabilities import capability_catalog
from .harness_adapters import probe_optional_harnesses
from .subagent_profiles import load_profiles, validate_parallel_write_isolation


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **extra}


def doctor_capabilities(
    root: str | Path,
    *,
    evidence_db: str | Path | None = None,
    live: bool = False,
) -> dict[str, Any]:
    """Build a JSON-safe report without network calls or MCP process starts.

    ``live`` is accepted as an explicit future expansion point. The current
    report remains safe even when a caller asks for live mode: it records that
    no external process was started instead of silently doing so.
    """

    workspace = Path(root).resolve()
    checks: list[dict[str, Any]] = []
    checks.append(_check("workspace", "ready" if workspace.is_dir() else "missing", str(workspace)))
    node = shutil.which("node")
    runtime_bundle = workspace / "pi-runtime" / "dist" / "main.mjs"
    checks.append(_check("node", "ready" if node else "missing", "available on PATH" if node else "node is not installed"))
    checks.append(_check("pi_runtime_bundle", "ready" if runtime_bundle.is_file() else "missing", str(runtime_bundle)))

    harnesses = [probe.to_dict() for probe in probe_optional_harnesses()]
    checks.extend(
        _check(
            f"harness:{probe['name']}",
            "ready" if probe["installed"] else "optional_missing",
            probe["notes"],
            import_name=probe["import_name"],
            api_surfaces=probe["api_surfaces"],
        )
        for probe in harnesses
    )

    profiles = load_profiles(workspace)
    profile_errors = validate_parallel_write_isolation(profiles, root=workspace)
    checks.append(
        _check(
            "subagent_profiles",
            "ready" if not profile_errors else "invalid",
            f"{len(profiles)} profile(s) loaded",
            profile_count=len(profiles),
            errors=profile_errors,
        )
    )
    catalog = capability_catalog(
        workspace=workspace,
        evidence_db=Path(evidence_db or workspace / "html-papers" / "evidence.sqlite"),
        mcp_servers=(),
        plugins=(),
    )
    failed = [item for item in checks if item["status"] in {"missing", "invalid"}]
    return {
        "schema_version": "scansci.capability-doctor.v1",
        "mode": "live_requested" if live else "static",
        "status": "failed" if failed else "ok",
        "external_processes_started": False,
        "network_calls_made": False,
        "checks": checks,
        "harnesses": harnesses,
        "profiles": [profile.to_dict() for profile in profiles],
        "capabilities": catalog,
        "notes": [
            "Static diagnostics never start MCP servers or contact providers.",
            "Live probing remains opt-in and is not performed by this read-only command yet." if live else "Use an explicit runtime probe when external connectivity must be tested.",
        ],
    }


__all__ = ["doctor_capabilities"]
