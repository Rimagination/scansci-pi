from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable


ENTITY_CANDIDATE_PROFILES = {"regex", "scientific-ngram"}

DEFAULT_ENTITY_STOPWORDS = {
    "Abstract",
    "Acknowledgments",
    "Author",
    "Background",
    "Conclusion",
    "Conclusions",
    "Data",
    "Discussion",
    "Figure",
    "Figures",
    "Introduction",
    "Materials",
    "Methods",
    "Results",
    "Supplementary",
    "Table",
    "Tables",
}

COMMON_NON_GENUS_WORDS = {
    "Analysis",
    "Data",
    "Evidence",
    "Figure",
    "Language",
    "Method",
    "Model",
    "Models",
    "Paper",
    "Random",
    "Result",
    "Results",
    "Study",
    "Table",
    "Treatment",
}

TECHNICAL_HEAD_TERMS = {
    "accuracy",
    "algorithm",
    "algorithms",
    "analysis",
    "annotation",
    "annotations",
    "approach",
    "approaches",
    "architecture",
    "architectures",
    "assay",
    "assays",
    "benchmark",
    "benchmarks",
    "cell",
    "cells",
    "classification",
    "classifier",
    "classifiers",
    "cluster",
    "clusters",
    "corpus",
    "data",
    "dataset",
    "datasets",
    "detection",
    "detector",
    "embedding",
    "embeddings",
    "evaluation",
    "experiment",
    "experiments",
    "extraction",
    "framework",
    "gene",
    "genes",
    "graph",
    "graphs",
    "method",
    "methods",
    "metric",
    "metrics",
    "model",
    "models",
    "network",
    "networks",
    "optimization",
    "prediction",
    "process",
    "processes",
    "protein",
    "proteins",
    "recognition",
    "regression",
    "relation",
    "relations",
    "retrieval",
    "sample",
    "samples",
    "sequence",
    "sequences",
    "simulation",
    "simulations",
    "species",
    "tagging",
    "task",
    "tasks",
    "temperature",
    "treatment",
    "treatments",
    "variable",
    "variables",
}

NGRAM_BLOCKLIST = {
    "this paper",
    "this study",
    "the paper",
    "the study",
    "our approach",
    "our method",
    "we propose",
    "we present",
    "we show",
}

NGRAM_BOUNDARY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "using",
    "via",
    "we",
    "with",
}

NGRAM_INTERNAL_STOPWORDS = NGRAM_BOUNDARY_STOPWORDS | {
    "after",
    "also",
    "between",
    "can",
    "during",
    "into",
    "than",
    "then",
    "these",
    "those",
    "was",
    "were",
}


def extract_entity_candidates_from_store(
    db_path: str | Path,
    *,
    output_path: str | Path | None = None,
    max_candidates: int = 500,
    max_source_spans: int = 5000,
    min_count: int = 1,
    profile: str = "regex",
) -> dict[str, object]:
    candidate_profile = _normalize_profile(profile)
    candidates = _candidate_records(
        _iter_evidence_rows(Path(db_path), limit=max_source_spans),
        min_count=max(1, int(min_count)),
        profile=candidate_profile,
    )
    candidates = candidates[: max(0, int(max_candidates))]
    if output_path is not None:
        _write_jsonl(Path(output_path), candidates)
    type_counts: dict[str, int] = {}
    for candidate in candidates:
        entity_type = str(candidate.get("entity_type", ""))
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
    return {
        "db_path": str(Path(db_path)),
        "output_path": str(Path(output_path)) if output_path is not None else "",
        "candidates": len(candidates),
        "type_counts": type_counts,
        "max_source_spans": int(max_source_spans),
        "min_count": int(min_count),
        "profile": candidate_profile,
    }


