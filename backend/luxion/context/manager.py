"""Context assembly: turn stored history into the message list we send (PRD §13-14).

Pipeline::

    budget ──► pick newest messages that fit
                  │
                  ├─ too old? ─► summarize (or just drop)
                  ├─ forced keep_recent tail ─► truncate until it fits
                  └─ prepend system prompt (+ summary system message)

Every turn returns a :class:`ContextStats` snapshot so the UI can show what
actually went over the wire.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from luxion.config.settings import Settings
from luxion.context.budget import ContextBudget
from luxion.context.compression import summarize
from luxion.context.records import HistoryRecord
from luxion.context.summary import SummaryState, next_state
from luxion.context.tokens import (
    CHARS_PER_TOKEN,
    MESSAGE_OVERHEAD_TOKENS,
    MIN_KEEP_CHARS,
    estimate_tokens,
    truncate_to_tokens,
)
from luxion.llm.base import LLMProvider
from luxion.llm.types import ChatMessage

logger = logging.getLogger(__name__)

Compression = Literal["none", "dropped", "summary"]


class ContextStats(BaseModel):
    """What a single turn actually sent, in estimated tokens."""

    budget_tokens: int
    reserve_tokens: int
    response_tokens: int
    spendable_tokens: int
    system_tokens: int
    summary_tokens: int
    history_tokens: int
    #: system + summary + history — the prompt size we handed the provider.
    estimated_tokens: int
    messages_sent: int
    history_sent: int
    history_available: int
    history_dropped: int
    #: Messages folded into the rolling summary during this turn.
    summarized: int
    truncated: bool
    compression: Compression = "none"


class BuiltContext(BaseModel):
    """Assembled prompt plus the state that should be persisted."""

    messages: list[ChatMessage]
    stats: ContextStats
    #: ``None`` means "summary unchanged, do not write"; otherwise persist.
    summary_state: SummaryState | None = None


def _cost(records: Sequence[HistoryRecord]) -> int:
    return sum(MESSAGE_OVERHEAD_TOKENS + estimate_tokens(r.content) for r in records)


def _clip(text: str, target_chars: int) -> str:
    if len(text) <= target_chars:
        return text
    return truncate_to_tokens(text, target_chars // CHARS_PER_TOKEN, min_chars=MIN_KEEP_CHARS)


def _shrink_to_fit(
    records: list[HistoryRecord], used: int, budget: int
) -> tuple[list[HistoryRecord], int, bool]:
    """Clip the largest messages until the history fits ``budget`` tokens."""
    total = used
    truncated = False
    records = list(records)
    # One pass per message is enough: a single clip always lands on the floor.
    for _ in range(len(records) + 2):
        if total <= budget:
            break
        index = max(range(len(records)), key=lambda i: len(records[i].content))
        record = records[index]
        if len(record.content) <= MIN_KEEP_CHARS:
            break
        overflow_chars = (total - budget) * CHARS_PER_TOKEN
        clipped = _clip(record.content, len(record.content) - overflow_chars)
        new_cost = MESSAGE_OVERHEAD_TOKENS + estimate_tokens(clipped)
        old_cost = MESSAGE_OVERHEAD_TOKENS + estimate_tokens(record.content)
        if new_cost >= old_cost:
            break
        records[index] = HistoryRecord(id=record.id, role=record.role, content=clipped)
        total -= old_cost - new_cost
        truncated = True
    return records, total, truncated


async def build_context(
    *,
    system_prompt: str,
    records: Sequence[HistoryRecord],
    summary: SummaryState,
    settings: Settings,
    provider: LLMProvider | None = None,
    model: str | None = None,
    allow_summarize: bool = True,
) -> BuiltContext:
    """Assemble the outgoing messages for one turn.

    ``allow_summarize=False`` skips the LLM summary (used by previews, where a
    side effect would be wrong).
    """
    cfg = settings.context
    budget = ContextBudget.from_settings(settings)
    system_tokens = estimate_tokens(system_prompt)
    summary_tokens = summary.tokens or estimate_tokens(summary.text)
    history_budget = budget.history_allowance(
        system_tokens=system_tokens, summary_tokens=summary_tokens
    )

    # 1) newest-first selection; the tail is mandatory, the rest is budget-bound.
    keep = max(cfg.keep_recent_messages, 1)
    selected_rev: list[HistoryRecord] = []
    used = 0
    for record in reversed(records):
        cost = MESSAGE_OVERHEAD_TOKENS + estimate_tokens(record.content)
        if len(selected_rev) >= keep and used + cost > history_budget:
            break
        selected_rev.append(record)
        used += cost
    selected = list(reversed(selected_rev))
    dropped = list(records[: len(records) - len(selected)])

    # 2) summarize what we are about to forget.
    new_summary: SummaryState | None = None
    summarized = 0
    uncovered = [record for record in dropped if record.id > summary.covered_through]
    enough = len(uncovered) >= cfg.summary_min_messages
    if uncovered and enough and cfg.summary_enabled and allow_summarize:
        text, _ = await summarize(
            summary.text,
            uncovered,
            provider=provider,
            model=model,
            max_tokens=cfg.summary_max_tokens,
        )
        if text:
            summarized = len(uncovered)
            new_summary = next_state(
                text=text,
                tokens=estimate_tokens(text),
                covered_through=uncovered[-1].id,
            )
            summary = new_summary
            summary_tokens = summary.tokens

    # 3) never send a message the summary already covers, then re-fit.
    if summary.present:
        selected = [record for record in selected if record.id > summary.covered_through]
    history_budget = budget.history_allowance(
        system_tokens=system_tokens, summary_tokens=summary_tokens
    )
    used = _cost(selected)
    truncated = False
    if used > history_budget and selected:
        selected, used, truncated = _shrink_to_fit(selected, used, history_budget)

    # 4) assemble.
    messages = [ChatMessage(role="system", content=system_prompt)]
    if summary.present:
        messages.append(
            ChatMessage(
                role="system",
                content=f"Conversation summary so far (older messages):\n{summary.text}",
            )
        )
    messages.extend(record.as_message() for record in selected)

    dropped_count = len(records) - len(selected)
    covered_count = sum(1 for record in records if record.id <= summary.covered_through)
    # "dropped" only when messages left the prompt *and* the summary does not
    # hold them yet; covered ones are not lost, just represented differently.
    compression: Compression
    if summarized:
        compression = "summary"
    elif dropped_count > covered_count:
        compression = "dropped"
    else:
        compression = "none"
    stats = ContextStats(
        budget_tokens=budget.total,
        reserve_tokens=budget.reserve,
        response_tokens=budget.response,
        spendable_tokens=budget.spendable,
        system_tokens=system_tokens,
        summary_tokens=summary_tokens,
        history_tokens=used,
        estimated_tokens=system_tokens + summary_tokens + used,
        messages_sent=len(messages),
        history_sent=len(selected),
        history_available=len(records),
        history_dropped=dropped_count,
        summarized=summarized,
        truncated=truncated,
        compression=compression,
    )
    if compression != "none":
        logger.info(
            "context_compressed",
            extra={
                "compression": compression,
                "dropped": dropped_count,
                "summarized": summarized,
                "estimated_tokens": stats.estimated_tokens,
                "budget_tokens": budget.total,
            },
        )
    return BuiltContext(messages=messages, stats=stats, summary_state=new_summary)
