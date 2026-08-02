"""Verify the full landing-page -> PDF-link -> byte download chain per mirror.

Builds on probe_scihub_curl_cffi.py: for mirrors that returned a 200 landing
page, extract the embedded PDF URL and attempt the actual PDF download with
curl_cffi (no browser). Reports which mirrors yield a real PDF end-to-end.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from curl_cffi import requests

LANDING_MIRRORS = [
    "https://sci-hub.ee",
    "https://sci-hub.wf",
    "https://sci-hub.ren",
    "https://sci-hub.shop",
    "https://sci-hub.hk",
    "https://sci-hub.mx",
]
DOI = "10.1038/nature12373"

# Sci-Hub embeds the PDF via <embed src="...pdf"> or a save button
# location.href='...pdf?download=true'. Match either, tolerate \/ escaping.
PDF_URL_PAT = re.compile(
    r"""(?:src|location\.href)\s*=\s*['"]([^'"]*?\.pdf(?:[^'"]*)?)['"]""",
    re.IGNORECASE,
)


def find_pdf_url(html: str, base: str) -> str | None:
    matches = PDF_URL_PAT.findall(html)
    for raw in matches:
        link = raw.replace("\\/", "/").split("#")[0]
        if not link:
            continue
        if not link.startswith("http"):
            link = urljoin(base, link)
        return link
    return None


def main() -> None:
    print(f"{'mirror':<22} {'landing':<9} {'pdf_link':<9} {'downloaded':<11} {'KB':<6}")
    print("-" * 62)
    for mirror in LANDING_MIRRORS:
        try:
            landing = requests.get(
                f"{mirror}/{DOI}", impersonate="chrome", timeout=20, allow_redirects=True
            )
            link = find_pdf_url(landing.text, str(landing.url))
            downloaded = False
            kb = 0
            if link:
                pdf = requests.get(link, impersonate="chrome", timeout=30, allow_redirects=True)
                downloaded = pdf.content[:4] == b"%PDF"
                kb = len(pdf.content) // 1024
            print(
                f"{mirror:<22} {landing.status_code:<9} "
                f"{'yes' if link else 'no':<9} {'yes' if downloaded else 'no':<11} {kb:<6}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"{mirror:<22} ERROR {type(exc).__name__}: {str(exc)[:60]}")


if __name__ == "__main__":
    main()
