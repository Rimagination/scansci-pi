import os

import requests

from scansci_html.official_sources import (
    CrossrefFullTextLinkFetcher,
    ElsevierXmlFetcher,
    OfficialSourceRegistry,
    OfficialSourceUnavailable,
    PmcJatsFetcher,
    SpringerNatureOpenAccessFetcher,
    WileyFullXmlFetcher,
    build_default_official_sources,
    scholarly_xml_to_html,
)


class FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        content: bytes | None = None,
        payload: dict | None = None,
        url: str = "",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self._payload = payload or {}
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")
        return None


class FakeSession:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.urls.append(url)
        if "idconv" in url:
            return FakeResponse(payload={"records": [{"doi": "10.1234/example", "pmcid": "PMC123456"}]})
        if "efetch.fcgi" in url:
            return FakeResponse(
                text="""
                <article>
                  <front>
                    <article-meta>
                      <title-group><article-title>PMC Structured Article</article-title></title-group>
                      <abstract><p>This abstract came from JATS XML.</p></abstract>
                    </article-meta>
                  </front>
                  <body>
                    <sec>
                      <title>Results</title>
                      <p>The body came from the official PMC JATS record.</p>
                    </sec>
                  </body>
                  <back>
                    <ref-list>
                      <title>References</title>
                      <ref id="r1"><mixed-citation>Example reference.</mixed-citation></ref>
                    </ref-list>
                  </back>
                </article>
                """,
                url=url,
            )
        raise AssertionError(f"unexpected URL: {url}")


def test_pmc_jats_fetcher_resolves_doi_and_converts_jats_to_html():
    session = FakeSession()
    fetcher = PmcJatsFetcher(session=session)

    response = fetcher.fetch("https://doi.org/10.1234/example")

    assert response.source == "pmc-jats"
    assert response.final_url.endswith("db=pmc&id=123456&retmode=xml")
    assert "<h1>PMC Structured Article</h1>" in response.html
    assert "<h2>Abstract</h2>" in response.html
    assert "<h2>Results</h2>" in response.html
    assert "<h2>References</h2>" in response.html
    assert "Example reference." in response.html
    assert any("idconv" in url for url in session.urls)
    assert any("efetch.fcgi" in url for url in session.urls)


class MappingSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.urls.append(url)
        self.headers.append(dict(kwargs.get("headers") or {}))
        for marker, response in self.responses.items():
            if marker in url:
                return response
        raise AssertionError(f"unexpected URL: {url}")


class ElsevierRouteSession:
    def __init__(
        self,
        *,
        direct_status: int = 200,
        direct_error: Exception | None = None,
        view_invalid: bool = False,
        pdf_content: bytes | None = None,
    ) -> None:
        self.direct_status = direct_status
        self.direct_error = direct_error
        self.view_invalid = view_invalid
        self.pdf_content = pdf_content or _two_page_pdf_bytes()
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        headers = dict(kwargs.get("headers") or {})
        proxies = kwargs.get("proxies", None)
        route = "configured_proxy" if _is_configured_proxy(proxies) else "direct"
        self.calls.append({"url": url, "headers": headers, "proxies": proxies, "route": route})
        if "/content/article/doi/" in url:
            if route == "direct" and self.direct_error is not None:
                raise self.direct_error
            if self.view_invalid and "view=FULL" in url:
                return FakeResponse(
                    text=(
                        "<service-error><status><statusCode>INVALID_INPUT</statusCode>"
                        "<statusText>View parameter specified in request is not valid</statusText>"
                        "</status></service-error>"
                    ),
                    status_code=400,
                    headers={"X-ELS-Status": "INVALID_INPUT - View parameter specified in request is not valid"},
                    url=url,
                )
            if route == "direct" and self.direct_status >= 400:
                return FakeResponse(
                    status_code=self.direct_status,
                    headers={"X-ELS-Status": "NOT_ENTITLED"},
                    url=url,
                )
            return FakeResponse(text=_elsevier_full_xml(), url=url)
        if "/content/object/eid/" in url:
            return FakeResponse(
                content=self.pdf_content,
                headers={"Content-Type": "application/pdf"},
                url=url,
            )
        raise AssertionError(f"unexpected URL: {url}")


class TrustEnvElsevierRouteSession(ElsevierRouteSession):
    def __init__(self) -> None:
        super().__init__()
        self.trust_env = True


def _is_configured_proxy(proxies: object) -> bool:
    return isinstance(proxies, dict) and any(bool(value) for value in proxies.values())


