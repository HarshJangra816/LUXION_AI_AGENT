"""Compression strategies for history that outgrows the budget (PRD §14).

Two tiers, tried in order:

1. **LLM summary** — one extra completion over the dropped messages, merged
   with the existing summary. Best quality, costs one short request.
2. **Heuristic roll-up** — deterministic first/last lines per message. Used
   when summarization is disabled or the provider fails, so compression never
   blocks or fails a chat turn.

Both are *lossy on purpose*: everything stays in SQLite, only the prompt view
is condensed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from luxion.context.records import HistoryRecord
from luxion.context.tokens import CHARS_PER_TOKEN
from luxion.llm.base import LLMProvider
from luxion.llm.types import ChatMessage

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """\
You are the memory subsystem of a personal AI assistant.

You receive a running summary of a conversation plus the newest messages that
are about to fall out of the context window. Produce an updated summary that
keeps, in plain prose and short bullet points:

- who the user is and their standing preferences
- decisions taken and their reasons
- open questions, commitments and unresolved issues
- concrete facts, names, paths and values that will still matter later

Omit pleasantries, repetition and anything already covered by the existing
summary. Do not answer the messages; only record what future replies need.
Aim well under {max_chars} characters."""


def _transcript(records: Sequence[HistoryRecord], *, max_chars: int) -> str:
    lines = [f"{record.role}: {record.content.strip()}" for record in records]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def heuristic_summary(existing: str, records: Sequence[HistoryRecord], *, max_chars: int) -> str:
    """Deterministic roll-up: keep first/last exchanges, drop the middle."""
    if not records:
        return existing.strip()
    lines = [f"{record.role}: {record.content.strip()[:160]}" for record in records[-6:]]
    block = " | ".join(lines)
    text = f"{existing.strip()}\n- {block}".strip() if existing.strip() else f"- {block}"
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


async def summarize(
    existing: str,
    records: Sequence[HistoryRecord],
    *,
    provider: LLMProvider | None,
    model: str | None,
    max_tokens: int,
) -> tuple[str, bool]:
    """Return ``(text, used_llm)``; never raises, never returns empty."""
    max_chars = max(200, max_tokens * CHARS_PER_TOKEN)
    fallback = heuristic_summary(existing, records, max_chars=max_chars)

    if provider is None or model is None or not records:
        return (existing.strip() or fallback, False)

    try:
        prompt = [
            ChatMessage(
                role="system",
                content=SUMMARY_SYSTEM_PROMPT.format(max_chars=max_chars),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Existing summary:\n{existing.strip() or '(none)'}\n\n"
                    f"New messages to fold in:\n"
                    f"{_transcript(records, max_chars=max_chars)}"
                ),
            ),
        ]
        result = await provider.complete(
            prompt, model=model, temperature=0.2, max_tokens=max_tokens
        )
    except Exception as exc:  # noqa: BLE001 - a failed summary must not fail the turn
        logger.warning(
            "summary_llm_failed",
            extra={"error": str(exc), "messages": len(records)},
        )
        return (existing.strip() or fallback, False)

    text = result.text.strip()
    if not text:
        return (existing.strip() or fallback, False)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return (text, True)
