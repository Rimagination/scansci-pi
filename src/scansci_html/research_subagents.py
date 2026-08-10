"""Bounded scientific sub-agent roles for ScanSci's durable task runtime.

The coordinator is deliberately small and product-owned.  Roles share the
parent notebook/evidence store, have explicit capability boundaries, and
produce normal durable child runs instead of opening an unrestricted shell or
an opaque second memory system.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .agent_capabilities import parse_resource_uri


MAX_CONCURRENT_SCIENTIFIC_SUBAGENTS = 3


@dataclass(frozen=True)
class ScientificRole:
    role_id: str
    label: str
    objective: str
    task_mode: str
    allowed_capabilities: tuple[str, ...]
    output_contract: str


SCIENTIFIC_ROLES: dict[str, ScientificRole] = {
    "literature_scout": ScientificRole(
        role_id="literature_scout",
        label="文献侦察员",
        objective="发现与问题直接相关的候选研究，去重并区分题录、摘要与可验证全文。",
        task_mode="research",
        allowed_capabilities=("discover_papers", "verify_doi", "search_web"),
        output_contract="候选文献表、检索式、来源状态与仍缺失的证据。",
    ),
    "fulltext_analyst": ScientificRole(
        role_id="fulltext_analyst",
        label="全文分析员",
        objective="读取任务已登记或知识库内的全文，提取研究问题、方法、结果、限制与可定位证据。",
        task_mode="task-documents+knowledge",
        allowed_capabilities=("read_task_documents", "summarize_documents", "search_local_evidence"),
        output_contract="逐文献结构化映射与跨文献可比字段。",
    ),
    "evidence_auditor": ScientificRole(
        role_id="evidence_auditor",
        label="证据审计员",
        objective="寻找反例、证据缺口、引用越界和仅由元数据支持的主张。",
        task_mode="knowledge",
        allowed_capabilities=("search_local_evidence", "build_verified_answer", "check_task_completion"),
        output_contract="通过项、争议项、反证、缺失全文与必须降低强度的结论。",
    ),
    "synthesis_writer": ScientificRole(
        role_id="synthesis_writer",
        label="综合写作者",
        objective="只使用共享证据库和其他角色已验证的结果，形成结构清楚、主张强度合适的综述。",
        task_mode="knowledge",
        allowed_capabilities=("summarize_documents", "build_verified_answer", "create_document"),
        output_contract="带证据边界的总结、共识/分歧、研究空白与可交付文档建议。",
    ),
}


def structured_output_schema(role: ScientificRole) -> dict[str, Any]:
    """Return the durable handoff contract shared by every child role."""

    return {
        "schema_version": "scansci.subagent-result.v1",
        "type": "object",
        "required": ["role", "findings", "evidence_uris", "uncertainties", "recommended_next_action"],
        "properties": {
            "role": {"const": role.role_id},
            "findings": {"type": "array", "maxItems": 20},
            "evidence_uris": {"type": "array", "maxItems": 40},
            "uncertainties": {"type": "array", "maxItems": 20},
            "recommended_next_action": {"type": "string", "maxLength": 300},
        },
    }


def validate_scientific_resource_uri(
    value: object,
    *,
    allowed_uris: Iterable[str],
) -> str | None:
    """Accept only an exact, host-issued ScanSci resource membership URI.

    URI parsing alone is not authority.  The caller supplies the concrete
    parent-owned resource set and this function rejects ambiguous spellings
    before applying exact membership, so percent-encoding cannot manufacture
    a different authority or path after validation.
    """

    raw = str(value or "").strip()
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return None
    lowered = raw.lower()
    if "%25" in lowered or "\\" in raw:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "scansci"
        or parsed.netloc not in {"run", "artifact", "evidence"}
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        return None
    for encoded_segment in parsed.path.split("/")[1:]:
        if not encoded_segment:
            return None
        try:
            decoded = unquote(encoded_segment, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if (
            decoded in {".", ".."}
            or "%" in decoded
            or "/" in decoded
            or "\\" in decoded
            or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
        ):
            return None
    return raw if raw in {str(uri) for uri in allowed_uris} else None


def validate_subagent_result(
    payload: object,
    *,
    role_id: str,
    allowed_uris: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate the one JSON handoff a scientific child may give its parent.

    Prose remains in the durable child run for diagnosis, but a coordinator
    never aggregates it as a scientific finding unless it passes this host
    owned schema check.
    """

    candidate: object = payload
    if isinstance(payload, dict):
        candidate = payload.get("subagent_handoff")
        if candidate is None:
            reader = payload.get("reader_answer")
            candidate = dict(reader).get("text") if isinstance(reader, dict) else payload.get("text")
    if isinstance(candidate, str):
        text = candidate.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            return {"valid": False, "errors": ["handoff_not_json"], "result": None}
    if not isinstance(candidate, dict):
        return {"valid": False, "errors": ["handoff_not_object"], "result": None}

    errors: list[str] = []
    if str(candidate.get("role", "")) != role_id:
        errors.append("role_mismatch")
    normalized: dict[str, Any] = {"role": role_id}
    for field, maximum in (("findings", 20), ("evidence_uris", 40), ("uncertainties", 20)):
        value = candidate.get(field)
        if not isinstance(value, list):
            errors.append(f"{field}_not_list")
            normalized[field] = []
            continue
        if len(value) > maximum:
            errors.append(f"{field}_too_large")
        normalized[field] = value[:maximum]
    action = str(candidate.get("recommended_next_action", "") or "").strip()
    if not action:
        errors.append("recommended_next_action_missing")
    normalized["recommended_next_action"] = action[:300]

    valid_uris: list[str] = []
    for value in list(normalized.get("evidence_uris", []) or []):
        if allowed_uris is not None:
            validated = validate_scientific_resource_uri(value, allowed_uris=allowed_uris)
            if validated is None:
                errors.append("invalid_evidence_uri")
                continue
            valid_uris.append(validated)
            continue
        parsed = parse_resource_uri(value)
        if not parsed or str(parsed.get("kind", "")) not in {"evidence", "paper", "artifact", "run"}:
            errors.append("invalid_evidence_uri")
            continue
        valid_uris.append(str(parsed["uri"]))
    normalized["evidence_uris"] = list(dict.fromkeys(valid_uris))
    return {"valid": not errors, "errors": list(dict.fromkeys(errors)), "result": normalized if not errors else None}


