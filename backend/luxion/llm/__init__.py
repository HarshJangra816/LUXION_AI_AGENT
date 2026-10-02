"""LLM subsystem: provider abstraction, registry and system prompt."""

from luxion.llm.base import CompletionResult, LLMProvider, ProviderHealth
from luxion.llm.errors import (
    LLMError,
    ModelNotFoundError,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from luxion.llm.registry import (
    PROVIDER_SPECS,
    PROVIDER_TYPES,
    aclose_provider,
    create_provider,
    get_provider,
    provider_health,
    reset_provider,
)
from luxion.llm.system_prompt import build_system_prompt
from luxion.llm.types import (
    ChatMessage,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamEvent,
    TokenUsage,
)

__all__ = [
    "PROVIDER_SPECS",
    "PROVIDER_TYPES",
    "LLMError",
    "LLMProvider",
    "ChatMessage",
    "CompletionResult",
    "ModelNotFoundError",
    "ProviderAuthError",
    "ProviderConnectionError",
    "ProviderHealth",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "StreamDelta",
    "StreamDone",
    "StreamError",
    "StreamEvent",
    "TokenUsage",
    "aclose_provider",
    "build_system_prompt",
    "create_provider",
    "get_provider",
    "provider_health",
    "reset_provider",
]
