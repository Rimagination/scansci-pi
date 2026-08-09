"""Explicit, serialisable task contracts for Agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any


TASK_CONTRACT_SCHEMA = "scansci.task-contract.v2"
TASK_CONTRACT_VERSION = 2
LEGACY_TASK_CONTRACT_SCHEMAS = frozenset({"scansci.task-contract.v1"})
_CONTRACT_SCHEMA_VERSIONS = {
    "scansci.task-contract.v1": 1,
    TASK_CONTRACT_SCHEMA: TASK_CONTRACT_VERSION,
}
_AUTHORITY_FIELDS = frozenset({
    "allowed_tools",
    "initial_tools",
    "allowed_mcp_servers",
    "allow_external_write",
    "autonomy",
    "capability_lease",
    "initial_tool_budget",
    "max_model_token_budget",
    "max_tool_budget",
    "model_token_budget",
    "recovery_budget",
    "required_tool_groups",
    "requires_plan",
    "risk_level",
})


def _contract_version(raw: Mapping[str, Any]) -> tuple[bool, int, str]:
    """Validate a serialized v1/v2 declaration without coercing bad input.

    A serialized contract must carry at least one exact supported declaration,
    and when both are present they must agree.  In particular, booleans, floats,
    whitespace, and arbitrary objects are never coerced into an
    authority-bearing version.
    """

    schema_present = "schema_version" in raw
    version_present = "version" in raw
    if not schema_present and not version_present:
        return False, 0, "missing schema_version and version"

    schema_version: int | None = None
    if schema_present:
        schema = raw.get("schema_version")
        if not isinstance(schema, str) or schema not in _CONTRACT_SCHEMA_VERSIONS:
            return False, 0, "unknown or malformed schema_version"
        schema_version = _CONTRACT_SCHEMA_VERSIONS[schema]

    declared_version: int | None = None
    if version_present:
        version = raw.get("version")
        if type(version) is int and version in (1, 2):
            declared_version = version
        elif isinstance(version, str) and version in {"1", "2"}:
            declared_version = int(version)
        else:
            return False, 0, "unknown or malformed version"

    if schema_version is not None and declared_version is not None and schema_version != declared_version:
        return False, 0, "schema_version and version conflict"
    resolved = schema_version if schema_version is not None else declared_version
    return True, int(resolved or 1), ""


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
    initial_tools: tuple[str, ...] = ()
    pause_policy: str = "pause only when a missing user choice changes the result"
    success_criteria: tuple[str, ...] = ()
    contract_id: str = ""
    version: str = TASK_CONTRACT_SCHEMA
    source_contract_valid: bool = True
    source_contract_error: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)
    _allowed_tools_present: bool = field(default=False, compare=False, repr=False)
    _initial_tools_present: bool = field(default=False, compare=False, repr=False)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        request: str = "",
        task_mode: str = "general",
    ) -> "TaskContract":
        raw = dict(payload or {})
        source_contract_valid, _source_version, source_contract_error = _contract_version(raw)
        if "source_contract_valid" in raw and raw.get("source_contract_valid") is not True:
            source_contract_valid = False
            source_contract_error = str(
                raw.get("source_contract_error") or "upstream contract was invalid"
            )
        allowed_tools_present = source_contract_valid and "allowed_tools" in raw
        initial_tools_present = source_contract_valid and "initial_tools" in raw
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
            "allowed_tools", "initial_tools", "pause_policy", "success_criteria", "version", "schema_version",
            "source_contract_valid", "source_contract_error",
        }
        extra = {
            key: value
            for key, value in raw.items()
            if key not in known and (source_contract_valid or key not in _AUTHORITY_FIELDS)
        }
        return cls(
            goal=goal,
            request=clean_request,
            output_format=str(raw.get("output_format") or "text").strip()[:120],
            constraints=_items(raw.get("constraints")),
            required_evidence=required,
            allowed_tools=_items(raw.get("allowed_tools")) if source_contract_valid else (),
            # A legacy v1 payload had no initial activation subset.  Reading
            # it preserves its authority while migrating the old behaviour
            # into an explicit v2 initial subset.  An omitted hard lease stays
            # omitted and must never be interpreted as an allow-all value.
            initial_tools=_items(
                raw.get("initial_tools")
                if initial_tools_present
                else raw.get("allowed_tools") if allowed_tools_present else None
            ),
            pause_policy=str(raw.get("pause_policy") or cls.pause_policy).strip()[:300],
            success_criteria=_items(raw.get("success_criteria"), limit=12),
            contract_id=contract_id,
            version=TASK_CONTRACT_SCHEMA,
            source_contract_valid=source_contract_valid,
            source_contract_error=source_contract_error,
            extra=extra,
            _allowed_tools_present=allowed_tools_present,
            _initial_tools_present=initial_tools_present or allowed_tools_present,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.extra)
        payload.update({
            "schema_version": TASK_CONTRACT_SCHEMA,
            "version": TASK_CONTRACT_VERSION,
            "source_contract_valid": self.source_contract_valid,
            "contract_id": self.contract_id,
            "goal": self.goal,
            "request": self.request,
            "output_format": self.output_format,
            "constraints": list(self.constraints),
            "required_evidence": list(self.required_evidence),
            "pause_policy": self.pause_policy,
            "success_criteria": list(self.success_criteria),
        })
        if self.source_contract_error:
            payload["source_contract_error"] = self.source_contract_error
        if self._allowed_tools_present:
            payload["allowed_tools"] = list(self.allowed_tools)
        if self._initial_tools_present:
            payload["initial_tools"] = list(self.initial_tools)
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


__all__ = [
    "LEGACY_TASK_CONTRACT_SCHEMAS",
    "TASK_CONTRACT_SCHEMA",
    "TASK_CONTRACT_VERSION",
    "TaskContract",
]
