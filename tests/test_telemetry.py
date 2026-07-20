from __future__ import annotations

import json
from pathlib import Path
import zipfile

from scansci_html.telemetry import diagnostic_span, diagnostics_summary, export_diagnostics_bundle
from scansci_html.webapp import NotebookWebApp


def test_local_diagnostics_redact_credentials_and_export_bundle(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    with diagnostic_span(
        workspace,
        "test.operation",
        {"document.count": 3, "api_key": "must-not-leak", "authorization.header": "also-secret"},
    ) as span:
        span.set_attribute("result.count", 2)

    summary = diagnostics_summary(workspace)
    assert summary["enabled"] is True
    assert summary["local_only"] is True
    assert summary["recent"][-1]["name"] == "test.operation"
    raw = (tmp_path / ".scansci-diagnostics" / "spans.jsonl").read_text(encoding="utf-8")
    assert "must-not-leak" not in raw
    assert "also-secret" not in raw

    bundle = export_diagnostics_bundle(workspace)
    with zipfile.ZipFile(bundle) as archive:
        assert {"spans.jsonl", "summary.json", "environment.json"}.issubset(archive.namelist())
        environment = json.loads(archive.read("environment.json"))
        assert environment["contains_credentials"] is False


def test_webapp_exposes_local_diagnostics_without_private_paths(tmp_path: Path):
    workspace = tmp_path / "workspace.sqlite"
    app = NotebookWebApp(workspace=workspace, evidence_db=tmp_path / "evidence.sqlite")

    health = app.dispatch("GET", "/api/health")
    diagnostics = app.dispatch("GET", "/api/diagnostics")
    exported = app.dispatch("POST", "/api/diagnostics/export", b"{}")
    bundle = app.dispatch("GET", "/api/diagnostics/bundle")

    assert health.status == 200
    assert diagnostics.status == 200
    assert json.loads(diagnostics.body)["local_only"] is True
    assert json.loads(exported.body)["download_url"] == "/api/diagnostics/bundle"
    assert bundle.status == 200
    assert bundle.content_type == "application/zip"
    assert bundle.body.startswith(b"PK")
