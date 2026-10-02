"""OpenAI-compatible chat provider (PRD §3.4 provider independence).

Covers OpenAI, Groq, DeepSeek, Together, LM Studio, vLLM, Ollama's ``/v1``
gateway — anything speaking ``POST /v1/chat/completions`` with SSE streaming.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from luxion.llm.base import LLMProvider
from luxion.llm.errors import (
    LLMError,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
    error_from_response,
)
from luxion.llm.types import (
    ChatMessage,
    StreamDelta,
    StreamDone,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolSchema,
)


def _as_int(value: object) -> int | None:
    """Coerce a provider-supplied count to ``int`` (None when unusable)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    """Coerce a provider-supplied money/count value to ``float``."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _absorb_fragment(fragments: dict[int, dict[str, str]], raw: object) -> None:
    """Merge one streamed ``delta.tool_calls[]`` entry into the accumulator.

    Providers send the id/name once and the arguments JSON in arbitrary
    chunks, always keyed by ``index``.
    """
    if not isinstance(raw, dict):
        return
    index = _as_int(raw.get("index")) or 0
    slot = fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if value := raw.get("id"):
        slot["id"] = str(value)
    function = raw.get("function")
    if isinstance(function, dict):
        if name := function.get("name"):
            slot["name"] += str(name)
        if arguments := function.get("arguments"):
            slot["arguments"] += str(arguments)


def _collect_calls(fragments: dict[int, dict[str, str]]) -> list[ToolCall] | None:
    """Turn accumulated fragments into :class:`ToolCall`s (sorted by index)."""
    if not fragments:
        return None
    calls: list[ToolCall] = []
    for position, index in enumerate(sorted(fragments), start=1):
        slot = fragments[index]
        if not slot["name"]:
            continue
        calls.append(
            ToolCall.from_fragments(
                id=slot["id"] or f"call_{position}",
                name=slot["name"],
                raw=slot["arguments"],
            )
        )
    return calls or None


class OpenAICompatProvider(LLMProvider):
    name = "openai"
    label = "OpenAI-compatible API"
    requires_api_key = True
    requires_base_url = True

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.as_provider_payload() for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": self._temperature(temperature),
            "max_tokens": self._max_tokens(max_tokens),
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        return self._stream(payload, model=model)

    async def _stream(self, payload: dict[str, Any], *, model: str) -> AsyncIterator[StreamEvent]:
        client = self._ensure_client()
        try:
            async with client.stream(
                "POST", self._url("/v1/chat/completions"), json=payload, headers=self._headers()
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise error_from_response(response.status_code, body, self.name)
                async for event in self._read_sse(response, model=model):
                    yield event
        except LLMError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.name} timed out after {self.config.request_timeout_s}s",
                provider=self.name,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"Cannot reach {self.base_url}", provider=self.name
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                f"{self.name} transport error: {exc}", provider=self.name
            ) from exc

    async def _read_sse(
        self, response: httpx.Response, *, model: str
    ) -> AsyncIterator[StreamEvent]:
        finish_reason: str | None = None
        usage: TokenUsage | None = None
        #: index → {id, name, arguments} while the model streams a tool call.
        fragments: dict[int, dict[str, str]] = {}
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if error := chunk.get("error"):
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise ProviderResponseError(f"{self.name}: {message}", provider=self.name)

            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if content := delta.get("content"):
                    yield StreamDelta(text=content)
                for fragment in delta.get("tool_calls") or []:
                    _absorb_fragment(fragments, fragment)
                if reason := choice.get("finish_reason"):
                    finish_reason = reason
            if raw_usage := chunk.get("usage"):
                details = raw_usage.get("prompt_tokens_details") or {}
                usage = TokenUsage(
                    prompt_tokens=_as_int(raw_usage.get("prompt_tokens")),
                    completion_tokens=_as_int(raw_usage.get("completion_tokens")),
                    total_tokens=_as_int(raw_usage.get("total_tokens")),
                    cost=_as_float(raw_usage.get("cost")),
                    cached_tokens=_as_int(details.get("cached_tokens")),
                )

        tool_calls = _collect_calls(fragments)
        if tool_calls and finish_reason in (None, "stop"):
            finish_reason = "tool_calls"
        yield StreamDone(
            finish_reason=finish_reason, usage=usage, model=model, tool_calls=tool_calls
        )

    async def list_models(self) -> list[str]:
        if self._models_cache is not None:
            return self._models_cache
        client = self._ensure_client()
        try:
            response = await client.get(self._url("/v1/models"), headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.name} timed out listing models", provider=self.name
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"Cannot reach {self.base_url}", provider=self.name
            ) from exc
        if response.status_code != 200:
            raise error_from_response(response.status_code, response.text, self.name)
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else payload
        self._models_cache = [
            str(item["id"]) for item in items or [] if isinstance(item, dict) and item.get("id")
        ]
        return self._models_cache
