import pytest
import requests

from scansci_html.llm import AnthropicCompatibleChatJsonClient, OpenAICompatibleChatJsonClient, analyze_vision_images, build_chat_json_client, complete_chat_text, stream_chat_text


def test_openai_compatible_chat_json_client_parses_json_content():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"quotes\": []}"}}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json([{"role": "user", "content": "hello"}], schema_name="quotes")

    assert result == {"quotes": []}
    assert calls == [
        (
            "https://example.test/v1/chat/completions",
            {"Authorization": "Bearer secret", "Content-Type": "application/json"},
            {
                "model": "chat-model",
                "messages": [{"role": "user", "content": "hello"}],
                "response_format": {"type": "json_object"},
                "max_tokens": 4096,
                "temperature": 0.2,
            },
            60.0,
        )
    ]


def test_openai_compatible_chat_json_client_discards_only_trailing_text_after_complete_object():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"title":"Review","sections":[]}} trailing'}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json([{"role": "user", "content": "review"}], schema_name="quotes")

    assert result == {"title": "Review", "sections": []}


def test_openai_compatible_chat_json_client_repairs_missing_review_sections_terminator():
    malformed = (
        '{"title":"Review","sections":[{"id":"1","title":"A","paragraphs":[]},'
        '{"id":"2","title":"B","paragraphs":[]},"comparison_table":{"columns":[],"rows":[]},'
        '"controversies":[],"open_questions":[],"limitations":[]}'
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": malformed}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json(
        [{"role": "user", "content": "review"}],
        schema_name="evidence_grounded_literature_review",
    )

    assert [section["id"] for section in result["sections"]] == ["1", "2"]
    assert result["comparison_table"] == {"columns": [], "rows": []}


def test_openai_compatible_chat_json_client_repairs_unquoted_known_review_keys():
    malformed = (
        '{"title":"Review","sections":[],comparison_table":{},controversies":[],'
        'open_questions":[],limitations":[]}'
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": malformed}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json(
        [{"role": "user", "content": "review"}],
        schema_name="evidence_grounded_literature_review",
    )

    assert result["comparison_table"] == {}
    assert result["open_questions"] == []


def test_build_chat_json_client_requires_openai_compatible_config():
    with pytest.raises(ValueError, match="base_url"):
        build_chat_json_client("openai-compatible", api_key="secret", model="chat-model")


def test_openai_json_client_recovers_cited_markdown_when_gateway_ignores_response_format():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "**土壤水分**\n\n遮阴减少蒸发并提高板下土壤含水量 [q0001]。\n\n**微气候**\n\n板下温度响应具有季节差异 [q0002]。"
                        }
                    }
                ]
            }

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json(
        [{"role": "system", "content": "Use evidence."}, {"role": "user", "content": "question"}],
        schema_name="answer_claims",
    )

    assert result["answer"] == [
        {"claim_id": "c0001", "text": "土壤水分：遮阴减少蒸发并提高板下土壤含水量 。", "quote_ids": ["q0001"]},
        {"claim_id": "c0002", "text": "微气候：板下温度响应具有季节差异 。", "quote_ids": ["q0002"]},
    ]
    assert "Return only JSON" in calls[0]["messages"][0]["content"]
    assert "at most 4" in calls[0]["messages"][0]["content"]
    assert calls[0]["max_tokens"] == 768


def test_openai_json_client_retries_a_truncated_answer_contract_once():
    responses = [
        '{"answer":[{"claim_id":"c0001","text":"重复",',
        '{"answer":[{"claim_id":"c0001","text":"BERT 使用双向注意力。","quote_ids":["q0001"]}],"limitations":[]}',
    ]
    calls = []

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return FakeResponse(responses.pop(0))

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        session=FakeSession(),
    )

    result = client.complete_json(
        [{"role": "user", "content": "BERT 是双向吗？"}],
        schema_name="answer_claims",
    )

    assert result["answer"][0]["quote_ids"] == ["q0001"]
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0
    assert "previous structured response was invalid" in calls[1]["messages"][0]["content"]


