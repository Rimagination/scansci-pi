from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from .models import SaveResult
from .service import save_clean_html


class BrokerService:
    """File-queue broker that keeps one browser fetcher alive across requests."""

    def __init__(
        self,
        *,
        broker_dir: str | Path,
        output_dir: str | Path,
        fetcher: object,
        source_fetchers: list[object] | None = None,
        snapshotter: object | None = None,
        min_text_length: int = 500,
        download_assets: bool = False,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.broker_dir = Path(broker_dir)
        self.output_dir = Path(output_dir)
        self.fetcher = fetcher
        self.source_fetchers = list(source_fetchers or [])
        self.snapshotter = snapshotter
        self.min_text_length = int(min_text_length)
        self.download_assets = bool(download_assets)
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        _ensure_dirs(self.broker_dir)

    def process_once(self) -> bool:
        request_path = _next_request_path(self.broker_dir)
        if request_path is None:
            return False
        running_path = _claim_request(request_path, self.broker_dir)
        request = _read_json(running_path)
        request_id = str(request.get("id") or running_path.stem)
        identifier = str(request.get("identifier") or "").strip()
        payload = self._process_identifier(identifier)
        payload["request_id"] = request_id
        _write_json_atomic(_response_path(self.broker_dir, request_id), payload)
        running_path.unlink(missing_ok=True)
        return True

    def run_forever(self, *, stop_file: str | Path | None = None) -> None:
        stop_path = Path(stop_file) if stop_file else self.broker_dir / "stop"
        while not stop_path.exists():
            if not self.process_once():
                time.sleep(self.poll_interval_seconds)

    def _process_identifier(self, identifier: str) -> dict[str, object]:
        if not identifier:
            return {
                "status": "fetch_error",
                "identifier": identifier,
                "doi": None,
                "title": "",
                "source_url": "",
                "output_path": "",
                "snapshot_path": "",
                "warnings": [],
                "error": "empty identifier",
                "structure": {},
            }
        try:
            result = save_clean_html(
                identifier,
                output_dir=self.output_dir,
                fetcher=self.fetcher,
                source_fetchers=self.source_fetchers,
                auth_fetcher=None,
                snapshotter=self.snapshotter,
                min_text_length=self.min_text_length,
                download_assets=self.download_assets,
            )
        except Exception as exc:
            return {
                "status": "fetch_error",
                "identifier": identifier,
                "doi": None,
                "title": "",
                "source_url": "",
                "output_path": "",
                "snapshot_path": "",
                "warnings": [],
                "error": f"{type(exc).__name__}: {exc}",
                "structure": {},
            }
        return save_result_payload(result)


def enqueue_request(broker_dir: str | Path, identifier: str) -> str:
    root = Path(broker_dir)
    _ensure_dirs(root)
    request_id = uuid.uuid4().hex
    _write_json_atomic(
        root / "requests" / f"{request_id}.json",
        {
            "id": request_id,
            "identifier": identifier,
            "created_at": time.time(),
        },
    )
    return request_id


def read_response(broker_dir: str | Path, request_id: str) -> dict[str, object] | None:
    path = _response_path(Path(broker_dir), request_id)
    if not path.exists():
        return None
    return _read_json(path)


def wait_for_response(
    broker_dir: str | Path,
    request_id: str,
    *,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 0.5,
) -> dict[str, object] | None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while time.monotonic() <= deadline:
        response = read_response(broker_dir, request_id)
        if response is not None:
            return response
        time.sleep(max(0.1, float(poll_interval_seconds)))
    return None


def save_result_payload(result: SaveResult) -> dict[str, object]:
    return {
        "status": result.status,
        "identifier": result.identifier,
        "doi": result.doi,
        "title": result.title,
        "source_url": result.source_url,
        "output_path": str(result.output_path) if result.output_path else "",
        "snapshot_path": str(result.snapshot_path) if result.snapshot_path else "",
        "warnings": list(result.warnings),
        "error": result.error,
        "structure": dict(result.structure),
    }


def _ensure_dirs(root: Path) -> None:
    for name in ("requests", "running", "responses"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _next_request_path(root: Path) -> Path | None:
    requests_dir = root / "requests"
    if not requests_dir.exists():
        return None
    return next(iter(sorted(requests_dir.glob("*.json"))), None)


def _claim_request(request_path: Path, root: Path) -> Path:
    running_path = root / "running" / request_path.name
    request_path.replace(running_path)
    return running_path


def _response_path(root: Path, request_id: str) -> Path:
    return root / "responses" / f"{request_id}.json"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