def extract_entity_candidates_from_jsonl(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    text_field: str = "source_text",
    id_field: str = "record_id",
    max_candidates: int = 500,
    min_count: int = 1,
    profile: str = "regex",
) -> dict[str, object]:
    candidate_profile = _normalize_profile(profile)
    source_rows = list(_iter_jsonl_text_rows(Path(input_path), text_field=text_field, id_field=id_field))
    candidates = _candidate_records(
        source_rows,
        min_count=max(1, int(min_count)),
        profile=candidate_profile,
    )
    candidates = candidates[: max(0, int(max_candidates))]
    if output_path is not None:
        _write_jsonl(Path(output_path), candidates)
    type_counts: dict[str, int] = {}
    for candidate in candidates:
        entity_type = str(candidate.get("entity_type", ""))
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
    return {
        "input_path": str(Path(input_path)),
        "output_path": str(Path(output_path)) if output_path is not None else "",
        "source_rows": len(source_rows),
        "candidates": len(candidates),
        "type_counts": type_counts,
        "text_field": text_field,
        "id_field": id_field,
        "min_count": int(min_count),
        "profile": candidate_profile,
    }


def _candidate_records(
    rows: Iterable[dict[str, Any]],
    *,
    min_count: int,
    profile: str = "regex",
) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    candidate_profile = _normalize_profile(profile)
    for row in rows:
        text = str(row.get("text", ""))
        evidence_id = str(row.get("evidence_id", ""))
        for surface, entity_type in _extract_candidate_mentions(text, profile=candidate_profile):
            normalized = _normalize_entity(surface)
            if not normalized:
                continue
            key = (entity_type, normalized)
            record = by_key.setdefault(
                key,
                {
                    "entity_type": entity_type,
                    "surface_form": surface,
                    "normalized": normalized,
                    "count": 0,
                    "evidence_ids": [],
                    "quotes": [],
                    "source": "regex",
                },
            )
            record["count"] = int(record["count"]) + 1
            evidence_ids = list(record["evidence_ids"])
            if evidence_id and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
                record["evidence_ids"] = evidence_ids[:10]
            quotes = list(record["quotes"])
            if evidence_id and len(quotes) < 5:
                quotes.append({"evidence_id": evidence_id, "text": text})
                record["quotes"] = quotes

    records = [
        {
            "entity_id": f"{entity_type}:{_safe_entity_id(normalized)}",
            **record,
        }
        for (entity_type, normalized), record in by_key.items()
        if int(record["count"]) >= min_count
    ]
    records.sort(
        key=lambda item: (
            -int(item.get("count", 0)),
            str(item.get("entity_type", "")),
            str(item.get("normalized", "")),
        )
    )
    return records


def _extract_candidate_mentions(text: str, *, profile: str = "regex") -> Iterable[tuple[str, str]]:
    candidate_profile = _normalize_profile(profile)
    seen: set[tuple[str, str]] = set()
    for match in _SCIENTIFIC_NAME_RE.finditer(text):
        surface = _clean_surface(match.group(1))
        if surface.split(" ", 1)[0] in COMMON_NON_GENUS_WORDS:
            continue
        item = (surface, "scientific_name")
        if _valid_surface(surface) and item not in seen:
            seen.add(item)
            yield item
    for match in _ACRONYM_RE.finditer(text):
        surface = _clean_surface(match.group(1))
        item = (surface, "acronym")
        if _valid_surface(surface, min_length=3) and item not in seen:
            seen.add(item)
            yield item
    for match in _CAPITALIZED_PHRASE_RE.finditer(text):
        surface = _clean_surface(match.group(1))
        item = (surface, "named_phrase")
        if _valid_surface(surface, min_length=4) and item not in seen:
            seen.add(item)
            yield item
    if candidate_profile == "scientific-ngram":
        for surface in _extract_scientific_ngrams(text):
            item = (surface, "scientific_keyphrase")
            if _valid_surface(surface, min_length=5) and item not in seen:
                seen.add(item)
                yield item


def _extract_scientific_ngrams(text: str) -> Iterable[str]:
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        tokens = [match.group(0) for match in _NGRAM_TOKEN_RE.finditer(sentence)]
        if len(tokens) < 2:
            continue
        for ngram_size in range(2, min(5, len(tokens)) + 1):
            for start in range(0, len(tokens) - ngram_size + 1):
                phrase_tokens = tokens[start : start + ngram_size]
                surface = _clean_surface(" ".join(phrase_tokens))
                if _valid_scientific_ngram(surface, phrase_tokens):
                    yield surface


