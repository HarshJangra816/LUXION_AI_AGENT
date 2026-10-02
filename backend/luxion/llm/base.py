"""Provider interface implemented by every LLM backend.

Contract
--------
* ``stream()`` yields :class:`StreamDelta` chunks followed by exactly one
  :class:`StreamDone`, or raises an :class:`LLMError`.
* ``list_models()`` returns the model ids the endpoint offers (used both for
  the Settings page and to resolve an empty ``llm.model``).
* ``health()`` never raises; it reports reachability for the UI.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence

import httpx
from pydantic import BaseModel

from luxion.config.settings import LLMConfig
from luxion.llm.errors import ModelNotFoundError
from luxion.llm.types import (
    ChatMessage,
    StreamDelta,
    StreamDone,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolSchema,
)


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    base_url: str
    models: list[str] = []
    error: str | None = None
    latency_ms: float | None = None


class CompletionResult(BaseModel):
    """Non-streaming convenience wrapper around the streaming contract."""

    text: str
    model: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None


class LLMProvider(ABC):
    """A chat-completion backend (cloud API or local runtime)."""

    name: str = ""
    label: str = ""
    requires_api_key: bool = False
    requires_base_url: bool = False
    #: Env var consulted when ``llm.api_key_env`` is empty (provider default).
    default_api_key_env: str = ""

    def __init__(self, config: LLMConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None
        self._models_cache: list[str] | None = None
        self._resolved_model: str | None = None

    # ------------------------------------------------------------------ http
    @property
    def base_url(self) -> str:
        """Effective endpoint for this provider.

        Defaults to the configured URL; providers with a fixed or
        provider-supplied endpoint (Ollama, OpenRouter) override this.
        """
        return (self.config.base_url or "").strip().rstrip("/")

    @property
    def api_key(self) -> str | None:
        """Resolved from ``llm.api_key`` or an env var (``llm.api_key_env``,
        falling back to the provider's own ``default_api_key_env``)."""
        if self.config.api_key:
            return self.config.api_key
        env = self.config.api_key_env or self.default_api_key_env
        if env:
            return os.environ.get(env) or None
        return None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout_s, connect=10.0),
                follow_redirects=True,
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ api
    @abstractmethod
    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield ``StreamDelta`` chunks then one ``StreamDone``.

        ``tools`` is the provider's ``tools[]`` payload; providers that do not
        support function calling may ignore it.
        """

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Model ids offered by this endpoint (cached)."""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> CompletionResult:
        """Buffer the stream into a single completion (tests, non-chat callers)."""
        parts: list[str] = []
        done: StreamDone | None = None
        async for event in self.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        ):
            if isinstance(event, StreamDelta):
                parts.append(event.text)
            else:
                done = event
        return CompletionResult(
            text="".join(parts),
            model=done.model if done else model,
            finish_reason=done.finish_reason if done else None,
            usage=done.usage if done else None,
            tool_calls=done.tool_calls if done else None,
        )

    async def resolve_model(self) -> str:
        """Configured model, or the first model the endpoint reports."""
        if self.config.model:
            return self.config.model
        if self._resolved_model:
            return self._resolved_model
        models = await self.list_models()
        if not models:
            raise ModelNotFoundError(
                f"Provider '{self.name}' reports no models and LUXION_LLM__MODEL is empty.",
                provider=self.name,
            )
        self._resolved_model = models[0]
        return self._resolved_model

    async def health(self) -> ProviderHealth:
        """Reachability probe. Never raises."""
        started = time.perf_counter()
        try:
            models = await self.list_models()
        except Exception as exc:  # noqa: BLE001 - health must stay reportable
            return ProviderHealth(
                provider=self.name,
                ok=False,
                base_url=self.base_url,
                error=str(exc) or exc.__class__.__name__,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        return ProviderHealth(
            provider=self.name,
            ok=True,
            base_url=self.base_url,
            models=models,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # --------------------------------------------------------------- helpers
    def _temperature(self, override: float | None) -> float:
        return self.config.temperature if override is None else override

    def _max_tokens(self, override: int | None) -> int:
        return self.config.max_tokens if override is None else override
