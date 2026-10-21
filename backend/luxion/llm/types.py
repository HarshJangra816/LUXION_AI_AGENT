"""Provider-agnostic chat types.

Providers only ever exchange these shapes, so adding a provider never changes
the service or API layers.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]

#: Provider-agnostic ``tools[]`` schema entry (OpenAI/Ollama function calling).
ToolSchema = dict[str, Any]


class ImagePayload(BaseModel):
    """One image attached to a chat turn (PRD §5.9 vision models).

    ``data`` is **raw base64** without a ``data:`` prefix — Ollama's
    ``/api/chat`` wants exactly that, and the OpenAI-compatible side is
    derived from it via :attr:`data_url`.
    """

    data: str
    mime: str = "image/png"

    @property
    def data_url(self) -> str:
        """``data:<mime>;base64,<data>`` — the OpenAI ``image_url`` form."""
        return f"data:{self.mime};base64,{self.data}"


class ToolCall(BaseModel):
    """One function invocation requested by the model (PRD §3.1)."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: Raw JSON the model produced, kept when it could not be parsed.
    raw_arguments: str | None = None

    @classmethod
    def from_fragments(cls, *, id: str, name: str, raw: str) -> ToolCall:
        """Build a call from streamed fragments, tolerating broken JSON."""
        text = (raw or "").strip()
        if not text:
            return cls(id=id, name=name, arguments={})
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return cls(id=id, name=name, arguments={}, raw_arguments=text)
        if not isinstance(parsed, dict):
            return cls(id=id, name=name, arguments={}, raw_arguments=text)
        return cls(id=id, name=name, arguments=parsed)

    def as_provider_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


class ChatMessage(BaseModel):
    """One chat turn as understood by every provider."""

    role: Role
    content: str
    #: Set on an assistant message that requested tool calls.
    tool_calls: list[ToolCall] | None = None
    #: Set on a ``role="tool"`` message: the call it answers.
    tool_call_id: str | None = None
    #: Images attached to this turn (PRD §5.9). Providers that cannot see
    #: pictures ignore them — the chat tools keep working unchanged.
    images: list[ImagePayload] = Field(default_factory=list)

    def as_provider_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.as_provider_payload() for call in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        return payload


def ollama_message_payload(message: ChatMessage) -> dict[str, Any]:
    """Shape one message for Ollama's ``/api/chat``.

    Ollama takes images as a sibling ``images[]`` array of base64 strings
    (no ``data:`` prefix), which is why the images live on the message rather
    than inside ``content``.
    """
    payload = message.as_provider_payload()
    if message.images:
        payload["images"] = [image.data for image in message.images]
    return payload


def openai_message_payload(message: ChatMessage) -> dict[str, Any]:
    """Shape one message for ``/v1/chat/completions``.

    OpenAI-compatible endpoints want the multimodal ``content`` array: one
    ``text`` part followed by one ``image_url`` part per image.
    """
    payload = message.as_provider_payload()
    if not message.images:
        return payload
    content: list[dict[str, Any]] = [{"type": "text", "text": payload["content"]}]
    content.extend(
        {"type": "image_url", "image_url": {"url": image.data_url}} for image in message.images
    )
    payload["content"] = content
    return payload


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    #: Actual spend reported by the provider, in USD. OpenRouter reports this
    #: on every response; other providers usually leave it unset (PRD §45).
    cost: float | None = None
    #: Prompt tokens the provider served from its cache (PRD §45).
    cached_tokens: int | None = None

    @classmethod
    def merge(cls, parts: list[TokenUsage | None]) -> TokenUsage | None:
        """Sum a multi-round agent turn into one usage record (PRD §45)."""
        present = [part for part in parts if part is not None]
        if not present:
            return None

        def _sum(getter) -> int | None:  # noqa: ANN001
            values = [getter(part) for part in present]
            return None if any(value is None for value in values) else sum(values)  # type: ignore[arg-type]

        costs = [part.cost for part in present]
        cached = [part.cached_tokens for part in present]
        return cls(
            prompt_tokens=_sum(lambda p: p.prompt_tokens),
            completion_tokens=_sum(lambda p: p.completion_tokens),
            total_tokens=_sum(lambda p: p.total_tokens),
            cost=None if any(value is None for value in costs) else round(sum(costs), 8),  # type: ignore[arg-type]
            cached_tokens=(
                None if any(value is None for value in cached) else sum(cached)  # type: ignore[arg-type]
            ),
        )


class StreamDelta(BaseModel):
    """Incremental assistant text."""

    type: Literal["delta"] = "delta"
    text: str


class StreamDone(BaseModel):
    """Terminal success event."""

    type: Literal["done"] = "done"
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    model: str | None = None
    #: Present when the model asked to call tools instead of answering
    #: (``finish_reason`` is then ``"tool_calls"``).
    tool_calls: list[ToolCall] | None = None


class StreamError(BaseModel):
    """Terminal failure event (only produced by the service layer)."""

    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False


StreamEvent = StreamDelta | StreamDone
