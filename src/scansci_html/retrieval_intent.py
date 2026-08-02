"""Shared, deterministic contracts for every external discovery request.

Search providers should receive a subject or identifier, never an entire UI
instruction.  This module is intentionally model-free: it is used by academic
metadata search, web discovery, journal lookup, Paper Atlas, and download
search, including calls that do not originate in the main task workflow.
"""

from __future__ import annotations

import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_LABELED_SUBJECT_RE = re.compile(
    r"(?:研究主题|检索主题|主题|期刊|论文题目|关键词|topic|research\s+topic|journal|title|keywords?)\s*[:：]\s*(?P<subject>[^\n]+)",
    re.IGNORECASE,
)
_TOPIC_SENTENCE_RE = re.compile(
    r"(?:关于|有关|与)\s*(?P<subject>[^，。！？?；;、\n]{2,160}?)\s*(?:有关|相关)?(?:的)?(?:学术)?(?:论文|文献|资料|文章|papers?|articles?|literature)",
    re.IGNORECASE,
)
_TOPIC_OBJECT_RE = re.compile(
    r"(?P<subject>[^，。！？?；;、\n]{2,160}?)\s*(?:有关|相关)(?:的)?\s*(?:学术)?(?:论文|文献|资料|文章|研究|papers?|articles?|literature)",
    re.IGNORECASE,
)
_SEARCH_PREFIX_RE = re.compile(
    r"^(?:请|帮我|请帮我|麻烦)?\s*(?:检索|搜索|查找|寻找|查询|look\s+up|search\s+for|find)\s*(?:一下|有关|关于)?\s*",
    re.IGNORECASE,
)
_GENERIC_SUFFIX_RE = re.compile(
    r"(?:相关|有关)?(?:的)?(?:研究|文献|论文|综述|进展|现状|研究进展|papers?|articles?|literature|review)$",
    re.IGNORECASE,
)
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
_ISSN_RE = re.compile(r"\b\d{4}-?\d{3}[\dXx]\b")
_QUOTED_TOPIC_RE = re.compile(r"[「『\"“](?P<subject>[^」』\"”]{2,160})[」』\"”]")
_REQUEST_TOPIC_TAIL_RE = re.compile(
    r"\s*(?:的)?(?:关键|核心|代表性|最相关)?(?:论文|文献|文章|资料|研究|papers?|articles?|literature)"
    r"(?:\s*(?:，|,|。|;|；).*)?$",
    re.IGNORECASE,
)


def compile_retrieval_intent(value: Any, *, kind: str = "academic") -> dict[str, Any]:
    """Compile a traceable query contract for an external discovery tool.

    ``kind`` is descriptive rather than permissive: the same extraction policy
    is used at every boundary, while each tool remains free to apply its own
    ranking or metadata validation.  This avoids a deceptively broad global
    relevance filter for tools such as exact journal or DOI lookups.
    """

    raw_query = _clean(value)
    if not raw_query:
        raise ValueError("query is required")
    identifier = _extract_identifier(raw_query)
    if identifier:
        return {
            "schema_version": 1,
            "kind": str(kind or "academic"),
            "raw_query": raw_query,
            "subject": identifier,
            "normalized_subject": identifier,
            "query_variants": [identifier],
            "required_terms": [],
            "intent_type": "exact_identifier",
            "extraction_method": "identifier",
            "quality_policy": "identifier_exact",
        }
    labelled = _LABELED_SUBJECT_RE.search(raw_query)
    topical = _TOPIC_SENTENCE_RE.search(raw_query) or _TOPIC_OBJECT_RE.search(raw_query)
    if labelled:
        subject, method = _clean(labelled.group("subject")), "labelled_subject"
    elif topical:
        subject, method = _clean(topical.group("subject")), "topic_sentence"
    else:
        stripped = _clean(_SEARCH_PREFIX_RE.sub("", raw_query))
        subject, method = (stripped or raw_query), "request_fallback"
    subject = _clean(_SEARCH_PREFIX_RE.sub("", subject))
    # A labelled field is already the user's explicit research subject. Keep
    # its display form and derive the shorter retrieval variant below.
    if not labelled:
        subject = _normalize_topic_subject(subject)
    if not subject:
        raise ValueError("未找到可检索的主题")
    normalized_subject = _strip_generic_suffix(subject)
    # Keep genuinely different reformulations, but never send a second request
    # that only adds a generic tail such as "论文" or "research".  The former
    # made the review dialog look as though it had duplicated a user's topic
    # and also wasted one of the deliberately bounded provider requests.
    # For an explicit labelled subject retain both the user's complete
    # wording and its compact search form. Other free-form requests still use
    # the conservative generic-tail de-duplication policy.
    variants = (
        _unique([subject, normalized_subject])[:3]
        if labelled
        else _unique_query_variants([normalized_subject, subject])[:3]
    )
    required_terms = [term for term in variants if _is_specific_concept(term)]
    return {
        "schema_version": 1,
        "kind": str(kind or "academic"),
        "raw_query": raw_query,
        "subject": subject[:220],
        "normalized_subject": normalized_subject[:220],
        "query_variants": variants,
        "required_terms": required_terms,
        "intent_type": "topic",
        "extraction_method": method,
        "quality_policy": "topic_relevance" if required_terms else "provider_ranking",
    }


def _extract_identifier(value: str) -> str:
    for pattern in (_DOI_RE, _ARXIV_RE, _ISSN_RE):
        match = pattern.search(value)
        if match:
            return match.group(0).strip().rstrip(".,;)。；")
    return ""


def _strip_generic_suffix(value: str) -> str:
    stripped = _GENERIC_SUFFIX_RE.sub("", _clean(value)).strip(" ，,;；。")
    return stripped if len(stripped) >= 2 else _clean(value)


def _normalize_topic_subject(value: str) -> str:
    """Remove request scaffolding while preserving the scholarly concept.

    Conversational Chinese requests often put the topic in quotation marks,
    followed by wording such as ``的关键论文``.  Provider APIs interpret that
    tail literally, so it must never become part of the research subject.
    """

    candidate = _clean(value)
    quoted = _QUOTED_TOPIC_RE.search(candidate)
    if quoted:
        candidate = quoted.group("subject")
    candidate = _REQUEST_TOPIC_TAIL_RE.sub("", candidate)
    return _clean(candidate).strip("「」『』\"“”' ")


def _is_specific_concept(value: str) -> bool:
    candidate = _clean(value)
    cjk_count = sum("\u3400" <= char <= "\u9fff" for char in candidate)
    latin_words = re.findall(r"[a-z0-9]+", candidate.casefold())
    return cjk_count >= 3 or len(latin_words) >= 2


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _unique_query_variants(values: list[str]) -> list[str]:
    """Deduplicate search variants after removing generic scholarly tails.

    ``_unique`` intentionally treats the raw display string as significant.
    Search planning needs a narrower rule: ``"RAG factuality"`` and
    ``"RAG factuality papers"`` describe the same outbound provider query.
    Preserve the first value so the compact normalized subject is what the UI
    and providers receive.
    """

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        key = _strip_generic_suffix(clean).casefold()
        if clean and key and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _clean(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").replace("\r", "\n")).strip()
