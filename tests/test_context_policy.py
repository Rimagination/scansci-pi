from __future__ import annotations

import base64
import json

import pytest

from scansci_html.context_policy import (
    ContextEnvelopeError,
    build_token_envelope,
    estimate_message_tokens,
    estimate_text_tokens,
)
from scansci_html.model_metadata import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    ModelRuntimeDescriptor,
    descriptor_from_model_record,
    parse_context_window_tokens,
)
from scansci_html.research_agent import ResearchAgentRuntime


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (32_768, 32_768),
        ("32K", 32 * 1024),
        ("200K", 200 * 1024),
        ("1.5M", int(1.5 * 1024 * 1024)),
        (" 200 k ", 200 * 1024),
    ],
)
def test_context_window_parser_accepts_numeric_and_human_units(raw: object, expected: int) -> None:
    assert parse_context_window_tokens(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "本地", "unknown", -1, 0, True, False, object()])
def test_context_window_parser_fails_closed_to_32k(raw: object) -> None:
    assert parse_context_window_tokens(raw) == DEFAULT_CONTEXT_WINDOW_TOKENS


def test_runtime_descriptor_uses_trusted_record_and_declares_budget_invariants() -> None:
    descriptor = descriptor_from_model_record(
        provider_id="fixture",
        provider_kind="openai-compatible",
        model_id="vision-model",
        model_record={
            "id": "vision-model",
            "context_window": "200K",
            "capabilities": ["reasoning", "tool", "vision"],
        },
        api_surface="responses",
    )

    assert descriptor.schema_version == "scansci.model-runtime.v1"
    assert descriptor.context_window_tokens == 204_800
    assert descriptor.input_modalities == ("text", "image")
    assert descriptor.capability_provenance == "settings:model-record"
    assert descriptor.context_provenance == "settings:model-record"
    assert descriptor.degraded is False
    assert descriptor.provider_input_tokens == 173_056
    assert descriptor.compaction_reserve_tokens == 25_600
    assert descriptor.keep_recent_tokens == 20_480
    assert descriptor.max_output_tokens == 12_288

    small = descriptor_from_model_record(
        provider_id="fixture",
        provider_kind="openai-compatible",
        model_id="small",
        model_record={"id": "small", "context_window": "32K", "capabilities": ["reasoning"]},
    )
    assert small.provider_input_tokens == 27_648
    assert small.compaction_reserve_tokens == 4_096
    assert small.keep_recent_tokens == 4_096
    assert small.max_output_tokens == 4_096


def test_runtime_descriptor_marks_unknown_local_and_boolean_metadata_as_degraded() -> None:
    for value in ("本地", "unknown", -5, True):
        descriptor = descriptor_from_model_record(
            provider_id="local",
            provider_kind="local",
            model_id="fixture",
            model_record={"id": "fixture", "context_window": value, "capabilities": ["reasoning"]},
        )
        assert descriptor.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
        assert descriptor.degraded is True
        assert descriptor.degradation_reasons


def test_runtime_descriptor_payload_rejects_noncanonical_or_inconsistent_metadata() -> None:
    payload = ModelRuntimeDescriptor.for_testing().to_dict()
    with pytest.raises(ValueError, match="canonical"):
        ModelRuntimeDescriptor.from_payload({**payload, "unexpected": True})

    with pytest.raises(ValueError, match="modalit"):
        ModelRuntimeDescriptor.from_payload({
            **payload,
            "input_modalities": ["text", "image"],
            "capabilities": ["reasoning"],
        })


def test_token_estimator_is_conservative_for_english_chinese_json_and_emoji() -> None:
    assert estimate_text_tokens("a" * 400) >= 100
    assert estimate_text_tokens("科研能力" * 25) >= 100
    assert estimate_text_tokens("🧪" * 40) >= 40
    fixture = json.dumps({"query": "检索", "items": ["alpha", "beta"]}, ensure_ascii=False)
    assert estimate_text_tokens(fixture) >= 15


def test_image_base64_is_not_counted_as_text_tokens() -> None:
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "inspect this image"},
            {"type": "image", "data": "A" * 4_000_000, "mimeType": "image/png"},
        ],
    }
    assert estimate_message_tokens(message) < 5_000


def test_high_resolution_image_uses_a_conservative_dimension_aware_token_charge() -> None:
    raw = bytearray(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    )
    raw[16:20] = (8_000).to_bytes(4, "big")
    raw[20:24] = (5_000).to_bytes(4, "big")
    message = {
        "role": "user",
        "content": [{
            "type": "image",
            "data": base64.b64encode(raw).decode("ascii"),
            "mimeType": "image/png",
        }],
    }

    assert estimate_message_tokens(message) > ModelRuntimeDescriptor.for_testing().provider_input_tokens


def test_token_envelope_keeps_host_contract_explicit_skill_and_final_user_sentinel() -> None:
    descriptor = ModelRuntimeDescriptor.for_testing(context_window_tokens=32_768)
    messages = [
        {
            "role": "system",
            "content": "HOST-OWNED TASK CONTRACT sentinel-contract",
            "context_kind": "host_contract",
        },
        {
            "role": "system",
            "content": "<selected_skill id=\"method\">sentinel-skill</selected_skill>",
            "context_kind": "explicit_skill",
        },
        {
            "role": "user",
            "content": "old-user " + ("x" * 100_000),
            "context_ref": "turn-old",
        },
        {"role": "assistant", "content": "old assistant " + ("y" * 100_000)},
        {
            "role": "tool",
            "content": "REFERENCED-TOOL " + ("z" * 100_000),
            "context_ref": "tool-result-old",
        },
        {"role": "user", "content": "FINAL-USER-SENTINEL: answer this exact request"},
    ]

    projected, report = build_token_envelope(
        messages,
        descriptor=descriptor,
        host_contract={"contract_id": "contract", "allowed_tools": []},
    )
    encoded = json.dumps(projected, ensure_ascii=False)

    assert "sentinel-contract" in encoded
    assert "sentinel-skill" in encoded
    assert "FINAL-USER-SENTINEL" in encoded
    assert ("old-user" in encoded) is ("old assistant" in encoded)
    assert "old-user" not in encoded
    assert "REFERENCED-TOOL" in encoded
    assert report.estimated_tokens <= descriptor.provider_input_tokens
    assert report.omitted_messages >= 1 or report.truncated_messages >= 1
    assert "omission_sha256" in encoded


def test_token_envelope_never_truncates_mandatory_final_user_request() -> None:
    descriptor = ModelRuntimeDescriptor.for_testing(context_window_tokens=32_768)
    final_request = "FINAL-SENTINEL " + ("重要" * 20_000)

    with pytest.raises(ContextEnvelopeError, match="mandatory"):
        build_token_envelope(
            [{"role": "user", "content": final_request}],
            descriptor=descriptor,
        )


def test_follow_up_with_ten_or_fewer_large_messages_is_still_enveloped() -> None:
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index} " + "x" * 20_000}
        for index in range(10)
    ]
    messages[-1] = {"role": "user", "content": "FINAL-FOLLOWUP-SENTINEL"}

    normalized = ResearchAgentRuntime._follow_up_messages(messages, max_recent=10, max_chars=12_000)
    descriptor = ModelRuntimeDescriptor.for_testing(context_window_tokens=32_768)
    projected, report = build_token_envelope(normalized, descriptor=descriptor)

    assert "FINAL-FOLLOWUP-SENTINEL" in projected[-1]["content"]
    assert report.estimated_tokens <= descriptor.provider_input_tokens
    assert report.omitted_messages > 0
