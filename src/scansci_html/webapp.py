"""Local, evidence-first Notebook web application.

The web application deliberately exposes only local ScanSci contracts.  Public
settings are stored next to the workspace while model credentials remain in the
operating-system credential manager.  The browser talks to a small same-origin
JSON API backed by the existing SQLite workspace and evidence store.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
import webbrowser

from .app_settings import (
    load_settings,
    local_model_presets,
    provider_presets,
    save_settings,
    set_document_service_api_key,
    set_provider_api_key,
)
from .app_update import AppUpdateService
from .build_info import current_build_info
from .image_attachments import attachment_asset
from .ingestion import ingest_sources, ingestion_source_path, ingestion_source_text
from .library_manager import connect_local_zotero, import_library_files, import_library_folder, register_zotero_library
from .local_model_market import download_model, installed_models, market_catalog
from .mcp_marketplace import install_marketplace_server, marketplace_catalog, sync_official_registry
from .research_agent import ResearchAgentRuntime
from .research_tools import (
    analyze_references,
    build_ppt_outline,
    capability_snapshot,
    create_ppt_project,
    download_paper,
    fetch_provider_models,
    search_journals,
    search_paper_atlas,
    test_local_model_connection,
    test_provider_connection,
    verify_doi_metadata,
)
from .skill_manager import install_skill, installed_skills, marketplace_skills, skill_library_path
from .slides_templates import list_slide_templates, slide_template_asset
from .slide_studio import save_browser_rendered_deck
from .telemetry import diagnostic_span, diagnostics_summary, export_diagnostics_bundle
from .vector_index import vector_cache_status
from .workspace import add_note_to_notebook, initialize_notebook, load_workspace_summary, record_citation_audit


# Pasted images are capped at 10 MiB and presentation sources at 30 MiB after
# decoding.  Base64 expansion needs room in the local JSON request before the
# per-file validation runs.
_MAX_REQUEST_BYTES = 170 * 1024 * 1024
_ASSET_DIR = Path(__file__).with_name("web")


def _diagnostic_route(path: str) -> str:
    """Keep route shape while omitting document, task, and attachment IDs."""

    normalized = re.sub(r"/ing-[a-f0-9]{32}(?=/|$)", "/{ingestion_id}", str(path))
    normalized = re.sub(r"/[a-f0-9]{20,}(?=/|$)", "/{id}", normalized)
    if normalized.startswith("/api/presentations/"):
        return "/api/presentations/{file}"
    return normalized[:240]


@dataclass(frozen=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes


class NotebookWebApp:
    """Routes the local Notebook UI and its small evidence API."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        evidence_db: str | Path,
        slides_root: str | Path | None = None,
        update_service: AppUpdateService | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.evidence_db = Path(evidence_db).resolve()
        self.slides_root = Path(slides_root).resolve() if slides_root is not None else None
        self.update_service = update_service or AppUpdateService()
        self.research_agent = ResearchAgentRuntime(workspace=self.workspace, evidence_db=self.evidence_db)

    def dispatch(self, method: str, target: str, body: bytes = b"") -> WebResponse:
        parsed_target = urlparse(target)
        path = parsed_target.path
        with diagnostic_span(
            self.workspace,
            "scansci.http.request",
            {"http.method": method, "http.route": _diagnostic_route(path), "http.request_bytes": len(body)},
        ) as span:
            try:
                if method == "GET":
                    response = self._get(path, parsed_target.query)
                elif method == "POST":
                    response = self._post(path, body)
                else:
                    response = self._json_error(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "method_not_allowed",
                        "Only GET and POST are supported.",
                    )
            except FileNotFoundError as error:
                response = self._json_error(HTTPStatus.NOT_FOUND, "not_found", str(error))
            except ValueError as error:
                response = self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))
            except RuntimeError as error:
                response = self._json_error(HTTPStatus.BAD_GATEWAY, "tool_failed", str(error))
            span.set_attribute("http.status_code", int(response.status))
            span.set_attribute("http.response_bytes", len(response.body))
            return response

    def _get(self, path: str, query: str = "") -> WebResponse:
        if path in {"/", "/index.html"}:
            return self._static_asset("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._static_asset("app.js", "application/javascript; charset=utf-8")
        if path == "/pdf-viewer.js":
            return self._static_asset("pdf-viewer.js", "application/javascript; charset=utf-8")
        if path == "/pptx-export.js":
            return self._static_asset("pptx-export.js", "application/javascript; charset=utf-8")
        if path == "/styles.css":
            return self._static_asset("styles.css", "text/css; charset=utf-8")
        if path.startswith("/vendor/"):
            relative = unquote(path.removeprefix("/"))
            content_type = {
                ".mjs": "application/javascript; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }.get(Path(relative).suffix.lower(), "application/octet-stream")
            return self._static_tree_asset(relative, content_type)
        if path == "/scansci-mark.png":
            return self._static_asset("scansci-mark.png", "image/png")
        if path == "/avatar-panda-male.png":
            return self._static_asset("avatar-panda-male.png", "image/png")
        if path == "/avatar-panda-female.png":
            return self._static_asset("avatar-panda-female.png", "image/png")
        if path == "/api/health":
            build = current_build_info()
            return self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "workspace_exists": self.workspace.exists(),
                    "evidence_store_exists": self.evidence_db.exists(),
                    "version": build["version"],
                    "build_id": build["build_id"],
                    "frozen": build["frozen"],
                    "executable": build["executable"],
                },
            )
        if path == "/api/diagnostics":
            summary = diagnostics_summary(self.workspace)
            summary["vector_cache"] = vector_cache_status(self.evidence_db)
            return self._json(HTTPStatus.OK, summary)
        if path == "/api/diagnostics/bundle":
            bundle = export_diagnostics_bundle(self.workspace)
            return WebResponse(HTTPStatus.OK, "application/zip", bundle.read_bytes())
        if path == "/api/workspace":
            return self._json(HTTPStatus.OK, load_workspace_summary(self.workspace))
        if path == "/api/settings":
            return self._json(HTTPStatus.OK, load_settings(self.workspace))
        if path == "/api/settings/presets":
            return self._json(
                HTTPStatus.OK,
                {"providers": provider_presets(), "local_models": local_model_presets()},
            )
        if path == "/api/local-models/installed":
            models = installed_models()
            return self._json(HTTPStatus.OK, {"models": models})
        if path == "/api/local-models/market":
            search = str(parse_qs(query).get("q", [""])[0] or "")
            return self._json(HTTPStatus.OK, market_catalog(search))
        if path == "/api/skills":
            return self._json(
                HTTPStatus.OK,
                {"skills": installed_skills(self.workspace), "library_path": str(skill_library_path(self.workspace))},
            )
        if path == "/api/skills/market":
            return self._json(HTTPStatus.OK, marketplace_skills())
        if path == "/api/mcp/marketplace":
            return self._json(HTTPStatus.OK, marketplace_catalog(self.workspace))
        if path == "/api/capabilities":
            return self._json(
                HTTPStatus.OK,
                capability_snapshot(workspace=self.workspace, evidence_db=self.evidence_db),
            )
        if path == "/api/runs":
            return self._json(HTTPStatus.OK, {"runs": self.research_agent.store.list_runs()})
        if path == "/api/runs/catalog":
            return self._json(HTTPStatus.OK, {"workflows": self.research_agent.workflow_catalog()})
        if path == "/api/slides/templates":
            return self._json(HTTPStatus.OK, list_slide_templates(self.slides_root))
        if path == "/api/app/update":
            return self._json(HTTPStatus.OK, self.update_service.status())

        parts = self._path_parts(path)
        if len(parts) == 6 and parts[:3] == ["api", "slides", "templates"] and parts[4] == "pages":
            asset = slide_template_asset(parts[3], parts[5], self.slides_root)
            return WebResponse(HTTPStatus.OK, "image/svg+xml; charset=utf-8", asset.read_bytes())
        if len(parts) == 3 and parts[:2] == ["api", "runs"]:
            return self._json(HTTPStatus.OK, self.research_agent.store.get_run(parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "download":
            return self._download_run_artifact(parts[2])
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "preview":
            return self._presentation_preview(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "notebooks"]:
            return self._json(HTTPStatus.OK, self._notebook(parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "notebooks"] and parts[3] == "citations":
            notebook = self._notebook(parts[2])
            return self._json(HTTPStatus.OK, {"notebook_id": notebook["notebook_id"], "citations": notebook["citations"]})
        if len(parts) == 4 and parts[:2] == ["api", "sources"] and parts[3] == "reader":
            return self._source_reader(parts[2])
        if len(parts) == 4 and parts[:2] == ["api", "sources"] and parts[3] == "original":
            return self._source_original(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "attachments"]:
            return self._attachment_asset(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "presentations"]:
            requested = Path(parts[2]).name
            root = (self.workspace.parent / "presentations").resolve()
            candidate = (root / requested).resolve()
            if root not in candidate.parents or candidate.suffix.lower() != ".pptx" or not candidate.is_file():
                raise FileNotFoundError("Presentation does not exist")
            return WebResponse(
                HTTPStatus.OK,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                candidate.read_bytes(),
            )
        if len(parts) == 6 and parts[:2] == ["api", "ingestions"] and parts[3] == "sources":
            if parts[5] == "file":
                source_path = ingestion_source_path(self.workspace, parts[2], parts[4])
                content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
                return WebResponse(HTTPStatus.OK, content_type, source_path.read_bytes())
            if parts[5] == "text":
                text = ingestion_source_text(self.workspace, parts[2], parts[4])
                return WebResponse(HTTPStatus.OK, "text/markdown; charset=utf-8", text.encode("utf-8"))
        if len(parts) >= 5 and parts[:2] == ["api", "sources"] and parts[3] == "files":
            return self._source_asset(parts[2], parts[4:])
        return self._json_error(HTTPStatus.NOT_FOUND, "not_found", "No route matches this path.")

    def _post(self, path: str, body: bytes) -> WebResponse:
        payload = self._json_body(body)
        parts = self._path_parts(path)
        if path == "/api/ask":
            return self._ask(payload)
        if path == "/api/chat":
            return self._json(HTTPStatus.OK, self.research_agent.chat(payload))
        if path == "/api/ingestions":
            return self._json(
                HTTPStatus.CREATED,
                ingest_sources(
                    self.workspace,
                    payload.get("source_files", []),
                    parser=str(payload.get("parser", "auto")),
                ),
            )
        if path == "/api/diagnostics/export":
            bundle = export_diagnostics_bundle(self.workspace)
            return self._json(
                HTTPStatus.CREATED,
                {
                    "ok": True,
                    "local_only": True,
                    "download_url": "/api/diagnostics/bundle",
                    "download_name": bundle.name,
                },
            )
        if path == "/api/runs":
            return self._json(HTTPStatus.ACCEPTED, self.research_agent.start(payload))
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "messages":
            return self._json(HTTPStatus.OK, self.research_agent.continue_run_conversation(parts[2], payload))
        if path == "/api/settings":
            return self._save_settings(payload)
        if path == "/api/app/update/check":
            return self._json(HTTPStatus.OK, self.update_service.check())
        if path == "/api/skills/install":
            return self._json(HTTPStatus.CREATED, install_skill(self.workspace, payload))
        if path == "/api/mcp/marketplace/sync":
            return self._json(HTTPStatus.OK, sync_official_registry(self.workspace))
        if path == "/api/mcp/marketplace/install":
            result = install_marketplace_server(self.workspace, str(payload.get("id", "")))
            return self._json(HTTPStatus.CREATED if result["created"] else HTTPStatus.OK, result)
        if path == "/api/library/folder":
            folder_path = str(payload.get("path", ""))
            notebook = self._requested_or_created_notebook(
                payload,
                title=Path(folder_path).name or "我的知识库",
                root_path=folder_path,
                library_kind=str(payload.get("library_kind", "folder")),
            )
            return self._json(
                HTTPStatus.OK,
                import_library_folder(
                    self.workspace,
                    self.evidence_db,
                    notebook_id=str(notebook["notebook_id"]),
                    folder_path=str(payload.get("path", "")),
                    library_kind=str(payload.get("library_kind", "folder")),
                ),
            )
        if path == "/api/library/zotero":
            zotero_path = str(payload.get("path", ""))
            notebook = self._requested_or_created_notebook(
                payload,
                title="Zotero 文献库",
                root_path=zotero_path,
                library_kind="zotero",
            )
            return self._json(
                HTTPStatus.OK,
                register_zotero_library(
                    self.workspace,
                    notebook_id=str(notebook["notebook_id"]),
                    folder_path=str(payload.get("path", "")),
                ),
            )
        if path == "/api/library/zotero/local":
            notebook = self._requested_or_created_notebook(
                payload,
                title="Zotero 文献库",
                root_path=self.workspace.parent,
                library_kind="zotero",
            )
            return self._json(
                HTTPStatus.OK,
                connect_local_zotero(
                    self.workspace,
                    notebook_id=str(notebook["notebook_id"]),
                ),
            )
        if path == "/api/library/files":
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            first_parent = Path(str(paths[0])).parent if paths else self.workspace.parent
            notebook = self._requested_or_created_notebook(
                payload,
                title="我的知识库",
                root_path=first_parent,
                library_kind="files",
            )
            return self._json(
                HTTPStatus.OK,
                import_library_files(
                    self.workspace,
                    self.evidence_db,
                    notebook_id=str(notebook["notebook_id"]),
                    file_paths=[str(path) for path in paths],
                ),
            )
        if len(parts) == 5 and parts[:3] == ["api", "settings", "providers"] and parts[4] == "api-key":
            return self._set_provider_api_key(parts[3], payload)
        if len(parts) == 5 and parts[:3] == ["api", "settings", "providers"] and parts[4] == "test":
            return self._test_provider(parts[3])
        if len(parts) == 5 and parts[:3] == ["api", "settings", "providers"] and parts[4] == "models":
            return self._fetch_provider_models(parts[3])
        if len(parts) == 5 and parts[:3] == ["api", "settings", "local-models"] and parts[4] == "test":
            return self._test_local_model(parts[3])
        if len(parts) == 5 and parts[:3] == ["api", "settings", "document-processing"] and parts[4] == "api-key":
            return self._set_document_service_api_key(parts[3], payload)
        if path == "/api/tools/journals/search":
            return self._json(HTTPStatus.OK, search_journals(str(payload.get("query", "")), limit=int(payload.get("limit", 8))))
        if path == "/api/tools/references/analyze":
            return self._json(HTTPStatus.OK, analyze_references(str(payload.get("text", "")), mode=str(payload.get("mode", "full"))))
        if path == "/api/tools/references/verify-doi":
            return self._json(
                HTTPStatus.OK,
                verify_doi_metadata(str(payload.get("doi", "")), expected_title=str(payload.get("title", ""))),
            )
        if path == "/api/local-models/download":
            return self._json(HTTPStatus.OK, download_model(str(payload.get("id", ""))))
        if path == "/api/tools/paper-atlas/search":
            return self._json(HTTPStatus.OK, search_paper_atlas(str(payload.get("query", ""))))
        if path == "/api/tools/papers/download":
            return self._json(
                HTTPStatus.OK,
                download_paper(
                    str(payload.get("identifier", "")),
                    workspace=self.workspace,
                    strategy=str(payload.get("strategy", "legal_only")),
                ),
            )
        if path == "/api/studio/ppt/outline":
            notebook = self._requested_notebook(payload)
            return self._json(
                HTTPStatus.OK,
                build_ppt_outline(
                    notebook,
                    topic=str(payload.get("topic", "")),
                    template_id=str(payload.get("template_id", "")),
                ),
            )
        if path == "/api/studio/ppt/project":
            notebook = self._requested_notebook(payload)
            return self._json(
                HTTPStatus.CREATED,
                create_ppt_project(
                    notebook,
                    workspace=self.workspace,
                    topic=str(payload.get("topic", "")),
                    template_id=str(payload.get("template_id", "")),
                ),
            )
        if path == "/api/studio/ppt/rendered":
            return self._json(
                HTTPStatus.CREATED,
                save_browser_rendered_deck(
                    self.workspace,
                    file_name=str(payload.get("file_name", "")),
                    base64_data=str(payload.get("base64", "")),
                ),
            )
        if len(parts) == 4 and parts[:2] == ["api", "notebooks"] and parts[3] == "notes":
            return self._add_note(parts[2], payload)
        if len(parts) == 4 and parts[:2] == ["api", "citations"] and parts[3] == "audits":
            return self._record_audit(parts[2], payload)
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
            return self._json(HTTPStatus.ACCEPTED, self.research_agent.cancel(parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume":
            return self._json(HTTPStatus.ACCEPTED, self.research_agent.resume(parts[2]))
        return self._json_error(HTTPStatus.NOT_FOUND, "not_found", "No route matches this path.")

    def _ask(self, payload: dict[str, Any]) -> WebResponse:
        return self._json(HTTPStatus.OK, self.research_agent.answer_sync(payload))

    def stream_chat(self, payload: dict[str, Any]):
        """Expose direct-chat deltas to the loopback HTTP handler."""

        return self.research_agent.chat_stream(payload)

    def _attachment_asset(self, attachment_id: str) -> WebResponse:
        path, content_type = attachment_asset(self.workspace, attachment_id)
        return WebResponse(HTTPStatus.OK, content_type, path.read_bytes())

    def _download_run_artifact(self, run_id: str) -> WebResponse:
        """Serve only the PPTX produced by a durable local research run."""

        run = self.research_agent.store.get_run(run_id)
        artifact = dict(run.get("output_artifact", {}) or {})
        candidate = Path(str(artifact.get("file_path", "") or "")).resolve()
        presentations = (self.workspace.parent / "presentations").resolve()
        if candidate.suffix.casefold() != ".pptx" or presentations not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError("这个任务没有可下载的 PPTX 文件")
        return WebResponse(
            HTTPStatus.OK,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            candidate.read_bytes(),
        )

    def _presentation_preview(self, run_id: str) -> WebResponse:
        """Return a lightweight cover preview for a completed source-to-PPT run.

        The cover uses the same title and colours as the generated deck.  This
        is intentionally local SVG rather than an untrusted document preview,
        so it works consistently in both the browser preview and the packaged
        desktop WebView.
        """

        run = self.research_agent.store.get_run(run_id)
        artifact = dict(run.get("output_artifact", {}) or {})
        payload = dict(artifact.get("payload", {}) or {})
        candidate = Path(str(artifact.get("file_path", "") or "")).resolve()
        presentations = (self.workspace.parent / "presentations").resolve()
        if candidate.suffix.casefold() != ".pptx" or presentations not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError("这个任务没有可预览的 PPTX 文件")
        outline = dict(payload.get("outline", {}) or {})
        plan = dict(payload.get("slide_plan", {}) or {})
        theme = dict(plan.get("theme", {}) or {})
        cover = str(theme.get("cover") or "091B2A").lstrip("#")[:6]
        accent = str(theme.get("accent") or "14897D").lstrip("#")[:6]
        title = html_escape(str(outline.get("title") or run.get("title") or "科研幻灯片")[:80])
        subtitle = html_escape(str(outline.get("central_question") or "基于上传材料生成的可编辑演示文稿")[:112])
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720" role="img" aria-label="{title}">
<rect width="1280" height="720" fill="#{cover}"/><rect x="82" y="80" width="154" height="8" rx="4" fill="#{accent}"/>
<circle cx="1124" cy="125" r="76" fill="none" stroke="#{accent}" stroke-width="5" opacity=".85"/>
<text x="84" y="250" fill="#ffffff" font-family="Microsoft YaHei, Arial, sans-serif" font-size="54" font-weight="700">{title}</text>
<text x="86" y="350" fill="#cfe8e6" font-family="Microsoft YaHei, Arial, sans-serif" font-size="25">{subtitle}</text>
<text x="86" y="650" fill="#a7bec7" font-family="Microsoft YaHei, Arial, sans-serif" font-size="18">ScanSci Presentation Studio · 可编辑 PPTX</text></svg>'''
        return WebResponse(HTTPStatus.OK, "image/svg+xml; charset=utf-8", svg.encode("utf-8"))

    def _save_settings(self, payload: dict[str, Any]) -> WebResponse:
        settings = payload.get("settings", payload)
        return self._json(HTTPStatus.OK, save_settings(self.workspace, settings))

    def _set_provider_api_key(self, provider_id: str, payload: dict[str, Any]) -> WebResponse:
        settings = set_provider_api_key(self.workspace, provider_id, str(payload.get("api_key", "")))
        return self._json(HTTPStatus.OK, settings)

    def _set_document_service_api_key(self, service_id: str, payload: dict[str, Any]) -> WebResponse:
        settings = set_document_service_api_key(self.workspace, service_id, str(payload.get("api_key", "")))
        return self._json(HTTPStatus.OK, settings)

    def _test_provider(self, provider_id: str) -> WebResponse:
        settings = load_settings(self.workspace)
        provider = next((item for item in settings.get("providers", []) if item.get("id") == provider_id), None)
        if provider is None:
            raise FileNotFoundError("找不到模型提供商")
        return self._json(
            HTTPStatus.OK,
            test_provider_connection(workspace=self.workspace, provider=dict(provider)),
        )

    def _fetch_provider_models(self, provider_id: str) -> WebResponse:
        settings = load_settings(self.workspace)
        provider = next((item for item in settings.get("providers", []) if item.get("id") == provider_id), None)
        if provider is None:
            raise FileNotFoundError("找不到模型提供商")
        return self._json(
            HTTPStatus.OK,
            fetch_provider_models(workspace=self.workspace, provider=dict(provider)),
        )

    def _test_local_model(self, local_model_id: str) -> WebResponse:
        settings = load_settings(self.workspace)
        local_model = next((item for item in settings.get("local_models", []) if item.get("id") == local_model_id), None)
        if local_model is None:
            raise FileNotFoundError("找不到本地模型")
        return self._json(HTTPStatus.OK, test_local_model_connection(dict(local_model)))

    def _requested_notebook(self, payload: dict[str, Any]) -> dict[str, Any]:
        notebook_id = str(payload.get("notebook_id", "")).strip()
        if notebook_id:
            return self._notebook(notebook_id)
        summary = load_workspace_summary(self.workspace)
        notebooks = list(summary.get("notebooks", []) or [])
        if not notebooks:
            raise FileNotFoundError("当前工作区没有可用资料库")
        return dict(notebooks[0])

    def _requested_or_created_notebook(
        self,
        payload: dict[str, Any],
        *,
        title: str,
        root_path: str | Path,
        library_kind: str,
    ) -> dict[str, Any]:
        """Resolve an explicit library or create a separate library card."""

        notebook_id = str(payload.get("notebook_id", "")).strip()
        if notebook_id:
            return self._notebook(notebook_id)
        created = initialize_notebook(
            self.workspace,
            title=title or "我的知识库",
            root_path=root_path or self.workspace.parent,
            metadata={"library_kind": library_kind, "created_by": "library_import"},
        )
        return self._notebook(str(created["notebook_id"]))

    def _add_note(self, notebook_id: str, payload: dict[str, Any]) -> WebResponse:
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not title:
            raise ValueError("title is required")
        if not body:
            raise ValueError("body is required")
        note = add_note_to_notebook(
            self.workspace,
            notebook_id=notebook_id,
            title=title,
            body=body,
            note_type=str(payload.get("note_type", "research_note") or "research_note"),
        )
        return self._json(HTTPStatus.CREATED, {"note": note, "notebook": self._notebook(notebook_id)})

    def _record_audit(self, citation_record_id: str, payload: dict[str, Any]) -> WebResponse:
        verdict = str(payload.get("verdict", "")).strip()
        if verdict not in {"supported", "partial_support", "unsupported", "needs_human_review"}:
            raise ValueError("verdict must be supported, partial_support, unsupported, or needs_human_review")
        confidence = payload.get("confidence")
        if confidence not in {None, ""}:
            try:
                confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError) as error:
                raise ValueError("confidence must be a number between 0 and 1") from error
        else:
            confidence = None
        audit = record_citation_audit(
            self.workspace,
            citation_record_id=citation_record_id,
            provider="human-notebook-review",
            verdict=verdict,
            reasoning=str(payload.get("reasoning", "")).strip(),
            confidence=confidence,
        )
        return self._json(HTTPStatus.CREATED, {"audit": audit})

    def _notebook(self, notebook_id: str) -> dict[str, Any]:
        summary = load_workspace_summary(self.workspace, notebook_id=notebook_id)
        notebooks = list(summary.get("notebooks", []) or [])
        if not notebooks:
            raise FileNotFoundError(f"Notebook does not exist: {notebook_id}")
        return dict(notebooks[0])

    def _source_reader(self, doc_id: str) -> WebResponse:
        source = self._source(doc_id)
        source_path = self._source_html_path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"Source HTML does not exist: {source_path}")
        text = source_path.read_text(encoding="utf-8", errors="replace")
        if source_path.suffix.lower() in {".md", ".markdown", ".txt"}:
            return WebResponse(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                self._markdown_source_reader(doc_id, source, text).encode("utf-8"),
            )
        base = f'<base href="/api/sources/{doc_id}/files/">'
        if re.search(r"<head\b[^>]*>", text, flags=re.IGNORECASE):
            text = re.sub(r"(<head\b[^>]*>)", r"\1" + base, text, count=1, flags=re.IGNORECASE)
        else:
            text = base + text
        return WebResponse(HTTPStatus.OK, "text/html; charset=utf-8", text.encode("utf-8"))

    def _markdown_source_reader(self, doc_id: str, source: dict[str, Any], full_text: str) -> str:
        """Render exact evidence anchors plus the complete converted source text."""

        rows: list[sqlite3.Row] = []
        source_db = Path(str(source.get("evidence_db_path", "") or ""))
        if not source_db.is_file():
            source_db = self.evidence_db
        if source_db.is_file():
            try:
                with sqlite3.connect(source_db) as connection:
                    connection.row_factory = sqlite3.Row
                    rows = list(
                        connection.execute(
                            """
                            select evidence_id, html_anchor, section, block_id, text
                            from evidence_spans
                            where doc_id = ?
                            order by sentence_index
                            """,
                            (doc_id,),
                        )
                    )
            except sqlite3.Error:
                rows = []
        blocks: list[str] = []
        last_section = None
        for row in rows:
            section = str(row["section"] or "正文")
            if section != last_section:
                blocks.append(f"<h2>{html_escape(section)}</h2>")
                last_section = section
            blocks.append(
                '<article class="evidence-block" '
                f'id="{html_escape(str(row["html_anchor"] or ""))}" '
                f'data-evidence-id="{html_escape(str(row["evidence_id"] or ""))}">'
                f'<span>{html_escape(str(row["evidence_id"] or ""))}</span>'
                f'<p>{html_escape(str(row["text"] or ""))}</p></article>'
            )
        title = html_escape(str(source.get("title") or doc_id))
        evidence = "".join(blocks) or '<p class="empty">这份来源尚未生成可定位证据块。</p>'
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
:root{{font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#2d3035;background:#fff}}body{{margin:0}}header{{position:sticky;top:0;z-index:3;padding:18px 28px 15px;border-bottom:1px solid #e7e8eb;background:rgba(255,255,255,.96);backdrop-filter:blur(14px)}}header span{{color:#96989f;font-size:11px;letter-spacing:.08em}}header h1{{margin:4px 0 0;font-size:20px;line-height:1.4}}main{{max-width:920px;margin:auto;padding:24px 30px 70px}}h2{{margin:28px 0 10px;color:#565960;font-size:14px}}.evidence-block{{scroll-margin-top:94px;margin:0 0 8px;padding:13px 16px;border:1px solid transparent;border-radius:10px;transition:background .18s,border-color .18s,box-shadow .18s}}.evidence-block>span{{display:block;margin-bottom:4px;color:#a0a2a8;font:10px ui-monospace,SFMono-Regular,Consolas,monospace}}.evidence-block p{{margin:0;font-size:15px;line-height:1.85}}.evidence-block:target{{border-color:#e7cb68;background:#fff8cf;box-shadow:0 0 0 4px rgba(225,190,66,.14)}}details{{margin-top:34px;border-top:1px solid #e7e8eb;padding-top:18px}}summary{{color:#707279;font-size:13px;cursor:pointer}}pre{{padding:18px;overflow:auto;border-radius:10px;background:#f7f7f8;white-space:pre-wrap;font:13px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace}}.empty{{color:#92949a}}</style></head><body><header><span>SCANSCI · EVIDENCE READER</span><h1>{title}</h1></header><main>{evidence}<details><summary>查看完整转换文本</summary><pre>{html_escape(full_text)}</pre></details></main></body></html>'''

    def _source_asset(self, doc_id: str, asset_parts: list[str]) -> WebResponse:
        source = self._source(doc_id)
        root = self._source_html_path(source).parent.resolve()
        requested = root.joinpath(*asset_parts).resolve()
        try:
            requested.relative_to(root)
        except ValueError as error:
            raise ValueError("Source asset path escapes the source directory") from error
        if not requested.is_file():
            raise FileNotFoundError(f"Source asset does not exist: {requested.name}")
        content_type, _ = mimetypes.guess_type(str(requested))
        return WebResponse(HTTPStatus.OK, content_type or "application/octet-stream", requested.read_bytes())

    def _source_original(self, doc_id: str) -> WebResponse:
        """Serve only the exact local source path already registered in the workspace."""

        source = self._source(doc_id)
        original = Path(str(source.get("source_url", "") or ""))
        if not original.is_absolute() or not original.is_file():
            raise FileNotFoundError("This source does not have a readable original file")
        content_type, _ = mimetypes.guess_type(str(original))
        return WebResponse(HTTPStatus.OK, content_type or "application/octet-stream", original.read_bytes())

    def _source(self, doc_id: str) -> dict[str, Any]:
        summary = load_workspace_summary(self.workspace)
        for notebook in list(summary.get("notebooks", []) or []):
            for source in list(dict(notebook).get("sources", []) or []):
                if str(dict(source).get("doc_id", "")) == doc_id:
                    return dict(source)
        raise FileNotFoundError(f"Source does not exist in the workspace: {doc_id}")

    @staticmethod
    def _source_html_path(source: dict[str, Any]) -> Path:
        evidence_value = str(source.get("evidence_html_path", "") or "")
        evidence_path = Path(evidence_value) if evidence_value else None
        if evidence_path is not None and evidence_path.exists():
            return evidence_path
        return Path(str(source.get("html_path", "") or ""))

    @staticmethod
    def _path_parts(path: str) -> list[str]:
        return [unquote(part) for part in path.split("/") if part]

    @staticmethod
    def _reader_url(doc_id: str, anchor: str) -> str:
        suffix = f"#{anchor}" if anchor else ""
        return f"/api/sources/{quote(doc_id, safe='')}/reader{suffix}"

    @staticmethod
    def _json_body(body: bytes) -> dict[str, Any]:
        if len(body) > _MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large")
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    @staticmethod
    def _json(status: int | HTTPStatus, payload: dict[str, Any]) -> WebResponse:
        return WebResponse(int(status), "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))

    @classmethod
    def _json_error(cls, status: int | HTTPStatus, code: str, message: str) -> WebResponse:
        return cls._json(status, {"error": {"code": code, "message": message}})

    @staticmethod
    def _static_asset(name: str, content_type: str) -> WebResponse:
        path = _ASSET_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"Notebook application asset does not exist: {name}")
        return WebResponse(HTTPStatus.OK, content_type, path.read_bytes())

    @staticmethod
    def _static_tree_asset(name: str, content_type: str) -> WebResponse:
        root = _ASSET_DIR.resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"Notebook application asset does not exist: {name}")
        return WebResponse(HTTPStatus.OK, content_type, path.read_bytes())


def serve_notebook(
    *,
    workspace: str | Path,
    evidence_db: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    """Start the local Notebook UI until interrupted by the user."""

    server = create_notebook_server(
        workspace=workspace,
        evidence_db=evidence_db,
        host=host,
        port=port,
    )
    url = f"http://{host}:{server.server_port}"
    print(f"ScanSci Notebook is running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return None
    finally:
        server.server_close()


def create_notebook_server(
    *,
    workspace: str | Path,
    evidence_db: str | Path,
    host: str = "127.0.0.1",
    port: int = 0,
    update_service: AppUpdateService | None = None,
) -> ThreadingHTTPServer:
    """Create a loopback-only HTTP server for the Notebook UI.

    The desktop shell uses this factory with an ephemeral port and owns the
    server lifecycle.  Keeping this boundary explicit means the same UI works
    in a browser for development and in a native desktop window for daily use.
    """

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ScanSci Notebook only binds to a loopback host; this local UI has no multi-user authentication.")
    app = NotebookWebApp(workspace=workspace, evidence_db=evidence_db, update_service=update_service)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self._dispatch()

        def _dispatch(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length > _MAX_REQUEST_BYTES:
                response = NotebookWebApp._json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "Request body is too large")
                self._write_response(response)
                return
            body = self.rfile.read(max(0, length))
            if self.command == "POST" and urlparse(self.path).path == "/api/chat/stream":
                self._stream_chat(body)
                return
            response = app.dispatch(self.command, self.path, body)
            self._write_response(response)

        def _write_response(self, response: WebResponse) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' data: blob:; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response.body)

        def _stream_chat(self, body: bytes) -> None:
            try:
                payload = NotebookWebApp._json_body(body)
            except ValueError as error:
                self._write_response(NotebookWebApp._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.close_connection = True
            with diagnostic_span(
                app.workspace,
                "scansci.chat.stream",
                {
                    "chat.message_count": len(list(payload.get("messages", []) or [])),
                    "chat.attachment_count": len(list(payload.get("source_files", []) or [])),
                    "chat.image_count": len(list(payload.get("images", []) or [])),
                },
            ) as span:
                try:
                    self._write_sse("ready", {})
                    last_event = "ready"
                    for event in app.stream_chat(payload):
                        event_type = str(event.get("type", "message"))
                        event_payload = {str(key): value for key, value in event.items() if key != "type"}
                        self._write_sse(event_type, event_payload)
                        last_event = event_type
                    span.set_attribute("chat.terminal_event", last_event)
                except (BrokenPipeError, ConnectionResetError):
                    span.set_attribute("chat.client_disconnected", True)
                    return
                except (ValueError, RuntimeError) as error:
                    span.record_exception(error)
                    self._write_sse("error", {"message": str(error)})
                except Exception as error:  # noqa: BLE001 - prevent closing an SSE response without a client event
                    span.record_exception(error)
                    self._write_sse("error", {"message": "The streaming response could not be completed."})

        def _write_sse(self, event_type: str, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
            frame = f"event: {event_type}\ndata: {encoded}\n\n".encode("utf-8")
            self.wfile.write(frame)
            self.wfile.flush()

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    return ThreadingHTTPServer((host, int(port)), Handler)
