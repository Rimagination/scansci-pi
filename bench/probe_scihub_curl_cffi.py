"""Probe which Sci-Hub mirrors can be reached with curl_cffi alone (no browser).

Read-only connectivity probe: sends a single GET per (mirror, DOI) and classifies
the response. Does not batch-download copyrighted content; the goal is only to
learn which mirrors' anti-bot layers yield to a TLS-fingerprinted HTTP client.

Usage:
    python bench/probe_scihub_curl_cffi.py            # default probe DOIs
    python bench/probe_scihub_curl_cffi.py --proxy socks5h://127.0.0.1:1080
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import quote

from curl_cffi import requests

# A small set of well-known DOIs that Sci-Hub has historically carried in full
# text. Used only to distinguish "mirror reachable + served PDF" from "mirror
# blocked us". Not for accumulating copies of papers.
PROBE_DOIS = [
    "10.1038/nature12373",      # Nature, widely mirrored
    "10.1126/science.1259855",  # Science
]

# Common Sci-Hub mirror domains observed in public lists. Order is arbitrary.
MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
    "https://sci-hub.ee",
    "https://sci-hub.wf",
    "https://sci-hub.ren",
    "https://sci-hub.shop",
    "https://sci-hub.hk",
    "https://sci-hub.mx",
    "https://sci.bban.top",
]

CHALLENGE_MARKERS = (
    b"cf-browser-verification",
    b"cf_chl_opt",
    b"just a moment",
    b"attention required",
    b"cloudflare",
    b"captcha",
    b"altcha",
    b"<html",
)


def classify(resp_bytes: bytes, status: int) -> str:
    """Classify a response body into got_pdf / challenge / landing / other."""
    head = resp_bytes[:8]
    if head.startswith(b"%PDF"):
        return "got_pdf"
    sample = resp_bytes[:4096].lower()
    if status in (403, 503, 429):
        for marker in CHALLENGE_MARKERS:
            if marker in sample:
                return "challenge"
        return "blocked_status"
    if b"<html" in sample:
        # An HTML page from sci-hub is usually the article landing/embed page,
        # which means we reached content but didn't follow the embed to the PDF.
        if any(m in sample for m in (b"captcha", b"altcha", b"just a moment", b"cloudflare")):
            return "challenge"
        return "landing_html"
    return "other"


def probe(mirror: str, doi: str, *, proxy: str | None, timeout: int = 20) -> dict:
    url = f"{mirror.rstrip('/')}/{quote(doi, safe='/')}"
    started = time.time()
    try:
        resp = requests.get(
            url,
            impersonate="chrome",
            proxies={"http": proxy, "https": proxy} if proxy else None,
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed = time.time() - started
        verdict = classify(resp.content, resp.status_code)
        size = len(resp.content)
        final_url = str(resp.url)
        return {
            "mirror": mirror,
            "doi": doi,
            "status": resp.status_code,
            "verdict": verdict,
            "bytes": size,
            "elapsed_s": round(elapsed, 2),
            "final_url": final_url[:80],
        }
    except Exception as exc:  # noqa: BLE001 - want to record every failure mode
        name = type(exc).__name__
        msg = str(exc).lower()
        # curl_cffi raises SSLError when the mirror RSTs the TLS handshake upon
        # detecting a non-browser fingerprint; plain ConnectionAborted/Reset is
        # the same story from the socket layer. Both mean "TLS-fingerprinted at
        # the door", which is the most actionable signal for our question.
        if "ssl" in name.lower() or "ssl" in msg or "connectionaborted" in msg or "connectionreset" in msg or "(35)" in msg or "(56)" in msg:
            verdict = "tls_blocked"
        else:
            verdict = "error"
        return {
            "mirror": mirror,
            "doi": doi,
            "status": None,
            "verdict": verdict,
            "bytes": 0,
            "elapsed_s": round(time.time() - started, 2),
            "error": f"{name}: {str(exc)[:120]}",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default=None, help="e.g. socks5h://127.0.0.1:1080")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    print(f"# curl_cffi probe | proxy={args.proxy} | impersonate=chrome\n")
    print(f"{'mirror':<24} {'doi':<22} {'verdict':<14} {'status':<7} {'bytes':<9} {'s':<6}")
    print("-" * 88)

    summary: dict[str, list[str]] = {"got_pdf": [], "landing_html": [], "challenge": [], "blocked_status": [], "tls_blocked": [], "error": [], "other": []}
    for mirror in MIRRORS:
        for doi in PROBE_DOIS:
            result = probe(mirror, doi, proxy=args.proxy, timeout=args.timeout)
            summary[result["verdict"]].append(mirror)
            err = result.get("error", "")
            tail = f" {err}" if err else f" {result.get('final_url', '')}"
            print(
                f"{result['mirror']:<24} {result['doi']:<22} {result['verdict']:<14} "
                f"{str(result['status']):<7} {result['bytes']:<9} {result['elapsed_s']:<6}{tail}"
            )

    print("\n# Mirror-level verdict (any probe DOI that succeeded counts)")
    seen: set[str] = set()
    for verdict in ("got_pdf", "landing_html", "challenge", "blocked_status", "tls_blocked", "error", "other"):
        mirrors = sorted({m for m in summary[verdict] if m not in seen})
        if mirrors:
            for m in mirrors:
                seen.add(m)
            print(f"  {verdict:<14}: {', '.join(mirrors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
