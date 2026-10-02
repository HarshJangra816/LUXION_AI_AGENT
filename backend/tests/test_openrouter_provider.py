"""OpenRouter provider: defaults, key resolution, usage/cost capture."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from luxion.api.schemas import build_llm_status
from luxion.config.settings import LLMConfig, Settings, get_settings
from luxion.llm.providers import OpenRouterProvider
from luxion.llm.providers.openrouter import DEFAULT_BASE_URL
from luxion.llm.registry import PROVIDER_SPECS, create_provider
from luxion.llm.types import ChatMessage, StreamDelta, StreamDone, TokenUsage
from luxion.services.chat import _persist_assistant

MESSAGES = [ChatMessage(role="user", content="hi")]


def _events(provider, *, model: str = "openrouter/test") -> list:  # noqa: ANN001
    async def run() -> list:
        collected = []
        async for event in provider.stream(MESSAGES, model=model):
            collected.append(event)
        return collected

    return asyncio.run(run())


def _provider(handler, **config) -> OpenRouterProvider:  # noqa: ANN001
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterProvider(LLMConfig(provider="openrouter", **config), client=client)


# ------------------------------------------------------------------ defaults
def test_base_url_defaults_to_openrouter_when_config_holds_local_ollama() -> None:
    # LLMConfig's own default points at Ollama; switching provider must not keep it.
    provider = create_provider(LLMConfig(provider="openrouter"))
    assert provider.base_url == DEFAULT_BASE_URL


def test_base_url_defaults_to_openrouter_when_empty() -> None:
    provider = create_provider(LLMConfig(provider="openrouter", base_url=""))
    assert provider.base_url == DEFAULT_BASE_URL


def test_configured_base_url_is_used_and_stripped() -> None:
    provider = create_provider(
        LLMConfig(provider="openrouter", base_url="https://proxy.example/v1/")
    )
    assert provider.base_url == "https://proxy.example/v1"


def test_api_key_env_defaults_to_openrouter_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert create_provider(LLMConfig(provider="openrouter")).api_key is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    assert create_provider(LLMConfig(provider="openrouter")).api_key == "sk-or-env"


def test_configured_api_key_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTOM_KEY", "sk-custom")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = create_provider(LLMConfig(provider="openrouter", api_key_env="CUSTOM_KEY"))
    assert provider.api_key == "sk-custom"


def test_inline_api_key_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    provider = create_provider(LLMConfig(provider="openrouter", api_key="sk-or-inline"))
    assert provider.api_key == "sk-or-inline"


# --------------------------------------------------------------- registration
def test_openrouter_is_registered() -> None:
    assert isinstance(create_provider(LLMConfig(provider="openrouter")), OpenRouterProvider)
    assert any(spec["id"] == "openrouter" for spec in PROVIDER_SPECS)


def test_status_reports_openrouter_label_and_key_env() -> None:
    status = build_llm_status(Settings(llm={"provider": "openrouter"}))
    assert status.provider == "openrouter"
    assert "OpenRouter" in status.label
    assert status.api_key_env == "OPENROUTER_API_KEY"
    assert status.base_url == DEFAULT_BASE_URL


# ---------------------------------------------------------------- streaming
def _openrouter_ok(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
    assert str(request.url).startswith(f"{DEFAULT_BASE_URL}/v1/chat/completions")
    assert request.headers["x-title"] == "Luxion"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    chunks = [
        {"choices": [{"delta": {"content": "Hi "}}]},
        {"choices": [{"delta": {"content": "there"}, "finish_reason": "stop"}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "cost": 0.00421,
                "prompt_tokens_details": {"cached_tokens": 96},
            },
        },
    ]
    body = "\n".join(f"data: {json.dumps(chunk)}" for chunk in chunks) + "\ndata: [DONE]\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_stream_parses_usage_cost_and_cached_tokens() -> None:
    provider = _provider(_openrouter_ok, api_key="sk-or-test")
    events = _events(provider)

    text = "".join(event.text for event in events if isinstance(event, StreamDelta))
    assert text == "Hi there"
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.finish_reason == "stop"
    assert done.usage is not None
    assert done.usage.total_tokens == 150
    assert done.usage.cost == pytest.approx(0.00421)
    assert done.usage.cached_tokens == 96


def test_usage_without_cost_leaves_cost_unset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        chunks = [
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
            {"usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
        ]
        body = "\n".join(f"data: {json.dumps(chunk)}" for chunk in chunks) + "\ndata: [DONE]\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    done = _events(_provider(handler, api_key="sk-or-test"))[-1]
    assert isinstance(done, StreamDone)
    assert done.usage is not None
    assert done.usage.cost is None
    assert done.usage.cached_tokens is None


def test_list_models_reads_openrouter_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek/deepseek-chat"},
                    {"id": "meta-llama/llama-3.3-70b"},
                ]
            },
        )

    provider = _provider(handler, api_key="sk-or-test")
    assert asyncio.run(provider.list_models()) == [
        "deepseek/deepseek-chat",
        "meta-llama/llama-3.3-70b",
    ]


# --------------------------------------------------------- cost persistence
def test_persist_assistant_stores_provider_cost(client: TestClient) -> None:
    conversation_id = client.post("/api/conversations", json={"title": "cost"}).json()["id"]
    message_id = _persist_assistant(
        conversation_id,
        "answer",
        usage=TokenUsage(prompt_tokens=120, completion_tokens=30, cost=0.00421),
    )

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    message = next(item for item in detail["messages"] if item["id"] == message_id)
    assert message["cost_usd"] == pytest.approx(0.00421)


def test_persist_assistant_omits_cost_when_provider_reports_none(client: TestClient) -> None:
    conversation_id = client.post("/api/conversations", json={"title": "no cost"}).json()["id"]
    message_id = _persist_assistant(
        conversation_id,
        "answer",
        usage=TokenUsage(prompt_tokens=120, completion_tokens=30),
    )

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    message = next(item for item in detail["messages"] if item["id"] == message_id)
    assert message["cost_usd"] is None


def test_settings_default_base_url_is_the_local_ollama_endpoint() -> None:
    assert get_settings().llm.base_url == "http://127.0.0.1:11434"
