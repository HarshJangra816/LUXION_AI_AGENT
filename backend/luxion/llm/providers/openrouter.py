"""OpenRouter provider (https://openrouter.ai).

OpenRouter is an OpenAI-compatible aggregator: one API key, 500+ models from
60+ upstream providers, plus free ``*:free`` model variants. It rides on
:class:`OpenAICompatProvider` and only supplies its own defaults:

* base URL falls back to the OpenRouter API when none is configured, so
  switching ``llm.provider`` never leaves the local Ollama URL behind;
* ``OPENROUTER_API_KEY`` is consulted when ``llm.api_key_env`` is empty;
* an ``X-Title`` attribution header identifies the app (optional for
  OpenRouter, useful for its per-app analytics);
* streaming responses always carry ``usage`` — including ``cost`` in USD and
  ``prompt_tokens_details.cached_tokens`` — which Luxion surfaces as real
  spend figures in the token dashboard (PRD §45).
"""

from __future__ import annotations

from luxion.config.settings import OLLAMA_BASE_URL
from luxion.llm.providers.openai_compat import OpenAICompatProvider

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    label = "OpenRouter"
    requires_api_key = True
    requires_base_url = False
    default_api_key_env = "OPENROUTER_API_KEY"

    @property
    def base_url(self) -> str:
        configured = (self.config.base_url or "").strip()
        if not configured or configured == OLLAMA_BASE_URL:
            return DEFAULT_BASE_URL
        return configured.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["X-Title"] = "Luxion"
        return headers