def _elsevier_full_xml() -> str:
    return """
    <article>
      <head>
        <dc:title>Elsevier API XML</dc:title>
        <dc:description>This abstract came from Elsevier FULL XML.</dc:description>
      </head>
      <body>
        <ce:section>
          <ce:section-title>Results</ce:section-title>
          <ce:para>Elsevier API body.</ce:para>
        </ce:section>
      </body>
      <xocs:attachments>
        <xocs:attachment attachment-eid="1-s2.0-S123456789-main.pdf" type="MAIN" mimetype="application/pdf" />
        <xocs:attachment attachment-eid="1-s2.0-S123456789-mmc1.pdf" type="SUPPLEMENT" mimetype="application/pdf" />
      </xocs:attachments>
    </article>
    """


def _two_page_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        + b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        + b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n"
        + b"3 0 obj << /Type /Page >> endobj\n"
        + b"4 0 obj << /Type /Page >> endobj\n"
        + (b"x" * 12000)
        + b"%%EOF"
    )


def _one_page_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        + b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        + b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        + b"3 0 obj << /Type /Page >> endobj\n"
        + (b"x" * 12000)
        + b"%%EOF"
    )


def test_scholarly_xml_to_html_handles_elsevier_like_xml():
    html = scholarly_xml_to_html(
        """
        <article>
          <head>
            <dc:title>Elsevier XML Article</dc:title>
            <dc:description>This abstract came from Elsevier XML.</dc:description>
          </head>
          <body>
            <ce:section>
              <ce:section-title>Results</ce:section-title>
              <ce:para>The structured body came from the API XML.</ce:para>
            </ce:section>
          </body>
          <tail>
            <ce:bibliography>
              <ce:bib-reference><ce:label>1</ce:label><ce:other-ref>Example citation.</ce:other-ref></ce:bib-reference>
            </ce:bibliography>
          </tail>
        </article>
        """
    )

    assert "<h1>Elsevier XML Article</h1>" in html
    assert "<h2>Abstract</h2>" in html
    assert "This abstract came from Elsevier XML." in html
    assert "<h2>Results</h2>" in html
    assert "The structured body came from the API XML." in html
    assert "<h2>References</h2>" in html
    assert "Example citation." in html


def test_scholarly_xml_to_html_handles_elsevier_full_text_retrieval_response():
    html = scholarly_xml_to_html(
        """
        <full-text-retrieval-response
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:ce="http://www.elsevier.com/xml/common/dtd"
            xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd">
          <coredata>
            <dc:title>Membrane fouling control</dc:title>
            <dc:creator>Ada Lovelace</dc:creator>
            <dc:description>This is the abstract.</dc:description>
          </coredata>
          <xocs:originalText>
            <xocs:doc>
              <xocs:body>
                <ce:section>
                  <ce:section-title>Introduction</ce:section-title>
                  <ce:para>First paragraph.</ce:para>
                </ce:section>
                <ce:bibliography>
                  <ce:bib-reference>
                    <ce:label>[1]</ce:label>
                    <ce:other-ref>Important cited work.</ce:other-ref>
                  </ce:bib-reference>
                </ce:bibliography>
              </xocs:body>
            </xocs:doc>
          </xocs:originalText>
        </full-text-retrieval-response>
        """
    )

    assert "<h1>Membrane fouling control</h1>" in html
    assert "<h2>Abstract</h2>" in html
    assert "This is the abstract." in html
    assert "<h2>Introduction</h2>" in html
    assert "First paragraph." in html
    assert "<h2>References</h2>" in html
    assert "[1] Important cited work." in html


def test_scholarly_xml_to_html_handles_elsevier_sections_wrapper():
    html = scholarly_xml_to_html(
        """
        <full-text-retrieval-response
            xmlns:ce="http://www.elsevier.com/xml/common/dtd"
            xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd">
          <coredata><title>Wrapped Sections</title></coredata>
          <xocs:originalText>
            <xocs:doc>
              <xocs:body>
                <ce:sections>
                  <ce:section>
                    <ce:section-title>Methods</ce:section-title>
                    <ce:para>The method text is nested under a sections wrapper.</ce:para>
                  </ce:section>
                </ce:sections>
              </xocs:body>
            </xocs:doc>
          </xocs:originalText>
        </full-text-retrieval-response>
        """
    )

    assert "<h2>Methods</h2>" in html
    assert "The method text is nested under a sections wrapper." in html


