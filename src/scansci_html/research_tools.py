"""Adapters that turn the existing ScanSci suite into research-agent tools.

The adapters are intentionally narrow: they expose status and explicit user
actions, keep downloads inside the current workspace, and never persist API
credentials outside the operating-system credential manager.
"""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib import error, parse, request

from .app_settings import get_provider_api_key
from .slides_templates import get_slide_template, resolve_slide_template_dir


_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ARXIV_PATTERN = re.compile(r"^(?:arxiv:)?(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?$", re.IGNORECASE)
_SAFE_NAME = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")
_SCANSCI_SUITE_ROOT = Path(os.getenv("SCANSCI_SUITE_ROOT", r"D:\scansci"))
_JOURNAL_API = "https://www.scansci.com/api/journals/search"
_CITATION_API = "https://www.scansci.com/api/citation/analyze"
# The public frontend currently serves its SPA shell for /api/* requests.
# Use the upstream Space API that the maintained Cloudflare proxy targets.
_PAPER_ATLAS_API = "https://rimagination-paper-atlas.hf.space/api"


SCANSCI_APPS: tuple[dict[str, str], ...] = (
    {
        "id": "journal-scout",
        "name": "Journal Scout",
        "description": "期刊分区、JCR、影响因子、CiteScore 与预警信息。",
        "url": "https://journal.scansci.com",
        "local_path": "journal-scout",
    },
    {
        "id": "citation-lab",
        "name": "Citation Lab",
        "description": "参考文献元数据、语境相关性与断言支持度核查。",
        "url": "https://citation.scansci.com",
        "local_path": "citation-lab",
    },
    {
        "id": "paper-atlas",
        "name": "Paper Atlas",
        "description": "论文引用关系、相似论文与主题网络。",
        "url": "https://paperatlas.scansci.com",
        "local_path": "paper-atlas",
    },
    {
        "id": "easyslides",
        "name": "EasySlides",
        "description": "从论文和研究资料生成可编辑学术 PPTX 的本地工具链。",
        "url": "https://easyslides.scansci.com",
        "local_path": "easyslides",
    },
    {
        "id": "paper-deck",
        "name": "PaperDeck",
        "description": "基于研究兴趣的每日论文发现。",
        "url": "https://paperdeck.scansci.com",
        "local_path": "paper-deck",
    },
)


def capability_snapshot(*, workspace: str | Path, evidence_db: str | Path) -> dict[str, Any]:
    """Return a truthful capability map for the desktop UI."""

    pdf_cli = shutil.which("scansci-pdf")
    apps = []
    for app in SCANSCI_APPS:
        local_path = _SCANSCI_SUITE_ROOT / app["local_path"]
        apps.append({**app, "local_available": local_path.is_dir(), "local_path": str(local_path)})
    return {
        "workspace": str(Path(workspace).resolve()),
        "evidence_store_ready": Path(evidence_db).is_file(),
        "download_directory": str(_download_directory(workspace)),
        "presentation_directory": str(_presentation_directory(workspace)),
        "apps": apps,
        "tools": [
            {
                "id": "evidence-trace",
                "name": "证据追溯",
                "status": "ready" if Path(evidence_db).is_file() else "needs-data",
                "description": "句子级证据、原文锚点与引用核验。",
            },
            {
                "id": "paper-download",
                "name": "论文获取",
                "status": "ready" if pdf_cli else "unavailable",
                "description": "通过本地 scansci-pdf 并行获取 DOI 或 arXiv 文献。",
            },
            {
                "id": "journal-scout",
                "name": "期刊分区",
                "status": "ready",
                "description": "调用 ScanSci Journal Scout 在线检索接口。",
            },
            {
                "id": "citation-lab",
                "name": "引文真伪核查",
                "status": "ready",
                "description": "调用 ScanSci Citation Lab 与 Crossref/OpenAlex 双源核验。",
            },
            {
                "id": "paper-atlas",
                "name": "Paper Atlas",
                "status": "external",
                "description": "优先检索论文；服务繁忙时转入 Paper Atlas 网页构建图谱。",
            },
            {
                "id": "ppt-studio",
                "name": "PPT Studio",
                "status": "ready" if (_SCANSCI_SUITE_ROOT / "easyslides" / "scripts" / "project_manager.py").is_file() else "unavailable",
                "description": "创建 EasySlides 项目、导入当前来源并生成可追溯大纲。",
            },
        ],
    }


