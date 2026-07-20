from __future__ import annotations

import requests

from .models import FetchResponse


class HttpFetcher:
    def __init__(self, *, timeout: float = 30.0, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.user_agent = user_agent or (
            "scansci-html/0.1 (+https://github.com/Rimagination/instsci; "
            "HTML-only authorized article capture)"
        )

    def fetch(self, url: str) -> FetchResponse:
        response = self.session.get(
            url,
            timeout=self.timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "User-Agent": self.user_agent,
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        return FetchResponse(
            url=url,
            final_url=response.url,
            html=response.text,
            status_code=response.status_code,
            source="http",
        )

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> requests.Response:
        request_headers = {"User-Agent": self.user_agent}
        request_headers.update(headers)
        response = self.session.get(url, timeout=timeout, headers=request_headers, allow_redirects=True)
        return response
