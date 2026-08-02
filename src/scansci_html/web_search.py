"""Source-linked public web search boundary for the Pi agent."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .retrieval_intent import compile_retrieval_intent


_BING_RSS_ENDPOINT = "https://www.bing.com/search"
_DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"


def search_public_web(query: str, *, limit: int = 8, timeout: float = 18.0) -> dict[str, Any]:
    """Search the public web and return compact, attributable discovery hits."""

    intent = compile_retrieval_intent(query, kind="web")
    normalized = str(intent["subject"])
    bounded_limit = max(1, min(12, int(limit)))
    response = requests.get(
        _DUCKDUCKGO_HTML_ENDPOINT,
        params={"q": normalized},
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScanSci/0.2",
        },
        timeout=max(3.0, float(timeout)),
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items: list[dict[str, str]] = []
    for result in soup.select(".result"):
        anchor = result.select_one(".result__a")
        if anchor is None:
            continue
        title = _plain_text(anchor.get_text(" ", strip=True))
        url = _duckduckgo_target(str(anchor.get("href", "") or ""))
        snippet_node = result.select_one(".result__snippet")
        snippet = _plain_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
        if not title or not url.startswith(("https://", "http://")):
            continue
        items.append(
            {
                "title": title[:300],
                "url": url[:2_000],
                "snippet": snippet[:1_200],
                "published_at": "",
            }
        )
        if len(items) >= bounded_limit:
            break
    if not items:
        items = _bing_rss_fallback(normalized, limit=bounded_limit, timeout=timeout)
    if not items:
        raise RuntimeError("The public web search returned no usable results")
    return {
        "query": normalized,
        "search_intent": intent,
        "count": len(items),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "duckduckgo-html" if soup.select_one(".result") else "bing-rss",
        "evidence_level": "web-discovery",
        "items": items,
    }


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return " ".join(without_tags.split())


def _duckduckgo_target(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def _bing_rss_fallback(query: str, *, limit: int, timeout: float) -> list[dict[str, str]]:
    response = requests.get(
        _BING_RSS_ENDPOINT,
        params={"q": query, "format": "rss", "setlang": "zh-Hans"},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScanSci/0.2"},
        timeout=max(3.0, float(timeout)),
    )
    response.raise_for_status()
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as error:
        raise RuntimeError("The fallback web search provider returned invalid RSS") from error
    items: list[dict[str, str]] = []
    for node in root.findall(".//item"):
        title = _plain_text(node.findtext("title", default=""))
        url = str(node.findtext("link", default="") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue
        items.append(
            {
                "title": title[:300],
                "url": url[:2_000],
                "snippet": _plain_text(node.findtext("description", default=""))[:1_200],
                "published_at": _plain_text(node.findtext("pubDate", default=""))[:120],
            }
        )
        if len(items) >= limit:
            break
    return items
