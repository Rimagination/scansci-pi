from __future__ import annotations

from pathlib import Path
import zipfile
from typing import Any

import requests

from .bench_import import _clean_id


BEIR_DATASET_URL_TEMPLATE = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"


def fetch_beir_dataset(
    dataset: str,
    output_dir: str | Path,
    *,
    url: str = "",
    force: bool = False,
    timeout: float = 120.0,
    session: Any | None = None,
) -> dict[str, object]:
    dataset_id = _clean_id(dataset).lower()
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir = resolved_output_dir / dataset_id
    zip_path = resolved_output_dir / f"{dataset_id}.zip"
    resolved_url = str(url or BEIR_DATASET_URL_TEMPLATE.format(dataset=dataset_id))

    downloaded = False
    extracted = False
    if force or not _looks_like_beir_dataset(dataset_dir):
        if force or not zip_path.exists():
            _download_file(resolved_url, zip_path, timeout=timeout, session=session)
            downloaded = True
        _safe_extract_zip(zip_path, resolved_output_dir)
        extracted = True

    data_path = _resolve_beir_data_path(resolved_output_dir, dataset_id)
    payload = inspect_beir_dataset(data_path, dataset=dataset_id)
    payload.update(
        {
            "dataset": dataset_id,
            "url": resolved_url,
            "zip_path": str(zip_path),
            "output_dir": str(resolved_output_dir),
            "downloaded": downloaded,
            "extracted": extracted,
        }
    )
    return payload


def inspect_beir_dataset(data_path: str | Path, *, dataset: str = "beir") -> dict[str, object]:
    root = Path(data_path)
    qrels_paths = _beir_qrels_paths(root)
    corpus_path = root / "corpus.jsonl"
    queries_path = root / "queries.jsonl"
    ready = corpus_path.exists() and queries_path.exists() and bool(qrels_paths)
    default_qrels_path = qrels_paths.get("test") or next(iter(qrels_paths.values()), "")
    return {
        "dataset": _clean_id(dataset).lower(),
        "data_path": str(root),
        "corpus_path": str(corpus_path) if corpus_path.exists() else "",
        "queries_path": str(queries_path) if queries_path.exists() else "",
        "qrels_paths": qrels_paths,
        "default_qrels_path": str(default_qrels_path),
        "ready": ready,
        "import_command": _beir_import_command(root, dataset, default_qrels_path) if ready else "",
    }


def _download_file(url: str, output_path: Path, *, timeout: float, session: Any | None) -> None:
    active_session = session or requests.Session()
    response = active_session.get(url, stream=True, timeout=timeout)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> None:
    resolved_output_dir = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target_path = (output_dir / member.filename).resolve()
            if not _is_relative_to(target_path, resolved_output_dir):
                raise ValueError(f"zip member escapes output directory: {member.filename}")
        archive.extractall(output_dir)


def _resolve_beir_data_path(output_dir: Path, dataset_id: str) -> Path:
    dataset_dir = output_dir / dataset_id
    if _looks_like_beir_dataset(dataset_dir):
        return dataset_dir
    if _looks_like_beir_dataset(output_dir):
        return output_dir
    for child in sorted(path for path in output_dir.iterdir() if path.is_dir()):
        if _looks_like_beir_dataset(child):
            return child
    return dataset_dir


def _looks_like_beir_dataset(path: Path) -> bool:
    return (path / "corpus.jsonl").exists() and (path / "queries.jsonl").exists() and bool(_beir_qrels_paths(path))


def _beir_qrels_paths(root: Path) -> dict[str, str]:
    qrels_dir = root / "qrels"
    if not qrels_dir.exists():
        return {}
    paths: dict[str, str] = {}
    for path in sorted(qrels_dir.glob("*.tsv")):
        split = path.stem.strip().lower() or "qrels"
        paths[split] = str(path)
    return paths


def _beir_import_command(root: Path, dataset: str, qrels_path: str | Path) -> str:
    dataset_id = _clean_id(dataset).lower()
    return (
        "scansci bench-import beir "
        f"--corpus {root / 'corpus.jsonl'} "
        f"--queries {root / 'queries.jsonl'} "
        f"--qrels {qrels_path} "
        f"--dataset-name {dataset_id} "
        f"--output bench/gold_questions.external.{dataset_id}.jsonl"
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
