from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any


def evaluate_ie_entities(
    gold_path: str | Path,
    predictions_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    gold_entities = list(_iter_gold_entities(_read_jsonl(Path(gold_path))))
    predicted_entities = list(_iter_prediction_entities(_read_jsonl(Path(predictions_path))))
    gold_untyped = Counter(_entity_key(entity) for entity in gold_entities if _entity_key(entity))
    pred_untyped = Counter(_entity_key(entity) for entity in predicted_entities if _entity_key(entity))
    gold_typed = Counter(_typed_entity_key(entity) for entity in gold_entities if _typed_entity_key(entity))
    pred_typed = Counter(_typed_entity_key(entity) for entity in predicted_entities if _typed_entity_key(entity))

    entity_matches = _counter_overlap(gold_untyped, pred_untyped)
    typed_entity_matches = _counter_overlap(gold_typed, pred_typed)
    payload: dict[str, object] = {
        "gold_path": str(Path(gold_path)),
        "predictions_path": str(Path(predictions_path)),
        "output_path": str(Path(output_path)) if output_path is not None else "",
        "gold_entities": sum(gold_untyped.values()),
        "predicted_entities": sum(pred_untyped.values()),
        "entity_matches": entity_matches,
        **_precision_recall_f1(
            entity_matches,
            predicted=sum(pred_untyped.values()),
            gold=sum(gold_untyped.values()),
            prefix="entity",
        ),
        "typed_gold_entities": sum(gold_typed.values()),
        "typed_predicted_entities": sum(pred_typed.values()),
        "typed_entity_matches": typed_entity_matches,
        **_precision_recall_f1(
            typed_entity_matches,
            predicted=sum(pred_typed.values()),
            gold=sum(gold_typed.values()),
            prefix="typed_entity",
        ),
    }
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(dict(json.loads(line)))
    return rows


def _iter_gold_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in rows:
        for entity in _as_list(row.get("entities")):
            if isinstance(entity, dict):
                entities.append(entity)
    return entities


def _iter_prediction_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row.get("entities"), list):
            for entity in _as_list(row.get("entities")):
                if isinstance(entity, dict):
                    entities.append(entity)
        else:
            entities.append(row)
    return entities


def _entity_key(entity: dict[str, Any]) -> str:
    return _normalize_mention(_first_non_empty(entity.get("text"), entity.get("surface_form"), entity.get("normalized")))


def _typed_entity_key(entity: dict[str, Any]) -> tuple[str, str] | None:
    text = _entity_key(entity)
    entity_type = _normalize_type(_first_non_empty(entity.get("type"), entity.get("entity_type"), entity.get("label")))
    if not text or not entity_type:
        return None
    return (text, entity_type)


def _normalize_mention(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text)
    return text


def _normalize_type(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _counter_overlap(left: Counter[Any], right: Counter[Any]) -> int:
    return sum((left & right).values())


def _precision_recall_f1(matches: int, *, predicted: int, gold: int, prefix: str) -> dict[str, float]:
    precision = matches / predicted if predicted else 0.0
    recall = matches / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        f"{prefix}_precision": precision,
        f"{prefix}_recall": recall,
        f"{prefix}_f1": f1,
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ""
