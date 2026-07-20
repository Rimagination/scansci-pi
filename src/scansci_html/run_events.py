"""Small AG-UI-compatible event vocabulary used by ScanSci transports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


RUN_STARTED = "RUN_STARTED"
RUN_FINISHED = "RUN_FINISHED"
RUN_ERROR = "RUN_ERROR"
STEP_STARTED = "STEP_STARTED"
STEP_FINISHED = "STEP_FINISHED"
TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
CUSTOM = "CUSTOM"


def new_run_id() -> str:
    return f"run-{uuid4().hex}"


def new_message_id() -> str:
    return f"msg-{uuid4().hex}"


def event(event_type: str, *, run_id: str, **payload: Any) -> dict[str, Any]:
    """Create a stable event envelope while keeping AG-UI field names."""

    return {
        "type": str(event_type),
        "event_id": f"evt-{uuid4().hex}",
        "runId": str(run_id),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        **payload,
    }

