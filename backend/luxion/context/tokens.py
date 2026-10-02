"""Token estimation without a tokenizer dependency.

Luxion deliberately does not ship a tokenizer (tiktoken / transformers are
large, model-specific and offline-unfriendly). Context budgets only need a
stable, fast estimate with a little head-room, and ``ContextConfig.reserve_tokens``
exists exactly to absorb the estimator's error. Provider-reported counts stay
authoritative for billing (:class:`~luxion.llm.types.TokenUsage`); estimates
only shape what we send.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from luxion.llm.types import ChatMessage

#: English prose averages ~4 characters per BPE token.
CHARS_PER_TOKEN = 4
#: Per-message framing cost (role header + separators), cf. OpenAI's cookbook.
MESSAGE_OVERHEAD_TOKENS = 4
#: Refuse to clip a message below this many characters.
MIN_KEEP_CHARS = 80
#: Marker appended wherever :func:`truncate_to_tokens` cuts text.
TRUNCATION_SUFFIX = "\n…[truncated]"


def estimate_tokens(text: str) -> int:
    """Rounded-up character heuristic for ``text`` (0 for empty input)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def estimate_message_tokens(message: ChatMessage) -> int:
    """Tokens a single chat message costs on the wire (content + framing)."""
    return estimate_tokens(message.content) + MESSAGE_OVERHEAD_TOKENS


def estimate_messages_tokens(messages: Iterable[ChatMessage]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def truncate_to_tokens(
    text: str, max_tokens: int, *, suffix: str = TRUNCATION_SUFFIX, min_chars: int = 0
) -> str:
    """Clip ``text`` to roughly ``max_tokens``, keeping the head of the text.

    ``min_chars`` floors the result (used when clipping prompt messages, where
    a sliver of context beats a hole in the transcript).
    """
    if max_tokens <= 0:
        return suffix.strip()
    budget_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= budget_chars:
        return text
    keep = max(min_chars, budget_chars - len(suffix))
    return text[:keep].rstrip() + suffix
