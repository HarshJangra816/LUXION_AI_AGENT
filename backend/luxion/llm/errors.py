"""LLM provider error hierarchy.

Every backend failure is translated into one of these so the API can expose a
stable machine-readable ``code`` to the frontend without leaking provider
specific payloads.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for anything that can go wrong while talking to a provider."""

    code = "llm_error"
    retryable = False

    def __init__(self, message: str, *, provider: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class ProviderConnectionError(LLMError):
    """Provider unreachable (DNS, refused connection, offline)."""

    code = "provider_connection"
    retryable = True


class ProviderTimeoutError(LLMError):
    """Provider did not answer within ``llm.request_timeout_s``."""

    code = "provider_timeout"
    retryable = True


class ProviderAuthError(LLMError):
    """Missing/invalid credentials (401/403)."""

    code = "provider_auth"
    retryable = False


class ProviderRateLimitError(LLMError):
    """Provider throttled us (429)."""

    code = "provider_rate_limit"
    retryable = True


class ProviderResponseError(LLMError):
    """Provider answered, but not with something we can use (5xx, bad JSON)."""

    code = "provider_response"
    retryable = False


class ModelNotFoundError(LLMError):
    """No usable model is configured or installed."""

    code = "model_not_found"
    retryable = False


def error_from_response(status_code: int, body: str, provider: str) -> LLMError:
    """Map an HTTP error payload onto the hierarchy above."""
    snippet = body.strip().replace("\n", " ")[:400] or "no response body"
    message = f"{provider} returned HTTP {status_code}: {snippet}"
    if status_code in (401, 403):
        return ProviderAuthError(message, provider=provider, status_code=status_code)
    if status_code == 404:
        return ModelNotFoundError(message, provider=provider, status_code=status_code)
    if status_code == 429:
        return ProviderRateLimitError(message, provider=provider, status_code=status_code)
    return ProviderResponseError(message, provider=provider, status_code=status_code)
