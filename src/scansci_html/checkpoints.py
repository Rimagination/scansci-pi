"""File-level checkpoints for reversible Agent edits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4


class CheckpointError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    root: str
    turn_id: str
    label: str
    created_at: str
    files: tuple[str, ...]
    conversation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "scansci.checkpoint.v1",
            "checkpoint_id": self.checkpoint_id,
            "root": self.root,
            "turn_id": self.turn_id,
            "label": self.label,
            "created_at": self.created_at,
            "files": list(self.files),
            "conversation": self.conversation,
        }


class CheckpointStore:
    """Store snapshots below ``<workspace>/.scansci/checkpoints`` only."""

    def __init__(self, root: str | Path) -> None:
        candidate = Path(root).resolve()
        self.root = candidate if candidate.is_dir() else candidate.parent
        self.base = self.root / ".scansci" / "checkpoints"

    def _inside(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise CheckpointError(f"Path is outside checkpoint root: {resolved}") from error
        return resolved

    def _checkpoint_dir(self, checkpoint_id: str) -> Path:
        value = str(checkpoint_id or "").strip()
        if not value or Path(value).name != value or value in {".", ".."}:
            raise CheckpointError("Invalid checkpoint id")
        directory = (self.base / value).resolve()
        try:
            directory.relative_to(self.base.resolve())
        except ValueError as error:
            raise CheckpointError("Invalid checkpoint directory") from error
        return directory

    def begin(
        self,
        *,
        turn_id: str = "",
        label: str = "",
        conversation: Mapping[str, Any] | None = None,
    ) -> Checkpoint:
        checkpoint_id = f"cp-{uuid4().hex}"
        directory = self._checkpoint_dir(checkpoint_id)
        (directory / "files").mkdir(parents=True, exist_ok=False)
        metadata = {
            "schema_version": "scansci.checkpoint.v1",
            "checkpoint_id": checkpoint_id,
            "root": str(self.root),
            "turn_id": str(turn_id or ""),
            "label": str(label or "")[:200],
            "created_at": _now(),
            "files": {},
            "conversation": bool(conversation is not None),
        }
        (directory / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if conversation is not None:
            (directory / "conversation.json").write_text(json.dumps(dict(conversation), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self._read_checkpoint(checkpoint_id)

    def _read_metadata(self, checkpoint_id: str) -> dict[str, Any]:
        path = self._checkpoint_dir(checkpoint_id) / "metadata.json"
        if not path.is_file():
            raise CheckpointError(f"Checkpoint not found: {checkpoint_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_metadata(self, checkpoint_id: str, metadata: Mapping[str, Any]) -> None:
        path = self._checkpoint_dir(checkpoint_id) / "metadata.json"
        path.write_text(json.dumps(dict(metadata), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _read_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        metadata = self._read_metadata(checkpoint_id)
        return Checkpoint(
            checkpoint_id=str(metadata["checkpoint_id"]),
            root=str(metadata["root"]),
            turn_id=str(metadata.get("turn_id", "")),
            label=str(metadata.get("label", "")),
            created_at=str(metadata.get("created_at", "")),
            files=tuple(sorted(str(item) for item in dict(metadata.get("files", {}) or {}))),
            conversation=bool(metadata.get("conversation", False)),
        )

    def capture(self, checkpoint_id: str, path: str | Path) -> Checkpoint:
        target = self._inside(path)
        if not target.is_file():
            raise CheckpointError(f"Only existing files can be captured: {target}")
        metadata = self._read_metadata(checkpoint_id)
        relative = target.relative_to(self.root).as_posix()
        snapshot_name = f"files/{relative}"
        snapshot = self._checkpoint_dir(checkpoint_id) / snapshot_name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, snapshot)
        files = dict(metadata.get("files", {}) or {})
        files[relative] = {"snapshot": snapshot_name, "sha256": _sha256(target.read_bytes()), "bytes": target.stat().st_size}
        metadata["files"] = files
        self._write_metadata(checkpoint_id, metadata)
        return self._read_checkpoint(checkpoint_id)

    def capture_many(self, checkpoint_id: str, paths: list[str | Path]) -> Checkpoint:
        for path in paths:
            self.capture(checkpoint_id, path)
        return self._read_checkpoint(checkpoint_id)

    def restore(self, checkpoint_id: str, *, mode: str = "code") -> dict[str, Any]:
        if mode not in {"code", "conversation", "both"}:
            raise CheckpointError("mode must be code, conversation, or both")
        metadata = self._read_metadata(checkpoint_id)
        restored: list[str] = []
        if mode in {"code", "both"}:
            for relative, info in dict(metadata.get("files", {}) or {}).items():
                target = self._inside(relative)
                snapshot = self._checkpoint_dir(checkpoint_id) / str(dict(info).get("snapshot", ""))
                if not snapshot.is_file():
                    raise CheckpointError(f"Snapshot is missing: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot, target)
                restored.append(relative)
        conversation: dict[str, Any] | None = None
        if mode in {"conversation", "both"} and bool(metadata.get("conversation", False)):
            conversation_path = self._checkpoint_dir(checkpoint_id) / "conversation.json"
            conversation = json.loads(conversation_path.read_text(encoding="utf-8")) if conversation_path.is_file() else None
        return {"checkpoint_id": checkpoint_id, "mode": mode, "restored_files": restored, "conversation": conversation}

    def fork(self, checkpoint_id: str, *, label: str = "") -> Checkpoint:
        source = self._checkpoint_dir(checkpoint_id)
        if not source.is_dir():
            raise CheckpointError(f"Checkpoint not found: {checkpoint_id}")
        target_id = f"cp-{uuid4().hex}"
        target = self._checkpoint_dir(target_id)
        shutil.copytree(source, target)
        metadata = self._read_metadata(target_id)
        metadata["checkpoint_id"] = target_id
        metadata["label"] = str(label or metadata.get("label", ""))[:200]
        metadata["parent_checkpoint_id"] = checkpoint_id
        self._write_metadata(target_id, metadata)
        return self._read_checkpoint(target_id)

    def list(self) -> list[Checkpoint]:
        if not self.base.is_dir():
            return []
        checkpoints: list[Checkpoint] = []
        for directory in sorted(self.base.iterdir()):
            if directory.is_dir() and (directory / "metadata.json").is_file():
                try:
                    checkpoints.append(self._read_checkpoint(directory.name))
                except (CheckpointError, json.JSONDecodeError, KeyError):
                    continue
        return checkpoints


__all__ = ["Checkpoint", "CheckpointError", "CheckpointStore"]