def test_provider_connection(
    *,
    workspace: str | Path,
    provider: dict[str, Any],
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Test a configured provider without returning credentials or response bodies."""

    started = time.perf_counter()
    kind = str(provider.get("kind", ""))
    if kind == "local":
        return {"ok": True, "status": "ready", "latency_ms": 0, "model_count": len(provider.get("models", []))}
    base_url = str(provider.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("Base URL 尚未配置")
    api_key = get_provider_api_key(workspace, str(provider.get("id", "")))
    if not api_key:
        raise ValueError("请先保存 API Key")
    endpoint = f"{base_url}/models"
    headers = {"Accept": "application/json", "User-Agent": "ScanSci-Desktop/0.1"}
    if kind == "anthropic-compatible":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = _request_json(endpoint, headers=headers, timeout=timeout)
    models = payload.get("data", []) if isinstance(payload, dict) else []
    return {
        "ok": True,
        "status": "connected",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "model_count": len(models) if isinstance(models, list) else 0,
    }


def fetch_provider_models(
    *,
    workspace: str | Path,
    provider: dict[str, Any],
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Read a provider's public model catalog without exposing its API key.

    The Model Services screen uses the OpenAI-compatible ``/models`` contract
    whenever a provider exposes it.  A provider that does not offer that
    contract can still be configured by adding model IDs manually.
    """

    kind = str(provider.get("kind", ""))
    if kind == "local":
        models = [dict(item) for item in provider.get("models", []) if isinstance(item, dict)]
        return {"provider": str(provider.get("name", "")), "models": models, "count": len(models)}
    base_url = str(provider.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("请先填写 API 地址")
    api_key = get_provider_api_key(workspace, str(provider.get("id", "")))
    if not api_key:
        raise ValueError("请先保存 API Key")
    headers = {"Accept": "application/json", "User-Agent": "ScanSci-Desktop/0.1"}
    if kind == "anthropic-compatible":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = _request_json(f"{base_url}/models", headers=headers, timeout=timeout)
    raw_models = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(raw_models, list) and isinstance(payload, dict):
        raw_models = payload.get("models", [])
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_models[:128] if isinstance(raw_models, list) else []:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        name = str(item.get("display_name") or item.get("name") or identifier).strip() or identifier
        context_window = str(item.get("context_window") or item.get("context_length") or "").strip()
        group = str(item.get("owned_by") or item.get("organization") or item.get("provider") or "默认模型").strip() or "默认模型"
        models.append({"id": identifier, "name": name, "group": group, "context_window": context_window})
    return {"provider": str(provider.get("name", "")), "models": models, "count": len(models)}


def test_local_model_connection(local_model: dict[str, Any], *, timeout: float = 4.0) -> dict[str, Any]:
    runtime = str(local_model.get("runtime", ""))
    if runtime == "builtin":
        return {"ok": True, "status": "ready", "latency_ms": 0, "models": [str(local_model.get("model_id", ""))]}
    base_url = str(local_model.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("本地服务地址尚未配置")
    started = time.perf_counter()
    payload = _request_json(f"{base_url}/models", timeout=timeout)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    model_ids = [str(item.get("id", "")) for item in rows[:20] if isinstance(item, dict)] if isinstance(rows, list) else []
    return {"ok": True, "status": "connected", "latency_ms": round((time.perf_counter() - started) * 1000), "models": model_ids}


def search_journals(query: str, *, limit: int = 8, timeout: float = 15.0) -> dict[str, Any]:
    clean = str(query or "").strip()
    if not clean:
        raise ValueError("请输入期刊名、ISSN 或 CN 号")
    endpoint = f"{_JOURNAL_API}?{parse.urlencode({'q': clean, 'limit': max(1, min(20, int(limit)))})}"
    payload = _request_json(
        endpoint,
        headers={
            "Origin": "https://journal.scansci.com",
            "Referer": "https://journal.scansci.com/",
        },
        timeout=timeout,
    )
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    items = []
    for row in rows[:20] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                "id": row.get("id"),
                "title": str(row.get("title", "")),
                "issn": str(row.get("issn", "")),
                "eissn": str(row.get("eissn", "")),
                "impact_factor": row.get("if_2023"),
                "impact_factor_year": row.get("if_year"),
                "jcr_quartile": str(row.get("jcr_quartile", "")),
                "cas_partition": str(row.get("cas_2025", "")),
                "top": bool(row.get("is_top")),
                "warning": bool(row.get("warning_latest") or row.get("xuankan_warning")),
                "tags": list(row.get("tags", []) or [])[:12],
                "detail_url": f"https://journal.scansci.com/journal.html?id={parse.quote(str(row.get('id', '')))}&q={parse.quote(clean)}",
            }
        )
    return {"query": clean, "items": items, "source": "ScanSci Journal Scout"}


def analyze_references(text: str, *, mode: str = "full", timeout: float = 35.0) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("请粘贴正文与参考文献，或仅粘贴参考文献")
    if len(clean) > 200_000:
        raise ValueError("单次核查文本不能超过 200,000 字符")
    normalized_mode = "references" if mode == "references" else "full"
    return _request_json(
        _CITATION_API,
        method="POST",
        data={"text": clean, "mode": normalized_mode},
        timeout=timeout,
    )


def search_paper_atlas(query: str, *, timeout: float = 30.0) -> dict[str, Any]:
    clean = str(query or "").strip()
    if not clean:
        raise ValueError("请输入论文题目、关键词或 DOI")
    external_url = "https://paperatlas.scansci.com/"
    try:
        payload = _request_json(
            f"{_PAPER_ATLAS_API}/search?{parse.urlencode({'q': clean})}",
            headers={"Referer": external_url},
            timeout=timeout,
        )
    except RuntimeError as exc:
        return {
            "query": clean,
            "items": [],
            "source": "ScanSci Paper Atlas",
            "status": "external",
            "external_url": external_url,
            "message": f"图谱计算服务暂不可用，可在 Paper Atlas 网页继续搜索。{exc}",
        }
    items = payload if isinstance(payload, list) else []
    return {
        "query": clean,
        "items": [dict(item) for item in items[:10] if isinstance(item, dict)],
        "source": "ScanSci Paper Atlas",
        "status": "ready",
        "external_url": external_url,
    }


def download_paper(
    identifier: str,
    *,
    workspace: str | Path,
    strategy: str = "legal_only",
    timeout: float = 180.0,
) -> dict[str, Any]:
    clean = str(identifier or "").strip()
    if not (_DOI_PATTERN.fullmatch(clean) or _ARXIV_PATTERN.fullmatch(clean)):
        raise ValueError("请输入有效 DOI 或 arXiv ID")
    normalized_strategy = strategy if strategy in {"legal_only", "oa_first", "gray_oa"} else "oa_first"
    executable = shutil.which("scansci-pdf")
    if normalized_strategy == "gray_oa" or not executable:
        return _download_from_public_archives(clean, workspace=workspace, strategy=normalized_strategy, timeout=timeout)
    output_dir = _download_directory(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in output_dir.glob("**/*") if path.is_file()}
    command = [executable, "get", clean, "--output", str(output_dir), "--strategy", normalized_strategy]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    after = {path.resolve() for path in output_dir.glob("**/*") if path.is_file()}
    created = sorted(str(path) for path in after - before)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "下载失败").strip()
        raise RuntimeError(detail[-1200:])
    return {
        "ok": True,
        "identifier": clean,
        "strategy": normalized_strategy,
        "output_dir": str(output_dir),
        "files": created,
        "message": (completed.stdout or "下载完成").strip()[-1200:],
    }


