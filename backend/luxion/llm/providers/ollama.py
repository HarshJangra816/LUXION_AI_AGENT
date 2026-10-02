"""Ollama provider (local models, PRD §5.4).

Protocol: ``POST {base}/api/chat`` with ``stream: true`` returning NDJSON.
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


def _ollama_call(raw: object, position: int) -> ToolCall:
    """Normalise Ollama's ``message.tool_calls[]`` (arguments may be an object)."""
    if not isinstance(raw, dict):
        return ToolCall(id=f"call_{position}", name="unknown", arguments={})
    function = raw.get("function") or {}
    name = str(function.get("name") or "unknown")
    arguments = function.get("arguments")
    if isinstance(arguments, dict):
        parsed: dict = arguments
    else:
        parsed, raw_text = {}, str(arguments or "")
        if raw_text.strip():
            try:
                loaded = json.loads(raw_text)
                parsed = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                return ToolCall(id=f"call_{position}", name=name, raw_arguments=raw_text)
    return ToolCall(id=str(raw.get("id") or f"call_{position}"), name=name, arguments=parsed)


class OllamaProvider(LLMProvider):
    name = "ollama"
    label = "Ollama (local)"
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
            "options": {
                "temperature": self._temperature(temperature),
                "num_predict": self._max_tokens(max_tokens),
            },
        }
        if tools:
            # Ollama's native endpoint takes the same function schema shape.
            payload["tools"] = list(tools)
        return self._stream(payload, model=model)

    async def _stream(self, payload: dict[str, Any], *, model: str) -> AsyncIterator[StreamEvent]:
        client = self._ensure_client()
        try:
            async with client.stream(
                "POST", self._url("/api/chat"), json=payload, headers=self._headers()
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise error_from_response(response.status_code, body, self.name)
                async for event in self._read_ndjson(response, model=model):
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
                f"Cannot reach Ollama at {self.base_url}. Is `ollama serve` running?",
                provider=self.name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                f"{self.name} transport error: {exc}", provider=self.name
            ) from exc

    async def _read_ndjson(
        self, response: httpx.Response, *, model: str
    ) -> AsyncIterator[StreamEvent]:
        finish_reason: str | None = None
        usage: TokenUsage | None = None
        tool_calls: list[ToolCall] = []
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderResponseError(
                    f"{self.name} sent malformed JSON: {line[:200]}", provider=self.name
                ) from exc
            if error := data.get("error"):
                raise ProviderResponseError(f"{self.name}: {error}", provider=self.name)

            message = data.get("message") or {}
            content = message.get("content")
            if content:
                yield StreamDelta(text=content)
            for call in message.get("tool_calls") or []:
                tool_calls.append(_ollama_call(call, len(tool_calls) + 1))

            if data.get("done"):
                prompt = data.get("prompt_eval_count")
                completion = data.get("eval_count")
                total = (
                    (prompt + completion) if prompt is not None and completion is not None else None
                )
                usage = TokenUsage(
                    prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
                )
                finish_reason = data.get("done_reason") or ("tool_calls" if tool_calls else "stop")
                yield StreamDone(
                    finish_reason=finish_reason,
                    usage=usage,
                    model=model,
                    tool_calls=tool_calls or None,
                )
                return
        yield StreamDone(
            finish_reason=finish_reason,
            usage=usage,
            model=model,
            tool_calls=tool_calls or None,
        )

    async def list_models(self) -> list[str]:
        if self._models_cache is not None:
            return self._models_cache
        client = self._ensure_client()
        try:
            response = await client.get(self._url("/api/tags"), headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.name} timed out listing models", provider=self.name
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"Cannot reach Ollama at {self.base_url}", provider=self.name
            ) from exc
        if response.status_code != 200:
            raise error_from_response(response.status_code, response.text, self.name)
        names = [
            str(item.get("name") or item.get("model"))
            for item in response.json().get("models", [])
            if item.get("name") or item.get("model")
        ]
        self._models_cache = names
        return names
