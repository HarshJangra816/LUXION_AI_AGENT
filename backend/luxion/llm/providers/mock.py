"""Offline provider used by tests and by ``LUXION_LLM__PROVIDER=mock``.

It never touches the network, which keeps the chat pipeline (history,
streaming, persistence, error mapping, **tool calling**) fully testable
without a live model.

Tool-call protocol (only when ``tools`` were offered): a user message
containing ``USE_TOOL <name>`` — optionally followed by a JSON object of
arguments — makes the model request that call *once*. The follow-up request
carries the ``role="tool"`` result, which suppresses the trigger and produces a
normal reply, so the agent loop terminates deterministically.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from luxion.config.settings import LLMConfig
from luxion.llm.base import LLMProvider
from luxion.llm.errors import ProviderResponseError
from luxion.llm.types import (
    ChatMessage,
    StreamDelta,
    StreamDone,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolSchema,
)

DEFAULT_REPLY = (
    "Luxion mock reply: I received your message and everything up to the model router is working."
)

_TRIGGER = re.compile(r"USE_TOOL\s+(?P<name>[A-Za-z0-9_]+)\s*(?P<args>\{.*?\})?", re.DOTALL)


class MockProvider(LLMProvider):
    name = "mock"
    label = "Mock (offline)"
    requires_api_key = False
    requires_base_url = False

    def __init__(self, config: LLMConfig, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config, client)
        self._models_cache = ["mock-1"]

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, model=model, tools=tools)

    async def _stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        prompt_tokens = sum(len(message.content.split()) for message in messages)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=0, total_tokens=prompt_tokens
        )

        tool_call = self._pending_tool_call(messages) if tools else None
        if tool_call is not None:
            yield StreamDone(
                finish_reason="tool_calls",
                usage=usage,
                model=model,
                tool_calls=[tool_call],
            )
            return

        reply = self._reply_for(messages)
        # Chunk by word so the frontend has to handle real incremental deltas.
        pieces = reply.split(" ")
        for index, word in enumerate(pieces):
            yield StreamDelta(text=word if index == len(pieces) - 1 else f"{word} ")
            if self.config.mock_delay_s:
                await asyncio.sleep(self.config.mock_delay_s)
        yield StreamDone(
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=len(pieces),
                total_tokens=prompt_tokens + len(pieces),
            ),
            model=model,
        )

    def _pending_tool_call(self, messages: Sequence[ChatMessage]) -> ToolCall | None:
        """Emit the requested call only on the first round of the turn."""
        if messages and messages[-1].role == "tool":
            return None
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        match = _TRIGGER.search(last_user)
        if not match:
            return None
        raw_args = match.group("args")
        arguments: dict[str, Any] = {}
        if raw_args:
            try:
                loaded = json.loads(raw_args)
                arguments = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                return None
        return ToolCall(id="call_mock_1", name=match.group("name"), arguments=arguments)

    def _reply_for(self, messages: Sequence[ChatMessage]) -> str:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "FAIL" in last_user.upper():
            raise ProviderResponseError("mock provider forced failure", provider=self.name)
        if messages and messages[-1].role == "tool":
            return f"{DEFAULT_REPLY}\n\nTool said: {messages[-1].content}"
        return f"{DEFAULT_REPLY}\n\nYou said: {last_user}"

    async def list_models(self) -> list[str]:
        return list(self._models_cache or [])