def test_openai_json_client_adds_cross_language_retrieval_query_contract():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"queries":["transformer training objective"]}'}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return FakeResponse()

    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1", api_key="secret", model="chat-model", session=FakeSession()
    )
    result = client.complete_json([{"role": "user", "content": "训练目标"}], schema_name="retrieval_queries")

    assert result == {"queries": ["transformer training objective"]}
    assert "include one English query" in calls[0]["messages"][0]["content"]
    assert calls[0]["max_tokens"] == 768


def test_openai_json_client_retries_rate_limits(monkeypatch):
    calls = []

    class RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "3"}

        def raise_for_status(self):
            raise requests.HTTPError("rate limited", response=self)

        def close(self):
            return None

    class SuccessResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"queries":["BERT training objective"]}'}}]}

    responses = [RateLimitedResponse(), SuccessResponse()]

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return responses.pop(0)

    sleeps = []
    monkeypatch.setattr("scansci_html.llm.time.sleep", sleeps.append)
    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1", api_key="secret", model="chat-model", session=FakeSession()
    )

    assert client.complete_json([{"role": "user", "content": "BERT"}], schema_name="retrieval_queries") == {
        "queries": ["BERT training objective"]
    }
    assert len(calls) == 2
    assert sleeps == [3.0]


def test_openai_json_client_honors_long_rate_limit_without_blocking_workflow(monkeypatch):
    calls = []

    class RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "30"}

        def raise_for_status(self):
            raise requests.HTTPError("rate limited", response=self)

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return RateLimitedResponse()

    sleeps = []
    monkeypatch.setattr("scansci_html.llm.time.sleep", sleeps.append)
    client = OpenAICompatibleChatJsonClient(
        base_url="https://example.test/v1", api_key="secret", model="chat-model", session=FakeSession()
    )

    with pytest.raises(RuntimeError, match="429"):
        client.complete_json([{"role": "user", "content": "BERT"}], schema_name="retrieval_queries")
    with pytest.raises(RuntimeError, match="保留原文证据"):
        client.complete_text([{"role": "user", "content": "translate"}])
    with pytest.raises(RuntimeError, match="本地证据流程"):
        client.complete_json([{"role": "user", "content": "BERT"}], schema_name="answer_claims")

    assert len(calls) == 1
    assert sleeps == []


def test_complete_chat_text_returns_a_plain_openai_compatible_reply():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "你好，我是 GLM。"}}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            assert url == "https://example.test/v1/chat/completions"
            assert headers["Authorization"] == "Bearer secret"
            assert json["stream"] is False
            assert json["max_tokens"] == 8192
            assert timeout == 90.0
            return FakeResponse()

    assert complete_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "你好"}],
        session=FakeSession(),
    ) == "你好，我是 GLM。"


def test_complete_chat_text_forwards_a_valid_thinking_mode_only_when_requested():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            calls.append(json)
            return FakeResponse()

    assert complete_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "hello"}],
        thinking_mode="disabled",
        session=FakeSession(),
    ) == "ok"
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_complete_chat_text_returns_actual_token_usage_when_requested():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
            }

    class FakeSession:
        def post(self, _url, *, headers, json, timeout):
            return FakeResponse()

    assert complete_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "hello"}],
        include_usage=True,
        session=FakeSession(),
    ) == ("ok", {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13})