def _download_from_public_archives(identifier: str, *, workspace: str | Path, strategy: str, timeout: float) -> dict[str, Any]:
    """Download from public archives when the optional CLI is not packaged.

    ``gray_oa`` covers lawful grey-literature locations such as institutional
    repositories and preprint archives; it never attempts to bypass a paid
    publisher page.
    """

    candidates = _public_fulltext_candidates(identifier, timeout=min(timeout, 35.0))
    if not candidates:
        raise RuntimeError("未找到可直接获取的开放全文或灰色文献存档版本。")
    output_dir = _download_directory(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for candidate in candidates:
        try:
            destination = _download_public_pdf(candidate, output_dir=output_dir, identifier=identifier, timeout=timeout)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        return {
            "ok": True,
            "identifier": identifier,
            "strategy": strategy,
            "output_dir": str(output_dir),
            "files": [str(destination)],
            "source": candidate["source"],
            "message": f"已从 {candidate['source']} 保存全文。",
        }
    raise RuntimeError("已找到全文入口，但下载失败：" + "；".join(errors[-3:]))


def _public_fulltext_candidates(identifier: str, *, timeout: float) -> list[dict[str, str]]:
    if _ARXIV_PATTERN.fullmatch(identifier):
        arxiv_id = identifier.removeprefix("arXiv:").removeprefix("ARXIV:")
        return [{"url": f"https://arxiv.org/pdf/{parse.quote(arxiv_id, safe='./')}.pdf", "source": "arXiv"}]
    encoded = parse.quote(identifier, safe="")
    candidates: list[dict[str, str]] = []
    try:
        work = _request_json(f"https://api.openalex.org/works/https://doi.org/{encoded}", timeout=timeout)
    except RuntimeError:
        work = {}
    if isinstance(work, dict):
        locations = [work.get("best_oa_location"), *(work.get("locations") or [])]
        for location in locations:
            if not isinstance(location, dict):
                continue
            url = str(location.get("pdf_url") or "").strip()
            if not url:
                continue
            source = dict(location.get("source") or {}).get("display_name") or "OpenAlex open-access archive"
            candidates.append({"url": url, "source": str(source)})
    try:
        crossref = _request_json(f"https://api.crossref.org/works/{encoded}", timeout=timeout)
    except RuntimeError:
        crossref = {}
    message = dict(crossref.get("message") or {}) if isinstance(crossref, dict) else {}
    for link in list(message.get("link") or []):
        if not isinstance(link, dict) or "pdf" not in str(link.get("content-type", "")).lower():
            continue
        url = str(link.get("URL") or "").strip()
        if url:
            candidates.append({"url": url, "source": "Publisher-declared PDF"})
    seen: set[str] = set()
    return [item for item in candidates if item["url"].startswith("https://") and not (item["url"] in seen or seen.add(item["url"]))]


def _download_public_pdf(candidate: dict[str, str], *, output_dir: Path, identifier: str, timeout: float) -> Path:
    req = request.Request(candidate["url"], headers={"Accept": "application/pdf,*/*;q=0.8", "User-Agent": "ScanSci-Desktop/0.2"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = response.read(200 * 1024 * 1024 + 1)
    except (error.HTTPError, error.URLError, OSError) as exc:
        raise RuntimeError(f"{candidate['source']} 不可访问") from exc
    if len(data) > 200 * 1024 * 1024:
        raise RuntimeError("全文文件超过 200 MB 上限")
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"{candidate['source']} 未返回 PDF")
    destination = output_dir / f"{_safe_project_name(identifier.replace('/', '_'))}.pdf"
    destination.write_bytes(data)
    return destination


def verify_doi_metadata(doi: str, *, expected_title: str = "", timeout: float = 15.0) -> dict[str, Any]:
    clean = str(doi or "").strip()
    if not _DOI_PATTERN.fullmatch(clean):
        raise ValueError("请输入有效 DOI")
    endpoint = f"https://api.crossref.org/works/{parse.quote(clean, safe='')}"
    payload = _request_json(endpoint, headers={"User-Agent": "ScanSci-Desktop/0.1"}, timeout=timeout)
    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    titles = message.get("title", []) if isinstance(message, dict) else []
    official_title = str(titles[0] if isinstance(titles, list) and titles else "")
    similarity = SequenceMatcher(None, expected_title.casefold().strip(), official_title.casefold().strip()).ratio() if expected_title.strip() and official_title else None
    return {
        "doi": str(message.get("DOI", clean)) if isinstance(message, dict) else clean,
        "status": "verified" if similarity is None or similarity >= 0.78 else "metadata-mismatch",
        "official_title": official_title,
        "title_similarity": round(similarity, 3) if similarity is not None else None,
        "publisher": str(message.get("publisher", "")) if isinstance(message, dict) else "",
        "journal": str((message.get("container-title") or [""])[0]) if isinstance(message, dict) else "",
        "type": str(message.get("type", "")) if isinstance(message, dict) else "",
        "url": str(message.get("URL", f"https://doi.org/{clean}")) if isinstance(message, dict) else f"https://doi.org/{clean}",
        "source": "Crossref REST API",
    }


def build_ppt_outline(
    notebook: dict[str, Any],
    *,
    topic: str = "",
    template_id: str = "",
) -> dict[str, Any]:
    sources = [dict(item) for item in list(notebook.get("sources", []) or [])]
    title = str(topic or notebook.get("title") or notebook.get("notebook_id") or "研究汇报").strip()
    slides: list[dict[str, Any]] = [
        {"index": 1, "title": title, "purpose": "封面与研究问题", "source_ids": []},
        {"index": 2, "title": "研究范围与证据边界", "purpose": "说明资料库覆盖范围、来源数量与限制", "source_ids": []},
        {"index": 3, "title": "证据版图", "purpose": "按主题、年份与来源组织证据", "source_ids": [str(item.get("doc_id", "")) for item in sources[:8]]},
    ]
    for source in sources[:4]:
        slides.append(
            {
                "index": len(slides) + 1,
                "title": str(source.get("title") or source.get("doc_id") or "核心文献"),
                "purpose": "提炼核心结论、方法与可核验原文",
                "source_ids": [str(source.get("doc_id", ""))],
                "doi": str(source.get("doi", "")),
            }
        )
    slides.extend(
        [
            {"index": len(slides) + 1, "title": "综合发现", "purpose": "汇总跨来源一致结论与冲突证据", "source_ids": [str(item.get("doc_id", "")) for item in sources[:12]]},
            {"index": len(slides) + 2, "title": "局限与下一步", "purpose": "标出证据不足、待核验断言与后续研究", "source_ids": []},
            {"index": len(slides) + 3, "title": "参考文献", "purpose": "保留 DOI 与原文跳转", "source_ids": [str(item.get("doc_id", "")) for item in sources]},
        ]
    )
    template = get_slide_template(template_id) if str(template_id).strip() else None
    return {
        "title": title,
        "format": "ppt169",
        "slide_count": len(slides),
        "slides": slides,
        "evidence_linked": True,
        "template": template,
        "template_id": str(template.get("id", "")) if template else "",
    }


def create_ppt_project(
    notebook: dict[str, Any],
    *,
    workspace: str | Path,
    topic: str = "",
    template_id: str = "",
) -> dict[str, Any]:
    script = _SCANSCI_SUITE_ROOT / "easyslides" / "scripts" / "project_manager.py"
    if not script.is_file():
        raise FileNotFoundError(f"未找到 EasySlides：{script}")
    outline = build_ppt_outline(notebook, topic=topic, template_id=template_id)
    project_root = _presentation_directory(workspace)
    project_root.mkdir(parents=True, exist_ok=True)
    base_name = _safe_project_name(str(outline["title"]))
    dated_name = f"{base_name}_ppt169_{datetime.now().strftime('%Y%m%d')}"
    if (project_root / dated_name).exists():
        base_name = f"{base_name}_{datetime.now().strftime('%H%M%S')}"
        dated_name = f"{base_name}_ppt169_{datetime.now().strftime('%Y%m%d')}"
    _run_command([sys.executable, str(script), "init", base_name, "--format", "ppt169", "--dir", str(project_root)], timeout=30)
    project_path = project_root / dated_name
    sources = []
    for item in list(notebook.get("sources", []) or []):
        source = dict(item)
        candidate = Path(str(source.get("evidence_html_path") or source.get("html_path") or ""))
        if candidate.is_file():
            sources.append(str(candidate.resolve()))
    if sources:
        _run_command([sys.executable, str(script), "import-sources", str(project_path), *sources, "--copy"], timeout=120)
    installed_template_path = ""
    template = dict(outline.get("template", {}) or {})
    if template:
        source_template = resolve_slide_template_dir(str(template["id"]))
        target_template = project_path / "templates" / str(template["id"])
        shutil.copytree(source_template, target_template, dirs_exist_ok=True)
        installed_template_path = str(target_template)
        (project_path / "template_selection.json").write_text(
            json.dumps(
                {
                    "provider": "EasySlides",
                    "template_id": template["id"],
                    "template_name": template["name"],
                    "template_path": f"templates/{template['id']}",
                    "format": template["format"],
                    "replication_mode": template["replication_mode"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    notes_dir = project_path / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "deck-plan.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    message = "EasySlides 项目已创建"
    if template:
        message += f"，已应用模板「{template.get('name', '')}」"
    return {
        "ok": True,
        "project_path": str(project_path),
        "imported_sources": len(sources),
        "outline": outline,
        "template": template or None,
        "template_id": str(template.get("id", "")),
        "installed_template_path": installed_template_path,
        "message": message,
    }


def _download_directory(workspace: str | Path) -> Path:
    return Path(workspace).resolve().parent / "downloads"


def _presentation_directory(workspace: str | Path) -> Path:
    return Path(workspace).resolve().parent / "presentations"


def _safe_project_name(value: str) -> str:
    clean = _SAFE_NAME.sub("_", value).strip("._-")[:64]
    return clean or "scansci_deck"


def _run_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "命令执行失败").strip()
        raise RuntimeError(detail[-1600:])
    return completed


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> Any:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ScanSci-Desktop/0.1",
        **(headers or {}),
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"远程服务返回 HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"无法连接远程服务：{exc.reason}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"远程服务响应无效：{exc}") from exc
