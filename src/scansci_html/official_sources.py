from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import re
from urllib.parse import quote, unquote, urlencode, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
import requests

from .credentials import credential_setup_message, get_credential
from .models import FetchResponse
from .paper_fetch_source import PaperFetchProviderFetcher, PaperFetchSourceUnavailable


class OfficialSourceUnavailable(RuntimeError):
    """Raised when an official structured source has no usable full text."""


class OfficialSourceRegistry:
    """Ordered official-source probes that skip unavailable providers."""

    def __init__(self, sources: Iterable[object]) -> None:
        self.sources = list(sources)

    def fetch_candidates(self, url: str) -> Iterator[FetchResponse]:
        for source in self.sources:
            try:
                yield source.fetch(url)
            except (OfficialSourceUnavailable, PaperFetchSourceUnavailable):
                continue


class PmcJatsFetcher:
    """Fetch official PMC JATS XML for DOI records and expose it as simple HTML."""

    source_name = "pmc-jats"

    def __init__(
        self,
        *,
        session: object | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.user_agent = user_agent or "scansci-html/0.1 official-source-probe"

    def fetch(self, url: str) -> FetchResponse:
        doi = _extract_doi(url)
        if not doi:
            raise OfficialSourceUnavailable("no DOI available for PMC lookup")
        pmcid = self._resolve_pmcid(doi)
        xml_url = _pmc_efetch_url(pmcid)
        response = self.session.get(
            xml_url,
            timeout=self.timeout,
            headers={"Accept": "application/xml,text/xml,*/*;q=0.8", "User-Agent": self.user_agent},
        )
        response.raise_for_status()
        html = jats_xml_to_html(response.text)
        return FetchResponse(
            url=url,
            final_url=str(getattr(response, "url", "") or xml_url),
            html=html,
            status_code=getattr(response, "status_code", None),
            source=self.source_name,
        )

    def _resolve_pmcid(self, doi: str) -> str:
        lookup_url = (
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            f"?ids={quote(doi, safe='/')}&format=json"
        )
        response = self.session.get(
            lookup_url,
            timeout=self.timeout,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        response.raise_for_status()
        payload = response.json()
        for record in payload.get("records", []):
            pmcid = str(record.get("pmcid") or "").strip()
            if pmcid:
                return pmcid
        raise OfficialSourceUnavailable(f"PMC has no JATS record for DOI {doi}")


class CrossrefFullTextLinkFetcher:
    """Discover publisher-deposited XML full-text links from Crossref metadata."""

    source_name = "crossref-fulltext-xml"

    def __init__(
        self,
        *,
        session: object | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
        elsevier_api_key: str | None = None,
        wiley_tdm_token: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.user_agent = user_agent or "scansci-html/0.1 crossref-fulltext-link-probe"
        self.elsevier_api_key = elsevier_api_key if elsevier_api_key is not None else get_credential(
            "elsevier-api-key"
        )
        self.wiley_tdm_token = wiley_tdm_token if wiley_tdm_token is not None else get_credential(
            "wiley-tdm-client-token"
        )

    def fetch(self, url: str) -> FetchResponse:
        doi = _extract_doi(url)
        if not doi:
            raise OfficialSourceUnavailable("no DOI available for Crossref full-text link lookup")
        metadata_url = f"https://api.crossref.org/v1/works/{quote(doi, safe='')}"
        response = self.session.get(
            metadata_url,
            timeout=self.timeout,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        response.raise_for_status()
        xml_url = _crossref_xml_link(response.json())
        if not xml_url:
            raise OfficialSourceUnavailable(f"Crossref has no XML full-text link for DOI {doi}")
        xml_response = self.session.get(
            xml_url,
            timeout=self.timeout,
            headers=self._xml_headers(xml_url),
        )
        xml_response.raise_for_status()
        return FetchResponse(
            url=url,
            final_url=str(getattr(xml_response, "url", "") or xml_url),
            html=scholarly_xml_to_html(xml_response.text),
            status_code=getattr(xml_response, "status_code", None),
            source=self.source_name,
        )

    def _xml_headers(self, xml_url: str) -> dict[str, str]:
        headers = {"Accept": "application/xml,text/xml,*/*;q=0.8", "User-Agent": self.user_agent}
        if "api.elsevier.com" in xml_url.lower() and self.elsevier_api_key:
            headers["X-ELS-APIKey"] = self.elsevier_api_key
        if "wiley.com" in xml_url.lower() and self.wiley_tdm_token:
            headers["Wiley-TDM-Client-Token"] = self.wiley_tdm_token
        return headers


class ElsevierXmlFetcher:
    """Fetch Elsevier Article Retrieval XML when an API key and entitlement exist."""

    source_name = "elsevier-xml"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        inst_token: str | None = None,
        session: object | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
        network_proxy: str | None = None,
        min_pdf_bytes: int = 10_000,
    ) -> None:
        self.api_key = api_key if api_key is not None else get_credential("elsevier-api-key")
        self.inst_token = (
            inst_token if inst_token is not None else get_credential("elsevier-inst-token")
        )
        self.session = session or requests.Session()
        if hasattr(self.session, "trust_env"):
            self.session.trust_env = False
        self.timeout = float(timeout)
        self.user_agent = user_agent or "scansci-html/0.1 elsevier-xml-probe"
        self.network_proxy = str(network_proxy or "").strip()
        self.min_pdf_bytes = max(0, int(min_pdf_bytes))

    def fetch(self, url: str) -> FetchResponse:
        doi = _extract_doi(url)
        if not doi:
            raise OfficialSourceUnavailable("no DOI available for Elsevier XML lookup")
        if not self.api_key:
            raise OfficialSourceUnavailable(
                "ELSEVIER_API_KEY is not set; " + credential_setup_message("elsevier-api-key")
            )
        endpoints = _elsevier_article_endpoints(doi)
        headers = self._api_headers("application/xml,text/xml,*/*;q=0.8")
        warnings: list[str] = []
        for route in self._routes(endpoints[0][1]):
            response = None
            endpoint = endpoints[0][1]
            for endpoint_name, candidate_endpoint in endpoints:
                endpoint = candidate_endpoint
                try:
                    response = self._get(candidate_endpoint, headers=headers, route=route)
                    response.raise_for_status()
                except Exception as exc:
                    warnings.append(_elsevier_route_failure_warning(route, response=response, exc=exc))
                    if endpoint_name == "view=FULL" and _elsevier_view_parameter_invalid(response):
                        warnings.append("elsevier API fallback: httpAccept=application/xml")
                        continue
                    response = None
                break
            if response is None:
                continue
            route_warnings = list(warnings)
            route_warnings.append(f"elsevier API route: {route.name}")
            route_warnings.extend(self._pdf_object_warnings(response.text, route=route))
            return FetchResponse(
                url=url,
                final_url=str(getattr(response, "url", "") or endpoint),
                html=scholarly_xml_to_html(response.text),
                status_code=getattr(response, "status_code", None),
                source=self.source_name,
                warnings=route_warnings,
            )
        detail = "; ".join(warnings) if warnings else "no entitled Elsevier API route"
        raise OfficialSourceUnavailable(detail)

    def _api_headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": self.user_agent,
            "X-ELS-APIKey": self.api_key,
        }
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token
        return headers

    def _routes(self, endpoint: str) -> tuple["_ElsevierApiRoute", ...]:
        routes = [_ElsevierApiRoute("direct", {"http": None, "https": None})]
        if self.network_proxy:
            routes.append(
                _ElsevierApiRoute(
                    "configured_proxy",
                    {"http": self.network_proxy, "https": self.network_proxy},
                )
            )
        return tuple(routes)

    def _get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        route: "_ElsevierApiRoute",
    ) -> object:
        kwargs: dict[str, object] = {"timeout": self.timeout, "headers": headers}
        if route.proxies is not None:
            kwargs["proxies"] = route.proxies
        return self.session.get(url, **kwargs)

    def _pdf_object_warnings(self, xml_text: str, *, route: "_ElsevierApiRoute") -> list[str]:
        warnings: list[str] = []
        for eid in elsevier_main_pdf_eids(xml_text):
            object_url = f"https://api.elsevier.com/content/object/eid/{quote(eid, safe='')}"
            response = None
            try:
                response = self._get(
                    object_url,
                    headers=self._api_headers("application/pdf"),
                    route=route,
                )
                response.raise_for_status()
            except Exception as exc:
                warnings.append(
                    _elsevier_object_failure_warning(eid, response=response, exc=exc)
                )
                continue
            reason = _elsevier_pdf_rejection_reason(response, min_pdf_bytes=self.min_pdf_bytes)
            if reason:
                warnings.append(f"elsevier PDF object rejected: {eid} reason={reason}")
                continue
            warnings.append(f"elsevier PDF object verified: {eid}")
            warnings.append(f"elsevier PDF bytes: {len(getattr(response, 'content', b'') or b'')}")
            return warnings
        return warnings


@dataclass(frozen=True)
class _ElsevierApiRoute:
    name: str
    proxies: dict[str, str | None] | None


_ELSEVIER_SUPPLEMENT_RE = re.compile(
    r"supplement|supplementary|mmc|appendix|graphical|thumbnail|image|figure",
    flags=re.I,
)
_ELSEVIER_MAIN_PDF_RE = re.compile(r"main|web-pdf|full[-_\s]?text|attachment|pdf", flags=re.I)
_ELSEVIER_ARTICLE_EID_RE = re.compile(r"\b1-s2\.0-[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\b")
_PDF_PAGE_RE = re.compile(rb"/Type\s*/Page\b")


def _elsevier_article_endpoints(doi: str) -> tuple[tuple[str, str], ...]:
    base = "https://api.elsevier.com/content/article/doi/" + quote(doi, safe="")
    return (
        ("view=FULL", f"{base}?{urlencode({'view': 'FULL'})}"),
        ("httpAccept=application/xml", f"{base}?{urlencode({'httpAccept': 'application/xml'})}"),
    )


def elsevier_main_pdf_eids(xml_text: str) -> tuple[str, ...]:
    """Return candidate Elsevier MAIN PDF object EIDs from Article Retrieval XML."""

    soup = BeautifulSoup(str(xml_text or ""), "xml")
    candidates: list[tuple[int, int, str]] = []
    article_eid = ""
    for index, tag in enumerate(soup.find_all(True)):
        attrs = {str(key).lower(): str(value) for key, value in getattr(tag, "attrs", {}).items()}
        tag_text = _text(tag)
        marker_text = " ".join([_tag_name(tag), tag_text, *attrs.keys(), *attrs.values()])
        for key in ("attachment-eid", "object-eid"):
            eid = attrs.get(key, "").strip()
            if not eid:
                continue
            if _ELSEVIER_SUPPLEMENT_RE.search(marker_text):
                continue
            score = 2 if _ELSEVIER_MAIN_PDF_RE.search(marker_text) else 1
            if "main" in marker_text.lower():
                score = 3
            candidates.append((score, index, eid))
        if not article_eid:
            article_eid = _elsevier_article_eid_from_tag(tag, tag_text, attrs)

    seen: set[str] = set()
    ordered: list[str] = []
    for _score, _index, eid in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if eid not in seen:
            ordered.append(eid)
            seen.add(eid)
    if ordered:
        return tuple(ordered)
    if article_eid:
        return (f"{article_eid}-main.pdf",)
    return ()


def _elsevier_article_eid_from_tag(tag: Tag, tag_text: str, attrs: dict[str, str]) -> str:
    values = [tag_text, *attrs.values()]
    for value in values:
        text = str(value or "").strip()
        if not text or ".pdf" in text.lower():
            continue
        match = _ELSEVIER_ARTICLE_EID_RE.search(text)
        if match:
            return match.group(0)
    return ""


def _elsevier_pdf_rejection_reason(response: object, *, min_pdf_bytes: int) -> str:
    content = bytes(getattr(response, "content", b"") or b"")
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if not (content.startswith(b"%PDF-") or "pdf" in content_type):
        return "not-pdf"
    if len(content) < min_pdf_bytes:
        return "too-small"
    page_count = len(_PDF_PAGE_RE.findall(content))
    if page_count <= 0:
        return "page-count-unavailable"
    if page_count <= 1:
        return "one-page-preview"
    return ""


def _elsevier_view_parameter_invalid(response: object | None) -> bool:
    if response is None:
        return False
    haystack = " ".join(
        [
            _header_value(response, "X-ELS-Status"),
            str(getattr(response, "text", "") or ""),
        ]
    ).lower()
    return "view parameter specified in request is not valid" in haystack


def _elsevier_route_failure_warning(
    route: _ElsevierApiRoute,
    *,
    response: object | None,
    exc: Exception,
) -> str:
    if response is None:
        return f"elsevier API route failed: {route.name} error={type(exc).__name__}"
    parts = [f"elsevier API route failed: {route.name}"]
    status = getattr(response, "status_code", None)
    if status:
        parts.append(f"status={status}")
    els_status = _header_value(response, "X-ELS-Status")
    if els_status:
        parts.append(f"x-els-status={els_status}")
    return " ".join(parts)


def _elsevier_object_failure_warning(
    eid: str,
    *,
    response: object | None,
    exc: Exception,
) -> str:
    if response is None:
        return f"elsevier PDF object failed: {eid} error={type(exc).__name__}"
    parts = [f"elsevier PDF object failed: {eid}"]
    status = getattr(response, "status_code", None)
    if status:
        parts.append(f"status={status}")
    els_status = _header_value(response, "X-ELS-Status")
    if els_status:
        parts.append(f"x-els-status={els_status}")
    return " ".join(parts)


def _header_value(response: object, name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    if not isinstance(headers, dict):
        return ""
    value = headers.get(name) or headers.get(name.lower())
    return str(value or "").strip()


class SpringerNatureOpenAccessFetcher:
    """Fetch Springer Nature Open Access JATS XML when an API key is configured."""

    source_name = "springer-openaccess-jats"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: object | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_credential("springer-nature-api-key")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.user_agent = user_agent or "scansci-html/0.1 springer-openaccess-jats-probe"

    def fetch(self, url: str) -> FetchResponse:
        doi = _extract_doi(url)
        if not doi:
            raise OfficialSourceUnavailable("no DOI available for Springer Nature OA lookup")
        if not self.api_key:
            raise OfficialSourceUnavailable("SPRINGER_NATURE_API_KEY is not set")
        endpoint = "https://api.springernature.com/openaccess/jats?" + urlencode(
            {"q": f"doi:{doi}", "api_key": self.api_key}
        )
        response = self.session.get(
            endpoint,
            timeout=self.timeout,
            headers={"Accept": "application/xml,text/xml,*/*;q=0.8", "User-Agent": self.user_agent},
        )
        response.raise_for_status()
        return FetchResponse(
            url=url,
            final_url=str(getattr(response, "url", "") or endpoint),
            html=scholarly_xml_to_html(response.text),
            status_code=getattr(response, "status_code", None),
            source=self.source_name,
        )


class WileyFullXmlFetcher:
    """Fetch Wiley Online Library full XML and expose it as clean HTML candidate."""

    source_name = "wiley-full-xml"

    def __init__(
        self,
        *,
        tdm_token: str | None = None,
        session: object | None = None,
        timeout: float = 20.0,
        user_agent: str | None = None,
    ) -> None:
        self.tdm_token = (
            tdm_token if tdm_token is not None else get_credential("wiley-tdm-client-token")
        )
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.user_agent = user_agent or "scansci-html/0.1 wiley-full-xml-probe"

    def fetch(self, url: str) -> FetchResponse:
        doi = _extract_doi(url)
        if not doi:
            raise OfficialSourceUnavailable("no DOI available for Wiley full XML lookup")
        if not _is_wiley_doi_or_url(doi, url):
            raise OfficialSourceUnavailable(f"not a Wiley DOI: {doi}")
        if not self.tdm_token:
            raise OfficialSourceUnavailable("WILEY_TDM_CLIENT_TOKEN is not set")
        endpoint = _wiley_full_xml_url(doi, url)
        response = self.session.get(
            endpoint,
            timeout=self.timeout,
            headers={
                "Accept": "application/xml,text/xml,*/*;q=0.8",
                "User-Agent": self.user_agent,
                "Wiley-TDM-Client-Token": self.tdm_token,
            },
        )
        response.raise_for_status()
        return FetchResponse(
            url=url,
            final_url=str(getattr(response, "url", "") or endpoint),
            html=scholarly_xml_to_html(response.text),
            status_code=getattr(response, "status_code", None),
            source=self.source_name,
        )


def build_default_official_sources(
    *,
    timeout: float = 20.0,
    credential_backend: object | None = None,
) -> list[object]:
    elsevier_api_key = get_credential("elsevier-api-key", backend=credential_backend)
    elsevier_inst_token = get_credential("elsevier-inst-token", backend=credential_backend)
    springer_api_key = get_credential("springer-nature-api-key", backend=credential_backend)
    wiley_tdm_token = get_credential("wiley-tdm-client-token", backend=credential_backend)
    sources: list[object] = [PmcJatsFetcher(timeout=timeout)]
    if elsevier_api_key:
        sources.append(
            ElsevierXmlFetcher(
                timeout=timeout,
                api_key=elsevier_api_key,
                inst_token=elsevier_inst_token,
            )
        )
    sources.append(
        CrossrefFullTextLinkFetcher(
            timeout=timeout,
            elsevier_api_key=elsevier_api_key,
            wiley_tdm_token=wiley_tdm_token,
        )
    )
    if wiley_tdm_token:
        sources.append(WileyFullXmlFetcher(timeout=timeout, tdm_token=wiley_tdm_token))
    if springer_api_key:
        sources.append(SpringerNatureOpenAccessFetcher(timeout=timeout, api_key=springer_api_key))
    sources.append(PaperFetchProviderFetcher(timeout=timeout))
    return sources


def scholarly_xml_to_html(xml_text: str) -> str:
    source = BeautifulSoup(str(xml_text or ""), "xml")
    article = _find_article(source)
    if article is None:
        raise OfficialSourceUnavailable("structured XML article payload is missing")

    meta = _first(source, ["article-meta", "head", "coredata"]) or _first(
        article, ["article-meta", "head", "coredata"]
    ) or article
    html = BeautifulSoup("", "lxml")
    output = html.new_tag("article")
    html.append(output)

    title = _first_text_by_names(
        meta,
        [
            "article-title",
            "title",
            "dc:title",
            "prism:publicationName",
        ],
    )
    _append_heading(html, output, 1, title or "Untitled article")

    abstract = _extract_abstract(meta, article)
    if abstract:
        _append_heading(html, output, 2, "Abstract")
        _append_text_tag(html, output, "p", abstract)

    _append_body_sections(html, output, article)
    _append_reference_candidates(html, output, article)
    return str(output)


def jats_xml_to_html(xml_text: str) -> str:
    return scholarly_xml_to_html(xml_text)


def _crossref_xml_link(payload: dict) -> str:
    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    links = message.get("link", []) if isinstance(message, dict) else []
    for link in links:
        if not isinstance(link, dict):
            continue
        content_type = str(link.get("content-type") or "").lower()
        url = str(link.get("URL") or link.get("url") or "").strip()
        if url and ("xml" in content_type or url.lower().endswith(".xml")):
            return url
    return ""


def _find_article(source: BeautifulSoup) -> Tag | None:
    root = source.find(True)
    if isinstance(root, Tag) and _tag_name_in(
        root, ["article", "ja:article", "full-text-retrieval-response"]
    ):
        return root
    for candidate in source.find_all(True):
        if _tag_name_in(candidate, ["article", "ja:article", "xocs:doc"]):
            return candidate
    return source.find(True)


def _first(parent: Tag | BeautifulSoup, names: list[str]) -> Tag | None:
    for tag in parent.find_all(True):
        if _tag_name_in(tag, names):
            return tag
    return None


def _first_text_by_names(parent: Tag | BeautifulSoup, names: list[str]) -> str:
    for tag in parent.find_all(True):
        if _tag_name_in(tag, names):
            text = _text(tag)
            if text:
                return text
    return ""


def _extract_abstract(meta: Tag, article: Tag) -> str:
    for name in ["abstract", "dc:description", "description", "ce:abstract"]:
        text = _first_text_by_names(meta, [name])
        if text:
            return text
    for name in ["abstract", "dc:description", "description", "ce:abstract"]:
        text = _first_text_by_names(article, [name])
        if text:
            return text
    return ""


def _append_body_sections(html: BeautifulSoup, output: Tag, article: Tag) -> None:
    body = _first(article, ["body", "ja:body", "xocs:body"])
    if body is None:
        return
    sections = _top_level_section_descendants(body)
    if sections:
        for section in sections:
            _append_section(html, output, section, level=2)
        return
    for paragraph in body.find_all(True):
        if _tag_name_in(paragraph, ["p", "ce:para", "para"]):
            text = _text(paragraph)
            if text:
                _append_text_tag(html, output, "p", text)


def _top_level_section_descendants(container: Tag) -> list[Tag]:
    sections: list[Tag] = []
    for tag in container.find_all(True):
        if not _tag_name_in(tag, ["sec", "ce:section", "section"]):
            continue
        has_section_parent = any(
            isinstance(parent, Tag)
            and parent is not container
            and _tag_name_in(parent, ["sec", "ce:section", "section"])
            for parent in tag.parents
        )
        if not has_section_parent:
            sections.append(tag)
    return sections


def _append_reference_candidates(html: BeautifulSoup, output: Tag, article: Tag) -> None:
    ref_list = _first(article, ["ref-list", "ce:bibliography", "bibliography"])
    if ref_list is None:
        return
    if _tag_name(ref_list) == "ref-list":
        _append_references(html, output, ref_list)
        return
    _append_heading(html, output, 2, "References")
    ordered = html.new_tag("ol")
    refs = [
        tag
        for tag in ref_list.find_all(True)
        if _tag_name_in(tag, ["ref", "ce:bib-reference", "bib-reference", "bib", "citation"])
    ]
    for ref in refs:
        text = _text(ref)
        if text:
            _append_text_tag(html, ordered, "li", text)
    if ordered.find("li"):
        output.append(ordered)


def _append_section(html: BeautifulSoup, parent: Tag, section: Tag, *, level: int) -> None:
    title = _direct_child_text_by_names(section, ["title", "ce:section-title", "section-title"])
    if title:
        _append_heading(html, parent, min(level, 6), title)
    for child in section.children:
        if not isinstance(child, Tag):
            continue
        if _tag_name_in(child, ["title", "ce:section-title", "section-title"]):
            continue
        if _tag_name_in(child, ["p", "ce:para", "para"]):
            _append_text_tag(html, parent, "p", _text(child))
        elif _tag_name_in(child, ["sec", "ce:section", "section"]):
            _append_section(html, parent, child, level=level + 1)
        elif _tag_name_in(child, ["fig", "table-wrap", "ce:figure"]):
            caption = _first_text_by_names(child, ["caption", "ce:caption"]) or _text(child)
            if caption:
                figure = html.new_tag("figure")
                _append_text_tag(html, figure, "figcaption", caption)
                parent.append(figure)


def _append_references(html: BeautifulSoup, parent: Tag, ref_list: Tag) -> None:
    title = _direct_child_text(ref_list, "title") or "References"
    _append_heading(html, parent, 2, title)
    ordered = html.new_tag("ol")
    for ref in ref_list.find_all(True, recursive=False):
        if not _tag_name_in(ref, ["ref"]):
            continue
        text = _first_text_by_names(ref, ["mixed-citation"]) or _text(ref)
        if text:
            _append_text_tag(html, ordered, "li", text)
    if ordered.find("li"):
        parent.append(ordered)


def _append_paragraphs_from_container(html: BeautifulSoup, parent: Tag, container: Tag) -> None:
    paragraphs = [
        tag for tag in container.find_all(True) if _tag_name_in(tag, ["p", "ce:para", "para"])
    ]
    if not paragraphs:
        text = _text(container)
        if text:
            _append_text_tag(html, parent, "p", text)
        return
    for paragraph in paragraphs:
        text = _text(paragraph)
        if text:
            _append_text_tag(html, parent, "p", text)


def _append_heading(html: BeautifulSoup, parent: Tag, level: int, text: str) -> None:
    _append_text_tag(html, parent, f"h{level}", text)


def _append_text_tag(html: BeautifulSoup, parent: Tag, name: str, text: str) -> None:
    tag = html.new_tag(name)
    tag.append(NavigableString(text))
    parent.append(tag)


def _first_text(parent: Tag, name: str) -> str:
    return _first_text_by_names(parent, [name])


def _direct_child_text(parent: Tag, name: str) -> str:
    for child in parent.children:
        if isinstance(child, Tag) and _tag_name_in(child, [name]):
            return _text(child)
    return ""


def _direct_child_text_by_names(parent: Tag, names: list[str]) -> str:
    for child in parent.children:
        if isinstance(child, Tag) and _tag_name_in(child, names):
            return _text(child)
    return ""


def _text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def _tag_name(tag: Tag) -> str:
    name = str(getattr(tag, "name", "") or "").lower()
    if tag.prefix:
        return f"{str(tag.prefix).lower()}:{name}"
    return name


def _tag_name_in(tag: Tag, names: Iterable[str]) -> bool:
    normalized = {str(name or "").lower() for name in names}
    local_names = {_local_name(name) for name in normalized}
    return _tag_name(tag) in normalized or _local_tag_name(tag) in local_names


def _local_tag_name(tag: Tag) -> str:
    return _local_name(str(getattr(tag, "name", "") or ""))


def _local_name(name: str) -> str:
    return str(name or "").rsplit(":", 1)[-1].lower()


def _extract_doi(value: str) -> str:
    raw = unquote(str(value or "").strip())
    parsed = urlparse(raw)
    if parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        return parsed.path.lstrip("/")
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", raw, flags=re.I)
    return match.group(0) if match else ""


def _is_wiley_doi_or_url(doi: str, url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    if host.endswith("onlinelibrary.wiley.com") or host == "api.wiley.com":
        return True
    normalized = doi.lower()
    return normalized.startswith(("10.1002/", "10.1046/", "10.1111/", "10.1113/"))


def _wiley_full_xml_url(doi: str, source_url: str) -> str:
    parsed = urlparse(str(source_url or ""))
    host = parsed.netloc if parsed.netloc.lower().endswith("onlinelibrary.wiley.com") else ""
    if not host:
        host = "onlinelibrary.wiley.com"
    encoded_doi = quote(doi, safe="/:().;-_")
    return f"https://{host}/doi/full-xml/{encoded_doi}"


def _pmc_efetch_url(pmcid: str) -> str:
    digits = re.sub(r"\D+", "", pmcid)
    if not digits:
        raise OfficialSourceUnavailable(f"invalid PMC id: {pmcid}")
    return f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={digits}&retmode=xml"