def select_scientific_roles(values: Iterable[object] | None) -> list[ScientificRole]:
    """Validate and bound a requested role set while preserving order."""

    requested = [str(value or "").strip() for value in list(values or [])]
    if not requested:
        requested = ["literature_scout", "fulltext_analyst", "evidence_auditor"]
    selected: list[ScientificRole] = []
    for role_id in requested:
        role = SCIENTIFIC_ROLES.get(role_id)
        if role is None:
            raise ValueError(f"Unsupported scientific sub-agent role: {role_id}")
        if role not in selected:
            selected.append(role)
        if len(selected) >= MAX_CONCURRENT_SCIENTIFIC_SUBAGENTS:
            break
    return selected


def delegation_prompt(
    role: ScientificRole,
    *,
    parent_title: str,
    parent_question: str,
    instruction: str = "",
) -> str:
    """Build the role's auditable prompt without hidden cross-agent chatter."""

    capabilities = ", ".join(role.allowed_capabilities)
    schema = structured_output_schema(role)
    extra = f"\nAdditional parent instruction: {instruction.strip()}" if instruction.strip() else ""
    return (
        f"You are the ScanSci scientific sub-agent “{role.label}”.\n"
        f"Parent task: {parent_title}\n"
        f"Research question: {parent_question}\n"
        f"Objective: {role.objective}\n"
        f"Allowed capability boundary: {capabilities}.\n"
        f"Output contract: {role.output_contract}\n"
        "Use the parent's linked notebook and shared evidence store. Do not claim that another role "
        "completed work unless its durable child result exists. Distinguish metadata, abstract, and full text. "
        "You have a read-only capability lease: do not create files, change settings, or call write-capable MCP tools. "
        "Return exactly one concise JSON object matching this handoff schema: "
        f"{schema}. Evidence references must use ScanSci resource URIs when available."
        f"{extra}"
    )


def public_role_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": role.role_id,
            "label": role.label,
            "objective": role.objective,
            "task_mode": role.task_mode,
            "allowed_capabilities": list(role.allowed_capabilities),
            "output_contract": role.output_contract,
            "output_schema": structured_output_schema(role),
        }
        for role in SCIENTIFIC_ROLES.values()
    ]
