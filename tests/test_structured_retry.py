from __future__ import annotations

from scansci_html.llm import OpenAICompatibleChatJsonClient, OpenAIResponsesJsonClient


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _responses_payload(content: str) -> dict:
    return {
        "id": "resp-test",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}],
    }


def test_chat_retry_uses_pydantic_validation_failure_to_repair():
    responses = [
        _Response(_chat_payload('{"answer":[{"claim_id":"c0001","text":"","quote_ids":[]}]}')),
        _Response(
            _chat_payload(
                '{"answer":[{"claim_id":"c0001","text":"BERT uses bidirectional attention.",'
                '"quote_ids":["q0001"]}],"limitations":[]}'
            )
        ),
    ]
    calls: list[dict] = []

    class Session:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return responses.pop(0)

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=Session(),
    )

    result = client.complete_json([{"role": "user", "content": "BERT"}], schema_name="answer_claims")

    assert result["answer"][0]["quote_ids"] == ["q0001"]
    assert len(calls) == 2
    assert "schema_validation" in calls[1]["messages"][0]["content"]
    assert "answer.0.text" in calls[1]["messages"][0]["content"]


def test_responses_retry_shares_a_two_request_correction_budget():
    responses = [
        _Response(_responses_payload('{"answer":[{"claim_id":"c0001","text":"","quote_ids":[]}]}')),
        _Response(
            _responses_payload(
                '{"answer":[{"claim_id":"c0001","text":"Supported claim.",'
                '"quote_ids":["q0001"]}],"limitations":[]}'
            )
        ),
    ]
    calls: list[dict] = []

    class Session:
        def post(self, url, *, headers, json, timeout):
            calls.append({"url": url, "body": json})
            return responses.pop(0)

    client = OpenAIResponsesJsonClient(
        base_url="https://api.example.test/v1",
        api_key="secret",
        model="responses-model",
        provider_id="openai",
        responses_enabled=True,
        session=Session(),
    )

    result = client.complete_json([{"role": "user", "content": "BERT"}], schema_name="answer_claims")

    assert result["answer"][0]["text"] == "Supported claim."
    assert len(calls) == 2
    assert calls[0]["url"].endswith("/responses")
    assert "schema_validation" in calls[1]["body"]["input"][0]["content"]
