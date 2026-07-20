from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import time
from typing import Any


DEFAULT_KEYPHRASE_MODEL = "ml6team/keyphrase-extraction-kbir-semeval2017"


def extract_ie_model_candidates_from_jsonl(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    model_name: str = DEFAULT_KEYPHRASE_MODEL,
    cache_dir: str | Path | None = None,
    text_field: str = "source_text",
    id_field: str = "record_id",
    max_rows: int = 0,
    max_candidates: int = 0,
    batch_size: int = 4,
    device: str = "auto",
    aggregation_strategy: str = "simple",
    min_score: float = 0.0,
    entity_type: str = "Keyphrase",
    pipeline_factory: Callable[..., Any] | None = None,
) -> dict[str, object]:
    source_rows = _read_jsonl_text_rows(Path(input_path), text_field=text_field, id_field=id_field, limit=max_rows)
    started = time.perf_counter()
    classifier = _build_token_classifier(
        model_name,
        cache_dir=cache_dir,
        device=device,
        aggregation_strategy=aggregation_strategy,
        pipeline_factory=pipeline_factory,
    )
    model_load_seconds = time.perf_counter() - started

    inference_started = time.perf_counter()
    prediction_rows: list[dict[str, object]] = []
    predicted_entities = 0
    total_limit = max(0, int(max_candidates or 0))
    for batch in _batched(source_rows, size=max(1, int(batch_size))):
        if total_limit and predicted_entities >= total_limit:
            break
        texts = [str(row.get("text", "")) for row in batch]
        outputs = _as_batch_outputs(classifier(texts, batch_size=max(1, int(batch_size))))
        for source_row, output in zip(batch, outputs, strict=False):
            if total_limit and predicted_entities >= total_limit:
                break
            entities: list[dict[str, object]] = []
            seen: set[tuple[str, int | None, int | None]] = set()
            for item in output:
                if total_limit and predicted_entities >= total_limit:
                    break
                entity = _model_output_to_entity(
                    item,
                    entity_type=entity_type,
                    min_score=min_score,
                )
                if entity is None:
                    continue
                key = (
                    _normalize_mention(entity.get("text")),
                    _optional_int(entity.get("start_char")),
                    _optional_int(entity.get("end_char")),
                )
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                entities.append(entity)
                predicted_entities += 1
            prediction_rows.append(
                {
                    "record_id": source_row.get("record_id", ""),
                    "source": "transformers-token-classification",
                    "model_name": model_name,
                    "entities": entities,
                }
            )

    inference_seconds = time.perf_counter() - inference_started
    elapsed_seconds = time.perf_counter() - started
    if output_path is not None:
        _write_jsonl(Path(output_path), prediction_rows)
    return {
        "input_path": str(Path(input_path)),
        "output_path": str(Path(output_path)) if output_path is not None else "",
        "model_name": model_name,
        "cache_dir": str(Path(cache_dir)) if cache_dir is not None else "",
        "source_rows": len(source_rows),
        "prediction_rows": len(prediction_rows),
        "documents_with_predictions": sum(1 for row in prediction_rows if row.get("entities")),
        "predicted_entities": predicted_entities,
        "model_load_seconds": model_load_seconds,
        "inference_seconds": inference_seconds,
        "elapsed_seconds": elapsed_seconds,
        "seconds_per_document": inference_seconds / len(source_rows) if source_rows else 0.0,
        "batch_size": max(1, int(batch_size)),
        "device": device,
        "aggregation_strategy": aggregation_strategy,
        "min_score": float(min_score),
        "entity_type": entity_type,
        "max_rows": int(max_rows),
        "max_candidates": int(max_candidates),
    }


def _build_token_classifier(
    model_name: str,
    *,
    cache_dir: str | Path | None,
    device: str,
    aggregation_strategy: str,
    pipeline_factory: Callable[..., Any] | None,
) -> Any:
    if pipeline_factory is None:
        try:
            from transformers import pipeline
        except Exception as error:  # pragma: no cover - depends on optional local packages
            raise RuntimeError(
                "transformers is required for ie-model-candidates; install the optional model dependencies first"
            ) from error
        pipeline_factory = pipeline
    kwargs: dict[str, object] = {
        "task": "token-classification",
        "model": model_name,
        "aggregation_strategy": aggregation_strategy,
        "device": _resolve_device(device),
    }
    if cache_dir is not None:
        kwargs["cache_dir"] = str(Path(cache_dir))
    return pipeline_factory(**kwargs)


def _resolve_device(device: str) -> int:
    normalized = str(device or "auto").strip().lower()
    if normalized in {"cpu", "-1"}:
        return -1
    if normalized in {"cuda", "gpu", "0"}:
        return 0
    if normalized != "auto":
        return int(normalized)
    try:
        import torch

        return 0 if torch.cuda.is_available() else -1
    except Exception:  # pragma: no cover - depends on optional local packages
        return -1


def _read_jsonl_text_rows(path: Path, *, text_field: str, id_field: str, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    row_limit = max(0, int(limit or 0))
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if row_limit and len(rows) >= row_limit:
            break
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        text = str(payload.get(text_field, "") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "record_id": str(payload.get(id_field, "") or f"row-{index}"),
                "text": text,
            }
        )
    return rows


def _model_output_to_entity(item: dict[str, Any], *, entity_type: str, min_score: float) -> dict[str, object] | None:
    score = float(item.get("score", 0.0) or 0.0)
    if score < float(min_score):
        return None
    surface = _clean_surface(item.get("word") or item.get("text") or "")
    if not _valid_surface(surface):
        return None
    return {
        "text": surface,
        "type": entity_type or _clean_surface(item.get("entity_group") or item.get("entity") or "Keyphrase"),
        "model_label": _clean_surface(item.get("entity_group") or item.get("entity") or ""),
        "score": score,
        "start_char": _optional_int(item.get("start")),
        "end_char": _optional_int(item.get("end")),
    }


def _as_batch_outputs(value: Any) -> list[list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [[]]
    if not value:
        return []
    if all(isinstance(item, dict) for item in value):
        return [value]
    outputs: list[list[dict[str, Any]]] = []
    for item in value:
        if isinstance(item, list):
            outputs.append([dict(entity) for entity in item if isinstance(entity, dict)])
        else:
            outputs.append([])
    return outputs


def _batched(rows: list[dict[str, object]], *, size: int) -> list[list[dict[str, object]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _write_jsonl(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _clean_surface(value: Any) -> str:
    text = str(value or "")
    text = text.replace(" ##", "")
    text = re.sub(r"\s+", " ", text.strip(" \t\r\n.,;:()[]{}"))
    return text.strip()


def _valid_surface(surface: str) -> bool:
    value = surface.strip()
    if len(value) < 2:
        return False
    if not re.search(r"[A-Za-z]", value):
        return False
    if value.lower() in {"abstract", "introduction", "method", "methods", "results", "discussion", "conclusion"}:
        return False
    return True


def _normalize_mention(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text)
    return text


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
