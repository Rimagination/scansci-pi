"""Explicit, serialisable task contracts for Agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any


TASK_CONTRACT_SCHEMA = "scansci.task-contract.v1"


def _items(value: Any, *, limit: int = 32) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = []
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))[:limit]


@dataclass(frozen=True)
class TaskContract:
    goal: str
    request: str = ""
    output_format: str = "text"
    constraints: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    pause_policy: str = "pause only when a missing user choice changes the result"
    success_criteria: tuple[str, ...] = ()
    contract_id: str = ""
    version: str = TASK_CONTRACT_SCHEMA
    extra: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        request: str = "",
        task_mode: str = "general",
    ) -> "TaskContract":
        raw = dict(payload or {})
        clean_request = re.sub(r"\s+", " ", str(request or "")).strip()
        goal = str(raw.get("goal") or clean_request or "Complete the requested task").strip()[:1200]
        mode = str(task_mode or "general")
        required = _items(raw.get("required_evidence"))
        if not required and any(part in mode.split("+") for part in ("research", "verified-answer", "benchmark")):
            required = ("source-grounded claims", "distinguish metadata from full text")
        contract_id = str(raw.get("contract_id") or "").strip()
        if not contract_id:
            digest = hashlib.sha256(f"{mode}\n{goal}".encode("utf-8")).hexdigest()[:12]
            contract_id = f"task-{digest}"
        known = {
            "contract_id", "goal", "request", "output_format", "constraints", "required_evidence",
            "allowed_tools", "pause_policy", "success_criteria", "version",
        }
        extra = {key: value for key, value in raw.items() if key not in known}
        return cls(
            goal=goal,
            request=clean_request,
            output_format=str(raw.get("output_format") or "text").strip()[:120],
            constraints=_items(raw.get("constraints")),
            required_evidence=required,
            allowed_tools=_items(raw.get("allowed_tools")),
            pause_policy=str(raw.get("pause_policy") or cls.pause_policy).strip()[:300],
            success_criteria=_items(raw.get("success_criteria"), limit=12),
            contract_id=contract_id,
            version=str(raw.get("version") or TASK_CONTRACT_SCHEMA),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.extra)
        payload.update({
            "schema_version": self.version,
            "contract_id": self.contract_id,
            "goal": self.goal,
            "request": self.request,
            "output_format": self.output_format,
            "constraints": list(self.constraints),
            "required_evidence": list(self.required_evidence),
            "allowed_tools": list(self.allowed_tools),
            "pause_policy": self.pause_policy,
            "success_criteria": list(self.success_criteria),
        })
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))

    def prompt_block(self) -> str:
        lines = [
            f"Task contract {self.contract_id}: {self.goal}",
            f"Output format: {self.output_format}.",
            f"Pause policy: {self.pause_policy}.",
        ]
        if self.constraints:
            lines.append("Constraints: " + "; ".join(self.constraints) + ".")
        if self.required_evidence:
            lines.append("Required evidence: " + "; ".join(self.required_evidence) + ".")
        if self.allowed_tools:
            lines.append("Allowed tools: " + ", ".join(self.allowed_tools) + ".")
        if self.success_criteria:
            lines.append("Success criteria: " + "; ".join(self.success_criteria) + ".")
        return "\n".join(lines)


__all__ = ["TASK_CONTRACT_SCHEMA", "TaskContract"]
