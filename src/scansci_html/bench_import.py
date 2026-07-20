from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


def import_qasper_rows(input_path: str | Path, *, limit: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper in _read_json_records(Path(input_path)):
        paper_id = _clean_id(_first_non_empty(paper.get("id"), paper.get("paper_id"), paper.get("title"), "paper"))
        title = str(paper.get("title", "")).strip()
        for index, (question_value, raw_question_id_value, raw_answer) in enumerate(
            _iter_qasper_questions(paper.get("qas", {}))
        ):
            question = str(question_value).strip()
            if not question:
                continue
            raw_question_id = str(_first_non_empty(raw_question_id_value, f"q{index + 1:04d}")).strip()
            question_id = f"qasper:{paper_id}:{_clean_id(raw_question_id)}"
            answer = _first_qasper_answer(raw_answer)
            unanswerable = bool(answer.get("unanswerable", False))
            evidence_texts = _unique_strings(
                _as_list(answer.get("highlighted_evidence")) or _as_list(answer.get("evidence"))
            )
            evidence_ids = [f"{question_id}.e{evidence_index:04d}" for evidence_index in range(1, len(evidence_texts) + 1)]
            row = {
                "question_id": question_id,
                "question": question,
                "answer_type": "external_qasper",
                "gold_evidence_ids": [] if unanswerable else evidence_ids,
                "required_points": [] if unanswerable else _qasper_required_points(answer),
                "forbidden_points": (
                    ["Do not answer from this corpus; QASPER marks this question unanswerable."]
                    if unanswerable
                    else []
                ),
                "answerable": not unanswerable,
                "annotation_status": "imported",
                "external_source": {
                    "dataset": "qasper",
                    "paper_id": paper_id,
                    "title": title,
                    "question_id": raw_question_id,
                },
                "candidate_evidence": [
                    {
                        "evidence_id": evidence_id,
                        "doc_id": paper_id,
                        "title": title,
                        "text": text,
                    }
                    for evidence_id, text in zip(evidence_ids, evidence_texts, strict=False)
                ],
            }
            rows.append(row)
            if limit > 0 and len(rows) >= limit:
                return rows
    return rows


def import_scifact_rows(
    claims_path: str | Path,
    corpus_path: str | Path,
    *,
    limit: int = 0,
) -> list[dict[str, Any]]:
    corpus = {_clean_id(record.get("doc_id")): record for record in _read_json_records(Path(corpus_path))}
    rows: list[dict[str, Any]] = []
    for claim in _read_json_records(Path(claims_path)):
        claim_id = _clean_id(_first_non_empty(claim.get("id"), len(rows) + 1))
        claim_text = str(claim.get("claim", "")).strip()
        if not claim_text:
            continue
        evidence_groups = _scifact_evidence_groups(claim.get("evidence", {}))
        evidence_ids: list[str] = []
        candidate_evidence: list[dict[str, Any]] = []
        labels: list[str] = []
        for doc_id, group in evidence_groups:
            labels.extend([str(group.get("label", "")).strip().upper()])
            doc = dict(corpus.get(_clean_id(doc_id), {}) or {})
            sentences = _as_list(doc.get("abstract"))
            title = str(doc.get("title", "")).strip()
            for sentence_index in _as_list(group.get("sentences")):
                try:
                    sentence_number = int(sentence_index)
                except (TypeError, ValueError):
                    continue
                if sentence_number < 0 or sentence_number >= len(sentences):
                    continue
                evidence_id = f"scifact:{_clean_id(doc_id)}.s{sentence_number + 1:04d}"
                evidence_ids.append(evidence_id)
                candidate_evidence.append(
                    {
                        "evidence_id": evidence_id,
                        "doc_id": _clean_id(doc_id),
                        "title": title,
                        "sentence_index": sentence_number,
                        "text": str(sentences[sentence_number]).strip(),
                    }
                )
        evidence_ids = _unique_strings(evidence_ids)
        label = next((value for value in labels if value), "")
        answerable = bool(evidence_ids)
        row = {
            "question_id": f"scifact:{claim_id}",
            "question": f"Verify this scientific claim: {claim_text}",
            "answer_type": "external_scifact_claim_verification",
            "gold_evidence_ids": evidence_ids,
            "required_points": [_scifact_required_point(label)] if answerable else [],
            "forbidden_points": [] if answerable else ["Do not support or refute this claim without SciFact evidence."],
            "answerable": answerable,
            "annotation_status": "imported",
            "external_source": {
                "dataset": "scifact",
                "claim_id": claim_id,
                "label": label,
            },
            "candidate_evidence": candidate_evidence,
        }
        rows.append(row)
        if limit > 0 and len(rows) >= limit:
            return rows
    return rows


def import_beir_rows(
    corpus_path: str | Path,
    queries_path: str | Path,
    qrels_path: str | Path,
    *,
    dataset: str = "beir",
    limit: int = 0,
    max_evidence_per_query: int = 0,
    benchmark_split: str = "dev",
) -> list[dict[str, Any]]:
    dataset_id = _clean_id(dataset or "beir")
    answer_type_dataset_id = _answer_type_id(dataset_id)
    corpus = {_clean_id(_beir_record_id(record)): record for record in _read_json_records(Path(corpus_path))}
    queries = _read_beir_queries(Path(queries_path))
    positives_by_query = _read_beir_qrels(Path(qrels_path))
    rows: list[dict[str, Any]] = []
    for raw_query_id, raw_doc_ids in positives_by_query.items():
        query_text = _lookup_by_raw_or_clean(queries, raw_query_id)
        question = str(query_text or "").strip()
        if not question:
            continue
        doc_ids = _unique_strings(raw_doc_ids)
        if max_evidence_per_query > 0:
            doc_ids = doc_ids[: int(max_evidence_per_query)]
        evidence_ids: list[str] = []
        candidate_evidence: list[dict[str, Any]] = []
        for raw_doc_id in doc_ids:
            doc_id = _clean_id(raw_doc_id)
            evidence_id = f"{dataset_id}:{doc_id}.s0001"
            evidence_ids.append(evidence_id)
            record = corpus.get(doc_id, {})
            candidate_evidence.append(
                {
                    "evidence_id": evidence_id,
                    "doc_id": doc_id,
                    "title": _beir_record_title(record),
                    "text": _beir_record_text(record),
                }
            )
        answerable = bool(evidence_ids)
        rows.append(
            {
                "question_id": f"{dataset_id}:{_clean_id(raw_query_id)}",
                "question": question,
                "answer_type": f"external_{answer_type_dataset_id}_document_retrieval",
                "gold_evidence_ids": evidence_ids,
                "required_points": (
                    [f"Retrieve the relevant {dataset_id} document(s) for this query."]
                    if answerable
                    else []
                ),
                "forbidden_points": [] if answerable else ["Do not answer without relevant BEIR evidence."],
                "answerable": answerable,
                "annotation_status": "imported",
                "benchmark_split": benchmark_split,
                "external_source": {
                    "dataset": dataset_id,
                    "format": "beir",
                    "query_id": str(raw_query_id),
                    "positive_doc_ids": [_clean_id(doc_id) for doc_id in doc_ids],
                    "benchmark_split": benchmark_split,
                },
                "candidate_evidence": candidate_evidence,
            }
        )
        if limit > 0 and len(rows) >= limit:
            return rows
    return rows


def import_scierc_ie_rows(
    input_path: str | Path,
    *,
    limit: int = 0,
    benchmark_split: str = "dev",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in _read_json_records(Path(input_path)):
        doc_key = str(_first_non_empty(record.get("doc_key"), record.get("doc_id"), record.get("id"), len(rows) + 1))
        sentence_tokens = [
            [str(token) for token in _as_list(sentence)]
            for sentence in _as_list(record.get("sentences"))
            if isinstance(sentence, list)
        ]
        flat_tokens = [token for sentence in sentence_tokens for token in sentence]
        entities: list[dict[str, Any]] = []
        entity_by_span: dict[tuple[int, int], dict[str, Any]] = {}
        for raw_entity in _iter_annotation_items(record.get("ner")):
            parsed_entity = _parse_scierc_entity(raw_entity, flat_tokens)
            if not parsed_entity:
                continue
            span_key = (int(parsed_entity["start_token"]), int(parsed_entity["end_token"]))
            if span_key in entity_by_span:
                continue
            entity_by_span[span_key] = parsed_entity
            entities.append(parsed_entity)

        relations: list[dict[str, Any]] = []
        for raw_relation in _iter_annotation_items(record.get("relations")):
            parsed_relation = _parse_scierc_relation(raw_relation, flat_tokens, entity_by_span)
            if parsed_relation:
                relations.append(parsed_relation)

        rows.append(
            {
                "record_id": f"scierc:{_clean_id(doc_key)}",
                "paper_id": doc_key,
                "answer_type": "external_scierc_information_extraction",
                "benchmark_task": "entity_relation_extraction",
                "source_text": _join_scierc_sentences(sentence_tokens),
                "entities": entities,
                "relations": relations,
                "annotation_status": "imported",
                "benchmark_split": benchmark_split,
                "external_source": {
                    "dataset": "scierc",
                    "format": "dygiepp",
                    "doc_key": doc_key,
                    "benchmark_split": benchmark_split,
                },
            }
        )
        if limit > 0 and len(rows) >= limit:
            return rows
    return rows


def import_scienceie_rows(
    input_path: str | Path,
    *,
    limit: int = 0,
    benchmark_split: str = "dev",
) -> list[dict[str, Any]]:
    root = Path(input_path)
    text_paths = [root] if root.is_file() and root.suffix.lower() == ".txt" else sorted(root.glob("*.txt"))
    rows: list[dict[str, Any]] = []
    for text_path in text_paths:
        doc_id = text_path.stem
        source_text = text_path.read_text(encoding="utf-8-sig")
        ann_path = text_path.with_suffix(".ann")
        entities_by_id: dict[str, dict[str, Any]] = {}
        relation_specs: list[dict[str, str]] = []
        if ann_path.exists():
            for raw_line in ann_path.read_text(encoding="utf-8-sig").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("T"):
                    entity = _parse_brat_entity(line, source_text)
                    if entity:
                        entities_by_id[str(entity["entity_id"])] = entity
                elif line.startswith("R"):
                    relation = _parse_brat_relation(line)
                    if relation:
                        relation_specs.append(relation)
        entities = list(entities_by_id.values())
        relations = [
            _scienceie_relation_record(relation, entities_by_id)
            for relation in relation_specs
            if relation.get("head_id") in entities_by_id and relation.get("tail_id") in entities_by_id
        ]
        rows.append(
            {
                "record_id": f"scienceie:{_clean_id(doc_id)}",
                "paper_id": doc_id,
                "answer_type": "external_scienceie_information_extraction",
                "benchmark_task": "entity_relation_extraction",
                "source_text": source_text,
                "entities": entities,
                "relations": relations,
                "annotation_status": "imported",
                "benchmark_split": benchmark_split,
                "external_source": {
                    "dataset": "scienceie",
                    "format": "brat",
                    "doc_id": doc_id,
                    "benchmark_split": benchmark_split,
                },
            }
        )
        if limit > 0 and len(rows) >= limit:
            return rows
    return rows


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] == "[":
        payload = json.loads(stripped)
        return [dict(record) for record in payload]
    if stripped[0] == "{":
        lines = [line for line in text.splitlines() if line.strip()]
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return [dict(json.loads(line)) for line in lines]
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return [dict(record) for record in payload["data"]]
        if _is_record_mapping(payload):
            records: list[dict[str, Any]] = []
            for record_id, record in payload.items():
                normalized = dict(record)
                normalized.setdefault("id", record_id)
                records.append(normalized)
            return records
        return [dict(payload)]
    return [dict(json.loads(line)) for line in text.splitlines() if line.strip()]


def _parse_scierc_entity(raw_entity: list[Any], flat_tokens: list[str]) -> dict[str, Any]:
    if len(raw_entity) < 3:
        return {}
    start = _int_or_none(raw_entity[0])
    end = _int_or_none(raw_entity[1])
    label = str(raw_entity[2]).strip()
    if start is None or end is None or not label:
        return {}
    text = _token_span_text(flat_tokens, start, end)
    if not text:
        return {}
    return {
        "text": text,
        "type": label,
        "start_token": start,
        "end_token": end,
    }


def _parse_scierc_relation(
    raw_relation: list[Any],
    flat_tokens: list[str],
    entity_by_span: dict[tuple[int, int], dict[str, Any]],
) -> dict[str, Any]:
    if len(raw_relation) < 5:
        return {}
    head_start = _int_or_none(raw_relation[0])
    head_end = _int_or_none(raw_relation[1])
    tail_start = _int_or_none(raw_relation[2])
    tail_end = _int_or_none(raw_relation[3])
    label = str(raw_relation[4]).strip()
    if None in {head_start, head_end, tail_start, tail_end} or not label:
        return {}
    assert head_start is not None
    assert head_end is not None
    assert tail_start is not None
    assert tail_end is not None
    head = entity_by_span.get((head_start, head_end), {})
    tail = entity_by_span.get((tail_start, tail_end), {})
    head_text = str(head.get("text") or _token_span_text(flat_tokens, head_start, head_end)).strip()
    tail_text = str(tail.get("text") or _token_span_text(flat_tokens, tail_start, tail_end)).strip()
    if not head_text or not tail_text:
        return {}
    return {
        "head": head_text,
        "tail": tail_text,
        "type": label,
        "head_start_token": head_start,
        "head_end_token": head_end,
        "tail_start_token": tail_start,
        "tail_end_token": tail_end,
    }


def _parse_brat_entity(line: str, source_text: str) -> dict[str, Any]:
    parts = line.split("\t")
    if len(parts) < 2:
        return {}
    entity_id = parts[0].strip()
    metadata = parts[1].strip()
    mention = parts[2].strip() if len(parts) >= 3 else ""
    metadata_parts = metadata.split(maxsplit=1)
    if len(metadata_parts) != 2:
        return {}
    label, offsets_text = metadata_parts
    offsets = [int(value) for value in re.findall(r"\d+", offsets_text)]
    if len(offsets) < 2:
        return {}
    start_char = offsets[0]
    end_char = offsets[-1]
    if not mention and 0 <= start_char <= end_char <= len(source_text):
        mention = source_text[start_char:end_char]
    if not entity_id or not label or not mention:
        return {}
    return {
        "entity_id": entity_id,
        "text": mention,
        "type": label,
        "start_char": start_char,
        "end_char": end_char,
    }


def _parse_brat_relation(line: str) -> dict[str, str]:
    parts = line.split("\t")
    if len(parts) < 2:
        return {}
    relation_id = parts[0].strip()
    fields = parts[1].split()
    if len(fields) < 3:
        return {}
    relation_type = fields[0].strip()
    args: dict[str, str] = {}
    for field in fields[1:]:
        if ":" not in field:
            continue
        name, value = field.split(":", 1)
        args[name] = value
    head_id = args.get("Arg1", "")
    tail_id = args.get("Arg2", "")
    if not relation_id or not relation_type or not head_id or not tail_id:
        return {}
    return {
        "relation_id": relation_id,
        "type": relation_type,
        "head_id": head_id,
        "tail_id": tail_id,
    }


def _scienceie_relation_record(
    relation: dict[str, str],
    entities_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    head_id = relation["head_id"]
    tail_id = relation["tail_id"]
    return {
        "relation_id": relation["relation_id"],
        "head": str(entities_by_id[head_id].get("text", "")),
        "tail": str(entities_by_id[tail_id].get("text", "")),
        "type": relation["type"],
        "head_id": head_id,
        "tail_id": tail_id,
    }


def _iter_annotation_items(value: Any) -> list[list[Any]]:
    if _looks_like_annotation_item(value):
        return [list(value)]
    items: list[list[Any]] = []
    if isinstance(value, list):
        for item in value:
            items.extend(_iter_annotation_items(item))
    return items


def _looks_like_annotation_item(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 3:
        return False
    return _int_or_none(value[0]) is not None and _int_or_none(value[1]) is not None


def _token_span_text(flat_tokens: list[str], start: int, end: int) -> str:
    if start < 0 or end < start or start >= len(flat_tokens):
        return ""
    return _join_tokens(flat_tokens[start : min(end + 1, len(flat_tokens))])


def _join_scierc_sentences(sentence_tokens: list[list[str]]) -> str:
    return " ".join(_join_tokens(sentence) for sentence in sentence_tokens if sentence).strip()


def _join_tokens(tokens: list[str]) -> str:
    text = ""
    no_space_before = {".", ",", ";", ":", "!", "?", "%", ")", "]", "}"}
    no_space_after = {"(", "[", "{"}
    for token in tokens:
        if not text:
            text = token
        elif token in no_space_before or text[-1:] in no_space_after:
            text += token
        else:
            text += f" {token}"
    return text


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_record_mapping(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if any(key in payload for key in ("id", "paper_id", "qas", "claim", "doc_id")):
        return False
    return all(isinstance(value, dict) for value in payload.values())


def _read_beir_queries(path: Path) -> dict[str, str]:
    queries: dict[str, str] = {}
    for record in _read_json_records(path):
        query_id = _beir_record_id(record)
        query_text = _first_non_empty(record.get("text"), record.get("query"), record.get("question"))
        if not str(query_id).strip() or not str(query_text).strip():
            continue
        queries[str(query_id).strip()] = str(query_text).strip()
        queries.setdefault(_clean_id(query_id), str(query_text).strip())
    return queries


def _read_beir_qrels(path: Path) -> dict[str, list[str]]:
    positives_by_query: dict[str, list[str]] = {}
    header: list[str] | None = None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if _looks_like_beir_qrels_header(parts):
            header = [_normalize_header_name(part) for part in parts]
            continue
        query_id, doc_id, score = _parse_beir_qrel_parts(parts, header)
        if not query_id or not doc_id or not _positive_qrel_score(score):
            continue
        positives_by_query.setdefault(query_id, [])
        if doc_id not in positives_by_query[query_id]:
            positives_by_query[query_id].append(doc_id)
    return positives_by_query


def _parse_beir_qrel_parts(parts: list[str], header: list[str] | None) -> tuple[str, str, str]:
    if header:
        query_index = _header_index(header, ["query-id", "queryid", "query", "qid"], 0)
        doc_index = _header_index(header, ["corpus-id", "corpusid", "doc-id", "docid", "document-id"], 1)
        score_index = _header_index(header, ["score", "relevance", "label"], 2)
        return (
            _part_at(parts, query_index),
            _part_at(parts, doc_index),
            _part_at(parts, score_index, "1"),
        )
    if len(parts) >= 4 and parts[1].upper() in {"0", "Q0"}:
        return parts[0], parts[2], parts[3]
    return _part_at(parts, 0), _part_at(parts, 1), _part_at(parts, 2, "1")


def _looks_like_beir_qrels_header(parts: list[str]) -> bool:
    normalized = {_normalize_header_name(part) for part in parts}
    query_names = {"query-id", "queryid", "query", "qid"}
    doc_names = {"corpus-id", "corpusid", "doc-id", "docid", "document-id"}
    return bool(normalized.intersection(query_names)) and bool(normalized.intersection(doc_names))


def _normalize_header_name(value: Any) -> str:
    return str(value).strip().lower().replace("_", "-")


def _header_index(header: list[str], names: list[str], default: int) -> int:
    for name in names:
        if name in header:
            return header.index(name)
    return default


def _part_at(parts: list[str], index: int, default: str = "") -> str:
    if index < 0 or index >= len(parts):
        return default
    return str(parts[index]).strip()


def _positive_qrel_score(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"true", "yes", "relevant"}


def _lookup_by_raw_or_clean(values: dict[str, str], raw_id: Any) -> str:
    raw_key = str(raw_id).strip()
    return values.get(raw_key) or values.get(_clean_id(raw_key)) or ""


def _beir_record_id(record: dict[str, Any]) -> Any:
    return _first_non_empty(
        record.get("_id"),
        record.get("id"),
        record.get("doc_id"),
        record.get("corpus_id"),
        record.get("query_id"),
        record.get("qid"),
    )


def _beir_record_title(record: dict[str, Any]) -> str:
    return str(_first_non_empty(record.get("title"), record.get("name"), "")).strip()


def _beir_record_text(record: dict[str, Any]) -> str:
    value = _first_non_empty(
        record.get("text"),
        record.get("contents"),
        record.get("abstract"),
        record.get("body"),
    )
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _answer_type_id(value: str) -> str:
    text = "".join(character if character.isalnum() else "_" for character in value.strip())
    text = "_".join(part for part in text.split("_") if part)
    return text or "beir"


def _iter_qasper_questions(qas: Any) -> list[tuple[Any, Any, Any]]:
    if isinstance(qas, dict):
        questions = _as_list(qas.get("question"))
        question_ids = _as_list(qas.get("question_id"))
        answers = _as_list(qas.get("answers"))
        return [
            (question, _nth(question_ids, index, f"q{index + 1:04d}"), _nth(answers, index, {}))
            for index, question in enumerate(questions)
        ]
    entries: list[tuple[Any, Any, Any]] = []
    for index, raw_entry in enumerate(_as_list(qas)):
        if not isinstance(raw_entry, dict):
            continue
        answers = _as_list(raw_entry.get("answers"))
        entries.append(
            (
                raw_entry.get("question", ""),
                _first_non_empty(raw_entry.get("question_id"), f"q{index + 1:04d}"),
                _nth(answers, 0, {}),
            )
        )
    return entries


def _first_qasper_answer(raw_answer: Any) -> dict[str, Any]:
    answer_container = dict(raw_answer or {}) if isinstance(raw_answer, dict) else {}
    answers = _as_list(answer_container.get("answer"))
    if answers:
        first = answers[0]
        return dict(first or {}) if isinstance(first, dict) else {}
    return answer_container


def _qasper_required_points(answer: dict[str, Any]) -> list[str]:
    for field in ("free_form_answer", "extractive_spans"):
        values = _unique_strings(_as_list(answer.get(field)))
        if values:
            return values
    if answer.get("yes_no") is True:
        return ["Yes."]
    if answer.get("yes_no") is False:
        return ["No."]
    return ["Answer must be supported by the imported QASPER evidence."]


def _scifact_evidence_groups(evidence: Any) -> list[tuple[str, dict[str, Any]]]:
    groups: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(evidence, dict):
        return groups
    for doc_id, raw_groups in evidence.items():
        for raw_group in _as_list(raw_groups):
            if isinstance(raw_group, dict):
                groups.append((str(doc_id), dict(raw_group)))
    return groups


def _scifact_required_point(label: str) -> str:
    normalized = label.upper()
    if normalized in {"SUPPORT", "SUPPORTS", "SUPPORTED"}:
        return "The claim is supported by the cited SciFact rationale."
    if normalized in {"CONTRADICT", "CONTRADICTS", "REFUTE", "REFUTES", "REFUTED"}:
        return "The claim is refuted by the cited SciFact rationale."
    return "The answer must use the cited SciFact rationale and preserve the SciFact label."


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _nth(values: list[Any], index: int, default: Any) -> Any:
    return values[index] if index < len(values) else default


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ""


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _clean_id(value: Any) -> str:
    text = str(value).strip()
    safe = "".join(character if character.isalnum() or character in {"-", "_", "."} else "-" for character in text)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "unknown"
