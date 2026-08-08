"""MinerU cloud API client for PDF-to-Markdown conversion.

Uses the ``mineru`` Python SDK when installed, falling back to a direct
``/file_parse`` HTTP post for environments that only have a token.

MinerU is an optional document processing backend.  If the SDK is absent,
the ingestion pipeline silently falls back to its built-in parsers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


MINERU_DEFAULT_BASE_URL = "https://mineru.net"
MINERU_SDK_BASE_URL = "https://mineru.net/api/v4"
MINERU_TIMEOUT = 300.0
USER_AGENT = "ScanSci/0.2 MinerU client"


class MinerUError(RuntimeError):
    """Raised when the MinerU service returns an error or is unreachable."""


def _convert_via_sdk(file_path: str | Path, *, api_key: str, timeout: float) -> str:
    """Use the official ``mineru`` SDK to parse a PDF."""

    # The ScanSci package also has a module named ``mineru``.  Use an
    # absolute import so we reach the installed SDK rather than ourselves.
    try:
        import importlib

        mineru_client = importlib.import_module("mineru.client")
        Client = getattr(mineru_client, "MinerU")
    except (ImportError, AttributeError) as exc:
        raise MinerUError(
            "MinerU SDK 未安装（`pip install mineru-open-sdk`）。"
        ) from exc

    client = Client(token=str(api_key).strip(), base_url=MINERU_SDK_BASE_URL)
    try:
        result = client.extract(str(Path(file_path).resolve()), timeout=int(timeout))
    except Exception as exc:
        raise MinerUError(f"MinerU SDK 调用失败：{exc}") from exc

    markdown = str(getattr(result, "markdown", getattr(result, "content", "")) or "")
    if not markdown.strip():
        raise MinerUError(
            f"MinerU 未返回可解析文本（状态：{getattr(result, 'state', 'unknown')}）。"
        )
    return markdown


def _convert_via_api(file_path: str | Path, *, api_key: str, base_url: str, timeout: float) -> str:
    """POST /file_parse directly when the SDK is not installed."""

    resolved = Path(file_path).resolve()
    endpoint = str(base_url or MINERU_DEFAULT_BASE_URL).rstrip("/")

    with resolved.open("rb") as payload:
        response = requests.post(
            f"{endpoint}/file_parse",
            files={"file": (resolved.name, payload, "application/pdf")},
            headers={
                "Authorization": f"Bearer {str(api_key).strip()}",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )
    _check_status(response)

    try:
        result = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise MinerUError(f"MinerU 返回无效 JSON：{exc}") from exc

    if not isinstance(result, dict):
        raise MinerUError(f"MinerU 返回意外格式：{type(result).__name__}")
    markdown = str(result.get("content", "") or "")
    if not markdown.strip():
        raise MinerUError(
            f"MinerU 未返回可解析文本。（状态：{result.get('status', 'unknown')}）"
        )
    return markdown


def mineru_convert(
    file_path: str | Path,
    *,
    api_key: str,
    base_url: str = "",
    timeout: float = MINERU_TIMEOUT,
) -> str:
    """Convert a PDF through MinerU Cloud and return Markdown text.

    Prefers the official ``mineru`` SDK when installed because it handles the
    full async upload → poll → download pipeline.  Falls back to a simple
    ``/file_parse`` HTTP POST for environments that only have a token.
    """

    resolved = Path(file_path).resolve()
    if not resolved.is_file():
        raise MinerUError(f"文件不存在：{resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise MinerUError("MinerU 仅支持 PDF 文件")
    if not str(api_key or "").strip():
        raise MinerUError("MinerU API key 尚未配置")

    try:
        return _convert_via_sdk(file_path, api_key=api_key, timeout=timeout)
    except MinerUError:
        pass
    except ImportError:
        pass

    return _convert_via_api(file_path, api_key=api_key, base_url=base_url, timeout=timeout)


def _check_status(response: requests.Response) -> None:
    status = response.status_code
    if status == 401:
        raise MinerUError("MinerU API key 无效或已过期。请在 mineru.net 重新获取。")
    if status == 402:
        raise MinerUError("MinerU 账户额度不足。请在 mineru.net 充值。")
    if status == 413:
        raise MinerUError("PDF 超过 MinerU 文件大小限制。")
    if status == 429:
        raise MinerUError("MinerU 请求频率过高，请稍后重试。")
    if not response.ok:
        detail = response.text[:500]
        raise MinerUError(f"MinerU 服务错误 ({status})。{detail}".rstrip())
