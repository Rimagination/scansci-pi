from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


LABEL_YES = "yes"
LABEL_NO = "no"
LABEL_INSUFFICIENT = "insufficient"
LABEL_UNKNOWN = "unknown"
LABEL_ERROR = "error"
LABEL_TEXT = "text"


YES_GOLD = {"yes", "y", "true"}
NO_GOLD = {"no", "n", "false"}
INSUFFICIENT_GOLD = {
    "insufficient information",
    "not enough information",
    "unknown",
    "cannot determine",
    "can't determine",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Score MiniRAG LiHua-World answer CSV outputs.")
    parser.add_argument("--input", required=True, help="MiniRAG output CSV with Question, Gold Answer, and answer column.")
    parser.add_argument("--query-csv", help="Optional original LiHua-World query_set.csv to join Evidence/Type.")
    parser.add_argument("--answer-column", default="minirag", help="Prediction column name. Default: minirag.")
    parser.add_argument("--output-prefix", help="Output path prefix. Defaults to input path without suffix + .score")
    parser.add_argument("--max-answer-chars", type=int, default=260, help="Answer preview length in markdown.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if args.output_prefix:
        output_prefix = Path(args.output_prefix)
    else:
        output_prefix = input_path.with_suffix("")
        output_prefix = output_prefix.with_name(output_prefix.name + ".score")
    query_meta = _read_query_meta(Path(args.query_csv)) if args.query_csv else {}
    rows = _read_rows(input_path)

    scored_rows = []
    for index, row in enumerate(rows, start=1):
        question = row.get("Question", "")
        gold_answer = row.get("Gold Answer", "")
        model_answer = row.get(args.answer_column, "")
        meta = query_meta.get(question, {})
        result = score_answer(question=question, gold_answer=gold_answer, model_answer=model_answer)
        scored_rows.append(
            {
                "index": index,
                "question": question,
                "gold_answer": gold_answer,
                "predicted_answer": result["predicted_answer"],
                "prediction_label": result["prediction_label"],
                "gold_label": result["gold_label"],
                "score_status": result["score_status"],
                "is_correct": result["is_correct"],
                "reason": result["reason"],
                "type": meta.get("Type", row.get("Type", "")),
                "evidence": meta.get("Evidence", row.get("Evidence", "")),
                "model_answer": model_answer,
            }
        )

    summary = summarize(scored_rows)
    payload = {
        "input": str(input_path),
        "answer_column": args.answer_column,
        "summary": summary,
        "rows": scored_rows,
    }

    json_path = _with_appended_extension(output_prefix, ".json")
    csv_path = _with_appended_extension(output_prefix, ".csv")
    md_path = _with_appended_extension(output_prefix, ".md")
    _write_json(json_path, payload)
    _write_csv(csv_path, scored_rows)
    _write_markdown(md_path, payload, max_answer_chars=max(args.max_answer_chars, 80))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {json_path}")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    return 0


def score_answer(*, question: str, gold_answer: str, model_answer: str) -> dict[str, Any]:
    gold_label = classify_gold(gold_answer)
    prediction_label, predicted_answer, reason = classify_prediction(question, model_answer)

    if prediction_label == LABEL_ERROR:
        return {
            "gold_label": gold_label,
            "prediction_label": prediction_label,
            "predicted_answer": predicted_answer,
            "score_status": "error",
            "is_correct": False,
            "reason": reason,
        }

    if gold_label in {LABEL_YES, LABEL_NO, LABEL_INSUFFICIENT}:
        is_correct = prediction_label == gold_label
        score_status = "correct" if is_correct else "incorrect"
    else:
        normalized_gold = normalize_text(gold_answer)
        normalized_answer = normalize_text(model_answer)
        if normalized_gold and normalized_gold == normalized_answer:
            is_correct = True
            score_status = "correct"
        elif normalized_gold and normalized_gold in normalized_answer:
            is_correct = True
            score_status = "contains_gold"
        else:
            is_correct = False
            score_status = "needs_judge"

    return {
        "gold_label": gold_label,
        "prediction_label": prediction_label,
        "predicted_answer": predicted_answer,
        "score_status": score_status,
        "is_correct": is_correct,
        "reason": reason,
    }


def _with_appended_extension(prefix: Path, extension: str) -> Path:
    return prefix.with_name(prefix.name + extension)


def classify_gold(gold_answer: str) -> str:
    normalized = normalize_text(gold_answer)
    if normalized in YES_GOLD:
        return LABEL_YES
    if normalized in NO_GOLD:
        return LABEL_NO
    if normalized in INSUFFICIENT_GOLD:
        return LABEL_INSUFFICIENT
    return LABEL_TEXT


def classify_prediction(question: str, answer: str) -> tuple[str, str, str]:
    if not str(answer or "").strip():
        return LABEL_ERROR, "Error", "empty answer"

    normalized = normalize_text(answer)
    if normalized == "error" or "traceback" in normalized or "error in minirag answer" in normalized:
        return LABEL_ERROR, "Error", "explicit error answer"

    first_window = _first_window(answer)
    conclusion = _conclusion_window(answer)
    joined = normalize_text(" ".join([first_window, conclusion]))

    if _has_insufficient_signal(joined):
        return LABEL_INSUFFICIENT, "Insufficient information", "insufficient-information phrase in answer"

    yes_score, yes_reason = _yes_score(joined)
    no_score, no_reason = _no_score(joined)

    if yes_score > no_score and yes_score > 0:
        return LABEL_YES, "Yes", yes_reason
    if no_score > yes_score and no_score > 0:
        return LABEL_NO, "No", no_reason

    # A weaker fallback helps verbose answers that state the fact without saying Yes.
    fallback = normalize_text(answer)
    yes_score, yes_reason = _yes_score(fallback)
    no_score, no_reason = _no_score(fallback)
    if yes_score > no_score and yes_score > 0:
        return LABEL_YES, "Yes", yes_reason
    if no_score > yes_score and no_score > 0:
        return LABEL_NO, "No", no_reason

    return LABEL_UNKNOWN, "Unknown", "no reliable yes/no/insufficient signal"


def _yes_score(text: str) -> tuple[int, str]:
    patterns = [
        (r"\byes\b", 4, "explicit yes"),
        (r"\bdid\s+(?:indeed\s+)?(?:send|ask|agree|request|tell|mention|go|watch|invite|thank)\b", 3, "affirmative did-verb"),
        (r"\b(it is|it's|it was|is)\s+(?:clear|evident|true)\s+that\b", 2, "clear-that affirmation"),
        (r"\bappears\s+that\b", 1, "appears-that affirmation"),
        (r"\btherefore\b.*\b(sent|asked|agreed|requested|thanked|came after|before)\b", 3, "therefore affirmative"),
        (r"\b(later|subsequently|afterward|afterwards)\s+(?:agreed|asked|sent|requested|thanked)\b", 3, "later affirmative"),
        (r"\b(?:eventually|later)\b.*\b(?:coordinated|confirmed|agreed|accepted|planned|plans)\b", 3, "eventual agreement"),
        (r"\bconcrete agreement\b.*\b(?:later|confirmed|dinner)\b", 3, "later concrete agreement"),
        (r"\b(sent|asked|agreed|requested|thanked)\b.*\b(before|after|later|prior to)\b", 2, "temporal affirmative"),
        (r"\b(before|after|later|prior to)\b.*\b(sent|asked|agreed|requested|thanked)\b", 2, "temporal affirmative"),
    ]
    return _score_patterns(text, patterns)


def _no_score(text: str) -> tuple[int, str]:
    patterns = [
        (r"\bno\b", 4, "explicit no"),
        (r"\bdid\s+not\s+(?!immediately\b)", 4, "did-not negation"),
        (r"\bdidn't\b", 4, "didn't negation"),
        (r"\bnot\s+(?:ask|asked|send|sent|agree|agreed|request|requested|thank|thanked)\b", 4, "not-verb negation"),
        (r"\bno indication\b", 4, "no-indication negation"),
        (r"\bthere is no\b", 3, "there-is-no negation"),
        (r"\bseparate (?:and unrelated )?events\b", 2, "separate-events negation"),
    ]
    return _score_patterns(text, patterns)


def _score_patterns(text: str, patterns: list[tuple[str, int, str]]) -> tuple[int, str]:
    score = 0
    reasons = []
    for pattern, weight, reason in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            score += weight
            reasons.append(reason)
    return score, "; ".join(reasons)


def _has_insufficient_signal(text: str) -> bool:
    phrases = [
        "insufficient information",
        "not enough information",
        "cannot determine",
        "can't determine",
        "unable to determine",
        "not possible to determine",
    ]
    return any(phrase in text for phrase in phrases)


def _first_window(answer: str) -> str:
    sentences = split_sentences(answer)
    return " ".join(sentences[:2])


def _conclusion_window(answer: str) -> str:
    sentences = split_sentences(answer)
    conclusion_markers = ("therefore", "thus", "so,", "in conclusion", "from these", "based on")
    marked = [sentence for sentence in sentences if normalize_text(sentence).startswith(conclusion_markers)]
    tail = sentences[-3:]
    return " ".join(marked[-2:] + tail)


def split_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", compact) if part.strip()]


def normalize_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .,:;!?\"'")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if row["is_correct"])
    status_counts = Counter(row["score_status"] for row in rows)
    prediction_counts = Counter(row["prediction_label"] for row in rows)
    gold_counts = Counter(row["gold_label"] for row in rows)
    by_type = {}
    for row in rows:
        row_type = row.get("type") or "unknown"
        bucket = by_type.setdefault(row_type, {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += int(bool(row["is_correct"]))
    for bucket in by_type.values():
        bucket["accuracy"] = _ratio(bucket["correct"], bucket["total"])

    return {
        "total": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": _ratio(correct, total),
        "status_counts": dict(sorted(status_counts.items())),
        "prediction_counts": dict(sorted(prediction_counts.items())),
        "gold_counts": dict(sorted(gold_counts.items())),
        "by_type": dict(sorted(by_type.items())),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_query_meta(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row.get("Question", ""): row for row in csv.DictReader(handle)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "index",
        "score_status",
        "is_correct",
        "gold_label",
        "prediction_label",
        "predicted_answer",
        "gold_answer",
        "type",
        "evidence",
        "reason",
        "question",
        "model_answer",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _write_markdown(path: Path, payload: dict[str, Any], *, max_answer_chars: int) -> None:
    summary = payload["summary"]
    lines = [
        "# LiHua-World Answer Score",
        "",
        f"- Input: `{payload['input']}`",
        f"- Answer column: `{payload['answer_column']}`",
        f"- Total: `{summary['total']}`",
        f"- Correct: `{summary['correct']}`",
        f"- Incorrect: `{summary['incorrect']}`",
        f"- Accuracy: `{summary['accuracy']:.3f}`",
        "",
        "## Counts",
        "",
        "```json",
        json.dumps(
            {
                "status_counts": summary["status_counts"],
                "gold_counts": summary["gold_counts"],
                "prediction_counts": summary["prediction_counts"],
                "by_type": summary["by_type"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## Rows",
        "",
        "| # | Type | Gold | Pred | Status | Reason | Question | Answer Preview |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            "| {index} | {type} | {gold} | {pred} | {status} | {reason} | {question} | {answer} |".format(
                index=row["index"],
                type=_md_cell(row.get("type") or ""),
                gold=_md_cell(row["gold_answer"]),
                pred=_md_cell(row["predicted_answer"]),
                status=_md_cell(row["score_status"]),
                reason=_md_cell(row["reason"]),
                question=_md_cell(row["question"]),
                answer=_md_cell(_truncate(row["model_answer"], max_answer_chars)),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _truncate(text: str, max_chars: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _md_cell(text: str) -> str:
    value = str(text or "").replace("\n", " ")
    value = value.replace("|", "\\|")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
