from __future__ import annotations

from collections.abc import Mapping
from html import escape
import mimetypes
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag
import requests

from .models import CleanHtmlDocument


SENSITIVE_QUERY_KEYS = {"invoice", "nonce", "idenid", "cookie", "token", "authorization"}
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
CONFUSABLE_MATH_CHARS = str.maketrans(
    {
        "\u03a1": "P",
        "\u0399": "I",
        "\u039a": "K",
    }
)

MATH_TAGS = {
    "annotation",
    "math",
    "mfrac",
    "mi",
    "mn",
    "mo",
    "mover",
    "mroot",
    "mrow",
    "msqrt",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
    "semantics",
}
ALLOWED_TAGS = {
    "a",
    "b",
    "br",
    "caption",
    "col",
    "colgroup",
    "em",
    "i",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
} | MATH_TAGS


def render_cnki_reader_json(
    payload: Mapping[str, Any],
    *,
    source_url: str = "",
    tablename: str = "",
    image_assets: Mapping[str, str] | None = None,
) -> CleanHtmlDocument:
    data = _payload_data(payload)
    metadata = _mapping(data.get("metadata"))
    source = _mapping(data.get("source"))
    filename = str(metadata.get("fileName") or "").strip()
    product = str(metadata.get("resourceType") or "CJFQ").strip()
    resource_type = str(source.get("type") or "JOURNAL").strip()
    title = _text_only(metadata.get("title")) or filename or "CNKI article"
    safe_source_url = _safe_source_url(source_url, fallback=f"cnki:{filename or 'reader'}")

    html = _standalone_html(
        data=data,
        metadata=metadata,
        source=source,
        title=title,
        source_url=safe_source_url,
        filename=filename,
        product=product,
        tablename=tablename,
        resource_type=resource_type,
        image_assets=image_assets or {},
    )
    text_length = len(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    warnings = []
    if _has_cnki_figure_urls(data) and not image_assets:
        warnings.append("cnki_figure_urls_stripped_annex_ids_retained")
    return CleanHtmlDocument(
        title=title,
        html=html,
        text_length=text_length,
        has_fulltext=bool(data.get("fullText")),
        access_status="fulltext" if data.get("fullText") else "unknown",
        source_url=safe_source_url,
        doi=None,
        warnings=warnings,
    )


def cnki_reader_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    data = _payload_data(payload)
    full_text = list(data.get("fullText") or [])
    return {
        "paragraphs": _count_type(full_text, "PARAGRAPH"),
        "sections": _count_type(full_text, "CATALOG"),
        "figures": _count_type(full_text, "FIGURE"),
        "tables": _count_type(full_text, "TABLE"),
        "references": len(list(data.get("references") or [])),
    }


def download_cnki_reader_images(
    payload: Mapping[str, Any],
    *,
    output_path: str | Path,
    assets_dir: str | Path | None = None,
    source_url: str = "",
    session: object | None = None,
    timeout: float = 30.0,
) -> tuple[dict[str, str], list[str]]:
    data = _payload_data(payload)
    output = Path(output_path)
    asset_dir = Path(assets_dir) if assets_dir is not None else output.with_name(f"{output.stem}_assets")
    active_session = session or requests.Session()
    warnings: list[str] = []
    image_assets: dict[str, str] = {}

    for index, image in enumerate(_cnki_image_hrefs(data), start=1):
        annex_id = image["annex_id"]
        href = image["href"]
        if not annex_id or not href:
            continue
        try:
            response = active_session.get(
                href,
                timeout=float(timeout),
                headers=_request_headers(_safe_source_url(source_url, fallback="")),
            )
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            content = bytes(getattr(response, "content", b"") or b"")
            content_type = _content_type(getattr(response, "headers", {}) or {})
            if not content:
                raise ValueError("empty image response")
            if content_type and not content_type.startswith("image/") and not _has_image_extension(annex_id):
                raise ValueError("non-image response")
            local_path = asset_dir / _asset_filename(index, annex_id, content_type)
            _write_binary_atomic(local_path, content)
            image_assets[annex_id] = _relative_html_path(local_path, output.parent)
        except Exception as exc:
            warnings.append(f"cnki image download failed for annexid {annex_id or index}: {type(exc).__name__}")

    return image_assets, warnings


def _payload_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        raise ValueError("CNKI reader payload must be a mapping or contain a mapping at data")
    return data


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _count_type(items: list[Any], item_type: str) -> int:
    return sum(1 for item in items if isinstance(item, Mapping) and item.get("type") == item_type)


def _text_only(value: Any) -> str:
    if not value:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def _item_titles(items: Any) -> list[str]:
    titles = []
    for item in items or []:
        if isinstance(item, Mapping) and item.get("title"):
            titles.append(str(item["title"]).strip())
    return titles


def _zh(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


def _sanitize_fragment(raw: Any) -> str:
    if raw is None:
        return ""
    soup = BeautifulSoup(str(raw), "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        name = tag.name.lower()

        if name in {
            "button",
            "embed",
            "form",
            "iframe",
            "img",
            "input",
            "object",
            "script",
            "select",
            "style",
            "svg",
            "textarea",
        }:
            tag.decompose()
            continue

        if name == "citation":
            _rewrite_citation_tag(tag)
            continue

        if name == "link":
            tag.decompose()
            continue

        if name == "a":
            _rewrite_anchor_tag(tag)
            continue

        if name == "mathml":
            tag.name = "span"
            tag.attrs = {"class": "mathml"}
            continue

        if name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        tag.attrs = _allowed_attrs(tag)

    _fix_math_confusables(soup)
    return "".join(str(child) for child in soup.contents).strip()


def _rewrite_citation_tag(tag: Tag) -> None:
    ref = ""
    link = tag.find("link")
    if isinstance(link, Tag) and link.get("href"):
        ref = _safe_id(link.get("href"))
    elif tag.get("id"):
        ref = _safe_id(tag.get("id"))
    for link_tag in list(tag.find_all("link")):
        link_tag.decompose()
    tag.name = "a"
    tag.attrs = {"class": "citation"}
    if ref:
        tag.attrs.update({"href": f"#ref-{ref}", "data-ref": ref})


def _rewrite_anchor_tag(tag: Tag) -> None:
    ref = ""
    if tag.get("type") == "reference" and tag.get("id"):
        ref = _safe_id(tag.get("id"))
    if ref:
        tag.attrs = {"class": "citation", "href": f"#ref-{ref}", "data-ref": ref}
    else:
        tag.unwrap()


def _allowed_attrs(tag: Tag) -> dict[str, str]:
    name = tag.name.lower()
    attrs: dict[str, str] = {}
    if name in {"td", "th"}:
        for attr in ("colspan", "rowspan"):
            value = str(tag.get(attr) or "")
            if re.fullmatch(r"\d{1,2}", value):
                attrs[attr] = value
    elif name == "span":
        classes = tag.get("class")
        if classes and "mathml" in classes:
            attrs["class"] = "mathml"
    elif name == "math":
        attrs["xmlns"] = "http://www.w3.org/1998/Math/MathML"
    elif name == "mo" and tag.get("stretchy") in {"true", "false"}:
        attrs["stretchy"] = str(tag.get("stretchy"))
    return attrs


def _fix_math_confusables(soup: BeautifulSoup | Tag) -> None:
    roots = list(soup.select(".mathml, math")) if isinstance(soup, (BeautifulSoup, Tag)) else []
    for root in roots:
        for node in list(root.find_all(string=True)):
            fixed = str(node).translate(CONFUSABLE_MATH_CHARS)
            if fixed != str(node):
                node.replace_with(NavigableString(fixed))


def _safe_id(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_.:-]", "", str(value or "").strip())


def _standalone_html(
    *,
    data: Mapping[str, Any],
    metadata: Mapping[str, Any],
    source: Mapping[str, Any],
    title: str,
    source_url: str,
    filename: str,
    product: str,
    tablename: str,
    resource_type: str,
    image_assets: Mapping[str, str],
) -> str:
    counts = cnki_reader_counts(data)
    title_en = _text_only(metadata.get("titleEN"))
    authors = _item_titles(data.get("authors"))
    authors_en = _item_titles(data.get("authorsEN"))
    affiliations = _item_titles(data.get("affiliation"))
    affiliations_en = _item_titles(data.get("affiliationEn"))
    keywords = _item_titles(data.get("keywords"))
    keywords_en = _item_titles(data.get("keywordsEN"))
    funds = _item_titles(data.get("funds"))
    source_title = _source_title(source)

    abstract_cn = _sanitize_fragment(metadata.get("abstracts"))
    abstract_en = _sanitize_fragment(metadata.get("abstractsEN"))
    body_html = _render_full_text(data.get("fullText") or [], image_assets=image_assets)
    refs_html = _render_references(data.get("references") or [])
    cn_comma = "\uff0c"
    cn_semicolon = "\uff1b"
    cn_colon = "\uff1a"
    authors_text = cn_comma.join(authors)
    affiliations_text = cn_semicolon.join(affiliations)
    keywords_text = cn_semicolon.join(keywords)
    funds_text = cn_semicolon.join(funds)

    meta_rows = _meta_rows(
        [
            (_zh(0x6765, 0x6E90), source_title),
            (_zh(0x6536, 0x7A3F, 0x65E5, 0x671F), str(metadata.get("receivedDate") or "")),
            (_zh(0x6587, 0x4EF6, 0x540D), filename),
            (_zh(0x8D44, 0x6E90, 0x7C7B, 0x578B), resource_type),
            (
                _zh(0x6B63, 0x6587, 0x5757),
                (
                    f"{counts['paragraphs']} {_zh(0x6BB5)}\uff0c"
                    f"{counts['sections']} {_zh(0x4E2A, 0x6807, 0x9898)}\uff0c"
                    f"{counts['figures']} {_zh(0x4E2A, 0x56FE)}\uff0c"
                    f"{counts['tables']} {_zh(0x4E2A, 0x8868)}"
                ),
            ),
            (_zh(0x53C2, 0x8003, 0x6587, 0x732E), f"{counts['references']} {_zh(0x6761)}"),
        ]
    )
    article_open = (
        f'<article data-source="cnki" data-source-url="{escape(source_url)}" '
        f'data-product="{escape(product)}" data-filename="{escape(filename)}" '
        f'data-tablename="{escape(tablename)}" data-resource="{escape(resource_type)}">\n'
    )

    return "".join(
        [
        "<!doctype html>\n"
        '<html lang="zh-CN">\n',
        "<head>\n",
        '<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        f"<title>{escape(title)}</title>\n",
        '<meta name="source" content="CNKI reader XML">\n',
        f'<meta name="source-filename" content="{escape(filename)}">\n',
        f'<meta name="source-product" content="{escape(product)}">\n',
        f"<style>{_css()}</style>\n",
        "</head>\n",
        "<body>\n",
        article_open,
        "<header>\n",
        f"<h1>{escape(title)}</h1>\n",
        f'<p class="english-title">{escape(title_en)}</p>\n',
        f'<p class="byline">{escape(authors_text)}</p>\n',
        f'<p class="byline byline-en">{escape("; ".join(authors_en))}</p>\n',
        f'<p class="affiliations">{escape(affiliations_text)}</p>\n',
        f'<p class="affiliations affiliations-en">{escape("; ".join(affiliations_en))}</p>\n',
        f'<dl class="meta">{meta_rows}</dl>\n',
        '<section class="abstracts" aria-labelledby="abstract-title">\n',
        f'<h2 id="abstract-title">{_zh(0x6458, 0x8981)}</h2>\n',
        f"<p>{abstract_cn}</p>\n",
        f'<p class="keywords"><strong>{_zh(0x5173, 0x952E, 0x8BCD)}{cn_colon}</strong>{escape(keywords_text)}</p>\n',
        "<h2>Abstract</h2>\n",
        f"<p>{abstract_en}</p>\n",
        f'<p class="keywords keywords-en"><strong>Keywords:</strong> {escape("; ".join(keywords_en))}</p>\n',
        f'<p class="funding"><strong>{_zh(0x57FA, 0x91D1, 0x9879, 0x76EE)}{cn_colon}</strong>{escape(funds_text)}</p>\n',
        "</section>\n",
        "</header>\n",
        '<section class="article-body">\n',
        f"{body_html}\n",
        "</section>\n",
        f"{refs_html}\n",
        "</article>\n",
        "</body>\n",
        "</html>\n",
        ]
    )


def _source_title(source: Mapping[str, Any]) -> str:
    bits = [str(source.get("title") or "").strip()]
    year = str(source.get("year") or "").strip()
    issue = str(source.get("issue") or "").strip()
    if year:
        bits.append(year + _zh(0x5E74))
    if issue:
        bits.append(_zh(0x7B2C) + issue + _zh(0x671F))
    value = " ".join(bit for bit in bits if bit)
    return value or "CNKI"


def _meta_rows(rows: list[tuple[str, str]]) -> str:
    parts = []
    for label, value in rows:
        if value:
            parts.append(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>")
    return "".join(parts)


def _render_full_text(items: Any, *, image_assets: Mapping[str, str]) -> str:
    blocks = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = _mapping(item.get("value"))
        item_type = item.get("type")
        if item_type == "PARAGRAPH":
            blocks.append(_render_paragraph(value))
        elif item_type == "CATALOG":
            blocks.append(_render_catalog(value))
        elif item_type == "TABLE":
            blocks.append(_render_table(value))
        elif item_type == "FIGURE":
            blocks.append(_render_figure(value, image_assets=image_assets))
    return "\n".join(blocks)


def _render_paragraph(value: Mapping[str, Any]) -> str:
    no = _safe_id(value.get("no"))
    content = _sanitize_fragment(value.get("content"))
    attrs = f' id="p-{no}" data-cnki-no="{no}"' if no else ""
    return f"<p{attrs}>{content}</p>"


def _render_catalog(value: Mapping[str, Any]) -> str:
    no = _safe_id(value.get("no"))
    level = str(value.get("level") or "").strip()
    tag = {"1": "h2", "2": "h3", "3": "h4"}.get(level, "h4")
    attrs = f' id="sec-{no}" data-cnki-no="{no}"' if no else ""
    return f"<{tag}{attrs}>{_sanitize_fragment(value.get('title'))}</{tag}>"


def _render_table(value: Mapping[str, Any]) -> str:
    no = _safe_id(value.get("no"))
    caption = _caption_html(value.get("title"), value.get("titleEN"))
    notes = _notes_html(value, prefix="table")
    rows = _sanitize_fragment(value.get("content"))
    return (
        f'<figure class="table-figure" id="table-{no}" data-cnki-no="{no}">'
        f"<figcaption>{caption}</figcaption>{notes}"
        f'<div class="table-scroll"><table><tbody>{rows}</tbody></table></div>'
        "</figure>"
    )


def _render_figure(value: Mapping[str, Any], *, image_assets: Mapping[str, str]) -> str:
    no = _safe_id(value.get("no"))
    annex_id = _figure_annex_id(value)
    annex_attr = f' data-annexid="{escape(annex_id)}"' if annex_id else ""
    caption = _caption_html(value.get("title"), value.get("enTitle") or value.get("titleEN"))
    notes = _notes_html(value, prefix="figure")
    asset_src = _safe_local_asset_path(image_assets.get(annex_id, ""))
    media = (
        f'<img src="{escape(asset_src)}" alt="{escape(_figure_alt_text(value))}" loading="lazy"{annex_attr}>'
        if asset_src
        else f'<div class="figure-media"{annex_attr}></div>'
    )
    return (
        f'<figure class="article-figure" id="fig-{no}" data-cnki-no="{no}"{annex_attr}>'
        f"{media}"
        f"<figcaption>{caption}{notes}</figcaption>"
        "</figure>"
    )


def _caption_html(title: Any, title_en: Any) -> str:
    parts = []
    title_html = _sanitize_fragment(title)
    title_en_html = _sanitize_fragment(title_en)
    if title_html:
        parts.append(f'<span class="caption-title">{title_html}</span>')
    if title_en_html:
        parts.append(f'<span class="caption-title-en">{title_en_html}</span>')
    return "".join(parts)


def _notes_html(value: Mapping[str, Any], *, prefix: str) -> str:
    parts = []
    for key in ("noteBefore", "noteAfter", "noteEnBefore", "noteEnAfter"):
        note = _sanitize_fragment(value.get(key))
        if note:
            parts.append(f'<p class="{prefix}-note">{note}</p>')
    return "".join(parts)


def _figure_annex_id(value: Mapping[str, Any]) -> str:
    hrefs = value.get("listImageHref") or []
    first = hrefs[0] if isinstance(hrefs, list) and hrefs else ""
    if not isinstance(first, str):
        return ""
    query = parse_qs(urlsplit(first).query)
    return _safe_id((query.get("annexid") or [""])[0])


def _figure_alt_text(value: Mapping[str, Any]) -> str:
    return " ".join(
        text
        for text in [
            _text_only(value.get("title")),
            _text_only(value.get("enTitle") or value.get("titleEN")),
        ]
        if text
    )


def _render_references(refs: Any) -> str:
    items = []
    for ref in refs or []:
        if not isinstance(ref, Mapping):
            continue
        no = _safe_id(ref.get("no"))
        seq = str(ref.get("seq") or "").strip()
        title = str(ref.get("title") or "")
        title = re.sub(r"^\s*\[\d+\]\s*", "", title)
        items.append(
            f'<li id="ref-{no}" data-cnki-no="{no}" data-seq="{escape(seq)}">'
            f'<span class="ref-label">[{escape(seq)}]</span> {_sanitize_fragment(title)}</li>'
        )
    return (
        f'<section id="references" class="references"><h2>{_zh(0x53C2, 0x8003, 0x6587, 0x732E)}</h2><ol>\n'
        + "\n".join(items)
        + "\n</ol></section>"
    )


def _has_cnki_figure_urls(data: Mapping[str, Any]) -> bool:
    for item in data.get("fullText") or []:
        if isinstance(item, Mapping) and item.get("type") == "FIGURE":
            value = _mapping(item.get("value"))
            if value.get("listImageHref"):
                return True
    return False


def _safe_source_url(source_url: str, *, fallback: str) -> str:
    value = str(source_url or "").strip()
    if not value:
        return fallback
    parsed = urlsplit(value)
    if not parsed.query:
        return value
    safe_query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), parsed.fragment))


def _cnki_image_hrefs(data: Mapping[str, Any]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for item in data.get("fullText") or []:
        if not isinstance(item, Mapping) or item.get("type") != "FIGURE":
            continue
        value = _mapping(item.get("value"))
        for href in value.get("listImageHref") or []:
            if not isinstance(href, str):
                continue
            annex_id = _figure_annex_id({"listImageHref": [href]})
            if annex_id:
                images.append({"annex_id": annex_id, "href": href})
    return images


def _request_headers(source_url: str) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        )
    }
    if source_url:
        headers["Referer"] = source_url
    return headers


