from __future__ import annotations

from pathlib import Path

from .models import FetchResponse


class RawHtmlSnapshotter:
    """Write the captured publisher DOM as an evidence snapshot beside clean HTML."""

    def __init__(self, snapshot_dir: str | Path) -> None:
        self.snapshot_dir = Path(snapshot_dir)

    def save(
        self,
        response: FetchResponse,
        *,
        output_path: Path,
        identifier: str,
        doi: str | None,
        title: str,
    ) -> Path:
        del identifier, doi, title
        snapshot_path = self.snapshot_dir / f"{output_path.stem}.raw.html"
        _write_text_atomic(snapshot_path, response.html)
        return snapshot_path


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
