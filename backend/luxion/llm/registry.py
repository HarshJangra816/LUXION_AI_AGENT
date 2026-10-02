"""Provider registry.

``get_provider()`` returns a cached instance for the active configuration so
an HTTP client (and its connection pool) is reused across requests. Changing
``LUXION_LLM__*`` values invalidates the cache automatically.
"""

from __future__ import annotations

from luxion.config.settings import LLMConfig, get_settings
from luxion.llm.base import LLMProvider, ProviderHealth
from luxion.llm.providers import (
    MockProvider,
    OllamaProvider,
    OpenAICompatProvider,
    OpenRouterProvider,
)

PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatProvider,
    "openai_compatible": OpenAICompatProvider,
    "openrouter": OpenRouterProvider,
    "mock": MockProvider,
}

#: Provider ids exposed in Settings with their human label + requirements.
PROVIDER_SPECS: list[dict[str, object]] = [
    {"id": "ollama", "label": "Ollama (local)", "requires_api_key": False, "local": True},
    {"id": "openai", "label": "OpenAI-compatible API", "requires_api_key": True, "local": False},
    {
        "id": "openrouter",
        "label": "OpenRouter (500+ models)",
        "requires_api_key": True,
        "local": False,
    },
    {
        "id": "openai_compatible",
        "label": "Custom OpenAI-compatible endpoint",
        "requires_api_key": False,
        "local": True,
    },
    {"id": "mock", "label": "Mock (offline)", "requires_api_key": False, "local": True},
]

_active: LLMProvider | None = None
_active_key: tuple[str, str, str, str] | None = None


def _cache_key(config: LLMConfig) -> tuple[str, str, str, str]:
    return (config.provider, config.base_url, config.model, config.api_key_env)


def create_provider(config: LLMConfig) -> LLMProvider:
    """Build a provider instance for ``config`` (no caching)."""
    try:
        provider_type = PROVIDER_TYPES[config.provider]
    except KeyError:
        known = ", ".join(sorted(PROVIDER_TYPES))
        raise ValueError(f"Unknown LLM provider '{config.provider}'. Known: {known}.") from None
    return provider_type(config)


def get_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Return the cached provider for the current configuration."""
    global _active, _active_key
    resolved = config if config is not None else get_settings().llm
    key = _cache_key(resolved)
    if _active is None or _active_key != key:
        _active = create_provider(resolved)
        _active_key = key
    return _active


def reset_provider() -> None:
    """Drop the cached provider (tests). HTTP clients close on GC."""
    global _active, _active_key
    _active = None
    _active_key = None


async def aclose_provider() -> None:
    """Close the cached provider's HTTP client on shutdown."""
    global _active, _active_key
    if _active is not None:
        await _active.aclose()
    _active = None
    _active_key = None


async def provider_health(config: LLMConfig | None = None) -> ProviderHealth:
    return await get_provider(config).health()