def test_crossref_fulltext_link_fetcher_discovers_and_reads_xml_link():
    session = MappingSession(
        {
            "api.crossref.org/v1/works": FakeResponse(
                payload={
                    "message": {
                        "link": [
                            {
                                "URL": "https://publisher.example/article.txt",
                                "content-type": "text/plain",
                            },
                            {
                                "URL": "https://publisher.example/article.xml",
                                "content-type": "application/xml",
                            },
                        ]
                    }
                }
            ),
            "publisher.example/article.xml": FakeResponse(
                text="""
                <article>
                  <front><article-meta><title-group><article-title>Crossref XML Link</article-title></title-group></article-meta></front>
                  <body><sec><title>Results</title><p>Crossref pointed to this official XML.</p></sec></body>
                </article>
                """,
                url="https://publisher.example/article.xml",
            ),
        }
    )
    fetcher = CrossrefFullTextLinkFetcher(session=session)

    response = fetcher.fetch("https://doi.org/10.1234/crossref")

    assert response.source == "crossref-fulltext-xml"
    assert response.final_url == "https://publisher.example/article.xml"
    assert "<h1>Crossref XML Link</h1>" in response.html
    assert "Crossref pointed to this official XML." in response.html
    assert any("api.crossref.org/v1/works/10.1234%2Fcrossref" in url for url in session.urls)


def test_elsevier_xml_fetcher_requires_api_key():
    fetcher = ElsevierXmlFetcher(api_key="", session=MappingSession({}))

    try:
        fetcher.fetch("https://doi.org/10.1016/j.example.2026.01.001")
    except OfficialSourceUnavailable as exc:
        assert "ELSEVIER_API_KEY" in str(exc)
        assert "https://dev.elsevier.com/apikey/manage" in str(exc)
        assert "scansci credentials set elsevier-api-key" in str(exc)
    else:
        raise AssertionError("missing API key should skip Elsevier source")


def test_elsevier_xml_fetcher_uses_article_retrieval_api_with_key():
    session = MappingSession(
        {
            "api.elsevier.com/content/article/doi": FakeResponse(
                text="""
                <article>
                  <head><dc:title>Elsevier API XML</dc:title></head>
                  <body><ce:section><ce:section-title>Results</ce:section-title><ce:para>Elsevier API body.</ce:para></ce:section></body>
                </article>
                """,
                url="https://api.elsevier.com/content/article/doi/10.1016/j.example.2026.01.001?httpAccept=text/xml",
            )
        }
    )
    fetcher = ElsevierXmlFetcher(api_key="key-123", session=session)

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert response.source == "elsevier-xml"
    assert "Elsevier API XML" in response.html
    assert session.headers[0]["X-ELS-APIKey"] == "key-123"
    assert "view=FULL" in session.urls[0]


def test_elsevier_xml_fetcher_uses_view_full_and_verifies_main_pdf_object_direct_first():
    session = ElsevierRouteSession()
    fetcher = ElsevierXmlFetcher(api_key="key-123", session=session)

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert response.source == "elsevier-xml"
    assert "Elsevier API XML" in response.html
    assert len(session.calls) == 2
    article_call, object_call = session.calls
    assert "/content/article/doi/10.1016%2Fj.example.2026.01.001" in str(article_call["url"])
    assert "view=FULL" in str(article_call["url"])
    assert "httpAccept" not in str(article_call["url"])
    assert article_call["route"] == "direct"
    assert object_call["route"] == "direct"
    assert "/content/object/eid/1-s2.0-S123456789-main.pdf" in str(object_call["url"])
    assert object_call["headers"]["Accept"] == "application/pdf"
    assert "elsevier API route: direct" in response.warnings
    assert "elsevier PDF object verified: 1-s2.0-S123456789-main.pdf" in response.warnings


def test_elsevier_xml_fetcher_direct_route_ignores_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ordinary-proxy.example:8080")
    session = TrustEnvElsevierRouteSession()
    fetcher = ElsevierXmlFetcher(api_key="key-123", session=session)

    fetcher.fetch("10.1016/j.example.2026.01.001")

    assert session.trust_env is False
    assert [call["route"] for call in session.calls] == ["direct", "direct"]
    assert all(call["proxies"] == {"http": None, "https": None} for call in session.calls)


def test_elsevier_xml_fetcher_falls_back_to_configured_proxy_after_direct_not_entitled():
    session = ElsevierRouteSession(direct_status=403)
    fetcher = ElsevierXmlFetcher(
        api_key="key-123",
        session=session,
        network_proxy="socks5://127.0.0.1:1080",
    )

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert "Elsevier API XML" in response.html
    assert [call["route"] for call in session.calls] == [
        "direct",
        "configured_proxy",
        "configured_proxy",
    ]
    assert session.calls[0]["proxies"] == {"http": None, "https": None}
    assert session.calls[1]["proxies"] == {
        "http": "socks5://127.0.0.1:1080",
        "https": "socks5://127.0.0.1:1080",
    }
    assert "elsevier API route failed: direct status=403 x-els-status=NOT_ENTITLED" in response.warnings
    assert "elsevier API route: configured_proxy" in response.warnings