def _content_type(headers: object) -> str:
    get = getattr(headers, "get", None)
    if not callable(get):
        return ""
    return str(get("Content-Type") or get("content-type") or "").split(";", 1)[0].strip().lower()


def _asset_filename(index: int, annex_id: str, content_type: str) -> str:
    basename = Path(annex_id).name
    stem = _safe_filename_part(Path(basename).stem) or f"image_{index:03d}"
    extension = Path(basename).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        extension = _extension_from_content_type(content_type)
    return f"{stem[:100]}{extension}"


def _extension_from_content_type(content_type: str) -> str:
    if content_type == "image/jpeg":
        return ".jpg"
    extension = mimetypes.guess_extension(content_type or "")
    if extension in {".jpe", ".jpeg"}:
        return ".jpg"
    return extension if extension in IMAGE_EXTENSIONS else ".bin"


def _has_image_extension(value: str) -> bool:
    return Path(value).suffix.lower() in IMAGE_EXTENSIONS


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")


def _safe_local_asset_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return ""
    if any(token in path.lower() for token in SENSITIVE_QUERY_KEYS):
        return ""
    return path.lstrip("/")


def _relative_html_path(path: Path, base_dir: Path) -> str:
    return os.path.relpath(path, start=base_dir).replace(os.sep, "/")


