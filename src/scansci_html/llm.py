from __future__ import annotations

import codecs
import json
import os
import re
import time
from typing import Any, Iterator, Protocol

import requests


_MANAGED_GATEWAY_SESSION = requests.Session()


def managed_gateway_session() -> requests.Session:
    """Return the desktop-process session used by ScanSci's managed gateway.

    Reusing its connection pool avoids recreating a proxy/TLS connection for
    every short chat turn. The session carries no user model credential.
    """

    return _MANAGED_GATEWAY_SESSION


def warm_managed_gateway_connection(base_url: str, *, timeout: float = 20.0) -> bool:
    """Open the managed gateway connection in the background before first use."""

    normalized = str(base_url or "").rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    if not normalized.startswith("https://"):
        return False
    try:
        response = managed_gateway_session().get(f"{normalized}/healthz", timeout=timeout)
    except requests.RequestException:
        return False
    return response.ok


class ChatJsonClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        ...

    def complete_text(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        ...


class CascadingChatJsonClient:
    """Latch onto the first healthy configured client for a bounded workflow."""

    def __init__(self, clients: list[ChatJsonClient]) -> None:
        if not clients:
            raise ValueError("at least one chat client is required")
        self.clients = list(clients)
        self._active_index = 0
        primary = self.clients[0]
        self.session = getattr(primary, "session", None)
        self.thinking_mode = getattr(primary, "thinking_mode", None)
        self.model = getattr(primary, "model", "")

    @property
    def active_model(self) -> str:
        return str(getattr(self.clients[self._active_index], "model", ""))

    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        return self._complete("complete_json", messages, schema_name=schema_name)

    def complete_text(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        return str(self._complete("complete_text", messages, max_tokens=max_tokens))

    def _complete(self, method_name: str, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for index in range(self._active_index, len(self.clients)):
            client = self.clients[index]
            try:
                result = getattr(client, method_name)(messages, **kwargs)
            except ValueError as error:
                last_error = error
                # A structured-output parse failure proves that the provider
                # answered even though it did not honor the JSON contract.
                # When a previous provider was unavailable, keep this
                # reachable fallback latched so a subsequent plain-text
                # recovery does not wait on the dead primary again.
                if method_name == "complete_json" and index > self._active_index:
                    self._active_index = index
                continue
            except RuntimeError as error:
                last_error = error
                continue
            self._active_index = index
            return result
        if last_error is not None:
            raise last_error
        raise RuntimeError("no chat client completed the request")


class OpenAICompatibleChatJsonClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        session: Any | None = None,
        thinking_mode: str | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for openai-compatible chat")
        if not api_key:
            raise ValueError("api_key is required for openai-compatible chat")
        if not model:
            raise ValueError("model is required for openai-compatible chat")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout)
        self.session = session or requests.Session()
        self.thinking_mode = thinking_mode if thinking_mode in {"enabled", "disabled"} else None
        self._rate_limited_until = 0.0

    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        if time.monotonic() < self._rate_limited_until:
            raise RuntimeError("模型结构化响应暂时受限，已立即切换到本地证据流程。")
        structured_messages = _with_structured_output_instruction(messages, schema_name=schema_name)
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": structured_messages,
            "response_format": {"type": "json_object"},
            # Structured workflows need enough visible completion budget. Some
            # reasoning models otherwise spend their default budget on hidden
            # analysis and return an empty JSON message.
            # A bounded answer-claim budget prevents compatible models from
            # repeating a valid claim until the response is truncated, which
            # would turn otherwise useful RAG output into invalid JSON.
            "max_tokens": (
                768
                if schema_name in {"answer_claims", "claim_verification", "retrieval_queries"}
                else 320 if schema_name == "literature_review_section"
                else 1024 if schema_name == "literature_review_overview"
                else 3072 if schema_name == "evidence_grounded_literature_review" else 4096
            ),
            "temperature": (
                0
                if schema_name in {
                    "evidence_grounded_literature_review",
                    "literature_review_section",
                    "literature_review_overview",
                }
                else 0.2
            ),
        }
        if self.thinking_mode:
            request_body["thinking"] = {"type": self.thinking_mode}
        retryable_schemas = {
            "answer_claims",
            "claim_verification",
            "retrieval_queries",
            "evidence_grounded_literature_review",
            "literature_review_section",
            "literature_review_overview",
            "scansci_scientific_slides",
        }
        # Review synthesis already validates every paragraph and has a
        # grounded evidence fallback. Retrying malformed section JSON here,
        # and then retrying the same section again at the workflow layer,
        # multiplies a slow gateway call without improving the accepted text.
        attempts = 1 if schema_name == "literature_review_section" else 2 if schema_name in retryable_schemas else 1
        for attempt in range(attempts):
            active_body = dict(request_body)
            if attempt:
                active_body["temperature"] = 0
                retry_instruction = (
                    "The previous structured response was invalid or truncated. Produce a fresh result now. "
                    "Return no more than three non-repeating items, output one complete JSON object only, "
                    "and stop immediately after its closing brace."
                )
                if schema_name == "evidence_grounded_literature_review":
                    retry_instruction = (
                        "The previous literature-review JSON was invalid or truncated. Produce a fresh compact result now. "
                        "Keep every planned section, use exactly one concise paragraph per section, at most three comparison "
                        "rows, at most two controversies, and exactly two open questions. Output one complete JSON object "
                        "only and stop immediately after its closing brace."
                    )
                active_body["messages"] = [
                    {
                        "role": "system",
                        "content": retry_instruction,
                    },
                    *structured_messages,
                ]
            response: Any | None = None
            for retry_index in range(3):
                try:
                    response = self.session.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=active_body,
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    self._rate_limited_until = 0.0
                    break
                except requests.RequestException as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    if status not in {429, 502, 503, 504} or retry_index >= 2:
                        raise RuntimeError(_public_model_error(error, prefix="模型结构化响应暂时不可用")) from error
                    headers = dict(getattr(getattr(error, "response", None), "headers", {}) or {})
                    try:
                        requested_delay = float(headers.get("Retry-After", headers.get("retry-after", 0)) or 0)
                    except (TypeError, ValueError):
                        requested_delay = 0
                    if status == 429:
                        self._rate_limited_until = time.monotonic() + min(120.0, max(30.0, requested_delay))
                        if requested_delay > 8 or retry_index >= 1:
                            raise RuntimeError(_public_model_error(error, prefix="模型结构化响应暂时不可用")) from error
                        delay = min(8.0, max(requested_delay, 2.0))
                    else:
                        delay = min(12.0, max(requested_delay, float(2 ** (retry_index + 1))))
                    if response is not None:
                        close = getattr(response, "close", None)
                        if callable(close):
                            close()
                        response = None
                    time.sleep(delay)
            if response is None:
                raise RuntimeError("模型结构化响应暂时不可用，请稍后重试。")
            content = response.json()["choices"][0]["message"]["content"]
            try:
                return _parse_json_content(content)
            except (TypeError, ValueError, json.JSONDecodeError):
                recovered = _recover_structured_content(content, schema_name=schema_name)
                if recovered is not None:
                    return recovered
        raise ValueError(f"Model did not return valid {schema_name} JSON") from None

    def complete_text(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        if time.monotonic() < self._rate_limited_until:
            raise RuntimeError("模型文本响应暂时受限，已立即保留原文证据。")
        result = complete_chat_text(
            "openai-compatible",
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            timeout=self.timeout,
            session=self.session,
            thinking_mode=self.thinking_mode,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return str(result)


class AnthropicCompatibleChatJsonClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        session: Any | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for anthropic-compatible chat")
        if not api_key:
            raise ValueError("api_key is required for anthropic-compatible chat")
        if not model:
            raise ValueError("model is required for anthropic-compatible chat")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def complete_json(self, messages: list[dict[str, str]], *, schema_name: str) -> Any:
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        conversation = [item for item in messages if item.get("role") in {"user", "assistant"}]
        response = self.session.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 4096,
                "system": "\n\n".join(system_parts) + "\nReturn one valid JSON object only.",
                "messages": conversation,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        content = "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
        return _parse_json_content(content)

    def complete_text(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        result = complete_chat_text(
            "anthropic-compatible",
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            timeout=self.timeout,
            session=self.session,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return str(result)


def build_chat_json_client(
    provider: str,
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    timeout: float = 60.0,
    session: Any | None = None,
    thinking_mode: str | None = None,
) -> ChatJsonClient:
    name = (provider or "").strip().lower()
    if name in {"openai-compatible", "openai"}:
        resolved_base_url = base_url or os.getenv("SCANSCI_CHAT_BASE_URL", "")
        resolved_api_key = api_key or os.getenv("SCANSCI_CHAT_API_KEY", "")
        resolved_model = model or os.getenv("SCANSCI_CHAT_MODEL", "")
        return OpenAICompatibleChatJsonClient(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=resolved_model,
            timeout=timeout,
            session=session,
            thinking_mode=thinking_mode,
        )
    if name in {"anthropic-compatible", "anthropic"}:
        resolved_base_url = base_url or os.getenv("SCANSCI_CHAT_BASE_URL", "")
        resolved_api_key = api_key or os.getenv("SCANSCI_CHAT_API_KEY", "")
        resolved_model = model or os.getenv("SCANSCI_CHAT_MODEL", "")
        return AnthropicCompatibleChatJsonClient(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            model=resolved_model,
            timeout=timeout,
            session=session,
        )
    raise ValueError(f"Unsupported chat provider: {provider}")


def complete_chat_text(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 90.0,
    session: Any | None = None,
    thinking_mode: str | None = None,
    include_usage: bool = False,
    max_tokens: int = 8192,
    temperature: float = 0.4,
) -> str | tuple[str, dict[str, int]]:
    """Return a plain conversational response without requiring a research library."""

    if not base_url:
        raise ValueError("base_url is required for chat")
    if not api_key:
        raise ValueError("api_key is required for chat")
    if not model:
        raise ValueError("model is required for chat")
    if not messages:
        raise ValueError("messages are required")

    name = (provider or "").strip().lower()
    if session is None and _litellm_enabled() and name in {"openai-compatible", "openai", "local", "anthropic-compatible", "anthropic"}:
        return _litellm_complete_chat(
            name,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout=timeout,
            thinking_mode=thinking_mode,
            include_usage=include_usage,
        )

    client = session or requests.Session()
    try:
        if name in {"openai-compatible", "openai", "local"}:
            request_body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max(64, int(max_tokens)),
                "temperature": float(temperature),
                "stream": False,
            }
            if thinking_mode in {"enabled", "disabled"}:
                request_body["thinking"] = {"type": thinking_mode}
            response = None
            for retry_index in range(3):
                try:
                    response = client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json=request_body,
                        timeout=timeout,
                    )
                    response.raise_for_status()
                    break
                except requests.RequestException as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    if status not in {429, 502, 503, 504} or retry_index >= 2:
                        raise
                    headers = dict(getattr(getattr(error, "response", None), "headers", {}) or {})
                    try:
                        requested_delay = float(headers.get("Retry-After", headers.get("retry-after", 0)) or 0)
                    except (TypeError, ValueError):
                        requested_delay = 0
                    time.sleep(min(30.0, max(requested_delay, float(2 ** (retry_index + 1)))))
            if response is None:
                raise RuntimeError("模型服务暂时不可用，请稍后重试。")
            response_payload = response.json()
            content = response_payload["choices"][0]["message"].get("content", "")
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            text = str(content).strip()
            usage = _chat_usage(response_payload)
        elif name in {"anthropic-compatible", "anthropic"}:
            system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
            conversation = [item for item in messages if item.get("role") in {"user", "assistant"}]
            response = client.post(
                f"{base_url.rstrip('/')}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={"model": model, "max_tokens": max(64, int(max_tokens)), "system": system, "messages": conversation},
                timeout=timeout,
            )
            response.raise_for_status()
            response_payload = response.json()
            blocks = response_payload.get("content", [])
            text = "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict)).strip()
            usage = _chat_usage(response_payload)
        else:
            raise ValueError(f"Unsupported chat provider: {provider}")
    except requests.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status == 503:
            raise RuntimeError("内置模型服务尚未启用；请由 ScanSci 管理员保存服务密钥后重试。") from error
        detail = f"（HTTP {status}）" if status else ""
        raise RuntimeError(f"模型服务暂时不可用{detail}，请稍后重试。") from error

    if not text:
        raise RuntimeError("The model returned an empty response")
    if include_usage:
        return text, usage
    return text


def stream_chat_text(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 90.0,
    session: Any | None = None,
    thinking_mode: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield OpenAI-compatible text deltas and a final usage event.

    GLM sends its token accounting in the final SSE chunk.  Keeping that event
    intact lets the local UI show real usage without estimating it in the
    browser.
    """

    if not base_url:
        raise ValueError("base_url is required for chat")
    if not api_key:
        raise ValueError("api_key is required for chat")
    if not model:
        raise ValueError("model is required for chat")
    if not messages:
        raise ValueError("messages are required")

    name = (provider or "").strip().lower()
    if session is None and _litellm_enabled() and name in {"openai-compatible", "openai", "local", "anthropic-compatible", "anthropic"}:
        yield from _litellm_stream_chat(
            name,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout=timeout,
            thinking_mode=thinking_mode,
        )
        return
    if name in {"anthropic-compatible", "anthropic"}:
        completed = complete_chat_text(
            provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout=timeout,
            session=session,
            thinking_mode=thinking_mode,
            include_usage=True,
        )
        text, usage = completed if isinstance(completed, tuple) else (completed, {})
        yield {"type": "delta", "content": text}
        yield {"type": "done", "usage": usage}
        return
    if name not in {"openai-compatible", "openai", "local"}:
        raise ValueError(f"Unsupported chat provider: {provider}")

    client = session or requests.Session()
    continuation_messages = [dict(item) for item in messages]
    complete_text = ""
    total_usage: dict[str, int] = {}
    final_reason = ""
    final_incomplete = False
    max_continuations = 3
    for attempt in range(max_continuations + 1):
        request_body: dict[str, Any] = {
            "model": model,
            "messages": continuation_messages,
            "max_tokens": 8192,
            "temperature": 0.4,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if thinking_mode in {"enabled", "disabled"}:
            request_body["thinking"] = {"type": thinking_mode}

        response: Any | None = None
        attempt_text = ""
        attempt_usage: dict[str, int] = {}
        finish_reason = ""
        try:
            for retry_index in range(3):
                try:
                    response = client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json=request_body,
                        timeout=timeout,
                        stream=True,
                    )
                    response.raise_for_status()
                    break
                except requests.RequestException as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    retryable = status in {429, 502, 503, 504}
                    if not retryable or retry_index >= 2:
                        raise
                    headers = dict(getattr(getattr(error, "response", None), "headers", {}) or {})
                    try:
                        requested_delay = float(headers.get("Retry-After", headers.get("retry-after", 0)) or 0)
                    except (TypeError, ValueError):
                        requested_delay = 0
                    delay = min(30.0, max(requested_delay, float(2 ** (retry_index + 1))))
                    if response is not None:
                        response.close()
                        response = None
                    yield {
                        "type": "retry",
                        "reason": "rate_limit" if status == 429 else "temporary_upstream_error",
                        "status": status,
                        "delay_seconds": delay,
                        "attempt": retry_index + 1,
                    }
                    time.sleep(delay)
            content_type = str(dict(getattr(response, "headers", {}) or {}).get("Content-Type", "")).lower()
            if "text/event-stream" not in content_type:
                raise RuntimeError("The model service did not return a streaming response")
            # Some OpenAI-compatible gateways omit `charset=utf-8` for SSE.
            response.encoding = "utf-8"
            decoder = codecs.getincrementaldecoder("utf-8")()
            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    line = decoder.decode(raw_line + b"\n").rstrip("\r\n")
                else:
                    line = str(raw_line or "")
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_usage = _chat_usage(event)
                if event_usage:
                    attempt_usage = event_usage
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason"))
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                content = delta.get("content", "")
                if isinstance(content, list):
                    content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                fragment = str(content or "")
                if fragment:
                    attempt_text += fragment
                    yield {"type": "delta", "content": fragment}
        except requests.RequestException as error:
            raise RuntimeError(_public_model_error(error, prefix="模型流式响应暂时不可用")) from error
        finally:
            if response is not None:
                response.close()

        complete_text += attempt_text
        total_usage = _merge_chat_usage(total_usage, attempt_usage)
        final_reason = finish_reason
        final_incomplete = _response_needs_continuation(
            finish_reason=finish_reason,
            attempt_text=attempt_text,
            complete_text=complete_text,
            messages=messages,
        )
        if not final_incomplete or attempt >= max_continuations or not attempt_text:
            break
        yield {"type": "continuation", "attempt": attempt + 1}
        continuation_messages = [
            *messages,
            {"role": "assistant", "content": _continuation_context(complete_text, messages)},
            {
                "role": "user",
                "content": (
                    "上一次回复未完整收束。请从断点直接继续，不要重复已有内容，"
                    "不要写‘继续’等过渡语，并务必收束成一个完整答案。"
                    + _completion_marker_reminder(messages)
                ),
            },
        ]
    yield {
        "type": "done",
        "usage": total_usage,
        "finish_reason": final_reason or "stop",
        "truncated": final_incomplete,
    }


def _chat_usage(payload: Any) -> dict[str, int]:
    """Normalize token accounting from OpenAI- and Anthropic-style responses."""

    if not isinstance(payload, dict):
        return {}
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        return {}

    def token_count(*keys: str) -> int | None:
        for key in keys:
            value = raw_usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    prompt_tokens = token_count("prompt_tokens", "input_tokens")
    completion_tokens = token_count("completion_tokens", "output_tokens")
    total_tokens = token_count("total_tokens")
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    usage: dict[str, int] = {}
    if prompt_tokens is not None:
        usage["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        usage["completion_tokens"] = completion_tokens
    if total_tokens is not None:
        usage["total_tokens"] = total_tokens
    return usage


def _merge_chat_usage(total: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    """Add token usage across bounded automatic continuation requests."""

    merged = dict(total)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = current.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            merged[key] = int(merged.get(key, 0)) + value
    return merged


def _litellm_enabled() -> bool:
    if str(os.getenv("SCANSCI_DISABLE_LITELLM", "")).strip().lower() in {"1", "true", "yes"}:
        return False
    try:
        import litellm  # noqa: F401

        return True
    except ImportError:
        return False


def _litellm_model(provider: str, model: str) -> str:
    if provider in {"anthropic-compatible", "anthropic"}:
        return model if model.startswith("anthropic/") else f"anthropic/{model}"
    return model if model.startswith("openai/") else f"openai/{model}"


def _litellm_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump()
        return payload if isinstance(payload, dict) else {}
    mapping = getattr(value, "json", None)
    if callable(mapping):
        try:
            payload = json.loads(mapping())
            return payload if isinstance(payload, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _litellm_kwargs(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    thinking_mode: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": _litellm_model(provider, model),
        "api_base": base_url.rstrip("/"),
        "api_key": api_key,
        "messages": messages,
        "timeout": timeout,
        "temperature": 0.4,
        "max_tokens": 8192,
        "drop_params": True,
        "max_retries": 1,
    }
    if thinking_mode in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking_mode}
    return payload


def _litellm_complete_chat(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    thinking_mode: str | None,
    include_usage: bool,
) -> str | tuple[str, dict[str, int]]:
    import litellm

    try:
        response = litellm.completion(
            **_litellm_kwargs(
                provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=messages,
                timeout=timeout,
                thinking_mode=thinking_mode,
            )
        )
    except Exception as error:  # LiteLLM normalizes provider-specific failures
        raise RuntimeError(_public_model_error(error, prefix="模型服务暂时不可用")) from error
    payload = _litellm_payload(response)
    choices = list(payload.get("choices", []) or [])
    message = dict(choices[0].get("message", {}) or {}) if choices and isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("The model returned an empty response")
    usage = _chat_usage(payload)
    return (text, usage) if include_usage else text


def _litellm_stream_chat(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    thinking_mode: str | None,
) -> Iterator[dict[str, Any]]:
    import litellm

    continuation_messages = [dict(item) for item in messages]
    complete_text = ""
    usage: dict[str, int] = {}
    final_reason = ""
    final_incomplete = False
    max_continuations = 3
    try:
        for attempt in range(max_continuations + 1):
            kwargs = _litellm_kwargs(
                provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=continuation_messages,
                timeout=timeout,
                thinking_mode=thinking_mode,
            )
            kwargs.update({"stream": True, "stream_options": {"include_usage": True}})
            attempt_text = ""
            attempt_usage: dict[str, int] = {}
            finish_reason = ""
            stream = litellm.completion(**kwargs)
            for chunk in stream:
                payload = _litellm_payload(chunk)
                event_usage = _chat_usage(payload)
                if event_usage:
                    attempt_usage = event_usage
                choices = list(payload.get("choices", []) or [])
                choice = dict(choices[0]) if choices and isinstance(choices[0], dict) else {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason"))
                delta = dict(choice.get("delta", {}) or {})
                content = delta.get("content", "")
                if isinstance(content, list):
                    content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                if content:
                    fragment = str(content)
                    attempt_text += fragment
                    yield {"type": "delta", "content": fragment}
            complete_text += attempt_text
            usage = _merge_chat_usage(usage, attempt_usage)
            final_reason = finish_reason
            final_incomplete = _response_needs_continuation(
                finish_reason=finish_reason,
                attempt_text=attempt_text,
                complete_text=complete_text,
                messages=messages,
            )
            if not final_incomplete or attempt >= max_continuations or not attempt_text:
                break
            yield {"type": "continuation", "attempt": attempt + 1}
            continuation_messages = [
                *messages,
                {"role": "assistant", "content": _continuation_context(complete_text, messages)},
                {
                    "role": "user",
                    "content": (
                        "上一次回复未完整收束。请从断点直接继续，不重复已有内容，并完成答案。"
                        + _completion_marker_reminder(messages)
                    ),
                },
            ]
    except Exception as error:
        raise RuntimeError(_public_model_error(error, prefix="模型流式响应暂时不可用")) from error
    yield {
        "type": "done",
        "usage": usage,
        "finish_reason": final_reason or "stop",
        "truncated": final_incomplete,
    }


def _response_needs_continuation(
    *,
    finish_reason: str,
    attempt_text: str,
    complete_text: str,
    messages: list[dict[str, Any]],
) -> bool:
    """Detect provider-side early stops without extending normal short replies."""

    if finish_reason == "length":
        return True
    marker = _requested_completion_marker(messages)
    if marker and not complete_text.rstrip().endswith(marker):
        return True
    value = attempt_text.rstrip()
    if not value:
        return False
    if value.endswith(("#", "**", "```", "：", ":", "，", ",", "（", "(")):
        return True
    return value.count("```") % 2 == 1


def _continuation_context(complete_text: str, messages: list[dict[str, Any]]) -> str:
    """Keep retries below the managed gateway input ceiling without duplication."""

    original_chars = sum(len(str(item.get("content", ""))) for item in messages)
    # Leave headroom for JSON framing and the continuation instruction under
    # the gateway's 48k character request limit.
    budget = max(2_000, 40_000 - original_chars)
    if len(complete_text) <= budget:
        return complete_text
    return "[较早内容已省略，以下为当前断点前的原文]\n" + complete_text[-budget:]


def _requested_completion_marker(messages: list[dict[str, Any]]) -> str:
    user_text = "\n".join(
        str(item.get("content", ""))
        for item in messages
        if str(item.get("role", "")).lower() == "user"
    )
    if not any(signal in user_text.lower() for signal in ("最后", "末尾", "结尾", "last line", "end with")):
        return ""
    markers = re.findall(r"【[^】\r\n]{1,40}】", user_text)
    return markers[-1] if markers else ""


def _completion_marker_reminder(messages: list[dict[str, Any]]) -> str:
    marker = _requested_completion_marker(messages)
    return f" 最后一行必须保留为 {marker}。" if marker else ""


def _public_model_error(error: BaseException, *, prefix: str) -> str:
    """Expose actionable status without reflecting provider secrets or bodies."""

    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return f"{prefix}（HTTP {status}），请稍后重试。" if status else f"{prefix}，请稍后重试。"


def analyze_vision_images(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    question: str,
    images: list[dict[str, str]],
    timeout: float = 90.0,
    session: Any | None = None,
) -> str:
    """Ask an OpenAI- or Anthropic-compatible vision model about local images."""

    if not images:
        raise ValueError("至少需要一张图片")
    if not base_url or not api_key or not model:
        raise ValueError("视觉模型的地址、密钥或模型 ID 尚未配置")
    prompt = (
        "你是 ScanSci 的图片分析助手。请基于用户上传的图片回答问题；"
        "准确区分图片中直接可见的信息和你的推断。图表请说明坐标、图例、趋势与不确定性；"
        "不要虚构论文、引文或实验结果。回答使用中文，简洁但完整。\n\n"
        f"用户问题：{question}"
    )
    kind = str(provider or "").strip().lower()
    active_session = session or requests.Session()
    if kind in {"openai", "openai-compatible"}:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image['mime_type']};base64,{image['data']}"},
            }
            for image in images
        )
        response = active_session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.2},
            timeout=float(timeout),
        )
        response.raise_for_status()
        payload = response.json()
        message = dict((payload.get("choices") or [{}])[0].get("message") or {})
        return _message_text(message.get("content"))
    if kind in {"anthropic", "anthropic-compatible"}:
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image["mime_type"], "data": image["data"]},
            }
            for image in images
        )
        response = active_session.post(
            f"{base_url.rstrip('/')}/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": content}]},
            timeout=float(timeout),
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        return _message_text(blocks)
    raise ValueError(f"当前服务商不支持视觉请求：{provider}")


def _message_text(content: object) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "\n".join(
            str(item.get("text", "")).strip()
            for item in content
            if isinstance(item, dict) and str(item.get("type", "text")) == "text"
        ).strip()
    else:
        text = ""
    if not text:
        raise ValueError("视觉模型没有返回可用文本")
    return text


def _parse_json_content(content: object) -> Any:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        balanced = _first_balanced_json_object(text)
        if balanced is None:
            raise
        return json.loads(balanced)


def _first_balanced_json_object(text: str) -> str | None:
    """Return one complete leading JSON object while rejecting truncation.

    Some compatible models append a Markdown note or one stray closing brace
    after an otherwise valid object. A quote-aware balance scan can discard
    only that suffix; it never invents missing braces for incomplete output.
    """

    start = str(text or "").find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
            if depth < 0:
                return None
    return None


def _with_structured_output_instruction(
    messages: list[dict[str, str]],
    *,
    schema_name: str,
) -> list[dict[str, str]]:
    """Add a portable JSON contract for gateways that ignore response_format."""

    instruction = {
        "answer_claims": (
            'Return only JSON in this exact shape: {"answer":[{"claim_id":"c0001",'
            '"text":"claim text","quote_ids":["q0001"]}],"limitations":[]}. '
            "Return 1 to at most 4 non-overlapping claims, ordered by importance. "
            "Never repeat a claim. Use only quote_ids present in the evidence table. "
            "Stop immediately after the JSON object and do not return Markdown."
        ),
        "claim_verification": (
            'Return only JSON in this exact shape: {"claims":[{"claim_id":"c0001",'
            '"support_status":"supported","verification_score":0.95}]}. '
            "Return exactly one verdict for every supplied claim_id, never repeat a claim_id, "
            "and stop immediately after the JSON object."
        ),
        "retrieval_queries": (
            'Return only JSON in this exact shape: {"queries":["query one","query two"]}. '
            "Return 2 to 4 short, keyword-rich search queries, include one English query when the question is not English, "
            "preserve named entities and numbers, do not answer the question, and do not return Markdown."
        ),
        "evidence_grounded_literature_review": (
            "Return one complete JSON object only, without Markdown fences, using this section shape exactly: "
            '{"sections":[{"id":"...","title":"...","text":"one paragraph","citation_ids":["1"]}]}. '
            "Do not create a paragraphs array. Keep every section from the supplied plan and write exactly one concise "
            "paragraph per section. Keep each Chinese paragraph within 220 Chinese characters "
            "or each English paragraph within 140 words. Use at most three comparison rows, at most two controversies, "
            "and exactly two open questions. Every factual paragraph or row must cite only supplied citation_ids. "
            "Stop immediately after the closing brace."
        ),
        "literature_review_section": (
            'Return only JSON in this exact shape: {"text":"one concise synthesis paragraph",'
            '"citation_ids":["1"]}. Do not add arrays of paragraphs or any other keys. Cite only supplied '
            "citation_ids and stop immediately after the closing brace."
        ),
        "literature_review_overview": (
            'Return only JSON with keys "title", "abstract", "comparison_table", "controversies", '
            '"open_questions", and "limitations". Use abstract {"text":"...","citation_ids":["1"]}; '
            'comparison_table {"columns":["研究对象","方法","主要发现","局限"],"rows":'
            '[{"cells":["...","...","...","..."],"citation_ids":["1"]}]}; controversies as at most two '
            'objects {"text":"...","citation_ids":["1"]}; open_questions as exactly two objects '
            '{"text":"...","basis":"...","citation_ids":["1"]}; and limitations as short strings. '
            "Use only supplied citation_ids, output one complete JSON object, and do not return Markdown."
        ),
    }.get(str(schema_name or ""))
    copied = [dict(item) for item in messages]
    if not instruction:
        return copied
    for item in copied:
        if item.get("role") == "system":
            item["content"] = f"{item.get('content', '').rstrip()}\n\n{instruction}"
            return copied
    return [{"role": "system", "content": instruction}, *copied]


def _recover_structured_content(content: object, *, schema_name: str) -> dict[str, Any] | None:
    """Recover the one safe contract emitted as cited Markdown by some models."""

    if schema_name == "literature_review_section":
        return _recover_known_object_keys(content, ("text", "citation_ids"))
    if schema_name == "literature_review_overview":
        return _recover_known_object_keys(
            content,
            ("title", "abstract", "comparison_table", "controversies", "open_questions", "limitations"),
        )
    if schema_name == "evidence_grounded_literature_review":
        return _recover_review_json(content)
    if schema_name != "answer_claims":
        return None
    text = str(content or "").strip()
    if not text:
        return None
    claims: list[dict[str, Any]] = []
    heading = ""
    for block in re.split(r"\n\s*\n", text):
        clean_block = block.strip()
        quote_ids = list(dict.fromkeys(re.findall(r"\[\s*(q\d{4,})\s*\]", clean_block, flags=re.IGNORECASE)))
        if not quote_ids:
            candidate = re.sub(r"^[#*\s]+|[#*\s]+$", "", clean_block).strip()
            if candidate and "\n" not in candidate and len(candidate) <= 40:
                heading = candidate
            continue
        claim_text = re.sub(r"\[\s*q\d{4,}\s*\]", "", clean_block, flags=re.IGNORECASE)
        claim_text = re.sub(r"^[#*\s]+|[#*\s]+$", "", claim_text).strip()
        if not claim_text:
            continue
        if heading and not claim_text.startswith(heading):
            claim_text = f"{heading}：{claim_text}"
        claims.append(
            {
                "claim_id": f"c{len(claims) + 1:04d}",
                "text": claim_text,
                "quote_ids": [item.lower() for item in quote_ids],
            }
        )
    if not claims:
        return None
    return {"answer": claims, "limitations": []}


def _recover_known_object_keys(content: object, keys: tuple[str, ...]) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    candidate = text
    for key in keys:
        candidate = re.sub(rf'(?<=[,{{])\s*{re.escape(key)}"\s*:', f'"{key}":', candidate)
    try:
        recovered = _parse_json_content(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return recovered if isinstance(recovered, dict) else None


def _recover_review_json(content: object) -> dict[str, Any] | None:
    """Repair two bounded punctuation omissions in the fixed review schema.

    The model sometimes omits either the sections array terminator or the
    opening quote on one of the known top-level keys. Repairs are limited to
    those literal schema keys. The candidate must then pass the regular JSON
    parser; no missing terminal content is invented.
    """

    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    candidate = text
    for key in ("comparison_table", "controversies", "open_questions", "limitations"):
        candidate = re.sub(rf'(?<=[,{{])\s*{re.escape(key)}"\s*:', f'"{key}":', candidate)
    try:
        repaired = _parse_json_content(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        repaired = None
    if isinstance(repaired, dict):
        return repaired

    marker = '"comparison_table"'
    marker_index = candidate.find(marker)
    if marker_index < 0 or '"sections"' not in candidate[:marker_index]:
        return None
    separator_index = candidate.rfind(",", 0, marker_index)
    if separator_index < 0 or _open_json_delimiters(candidate[:separator_index]) != ["{", "["]:
        return None
    candidate = f"{candidate[:separator_index]}]{candidate[separator_index:]}"
    try:
        repaired = _parse_json_content(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return repaired if isinstance(repaired, dict) else None


def _open_json_delimiters(text: str) -> list[str]:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in str(text or ""):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            expected = "{" if char == "}" else "["
            if not stack or stack[-1] != expected:
                return []
            stack.pop()
    return stack
