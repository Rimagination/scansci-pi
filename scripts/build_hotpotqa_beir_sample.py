from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATASET_NAME = "hotpotqa-distractor-small"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a HotpotQA distractor JSON sample into BEIR-style corpus/queries/qrels files."
    )
    parser.add_argument("--input", required=True, help="HotpotQA distractor JSON path.")
    parser.add_argument("--output-dir", required=True, help="Output directory for BEIR-style files.")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME, help="Dataset name written to manifest.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum questions to convert; 0 converts all.")
    parser.add_argument("--split", default="dev", help="Qrels split filename stem, e.g. dev or test.")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    records = _records_from_payload(payload)
    if not isinstance(records, list):
        raise SystemExit("HotpotQA input must be a JSON list or an object with a data list.")

    converted = convert_hotpotqa_records(records, limit=max(int(args.limit), 0))
    output_dir = Path(args.output_dir)
    qrels_dir = output_dir / "qrels"
    qrels_dir.mkdir(parents=True, exist_ok=True)

    corpus_path = output_dir / "corpus.jsonl"
    queries_path = output_dir / "queries.jsonl"
    qrels_path = qrels_dir / f"{args.split}.tsv"
    manifest_path = output_dir / "manifest.json"

    _write_jsonl(corpus_path, converted["corpus"])
    _write_jsonl(queries_path, converted["queries"])
    qrels_path.write_text(_qrels_tsv(converted["qrels"]), encoding="utf-8")

    manifest = {
        "dataset": args.dataset_name,
        "format": "beir",
        "source_format": "hotpotqa_distractor",
        "source_input": str(Path(args.input)),
        "official_source_url": "https://hotpotqa.github.io/",
        "official_dev_url": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
        "mirror_url": "https://huggingface.co/datasets/namlh2004/hotpotqa",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": int(args.limit),
        "questions": len(converted["queries"]),
        "documents": len(converted["corpus"]),
        "positive_qrels": len(converted["qrels"]),
        "retrieval_scope": "distractor-context documents",
        "gold_granularity": "supporting-fact titles mapped to paragraph-level documents",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def convert_hotpotqa_records(records: list[dict[str, Any]], *, limit: int) -> dict[str, list[dict[str, Any]]]:
    corpus: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    qrels: list[dict[str, Any]] = []
    converted_questions = 0

    for record in records:
        question = str(record.get("question", "")).strip()
        raw_question_id = str(record.get("_id") or record.get("id") or converted_questions + 1).strip()
        if not question or not raw_question_id:
            continue

        query_id = _clean_id(raw_question_id)
        context_docs: list[tuple[str, str, str]] = []
        for index, item in enumerate(_iter_context_items(record.get("context")), start=1):
            title, sentences = _parse_context_item(item)
            text = " ".join(sentence.strip() for sentence in sentences if sentence.strip())
            if not text:
                continue
            doc_id = f"{query_id}-doc-{index:02d}"
            context_docs.append((doc_id, title, text))
            corpus.append({"_id": doc_id, "title": title, "text": text})

        support_titles = _support_titles(record.get("supporting_facts"))
        positive_doc_ids = [doc_id for doc_id, title, _ in context_docs if title.strip().lower() in support_titles]
        if not positive_doc_ids:
            continue

        queries.append({"_id": query_id, "text": question})
        for doc_id in dict.fromkeys(positive_doc_ids):
            qrels.append({"query-id": query_id, "corpus-id": doc_id, "score": 1})

        converted_questions += 1
        if limit > 0 and converted_questions >= limit:
            break

    return {"corpus": corpus, "queries": queries, "qrels": qrels}


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [dict(entry.get("row", entry)) for entry in payload["rows"] if isinstance(entry, dict)]
    records = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise SystemExit("HotpotQA input must be a JSON list, an object with data, or a HuggingFace rows response.")
    return [dict(record) for record in records if isinstance(record, dict)]


def _iter_context_items(context: Any) -> list[Any]:
    if isinstance(context, dict):
        titles = _as_list(context.get("title"))
        sentence_groups = _as_list(context.get("sentences"))
        return [[title, sentences] for title, sentences in zip(titles, sentence_groups, strict=False)]
    return _as_list(context)


def _support_titles(supporting_facts: Any) -> set[str]:
    if isinstance(supporting_facts, dict):
        return {str(title).strip().lower() for title in _as_list(supporting_facts.get("title")) if str(title).strip()}
    return {
        str(fact[0]).strip().lower()
        for fact in _as_list(supporting_facts)
        if isinstance(fact, list) and fact and str(fact[0]).strip()
    }


def _parse_context_item(item: Any) -> tuple[str, list[str]]:
    if isinstance(item, list) and len(item) >= 2:
        title = str(item[0]).strip()
        sentences = [str(sentence) for sentence in _as_list(item[1])]
        return title, sentences
    if isinstance(item, dict):
        title = str(item.get("title", "")).strip()
        sentences = [str(sentence) for sentence in _as_list(item.get("sentences") or item.get("text"))]
        return title, sentences
    return "", []


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _qrels_tsv(rows: list[dict[str, Any]]) -> str:
    lines = ["query-id\tcorpus-id\tscore"]
    lines.extend(f"{row['query-id']}\t{row['corpus-id']}\t{row['score']}" for row in rows)
    return "\n".join(lines) + "\n"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    output = []
    last_was_dash = False
    for character in text:
        if character.isalnum():
            output.append(character)
            last_was_dash = False
        elif not last_was_dash:
            output.append("-")
            last_was_dash = True
    return "".join(output).strip("-") or "item"


if __name__ == "__main__":
    raise SystemExit(main())
