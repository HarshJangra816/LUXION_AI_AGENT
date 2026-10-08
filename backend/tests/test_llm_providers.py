"""LLM provider abstraction: protocol parsing, error mapping, registry."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from luxion.config.settings import LLMConfig, Settings, get_settings
from luxion.llm.base import LLMProvider
from luxion.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderResponseError,
)
from luxion.llm.providers import OllamaProvider, OpenAICompatProvider
from luxion.llm.registry import create_provider, get_provider
from luxion.llm.system_prompt import build_system_prompt
from luxion.llm.types import ChatMessage, StreamDelta, StreamDone

MESSAGES = [ChatMessage(role="user", content="hi")]


def _events(provider: LLMProvider, *, model: str = "test-model") -> list:
    async def run() -> list:
        collected = []
        async for event in provider.stream(MESSAGES, model=model):
            collected.append(event)
        return collected

    return asyncio.run(run())


def _provider(provider_type: type[LLMProvider], handler, **config) -> LLMProvider:  # noqa: ANN001
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider_type(LLMConfig(**config), client=client)


# --------------------------------------------------------------------- ollama
def _ollama_done_line() -> str:
    return json.dumps(
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 2,
        }
    )


def _ollama_ok(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
    payload = json.loads(request.content)
    assert payload["stream"] is True
    assert payload["think"] is False
    assert payload["messages"][0]["role"] == "user"
    lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hel"}}),
        json.dumps({"message": {"role": "assistant", "content": "lo"}}),
        _ollama_done_line(),
    ]
    return httpx.Response(200, text="\n".join(lines))


def test_ollama_streams_ndjson_deltas() -> None:
    provider = _provider(OllamaProvider, _ollama_ok, provider="ollama")
    events = _events(provider)

    text = "".join(event.text for event in events if isinstance(event, StreamDelta))
    assert text == "Hello"
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.finish_reason == "stop"
    assert done.usage is not None
    assert done.usage.prompt_tokens == 4
    assert done.usage.total_tokens == 6


def test_ollama_forwards_the_think_switch() -> None:
    """A reasoning model that is allowed to think is asked to do so."""
    seen: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bool(json.loads(request.content)["think"]))
        return httpx.Response(200, text=_ollama_done_line())

    provider = _provider(OllamaProvider, handler, provider="ollama", think=True)
    _events(provider)
    assert seen == [True]


def test_ollama_unknown_model_is_model_not_found() -> None:
    provider = _provider(
        OllamaProvider,
        lambda request: httpx.Response(404, text='{"error":"model not found"}'),
        provider="ollama",
    )
    with pytest.raises(ModelNotFoundError):
        _events(provider)


def test_ollama_unreachable_maps_to_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(OllamaProvider, handler, provider="ollama")
    with pytest.raises(ProviderConnectionError) as excinfo:
        _events(provider)
    assert "ollama serve" in str(excinfo.value)


def test_ollama_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    provider = _provider(OllamaProvider, handler, provider="ollama")
    assert asyncio.run(provider.list_models()) == ["llama3:8b"]


# ---------------------------------------------------------------- openai-compat
def _openai_ok(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
    chunks = [
        {"choices": [{"delta": {"content": "Hi "}}]},
        {"choices": [{"delta": {"content": "there"}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
    ]
    body = "\n".join(f"data: {json.dumps(chunk)}" for chunk in chunks) + "\ndata: [DONE]\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_openai_compat_parses_sse_and_usage() -> None:
    provider = _provider(
        OpenAICompatProvider,
        _openai_ok,
        provider="openai",
        base_url="https://api.example.com",
        api_key="sk-test",
    )
    events = _events(provider)

    text = "".join(event.text for event in events if isinstance(event, StreamDelta))
    assert text == "Hi there"
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.finish_reason == "stop"
    assert done.usage is not None
    assert done.usage.total_tokens == 10


def test_openai_compat_missing_key_maps_to_auth_error() -> None:

    provider = _provider(
        OpenAICompatProvider,
        lambda request: httpx.Response(401, text='{"error":{"message":"bad key"}}'),
        provider="openai",
        base_url="https://api.example.com",
    )
    with pytest.raises(ProviderAuthError):
        _events(provider)


def test_openai_compat_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})

    provider = _provider(
        OpenAICompatProvider,
        handler,
        provider="openai",
        base_url="https://api.example.com",
        api_key="sk-test",
    )
    assert asyncio.run(provider.list_models()) == ["gpt-4o-mini"]


# ----------------------------------------------------------------------- mock
def test_mock_provider_streams_without_network() -> None:
    provider = create_provider(LLMConfig(provider="mock"))
    events = _events(provider, model="mock-1")
    text = "".join(event.text for event in events if isinstance(event, StreamDelta))
    assert "Luxion mock reply" in text
    assert isinstance(events[-1], StreamDone)


def test_mock_provider_forced_failure() -> None:
    provider = create_provider(LLMConfig(provider="mock"))
    messages = [ChatMessage(role="user", content="FAIL")]
    with pytest.raises(ProviderResponseError):

        async def run() -> None:
            async for _ in provider.stream(messages, model="mock-1"):
                pass

        asyncio.run(run())


# -------------------------------------------------------------------- registry
def test_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_provider(LLMConfig(provider="nope"))


def test_registry_caches_until_config_changes() -> None:
    first = get_provider(LLMConfig(provider="mock"))
    assert get_provider(LLMConfig(provider="mock")) is first
    other = get_provider(LLMConfig(provider="mock", model="other-model"))
    assert other is not first


def test_resolve_model_prefers_configured_model() -> None:
    provider = create_provider(LLMConfig(provider="mock", model="my-model"))
    assert asyncio.run(provider.resolve_model()) == "my-model"


def test_resolve_model_falls_back_to_reported_models() -> None:
    provider = create_provider(LLMConfig(provider="mock"))
    assert asyncio.run(provider.resolve_model()) == "mock-1"


def test_resolve_model_raises_when_nothing_configured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json={"models": []})

    provider = _provider(OllamaProvider, handler, provider="ollama")
    with pytest.raises(ModelNotFoundError):
        asyncio.run(provider.resolve_model())


# ------------------------------------------------------------- system prompt
def test_default_system_prompt_identifies_luxion() -> None:
    prompt = build_system_prompt(get_settings())
    assert "Luxion" in prompt
    assert "Autonomy: level" in prompt
    assert "Current UTC time:" in prompt


def test_custom_system_prompt_overrides_default() -> None:
    settings = Settings(llm={"system_prompt": "custom rules only"})
    assert build_system_prompt(settings) == "custom rules only"