def _valid_scientific_ngram(surface: str, tokens: list[str]) -> bool:
    normalized = _normalize_entity(surface)
    if normalized in NGRAM_BLOCKLIST:
        return False
    if len(normalized) < 5 or len(normalized) > 90:
        return False
    lowered = [token.lower() for token in tokens]
    if lowered[0] in NGRAM_BOUNDARY_STOPWORDS or lowered[-1] in NGRAM_BOUNDARY_STOPWORDS:
        return False
    if all(token in NGRAM_INTERNAL_STOPWORDS for token in lowered):
        return False
    if any(token in DEFAULT_ENTITY_STOPWORDS for token in tokens):
        return False
    if re.search(r"\b(?:we|our|paper|study)\b", normalized):
        return False
    alpha_tokens = [token for token in lowered if re.search(r"[a-z]", token)]
    if len(alpha_tokens) < 2:
        return False
    technical_signal = any(token in TECHNICAL_HEAD_TERMS for token in lowered)
    technical_signal = technical_signal or any(re.search(r"(tion|sion|ment|ness|ance|ence|ity|ing|ive|al|ic)$", token) for token in lowered)
    technical_signal = technical_signal or any(re.search(r"[0-9-]", token) for token in tokens)
    technical_signal = technical_signal or any(token.isupper() and len(token) >= 3 for token in tokens)
    return technical_signal


def _valid_surface(surface: str, *, min_length: int = 2) -> bool:
    value = surface.strip()
    if len(value) < min_length:
        return False
    if value in DEFAULT_ENTITY_STOPWORDS:
        return False
    if value.lower() in {item.lower() for item in DEFAULT_ENTITY_STOPWORDS}:
        return False
    return bool(re.search(r"[A-Za-z]", value))


def _normalize_entity(surface: str) -> str:
    return re.sub(r"\s+", " ", surface.strip()).lower()


def _safe_entity_id(value: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return safe or "unknown"


def _clean_surface(surface: str) -> str:
    value = re.sub(r"\s+", " ", surface.strip(" \t\r\n.,;:()[]{}"))
    return value.strip()


def _iter_evidence_rows(db_path: Path, *, limit: int) -> Iterable[dict[str, Any]]:
    row_limit = max(0, int(limit))
    sql = "select evidence_id, title, section, section_kind, text from evidence_spans order by evidence_id"
    params: tuple[Any, ...] = ()
    if row_limit > 0:
        sql += " limit ?"
        params = (row_limit,)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute(sql, params):
            yield dict(row)


def _iter_jsonl_text_rows(path: Path, *, text_field: str, id_field: str) -> Iterable[dict[str, Any]]:
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        text = str(payload.get(text_field, "") or "")
        if not text.strip():
            continue
        row_id = str(payload.get(id_field, "") or f"row-{index}")
        yield {"evidence_id": row_id, "text": text}


def _write_jsonl(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_profile(profile: str) -> str:
    value = str(profile or "regex").strip().lower()
    if value not in ENTITY_CANDIDATE_PROFILES:
        choices = ", ".join(sorted(ENTITY_CANDIDATE_PROFILES))
        raise ValueError(f"unsupported entity candidate profile: {profile!r}; expected one of {choices}")
    return value


_SCIENTIFIC_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}\s+[a-z][a-z-]{2,})(?:\s+(?:subsp\.|var\.)\s+[a-z-]{2,})?\b")
_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9-]{2,})\b")
_CAPITALIZED_PHRASE_RE = re.compile(
    r"\b([A-Z][a-z][A-Za-z-]+(?:\s+(?:of|and|for|in|with|the|[A-Z][a-z][A-Za-z-]+)){1,5})\b"
)
_NGRAM_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9-]*\b")
_SENTENCE_SPLIT_RE = re.compile(r"[\r\n.!?;:()\[\]{}]+")