def test_elsevier_xml_fetcher_falls_back_to_configured_proxy_after_direct_timeout():
    session = ElsevierRouteSession(direct_error=requests.Timeout("direct timed out"))
    fetcher = ElsevierXmlFetcher(
        api_key="key-123",
        session=session,
        network_proxy="socks5://127.0.0.1:1080",
    )

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert "Elsevier API XML" in response.html
    assert [call["route"] for call in session.calls] == [
        "direct",
        "configured_proxy",
        "configured_proxy",
    ]
    assert "elsevier API route failed: direct error=Timeout" in response.warnings
    assert "elsevier API route: configured_proxy" in response.warnings


def test_elsevier_xml_fetcher_falls_back_to_httpaccept_xml_when_view_full_is_invalid():
    session = ElsevierRouteSession(view_invalid=True)
    fetcher = ElsevierXmlFetcher(api_key="key-123", session=session)

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert "Elsevier API XML" in response.html
    assert len(session.calls) == 3
    assert "view=FULL" in str(session.calls[0]["url"])
    assert "httpAccept=application%2Fxml" in str(session.calls[1]["url"])
    assert "/content/object/eid/1-s2.0-S123456789-main.pdf" in str(session.calls[2]["url"])
    assert "elsevier API route failed: direct status=400 x-els-status=INVALID_INPUT - View parameter specified in request is not valid" in response.warnings
    assert "elsevier API fallback: httpAccept=application/xml" in response.warnings


def test_elsevier_xml_fetcher_rejects_one_page_pdf_preview_evidence():
    session = ElsevierRouteSession(pdf_content=_one_page_pdf_bytes())
    fetcher = ElsevierXmlFetcher(api_key="key-123", session=session)

    response = fetcher.fetch("10.1016/j.example.2026.01.001")

    assert "Elsevier API XML" in response.html
    assert "elsevier PDF object rejected: 1-s2.0-S123456789-main.pdf reason=one-page-preview" in response.warnings
    assert "elsevier PDF object verified: 1-s2.0-S123456789-main.pdf" not in response.warnings


def test_elsevier_xml_fetcher_sends_optional_institution_token():
    session = MappingSession(
        {
            "api.elsevier.com/content/article/doi": FakeResponse(
                text="""
                <article>
                  <head><dc:title>Elsevier API XML</dc:title></head>
                  <body><ce:section><ce:section-title>Results</ce:section-title><ce:para>Elsevier API body.</ce:para></ce:section></body>
                </article>
                """,
            )
        }
    )
    fetcher = ElsevierXmlFetcher(api_key="key-123", inst_token="inst-token", session=session)

    fetcher.fetch("10.1016/j.example.2026.01.001")

    assert session.headers[0]["X-ELS-APIKey"] == "key-123"
    assert session.headers[0]["X-ELS-Insttoken"] == "inst-token"


def test_springer_openaccess_fetcher_requires_api_key():
    fetcher = SpringerNatureOpenAccessFetcher(api_key="", session=MappingSession({}))

    try:
        fetcher.fetch("https://doi.org/10.1007/example")
    except OfficialSourceUnavailable as exc:
        assert "SPRINGER_NATURE_API_KEY" in str(exc)
    else:
        raise AssertionError("missing API key should skip Springer source")


def test_springer_openaccess_fetcher_queries_doi_and_converts_xml_record():
    session = MappingSession(
        {
            "api.springernature.com/openaccess/jats": FakeResponse(
                text="""
                <response>
                  <records>
                    <article>
                      <front><article-meta><title-group><article-title>Springer OA XML</article-title></title-group></article-meta></front>
                      <body><sec><title>Results</title><p>Springer OA body.</p></sec></body>
                    </article>
                  </records>
                </response>
                """,
                url="https://api.springernature.com/openaccess/jats?q=doi:10.1007/example&api_key=sn-key",
            )
        }
    )
    fetcher = SpringerNatureOpenAccessFetcher(api_key="sn-key", session=session)

    response = fetcher.fetch("10.1007/example")

    assert response.source == "springer-openaccess-jats"
    assert "Springer OA XML" in response.html
    assert "Springer OA body." in response.html
    assert "q=doi%3A10.1007%2Fexample" in session.urls[0]
    assert "api_key=sn-key" in session.urls[0]


