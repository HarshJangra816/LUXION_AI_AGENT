"""Usage, cost and context-window reporting (PRD §13-14).

Token counts come from the columns written by the chat pipeline; USD cost and
the per-turn context composition live in ``messages.meta`` (money and derived
state are not columns, so no migration is needed to add them).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from luxion.config.settings import Settings
from luxion.context import (
    ContextStats,
    HistoryRecord,
    SummaryState,
    build_context,
    state_from_meta,
)
from luxion.context.budget import ContextBudget
from luxion.database.models import Conversation, Message
from luxion.database.session import get_session_factory
from luxion.llm.system_prompt import build_system_prompt
from luxion.llm.types import Role
from luxion.services.conversations import ConversationNotFound


class TokenTotals(BaseModel):
    messages: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class UsageTotals(TokenTotals):
    conversations: int = 0


class ContextBudgetOut(BaseModel):
    total: int
    reserve: int
    response: int
    spendable: int
    keep_recent_messages: int
    summary_enabled: bool
    summary_max_tokens: int
    max_history_messages: int


class ConversationUsage(BaseModel):
    id: str
    title: str | None = None
    messages: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class RecentTurn(BaseModel):
    conversation_id: str
    title: str | None = None
    message_id: int
    created_at: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    context: ContextStats | None = None


class UsageReport(BaseModel):
    budget: ContextBudgetOut
    totals: UsageTotals
    conversations: list[ConversationUsage] = []
    recent_turns: list[RecentTurn] = []


class SummaryStateOut(BaseModel):
    present: bool = False
    tokens: int = 0
    covered_through: int = 0
    updated_at: str | None = None


class ConversationContextReport(BaseModel):
    conversation_id: str
    title: str | None = None
    totals: TokenTotals = TokenTotals()
    summary: SummaryStateOut = SummaryStateOut()
    #: What the *next* turn would send (no summarization side effects).
    context: ContextStats
    budget: ContextBudgetOut


def budget_out(settings: Settings) -> ContextBudgetOut:
    budget = ContextBudget.from_settings(settings)
    cfg = settings.context
    return ContextBudgetOut(
        **budget.as_dict(),
        keep_recent_messages=cfg.keep_recent_messages,
        summary_enabled=cfg.summary_enabled,
        summary_max_tokens=cfg.summary_max_tokens,
        max_history_messages=cfg.max_history_messages,
    )


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.isoformat()
    return str(value)


def _cost_of(meta: Any) -> float:
    if isinstance(meta, dict) and isinstance(meta.get("cost_usd"), (int, float)):
        return float(meta["cost_usd"])
    return 0.0


def context_stats_of(meta: Any) -> ContextStats | None:
    if not isinstance(meta, dict) or not isinstance(meta.get("context"), dict):
        return None
    try:
        return ContextStats.model_validate(meta["context"])
    except Exception:  # noqa: BLE001 - unknown meta must not break reporting
        return None


def usage_report(db: Session, settings: Settings, *, recent_limit: int = 20) -> UsageReport:
    """Aggregate spend and context budget across the whole workspace."""
    messages, tokens_in, tokens_out = db.execute(
        select(
            func.count(Message.id),
            func.coalesce(func.sum(Message.tokens_in), 0),
            func.coalesce(func.sum(Message.tokens_out), 0),
        )
    ).one()

    titles = dict(db.execute(select(Conversation.id, Conversation.title)).all())

    per_conversation: dict[str, list[int]] = {}
    for conversation_id, count, c_in, c_out in db.execute(
        select(
            Message.conversation_id,
            func.count(Message.id),
            func.coalesce(func.sum(Message.tokens_in), 0),
            func.coalesce(func.sum(Message.tokens_out), 0),
        ).group_by(Message.conversation_id)
    ):
        row = per_conversation.setdefault(conversation_id, [0, 0, 0])
        row[0] += int(count)
        row[1] += int(c_in)
        row[2] += int(c_out)

    # USD lives in meta, so cost is summed row by row rather than in SQL.
    cost = 0.0
    cost_by: dict[str, float] = {}
    for conversation_id, meta in db.execute(
        select(Message.conversation_id, Message.meta).where(Message.role == "assistant")
    ):
        spent = _cost_of(meta)
        if spent:
            cost_by[conversation_id] = cost_by.get(conversation_id, 0.0) + spent
            cost += spent

    usage = [
        ConversationUsage(
            id=conversation_id,
            title=titles.get(conversation_id),
            messages=row[0],
            tokens_in=row[1],
            tokens_out=row[2],
            cost_usd=round(cost_by.get(conversation_id, 0.0), 6),
        )
        for conversation_id, row in per_conversation.items()
    ]
    usage.sort(key=lambda item: (item.cost_usd, item.messages), reverse=True)

    recent: list[RecentTurn] = []
    for message, title in db.execute(
        select(Message, Conversation.title)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.role == "assistant")
        .order_by(Message.id.desc())
        .limit(recent_limit)
    ):
        recent.append(
            RecentTurn(
                conversation_id=message.conversation_id,
                title=title,
                message_id=message.id,
                created_at=_iso(message.created_at),
                tokens_in=message.tokens_in,
                tokens_out=message.tokens_out,
                cost_usd=_cost_of(message.meta) or None,
                context=context_stats_of(message.meta),
            )
        )

    return UsageReport(
        budget=budget_out(settings),
        totals=UsageTotals(
            messages=int(messages),
            conversations=len(titles),
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            cost_usd=round(cost, 6),
        ),
        conversations=usage,
        recent_turns=recent,
    )


def _load_conversation(
    conversation_id: str, settings: Settings
) -> tuple[str | None, list[HistoryRecord], SummaryState, TokenTotals]:
    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        stored = list(conversation.messages)
        # Same window the chat pipeline loads, so the preview matches the turn.
        limit = settings.context.max_history_messages
        records = [
            HistoryRecord(id=message.id, role=cast(Role, message.role), content=message.content)
            for message in (stored if len(stored) <= limit else stored[-limit:])
        ]
        totals = TokenTotals(
            messages=len(stored),
            tokens_in=sum(message.tokens_in or 0 for message in stored),
            tokens_out=sum(message.tokens_out or 0 for message in stored),
            cost_usd=round(sum(_cost_of(message.meta) for message in stored), 6),
        )
        return conversation.title, records, state_from_meta(conversation.meta), totals


async def conversation_context(
    conversation_id: str, settings: Settings
) -> ConversationContextReport:
    """Preview the prompt that the next turn would send (no side effects)."""
    title, records, summary, totals = await run_in_threadpool(
        _load_conversation, conversation_id, settings
    )
    built = await build_context(
        system_prompt=build_system_prompt(settings),
        records=records,
        summary=summary,
        settings=settings,
        allow_summarize=False,
    )
    return ConversationContextReport(
        conversation_id=conversation_id,
        title=title,
        totals=totals,
        summary=SummaryStateOut(
            present=summary.present,
            tokens=summary.tokens,
            covered_through=summary.covered_through,
            updated_at=summary.updated_at,
        ),
        context=built.stats,
        budget=budget_out(settings),
    )
