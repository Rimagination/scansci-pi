"""Stable, per-workspace connector catalog for local knowledge sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .app_settings import load_settings, notion_api_token_configured
from .notion_integration import test_notion_connection
from .obsidian_integration import obsidian_status
from .workspace import load_workspace_summary
from .zotero_integration import zotero_status


_NATIVE_CAPABILITIES = {
    "zotero": [
        "status",
        "search",
        "collections",
        "item_metadata",
        "attachment_fulltext",
        "open_attachment",
        "bibtex_export",
        "formatted_citations",
        "import_records_requires_confirmation",
    ],
    "obsidian": ["status", "search", "read_note", "backlinks"],
    "notion": ["status", "search", "read_page", "read_database", "sync"],
}


def connector_catalog(workspace: str | Path, *, inspect_runtime: bool = False) -> dict[str, Any]:
    """Describe native and MCP capabilities linked to this user's workspace."""

    summary = load_workspace_summary(workspace)
    notebooks = list(summary.get("notebooks", []) or [])
    settings = load_settings(workspace)
    mcp_records = [record for record in list(settings.get("mcp_servers", []) or []) if isinstance(record, dict)]
    connectors = []
    for kind in ("zotero", "obsidian", "notion"):
        libraries = [
            {
                "notebook_id": str(notebook.get("notebook_id", "")),
                "title": str(notebook.get("title", "")),
                "root_path": str(notebook.get("root_path", "")),
                "source_count": int(dict(notebook.get("counts", {}) or {}).get("sources", 0) or 0),
            }
            for notebook in notebooks
            if str(dict(notebook.get("metadata", {}) or {}).get("library_kind", "")) == kind
        ]
        associated_mcp = [
            {
                "id": str(record.get("id", "")),
                "name": str(record.get("name", "")),
                "enabled": bool(record.get("enabled")),
                "transport": str(record.get("transport", "stdio")),
                "allow_write": bool(record.get("allow_write")),
            }
            for record in mcp_records
            if str(record.get("connector_kind", "")) == kind and not record.get("uninstalled")
        ]
        runtime: dict[str, Any] = {}
        if inspect_runtime and kind == "zotero":
            runtime = zotero_status(timeout=0.35)
        elif inspect_runtime and kind == "obsidian":
            checked = []
            for library in libraries:
                try:
                    checked.append(obsidian_status(library["root_path"]))
                except (FileNotFoundError, OSError, ValueError) as error:
                    checked.append({"ok": False, "vault_path": library["root_path"], "error": str(error)})
            runtime = {"vaults": checked, "available": any(item.get("ok") for item in checked)}
        elif inspect_runtime and kind == "notion":
            runtime = {"token_configured": notion_api_token_configured(workspace)}
            if runtime["token_configured"]:
                try:
                    runtime.update(test_notion_connection(workspace))
                except Exception as error:
                    runtime.update({"ok": False, "error": str(error)})
        connectors.append(
            {
                "id": kind,
                "kind": kind,
                "scope": "current-user-workspace",
                "connected": bool(libraries),
                "read_only_by_default": True,
                "libraries": libraries,
                "native_capabilities": list(_NATIVE_CAPABILITIES[kind]),
                "mcp_servers": associated_mcp,
                "runtime": runtime,
            }
        )
    return {"workspace_path": str(Path(workspace).resolve()), "connectors": connectors}


def test_connector(workspace: str | Path, connector_kind: str) -> dict[str, Any]:
    """Perform an explicit connection check requested by the user."""

    kind = str(connector_kind or "").strip().lower()
    catalog = connector_catalog(workspace, inspect_runtime=True)
    connector = next((item for item in catalog["connectors"] if item["kind"] == kind), None)
    if connector is None:
        raise ValueError("connector_kind must be 'zotero', 'obsidian' or 'notion'")
    return connector