def test_wiley_full_xml_fetcher_uses_token_header_and_converts_xml():
    session = MappingSession(
        {
            "onlinelibrary.wiley.com/doi/full-xml/10.1111/example.2026.001": FakeResponse(
                text="""
                <component xmlns="http://www.wiley.com/namespaces/wiley" type="serialArticle">
                  <header>
                    <publicationMeta>
                      <titleGroup><title type="main">Wiley XML Article</title></titleGroup>
                    </publicationMeta>
                    <contentMeta>
                      <titleGroup><title type="main">Wiley XML Article</title></titleGroup>
                      <abstractGroup><abstract><p>This abstract came from Wiley XML.</p></abstract></abstractGroup>
                    </contentMeta>
                  </header>
                  <body>
                    <section>
                      <title>Results</title>
                      <p>The structured body came from Wiley full XML.</p>
                    </section>
                  </body>
                  <bibliography>
                    <bib><citation>Example Wiley reference.</citation></bib>
                  </bibliography>
                </component>
                """,
                url="https://onlinelibrary.wiley.com/doi/full-xml/10.1111/example.2026.001",
            )
        }
    )
    fetcher = WileyFullXmlFetcher(tdm_token="wiley-token", session=session)

    response = fetcher.fetch("10.1111/example.2026.001")

    assert response.source == "wiley-full-xml"
    assert "Wiley XML Article" in response.html
    assert "The structured body came from Wiley full XML." in response.html
    assert "Example Wiley reference." in response.html
    assert session.headers[0]["Wiley-TDM-Client-Token"] == "wiley-token"
    assert session.headers[0]["Accept"] == "application/xml,text/xml,*/*;q=0.8"


def test_wiley_full_xml_fetcher_rejects_non_wiley_doi_prefix():
    fetcher = WileyFullXmlFetcher(tdm_token="wiley-token", session=MappingSession({}))

    try:
        fetcher.fetch("10.1016/j.example.2026.01.001")
    except OfficialSourceUnavailable as exc:
        assert "not a Wiley DOI" in str(exc)
    else:
        raise AssertionError("non-Wiley DOI should skip Wiley source")


def test_official_source_registry_continues_after_unavailable_source():
    class MissingSource:
        def fetch(self, _url):
            raise OfficialSourceUnavailable("not here")

    class HitSource:
        def fetch(self, url):
            return FakeResponse() if False else PmcJatsFetcher(session=FakeSession()).fetch(url)

    registry = OfficialSourceRegistry([MissingSource(), HitSource()])

    responses = list(registry.fetch_candidates("https://doi.org/10.1234/example"))

    assert len(responses) == 1
    assert responses[0].source == "pmc-jats"


def test_default_official_sources_include_keyed_publishers_when_env_is_present(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "elsevier-key")
    monkeypatch.setenv("SPRINGER_NATURE_API_KEY", "springer-key")
    monkeypatch.setenv("WILEY_TDM_CLIENT_TOKEN", "wiley-token")

    sources = build_default_official_sources(timeout=1.0)

    source_names = [source.source_name for source in sources]
    assert source_names == [
        "pmc-jats",
        "elsevier-xml",
        "crossref-fulltext-xml",
        "wiley-full-xml",
        "springer-openaccess-jats",
        "paper-fetch-provider",
    ]


def test_default_official_sources_skip_keyed_publishers_without_env(monkeypatch):
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.delenv("SPRINGER_NATURE_API_KEY", raising=False)
    backend = CredentialBackend({})

    sources = build_default_official_sources(timeout=1.0, credential_backend=backend)

    source_names = [source.source_name for source in sources]
    assert source_names == ["pmc-jats", "crossref-fulltext-xml", "paper-fetch-provider"]


class CredentialBackend:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))


def test_default_official_sources_include_keyed_publishers_from_keyring(monkeypatch):
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.delenv("SPRINGER_NATURE_API_KEY", raising=False)
    backend = CredentialBackend(
        {
            ("scansci-html", "elsevier_api_key"): "elsevier-key",
            ("scansci-html", "springer_nature_api_key"): "springer-key",
            ("scansci-html", "wiley_tdm_client_token"): "wiley-token",
        }
    )

    sources = build_default_official_sources(timeout=1.0, credential_backend=backend)

    assert [source.source_name for source in sources] == [
        "pmc-jats",
        "elsevier-xml",
        "crossref-fulltext-xml",
        "wiley-full-xml",
        "springer-openaccess-jats",
        "paper-fetch-provider",
    ]
