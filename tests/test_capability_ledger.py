from __future__ import annotations

import pytest

from scansci_html.capability_ledger import CapabilityLedger, CapabilityDeliveryError


def test_capability_ledger_requires_one_success_per_group() -> None:
    ledger = CapabilityLedger(
        [["search_web", "discover_papers"], ["summarize_documents"]]
    )

    ledger.record_event({"type": "tool.failed", "name": "search_web", "error": "HTTP 503"})
    assert ledger.ready is False
    assert ledger.safe_retry_allowed() is True
    assert ledger.to_dict()["failed_groups"] == [["discover_papers", "search_web"]]

    ledger.mark_recovery_attempt()
    ledger.record_event({"type": "tool.completed", "name": "discover_papers", "result": {"count": 2}})
    ledger.record_event({"type": "tool.completed", "name": "summarize_documents", "result": {"count": 2}})

    assert ledger.ready is True
    assert ledger.to_dict()["status"] == "ready"
    assert ledger.to_dict()["reminder_sent"] is True


def test_mutating_failure_is_not_replayed_automatically() -> None:
    ledger = CapabilityLedger([["download_and_index"]])
    ledger.record_event({"type": "status", "status": "tool_started", "name": "download_and_index"})
    ledger.record_event({"type": "tool.failed", "name": "download_and_index", "error": "timeout"})

    assert ledger.has_non_idempotent_effect is True
    assert ledger.safe_retry_allowed() is False
    error = ledger.delivery_error()
    assert isinstance(error, CapabilityDeliveryError)
    assert error.failure["retryable"] is False
    assert error.failure["capability_ledger"]["failed_groups"] == [["download_and_index"]]


@pytest.mark.parametrize("provider_error", ["HTTP 429", "HTTP 503"])
def test_search_tools_is_internal_read_only_when_the_followup_provider_call_fails(
    provider_error: str,
) -> None:
    ledger = CapabilityLedger([["search_web"]])
    ledger.record_event({"type": "status", "status": "tool_started", "name": "search_tools"})
    ledger.record_event({"type": "tool.completed", "name": "search_tools", "result": {"activated": []}})

    assert ledger.has_non_idempotent_effect is False
    assert ledger.safe_retry_allowed() is True
    assert ledger.delivery_error(cause=provider_error).failure["retryable"] is True


@pytest.mark.parametrize("tool_name", ["submit_plan", "download_and_index"])
def test_control_and_effectful_tools_still_block_automatic_replay(tool_name: str) -> None:
    ledger = CapabilityLedger([["search_web"]])
    ledger.record_event({"type": "status", "status": "tool_started", "name": tool_name})

    assert ledger.has_non_idempotent_effect is True
    assert ledger.safe_retry_allowed() is False


def test_preflight_marks_an_entire_required_group_unavailable() -> None:
    ledger = CapabilityLedger.from_contract(
        {
            "required_tool_groups": [["zotero_search", "kb_search"]],
            "unavailable_tools": ["zotero_search", "kb_search"],
        }
    )

    assert ledger.unavailable_groups() == [("kb_search", "zotero_search")]
    assert ledger.safe_retry_allowed() is False
    assert ledger.delivery_error().failure["code"] == "capability_unavailable"
