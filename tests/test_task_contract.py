from __future__ import annotations

import json
from pathlib import Path

import pytest

from scansci_html.task_contract import TASK_CONTRACT_SCHEMA, TaskContract
from scansci_html.tool_authorization import (
    ToolAuthorizationError,
    approval_token_from_response,
    authorize_tool_call,
)


def test_task_contract_reads_legacy_v1_and_writes_only_v2() -> None:
    contract = TaskContract.from_payload(
        {
            "schema_version": "scansci.task-contract.v1",
            "version": 1,
            "goal": "legacy",
            "allowed_tools": ["inspect_workspace"],
        }
    )

    payload = contract.to_dict()

    assert TASK_CONTRACT_SCHEMA == "scansci.task-contract.v2"
    assert payload["schema_version"] == TASK_CONTRACT_SCHEMA
    assert payload["version"] == 2
    assert payload["allowed_tools"] == ["inspect_workspace"]


def test_task_contract_preserves_missing_versus_explicit_empty_tool_lease() -> None:
    omitted = TaskContract.from_payload({"goal": "omitted"}).to_dict()
    explicit = TaskContract.from_payload({"goal": "empty", "allowed_tools": []}).to_dict()

    assert "allowed_tools" not in omitted
    assert explicit["allowed_tools"] == []


def test_v2_contract_fixture_round_trips_without_expanding_initial_tools() -> None:
    fixture = Path(__file__).parent / "fixtures" / "pi_task_contract_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    round_tripped = TaskContract.from_payload(payload).to_dict()

    assert round_tripped["schema_version"] == TASK_CONTRACT_SCHEMA
    assert round_tripped["allowed_tools"] == ["inspect_workspace", "kb_search"]
    assert round_tripped["initial_tools"] == ["inspect_workspace"]


def test_tool_authorization_denies_missing_empty_spoofed_and_over_budget_calls() -> None:
    descriptor = {"id": "inspect_workspace", "risk_level": "read_only", "idempotent": True}
    base = {
        "request_id": "request-current",
        "active_request_id": "request-current",
        "descriptor": descriptor,
        "call_count": 0,
    }

    with pytest.raises(ToolAuthorizationError, match="missing"):
        authorize_tool_call(tool_name="inspect_workspace", contract={}, **base)
    with pytest.raises(ToolAuthorizationError, match="empty"):
        authorize_tool_call(tool_name="inspect_workspace", contract={"allowed_tools": []}, **base)
    with pytest.raises(ToolAuthorizationError, match="another request"):
        authorize_tool_call(
            tool_name="inspect_workspace",
            contract={"allowed_tools": ["inspect_workspace"], "max_tool_budget": 2},
            **{**base, "request_id": "request-stale"},
        )
    with pytest.raises(ToolAuthorizationError, match="budget"):
        authorize_tool_call(
            tool_name="inspect_workspace",
            contract={
                "allowed_tools": ["inspect_workspace"],
                "risk_level": "read_only",
                "max_tool_budget": 1,
            },
            **{**base, "call_count": 1},
        )


def test_approval_token_is_created_only_for_explicit_request_scoped_approve() -> None:
    assert approval_token_from_response("request-a", {}) is None
    assert approval_token_from_response("request-a", {"decision": "approved"}) is None
    assert approval_token_from_response("request-a", {"decision": "continue"}) is None

    token = approval_token_from_response("request-a", {"decision": "approve"})

    assert token is not None
    assert token.request_id == "request-a"
    with pytest.raises(ToolAuthorizationError, match="approved plan"):
        authorize_tool_call(
            tool_name="download_and_index",
            contract={
                "allowed_tools": ["download_and_index"],
                "risk_level": "reversible",
                "requires_plan": True,
                "max_tool_budget": 2,
            },
            descriptor={"id": "download_and_index", "risk_level": "reversible", "idempotent": False},
            request_id="request-b",
            active_request_id="request-b",
            approval_token=token,
            call_count=0,
        )

    decision = authorize_tool_call(
        tool_name="download_and_index",
        contract={
            "allowed_tools": ["download_and_index"],
            "risk_level": "reversible",
            "requires_plan": True,
            "max_tool_budget": 2,
        },
        descriptor={"id": "download_and_index", "risk_level": "reversible", "idempotent": False},
        request_id="request-a",
        active_request_id="request-a",
        approval_token=token,
        call_count=0,
    )
    assert decision.allowed is True
