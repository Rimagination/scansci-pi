"""Durable history for ScanSci's lightweight direct conversations.

Direct chats are intentionally not research runs: they do not have stages,
artifacts, or a worker lifecycle.  They still need a small local history store
so that a completed answer survives navigation and application restarts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4


_MAX_CONVERSATIONS = 200
_MAX_MESSAGES = 32
_MAX_TEXT_LENGTH = 200_000
_MAX_LIST_ITEMS = 100
_MAX_DICT_ITEMS = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = _MAX_TEXT_LENGTH) -> str:
    return str(value or "").strip()[:limit]


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    """Copy JSON-like UI metadata without retaining pasted image payloads."""

    if depth > 6:
        return "…"
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [_bounded_json(item, depth=depth + 1) for item in value[:_MAX_LIST_ITEMS]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_DICT_ITEMS]:
            name = str(key)
            if name in {"data_url", "preview_url", "base64", "content_bytes"}:
                continue
            result[name] = _bounded_json(item, depth=depth + 1)
        return result
    return str(value)[:_MAX_TEXT_LENGTH]


def _message(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role", "") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    result: dict[str, Any] = {
        "role": role,
        "content": _text(raw.get("content", "")),
    }
    for key in (
        "created_at",
        "mode",
        "processing_ms",
        "usage",
        "model",
        "knowledgeScopes",
        "reader_answer",
        "trace",
        "interaction",
        "error",
        "failure",
    ):
        if key in raw and raw[key] is not None:
            result[key] = _bounded_json(raw[key])
    if isinstance(raw.get("skills"), list):
        result["skills"] = _bounded_json(raw["skills"])
    if isinstance(raw.get("sources"), list):
        result["sources"] = _bounded_json(raw["sources"])
    if isinstance(raw.get("images"), list):
        # Keep the durable attachment reference for history previews, but not
        # the potentially multi-megabyte image data URL.  Older versions only
        # kept name/type/size, which made the thumbnail disappear after reload.
        result["images"] = [
            {
                key: _bounded_json(item.get(key))
                for key in ("id", "name", "mime_type", "type", "size", "preview_url")
                if isinstance(item, dict) and item.get(key) is not None
            }
            for item in raw["images"][:_MAX_LIST_ITEMS]
            if isinstance(item, dict)
        ]
    if isinstance(raw.get("audio"), list):
        # Audio bytes are stored outside the history file.  Keep only enough
        # metadata to explain what was attached when the conversation is
        # reopened.
        result["audio"] = [
            {
                key: _bounded_json(item.get(key))
                for key in ("name", "mime_type", "type", "size", "audio_url")
                if isinstance(item, dict) and item.get(key) is not None
            }
            for item in raw["audio"][:_MAX_LIST_ITEMS]
            if isinstance(item, dict)
        ]
    return result


class DirectChatHistoryStore:
    """A bounded, atomic JSON store scoped to the current ScanSci workspace."""

    def __init__(self, workspace: str | Path) -> None:
        workspace_path = Path(workspace).expanduser().resolve()
        self.path = workspace_path.parent / ".scansci-direct-chat-history.json"
        self._lock = threading.RLock()

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # A corrupt history must never prevent the main workspace from
            # opening.  The next successful save will replace it atomically.
            return []
        rows = payload.get("conversations", []) if isinstance(payload, dict) else []
        return [
            row
            for row in rows[:_MAX_CONVERSATIONS]
            if isinstance(row, dict) and str(row.get("conversation_id", "")).strip()
        ]

    def _write_unlocked(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {"version": 1, "conversations": rows[:_MAX_CONVERSATIONS]},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _title(payload: dict[str, Any], messages: list[dict[str, Any]]) -> str:
        supplied = _text(payload.get("title"), 120)
        if supplied:
            return supplied
        for message in messages:
            if message["role"] == "user" and message["content"]:
                return message["content"].splitlines()[0][:120]
        return "直接对话"

    @staticmethod
    def _model(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        for message in reversed(messages):
            if message["role"] == "assistant" and isinstance(message.get("model"), dict):
                return deepcopy(message["model"])
        return None

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        messages = row.get("messages", []) if isinstance(row.get("messages"), list) else []
        preview = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("content"):
                preview = _text(message["content"], 180)
                break
        return {
            "kind": "direct",
            "conversation_id": str(row.get("conversation_id", "")),
            "title": _text(row.get("title"), 120) or "直接对话",
            "preview": preview,
            "created_at": str(row.get("created_at", "") or ""),
            "updated_at": str(row.get("updated_at", "") or ""),
            "message_count": len(messages),
            "session_id": str(row.get("session_id", "") or ""),
            "model": deepcopy(row.get("model")),
            "archived": bool(row.get("archived", False)),
        }

    def list(self, limit: int = 200, *, view: str = "active") -> dict[str, Any]:
        requested_view = str(view or "active").strip().lower()
        if requested_view not in {"active", "archived", "all"}:
            requested_view = "active"
        with self._lock:
            rows = self._read_unlocked()
            rows.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
            if requested_view != "all":
                wanted_archived = requested_view == "archived"
                rows = [row for row in rows if bool(row.get("archived", False)) == wanted_archived]
            return {
                "ok": True,
                "view": requested_view,
                "conversations": [self._summary(row) for row in rows[: max(1, min(_MAX_CONVERSATIONS, int(limit or 200)))]],
            }

    def get(self, conversation_id: str) -> dict[str, Any]:
        wanted = _text(conversation_id, 160)
        with self._lock:
            for row in self._read_unlocked():
                if str(row.get("conversation_id", "")) == wanted:
                    return {"ok": True, **deepcopy(row)}
        raise FileNotFoundError("Direct conversation does not exist")

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Direct conversation payload must be an object")
        conversation_id = _text(payload.get("conversation_id"), 160) or uuid4().hex
        raw_messages = payload.get("messages", [])
        messages = [item for raw in raw_messages[-_MAX_MESSAGES:] if (item := _message(raw)) is not None]
        if not messages:
            raise ValueError("Direct conversation must contain at least one message")
        now = _now()
        with self._lock:
            rows = self._read_unlocked()
            previous = next((row for row in rows if str(row.get("conversation_id", "")) == conversation_id), None)
            row = {
                "kind": "direct",
                "conversation_id": conversation_id,
                "title": self._title(payload, messages),
                "created_at": str((previous or {}).get("created_at", "") or now),
                "updated_at": now,
                "session_id": _text(payload.get("session_id"), 200),
                "messages": messages,
                "model": self._model(messages),
                "archived": False,
            }
            rows = [item for item in rows if str(item.get("conversation_id", "")) != conversation_id]
            rows.insert(0, row)
            self._write_unlocked(rows)
            return {"ok": True, **deepcopy(row)}

    def set_archived(self, conversation_id: str, archived: bool) -> dict[str, Any]:
        wanted = _text(conversation_id, 160)
        with self._lock:
            rows = self._read_unlocked()
            for row in rows:
                if str(row.get("conversation_id", "")) != wanted:
                    continue
                row["archived"] = bool(archived)
                row["updated_at"] = _now()
                self._write_unlocked(rows)
                return {"ok": True, **deepcopy(row)}
        raise FileNotFoundError("Direct conversation does not exist")

    def delete(self, conversation_id: str) -> dict[str, Any]:
        wanted = _text(conversation_id, 160)
        with self._lock:
            rows = self._read_unlocked()
            remaining = [row for row in rows if str(row.get("conversation_id", "")) != wanted]
            if len(remaining) == len(rows):
                raise FileNotFoundError("Direct conversation does not exist")
            self._write_unlocked(remaining)
            return {"ok": True, "conversation_id": wanted}