def _write_binary_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _css() -> str:
    return """
:root { --ink:#17202a; --muted:#5b6570; --line:#d9dee5; --soft:#f5f7fa; --accent:#126a73; }
* { box-sizing: border-box; }
body { margin:0; font-family:"Noto Serif SC","Source Han Serif SC","Songti SC",SimSun,serif; color:var(--ink); background:#fff; line-height:1.78; }
article { max-width:920px; margin:0 auto; padding:44px 28px 72px; }
h1 { margin:0 0 10px; font-size:2rem; line-height:1.25; text-align:center; }
.english-title { margin:0 auto 24px; max-width:760px; text-align:center; color:var(--muted); line-height:1.45; font-family:Georgia,"Times New Roman",serif; }
.byline, .affiliations, .keywords, .funding { text-align:center; margin:6px 0; }
.meta { display:grid; grid-template-columns:max-content 1fr; gap:4px 14px; margin:24px 0; padding:16px 18px; border:1px solid var(--line); background:var(--soft); font-size:.95rem; }
.meta dt { font-weight:700; color:var(--accent); }
.meta dd { margin:0; }
.abstracts { margin:28px 0 34px; padding-top:8px; border-top:2px solid var(--line); border-bottom:2px solid var(--line); }
.abstracts h2 { font-size:1.05rem; margin:16px 0 4px; }
.abstracts p, .article-body p { margin:0 0 14px; }
.article-body p { text-align:justify; }
h2, h3, h4 { margin:28px 0 12px; line-height:1.35; font-family:"Noto Sans SC","Microsoft YaHei",sans-serif; }
h2 { font-size:1.45rem; border-bottom:1px solid var(--line); padding-bottom:6px; }
h3 { font-size:1.18rem; color:var(--accent); }
.citation { color:var(--accent); text-decoration:none; }
.citation:hover { text-decoration:underline; }
.mathml, math { font-family:"Cambria Math","STIX Two Math",serif; }
.article-figure, .table-figure { margin:28px 0; }
.figure-media { min-height:120px; border:1px dashed var(--line); background:repeating-linear-gradient(135deg,#fafafa,#fafafa 10px,#f2f4f6 10px,#f2f4f6 20px); }
figcaption { margin-top:8px; color:#26323f; line-height:1.55; }
.caption-title, .caption-title-en { display:block; font-weight:700; }
.caption-title-en { color:var(--muted); font-family:Georgia,"Times New Roman",serif; font-weight:600; }
.figure-note, .table-note { margin:4px 0 0; color:var(--muted); font-size:.95rem; }
.table-scroll { overflow-x:auto; border:1px solid var(--line); }
table { width:100%; border-collapse:collapse; font-size:.92rem; line-height:1.45; }
td, th { border:1px solid var(--line); padding:7px 9px; vertical-align:top; }
.references { margin-top:36px; border-top:2px solid var(--line); padding-top:12px; }
.references ol { list-style:none; padding:0; margin:0; }
.references li { margin:0 0 9px; padding-left:3.2em; text-indent:-3.2em; line-height:1.55; }
.ref-label { display:inline-block; min-width:3em; color:var(--accent); font-weight:700; }
@media (max-width:680px) { article { padding:28px 16px 54px; } h1 { font-size:1.45rem; } .meta { grid-template-columns:1fr; } }
""".strip()