def test_stream_chat_text_yields_openai_deltas_and_final_usage():
    calls = []

    class FakeResponse:
        headers = {"Content-Type": "text/event-stream; charset=utf-8"}

        def __init__(self):
            self.closed = False
            self.encoding = None

        def raise_for_status(self):
            return None

        def iter_lines(self, *, decode_unicode):
            assert decode_unicode is False
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                    b'data: {"choices":[{"delta":{"content":"lo"}}]}',
                    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}',
                    b"data: [DONE]",
                ]
            )

        def close(self):
            self.closed = True

    response = FakeResponse()

    class FakeSession:
        def post(self, _url, *, headers, json, timeout, stream):
            calls.append({"json": json, "stream": stream})
            return response

    events = list(
        stream_chat_text(
            "openai-compatible",
            base_url="https://example.test/v1",
            api_key="secret",
            model="chat-model",
            messages=[{"role": "user", "content": "hello"}],
            session=FakeSession(),
        )
    )

    assert calls == [{"json": {"model": "chat-model", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 8192, "temperature": 0.4, "stream": True, "stream_options": {"include_usage": True}}, "stream": True}]
    assert events == [
        {"type": "delta", "content": "Hel"},
        {"type": "delta", "content": "lo"},
        {"type": "done", "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}, "finish_reason": "stop", "truncated": False},
    ]
    assert response.closed is True
    assert response.encoding == "utf-8"


def test_litellm_adapter_handles_custom_openai_compatible_completion(monkeypatch):
    import litellm

    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {
            "choices": [{"message": {"content": "adapter ready"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    monkeypatch.delenv("SCANSCI_DISABLE_LITELLM", raising=False)
    monkeypatch.setattr(litellm, "completion", fake_completion)
    result = complete_chat_text(
        "openai-compatible",
        base_url="https://gateway.example/v1",
        api_key="private-key",
        model="custom-model",
        messages=[{"role": "user", "content": "hello"}],
        include_usage=True,
    )

    assert result == ("adapter ready", {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
    assert calls[0]["model"] == "openai/custom-model"
    assert calls[0]["api_base"] == "https://gateway.example/v1"
    assert calls[0]["drop_params"] is True


def test_litellm_adapter_streams_and_never_reflects_api_keys(monkeypatch):
    import litellm

    def fake_stream(**kwargs):
        assert kwargs["stream"] is True
        return iter(
            [
                {"choices": [{"delta": {"content": "A"}}]},
                {"choices": [{"delta": {"content": "B"}}], "usage": {"total_tokens": 4}},
            ]
        )

    monkeypatch.delenv("SCANSCI_DISABLE_LITELLM", raising=False)
    monkeypatch.setattr(litellm, "completion", fake_stream)
    events = list(
        stream_chat_text(
            "openai-compatible",
            base_url="https://gateway.example/v1",
            api_key="do-not-leak",
            model="custom-model",
            messages=[{"role": "user", "content": "hello"}],
        )
    )
    assert events == [
        {"type": "delta", "content": "A"},
        {"type": "delta", "content": "B"},
        {"type": "done", "usage": {"total_tokens": 4}, "finish_reason": "stop", "truncated": False},
    ]

    monkeypatch.setattr(litellm, "completion", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("do-not-leak")))
    with pytest.raises(RuntimeError) as caught:
        complete_chat_text(
            "openai-compatible",
            base_url="https://gateway.example/v1",
            api_key="do-not-leak",
            model="custom-model",
            messages=[{"role": "user", "content": "hello"}],
        )
    assert "do-not-leak" not in str(caught.value)


def test_stream_chat_text_automatically_continues_after_length_finish():
    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self, lines):
            self.lines = lines

        def raise_for_status(self):
            return None

        def iter_lines(self, *, decode_unicode):
            assert decode_unicode is False
            return iter(self.lines)

        def close(self):
            return None

    responses = [
        FakeResponse([
            b'data: {"choices":[{"delta":{"content":"first"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"length"}],"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}',
            b"data: [DONE]",
        ]),
        FakeResponse([
            b'data: {"choices":[{"delta":{"content":" second"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":9,"completion_tokens":2,"total_tokens":11}}',
            b"data: [DONE]",
        ]),
    ]
    calls = []

    class FakeSession:
        def post(self, _url, *, headers, json, timeout, stream):
            calls.append(json)
            return responses.pop(0)

    events = list(stream_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "write a complete answer"}],
        session=FakeSession(),
    ))

    assert [event["type"] for event in events] == ["delta", "continuation", "delta", "done"]
    assert "直接继续" in calls[1]["messages"][-1]["content"]
    assert events[-1] == {
        "type": "done",
        "usage": {"prompt_tokens": 14, "completion_tokens": 5, "total_tokens": 19},
        "finish_reason": "stop",
        "truncated": False,
    }


def test_stream_chat_text_continues_when_provider_stops_before_required_marker():
    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self, lines):
            self.lines = lines

        def raise_for_status(self):
            return None

        def iter_lines(self, *, decode_unicode):
            assert decode_unicode is False
            return iter(self.lines)

        def close(self):
            return None

    responses = [
        FakeResponse([
            'data: {"choices":[{"delta":{"content":"第一部分："}}]}'.encode(),
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            b"data: [DONE]",
        ]),
        FakeResponse([
            'data: {"choices":[{"delta":{"content":"内容\\n【回答完毕】"}}]}'.encode(),
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            b"data: [DONE]",
        ]),
    ]
    calls = []

    class FakeSession:
        def post(self, _url, *, headers, json, timeout, stream):
            calls.append(json)
            return responses.pop(0)

    events = list(stream_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "写完整指南，最后一行写【回答完毕】。"}],
        session=FakeSession(),
    ))

    assert [event["type"] for event in events] == ["delta", "continuation", "delta", "done"]
    assert "【回答完毕】" in calls[1]["messages"][-1]["content"]
    assert len(calls[1]["messages"]) == 3
    assert events[-1]["truncated"] is False


