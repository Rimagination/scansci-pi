"""Minimal MinerU Cloud client used by the document-ingestion boundary.

MinerU is asynchronous: a request returns a signed upload URL, the PDF is
uploaded, and a second endpoint is polled until a Markdown result is ready.
Small PDFs use the lightweight Agent API; larger or multi-page files use the
Precision API.  The public function returns only Markdown because that is the
canonical text artifact consumed by ScanSci's evidence index.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Any
import zipfile

from pypdf import PdfReader
import requests


MINERU_DEFAULT_BASE_URL = "https://mineru.net"
MINERU_TIMEOUT = 600.0
MINERU_POLL_INTERVAL = 3.0
AGENT_MAX_FILE_BYTES = 10 * 1024 * 1024
AGENT_MAX_PAGES = 20
USER_AGENT = "ScanSci/0.3 MinerU client"
AGENT_FALLBACK_ERROR_CODES = {-30001, -30002, -30003}


class MinerUError(RuntimeError):
    """Raised when MinerU cannot produce a non-empty Markdown result."""


def mineru_convert(
    file_path: str | Path,
    *,
    api_key: str,
    base_url: str = "",
    timeout: float = MINERU_TIMEOUT,
    api_mode: str = "auto",
    language: str = "ch",
    enable_table: bool = True,
    enable_formula: bool = True,
    is_ocr: bool = False,
    poll_interval: float = MINERU_POLL_INTERVAL,
) -> str:
    """Convert a PDF through MinerU and return its structured Markdown.

    ``api_mode='auto'`` uses Agent for files within its documented 10 MB/20
    page limits and transparently retries with Precision when the Agent route
    returns a standard-API/limit/rate-limit error.  The API key is accepted
    only in memory and is never included in exceptions or response details.
    """

    resolved = Path(file_path).expanduser().resolve()
    if not resolved.is_file():
        raise MinerUError(f"文件不存在：{resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise MinerUError("MinerU 仅支持 PDF 文件")
    token = str(api_key or "").strip()
    if not token:
        raise MinerUError("MinerU API key 尚未配置")
    mode = str(api_mode or "auto").strip().lower()
    if mode not in {"auto", "agent", "precision"}:
        raise MinerUError("MinerU API 模式必须是 auto、agent 或 precision")

    chosen = mode if mode != "auto" else _choose_api_mode(resolved)
    if chosen == "precision":
        return _convert_precision(
            resolved,
            api_key=token,
            base_url=base_url,
            timeout=timeout,
            language=language,
            enable_table=enable_table,
            enable_formula=enable_formula,
            is_ocr=is_ocr,
            poll_interval=poll_interval,
        )
    try:
        return _convert_agent(
            resolved,
            base_url=base_url,
            timeout=timeout,
            language=language,
            enable_table=enable_table,
            enable_formula=enable_formula,
            is_ocr=is_ocr,
            poll_interval=poll_interval,
        )
    except MinerUError as error:
        if mode == "auto" and _should_fallback_from_agent(error):
            return _convert_precision(
                resolved,
                api_key=token,
                base_url=base_url,
                timeout=timeout,
                language=language,
                enable_table=enable_table,
                enable_formula=enable_formula,
                is_ocr=is_ocr,
                poll_interval=poll_interval,
            )
        raise


def _choose_api_mode(path: Path) -> str:
    try:
        if path.stat().st_size > AGENT_MAX_FILE_BYTES:
            return "precision"
    except OSError:
        return "precision"
    pages = _pdf_page_count(path)
    return "precision" if pages is not None and pages > AGENT_MAX_PAGES else "agent"


def _pdf_page_count(path: Path) -> int | None:
    try:
        reader = PdfReader(str(path), strict=False)
        return len(reader.pages)
    except Exception:
        return None


def _convert_agent(
    path: Path,
    *,
    base_url: str,
    timeout: float,
    language: str,
    enable_table: bool,
    enable_formula: bool,
    is_ocr: bool,
    poll_interval: float,
) -> str:
    endpoint = _agent_endpoint(base_url)
    payload: dict[str, Any] = {
        "file_name": path.name,
        "language": language or "ch",
        "enable_table": bool(enable_table),
        "is_ocr": bool(is_ocr),
        "enable_formula": bool(enable_formula),
    }
    init = _json_request("POST", f"{endpoint}/parse/file", payload=payload, headers=_headers())
    data = _success_data(init, "Agent 获取上传地址")
    task_id = str(data.get("task_id", "")).strip()
    file_url = str(data.get("file_url", "")).strip()
    if not task_id or not file_url:
        raise MinerUError("MinerU Agent 未返回任务号和上传地址")
    _upload(path, file_url, timeout=min(max(float(timeout), 1.0), 180.0))

    deadline = time.monotonic() + max(float(timeout), 1.0)
    markdown_url = ""
    while time.monotonic() < deadline:
        poll = _json_request("GET", f"{endpoint}/parse/{task_id}", headers=_headers())
        data = _success_data(poll, "Agent 查询任务")
        state = str(data.get("state", "")).strip().lower()
        if state == "done":
            markdown_url = str(data.get("markdown_url", "")).strip()
            break
        if state == "failed":
            code = data.get("err_code")
            detail = _safe_detail(data.get("err_msg") or "未知错误")
            raise MinerUError(f"MinerU Agent 解析失败{f' ({code})' if code is not None else ''}：{detail}")
        time.sleep(max(0.0, min(float(poll_interval), 10.0)))
    if not markdown_url:
        raise MinerUError("MinerU Agent 解析超时或未返回 Markdown 地址")
    return _download_markdown(markdown_url, timeout=min(max(float(timeout), 1.0), 180.0))


def _convert_precision(
    path: Path,
    *,
    api_key: str,
    base_url: str,
    timeout: float,
    language: str,
    enable_table: bool,
    enable_formula: bool,
    is_ocr: bool,
    poll_interval: float,
) -> str:
    endpoint = _precision_endpoint(base_url)
    headers = _headers(api_key)
    payload: dict[str, Any] = {
        "files": [{"name": path.name, "data_id": path.stem, "is_ocr": bool(is_ocr)}],
        "model_version": "vlm",
        "enable_formula": bool(enable_formula),
        "enable_table": bool(enable_table),
        "language": language or "ch",
    }
    init = _json_request("POST", f"{endpoint}/file-urls/batch", payload=payload, headers=headers)
    data = _success_data(init, "Precision 获取上传地址")
    batch_id = str(data.get("batch_id", "")).strip()
    upload_urls = _upload_urls(data.get("file_urls") or data.get("files"))
    if not batch_id or not upload_urls:
        raise MinerUError("MinerU Precision 未返回批次号和上传地址")
    _upload(path, upload_urls[0], timeout=min(max(float(timeout), 1.0), 180.0))

    deadline = time.monotonic() + max(float(timeout), 1.0)
    zip_url = ""
    while time.monotonic() < deadline:
        poll = _json_request(
            "GET",
            f"{endpoint}/extract-results/batch/{batch_id}",
            headers=headers,
        )
        data = _success_data(poll, "Precision 查询任务")
        results = data.get("extract_result") or data.get("extract_results") or []
        if isinstance(results, dict):
            results = [results]
        for result in results if isinstance(results, list) else []:
            if not isinstance(result, dict):
                continue
            state = str(result.get("state", "")).strip().lower()
            if state == "done":
                zip_url = str(result.get("full_zip_url", "")).strip()
                break
            if state == "failed":
                raise MinerUError(f"MinerU Precision 解析失败：{_safe_detail(result.get('err_msg') or '未知错误')}")
        if zip_url:
            break
        time.sleep(max(0.0, min(float(poll_interval), 10.0)))
    if not zip_url:
        raise MinerUError("MinerU Precision 解析超时或未返回结果压缩包")
    return _download_precision_markdown(zip_url, timeout=min(max(float(timeout), 1.0), 180.0), stem=path.stem)


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            url,
            json=payload,
            headers=headers or _headers(),
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise MinerUError(f"无法连接 MinerU：{type(error).__name__}") from error
    _check_status(response)
    try:
        result = response.json()
    except (ValueError, json.JSONDecodeError) as error:
        raise MinerUError("MinerU 返回了无效 JSON") from error
    if not isinstance(result, dict):
        raise MinerUError("MinerU 返回格式不是对象")
    return result


def _success_data(payload: dict[str, Any], action: str) -> dict[str, Any]:
    code = payload.get("code", 0)
    if code not in (0, "0", None):
        raise MinerUError(f"{action}失败（错误码 {code}）：{_safe_detail(payload.get('msg') or payload.get('message') or '未知错误')}")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise MinerUError(f"{action}返回格式无效")
    return data


def _upload_urls(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            urls.append(item.strip())
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("file_url") or item.get("upload_url") or "").strip()
            if url:
                urls.append(url)
    return urls


def _upload(path: Path, url: str, *, timeout: float) -> None:
    try:
        response = requests.put(
            url,
            data=path.read_bytes(),
            # Signed object-storage URLs may reject headers that were not part
            # of the signature.  Keep the upload request to the required
            # content length only.
            headers={"Content-Length": str(path.stat().st_size)},
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise MinerUError(f"MinerU 上传失败：{type(error).__name__}") from error
    if response.status_code not in {200, 201, 204}:
        raise MinerUError(f"MinerU 上传失败（HTTP {response.status_code}）")


def _download_markdown(url: str, *, timeout: float) -> str:
    try:
        response = requests.get(url, headers=_headers(), timeout=timeout)
    except requests.RequestException as error:
        raise MinerUError(f"MinerU Markdown 下载失败：{type(error).__name__}") from error
    _check_status(response)
    text = response.content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise MinerUError("MinerU 返回了空 Markdown")
    return text


def _download_precision_markdown(url: str, *, timeout: float, stem: str) -> str:
    try:
        response = requests.get(url, headers=_headers(), timeout=timeout)
    except requests.RequestException as error:
        raise MinerUError(f"MinerU 结果下载失败：{type(error).__name__}") from error
    _check_status(response)
    if not response.content:
        raise MinerUError("MinerU 返回了空结果压缩包")
    with tempfile.TemporaryDirectory(prefix=".mineru-result-") as temporary:
        root = Path(temporary)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                _safe_extract(archive, root)
        except (zipfile.BadZipFile, OSError) as error:
            raise MinerUError("MinerU 结果不是有效压缩包") from error
        markdown = _choose_markdown(root, stem)
        if markdown is None:
            raise MinerUError("MinerU 结果压缩包中没有 Markdown 文件")
        text = markdown.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        raise MinerUError("MinerU 返回了空 Markdown")
    return text


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != root and root not in target.parents:
            raise MinerUError("MinerU 结果压缩包包含不安全路径")
    archive.extractall(destination)


def _choose_markdown(root: Path, stem: str) -> Path | None:
    files = [path for path in root.rglob("*.md") if path.is_file()]
    if not files:
        return None
    preferred = {f"{stem}.md".casefold(), "full.md", "layout.md"}
    for path in files:
        if path.name.casefold() in preferred:
            return path
    return max(files, key=lambda path: path.stat().st_size)


def _agent_endpoint(base_url: str) -> str:
    root = _base_root(base_url)
    return f"{root}/api/v1/agent"


def _precision_endpoint(base_url: str) -> str:
    root = _base_root(base_url)
    return f"{root}/api/v4"


def _base_root(base_url: str) -> str:
    value = str(base_url or MINERU_DEFAULT_BASE_URL).strip().rstrip("/")
    for suffix in ("/api/v4", "/api/v1/agent", "/api/v1"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.rstrip("/")


def _headers(api_key: str = "") -> dict[str, str]:
    result = {"Accept": "*/*", "User-Agent": USER_AGENT}
    if str(api_key or "").strip():
        result["Authorization"] = f"Bearer {str(api_key).strip()}"
    return result


def _check_status(response: requests.Response) -> None:
    status = int(response.status_code)
    if 200 <= status < 300:
        return
    messages = {
        401: "MinerU API key 无效或已过期",
        402: "MinerU 账户额度不足",
        413: "PDF 超过 MinerU 文件大小限制",
        429: "MinerU 请求频率过高，请稍后重试",
    }
    if status in messages:
        raise MinerUError(f"{messages[status]}（HTTP {status}）")
    detail = _safe_detail(getattr(response, "text", ""))
    raise MinerUError(f"MinerU 服务错误（HTTP {status}）{': ' + detail if detail else ''}")


def _safe_detail(value: Any) -> str:
    text = " ".join(str(value or "").split())[:300]
    return re.sub(r"Bearer\s+[^\s,;]+", "Bearer [redacted]", text, flags=re.IGNORECASE)


def _should_fallback_from_agent(error: MinerUError) -> bool:
    message = str(error).lower()
    if "http 429" in message or "频率过高" in message or "standard api" in message or "limit" in message or "限制" in message:
        return True
    return any(str(code) in message for code in AGENT_FALLBACK_ERROR_CODES)
