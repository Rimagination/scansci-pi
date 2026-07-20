from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import time
from typing import Any


def apply_text_type_classifier(
    train_gold_path: str | Path,
    predictions_path: str | Path,
    *,
    output_path: str | Path | None = None,
    classifier: str = "char-logreg",
) -> dict[str, object]:
    if classifier != "char-logreg":
        raise ValueError("unsupported IE type classifier: expected char-logreg")
    train_entities = _read_gold_entities(Path(train_gold_path))
    if not train_entities:
        raise ValueError("training gold contains no typed entities")
    prediction_rows = _read_jsonl(Path(predictions_path))

    started = time.perf_counter()
    model = _fit_char_logreg_classifier(train_entities)
    fit_seconds = time.perf_counter() - started

    predict_started = time.perf_counter()
    predicted_texts: list[str] = []
    refs: list[tuple[int, int]] = []
    for row_index, row in enumerate(prediction_rows):
        for entity_index, entity in enumerate(_as_list(row.get("entities"))):
            if not isinstance(entity, dict):
                continue
            text = _entity_text(entity)
            if text:
                predicted_texts.append(text)
                refs.append((row_index, entity_index))
    labels = list(model.predict(predicted_texts)) if predicted_texts else []
    for (row_index, entity_index), label in zip(refs, labels, strict=False):
        entity = prediction_rows[row_index]["entities"][entity_index]
        if isinstance(entity, dict):
            entity["type"] = str(label)
            entity["type_classifier"] = classifier
    predict_seconds = time.perf_counter() - predict_started

    if output_path is not None:
        _write_jsonl(Path(output_path), prediction_rows)
    label_counts = Counter(label for _, label in train_entities)
    predicted_label_counts = Counter(labels)
    return {
        "train_gold_path": str(Path(train_gold_path)),
        "predictions_path": str(Path(predictions_path)),
        "output_path": str(Path(output_path)) if output_path is not None else "",
        "classifier": classifier,
        "train_entities": len(train_entities),
        "train_label_counts": dict(sorted(label_counts.items())),
        "prediction_rows": len(prediction_rows),
        "typed_predictions": len(labels),
        "predicted_label_counts": dict(sorted(predicted_label_counts.items())),
        "fit_seconds": fit_seconds,
        "predict_seconds": predict_seconds,
        "elapsed_seconds": fit_seconds + predict_seconds,
    }


def _fit_char_logreg_classifier(train_entities: list[tuple[str, str]]) -> Any:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
    except Exception as error:  # pragma: no cover - depends on optional local packages
        raise RuntimeError("scikit-learn is required for the char-logreg IE type classifier") from error

    texts = [text for text, _ in train_entities]
    labels = [label for _, label in train_entities]
    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), lowercase=True, min_df=1),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    model.fit(texts, labels)
    return model


def _read_gold_entities(path: Path) -> list[tuple[str, str]]:
    rows = _read_jsonl(path)
    entities: list[tuple[str, str]] = []
    for row in rows:
        for entity in _as_list(row.get("entities")):
            if not isinstance(entity, dict):
                continue
            text = _entity_text(entity)
            label = str(entity.get("type") or entity.get("entity_type") or "").strip()
            if text and label:
                entities.append((text, label))
    return entities


def _entity_text(entity: dict[str, Any]) -> str:
    return str(entity.get("text") or entity.get("surface_form") or entity.get("normalized") or "").strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(dict(json.loads(line)))
    return rows


def _write_jsonl(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