def test_stream_chat_text_retries_rate_limits_without_losing_the_reply(monkeypatch):
    class RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "7"}

        def raise_for_status(self):
            raise requests.HTTPError("rate limited", response=self)

        def close(self):
            return None

    class SuccessResponse:
        headers = {"Content-Type": "text/event-stream"}
        encoding = None

        def raise_for_status(self):
            return None

        def iter_lines(self, *, decode_unicode):
            assert decode_unicode is False
            return iter([
                b'data: {"choices":[{"delta":{"content":"recovered"}}]}',
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                b"data: [DONE]",
            ])

        def close(self):
            return None

    responses = [RateLimitedResponse(), SuccessResponse()]

    class FakeSession:
        def post(self, _url, *, headers, json, timeout, stream):
            return responses.pop(0)

    sleeps = []
    monkeypatch.setattr("scansci_html.llm.time.sleep", sleeps.append)
    events = list(stream_chat_text(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="chat-model",
        messages=[{"role": "user", "content": "hello"}],
        session=FakeSession(),
    ))

    assert events[0] == {
        "type": "retry",
        "reason": "rate_limit",
        "status": 429,
        "delay_seconds": 7.0,
        "attempt": 1,
    }
    assert events[1]["content"] == "recovered"
    assert events[-1]["truncated"] is False
    assert sleeps == [7.0]


def test_anthropic_compatible_chat_json_client_parses_text_blocks():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "```json\n{\"quotes\": []}\n```"}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return FakeResponse()

    client = AnthropicCompatibleChatJsonClient(
        base_url="https://api.anthropic.test/v1",
        api_key="secret",
        model="claude-test",
        session=FakeSession(),
    )

    result = client.complete_json(
        [{"role": "system", "content": "Return quotes."}, {"role": "user", "content": "hello"}],
        schema_name="quotes",
    )

    assert result == {"quotes": []}
    assert calls[0][0] == "https://api.anthropic.test/v1/messages"
    assert calls[0][1]["x-api-key"] == "secret"
    assert calls[0][2]["messages"] == [{"role": "user", "content": "hello"}]


def test_build_chat_json_client_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported chat provider"):
        build_chat_json_client("unknown")


def test_openai_compatible_vision_request_embeds_local_image_data():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "图中显示一条上升曲线。"}}]}

    class FakeSession:
        def post(self, url, *, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return FakeResponse()

    text = analyze_vision_images(
        "openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
        model="vision-model",
        question="这张图说明什么？",
        images=[{"mime_type": "image/png", "data": "aGVsbG8="}],
        session=FakeSession(),
    )

    assert text == "图中显示一条上升曲线。"
    assert calls[0][0] == "https://example.test/v1/chat/completions"
    assert calls[0][2]["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
