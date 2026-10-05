"""Streaming chat orchestration + the agent loop (PRD §3.1, §8).

Pipeline per turn::

    user text -> persist user message -> build context (budget/compress)
              -> provider.stream() -> deltas
                 ├─ finish_reason=tool_calls -> permission -> execute -> repeat
                 └─ stop -> persist assistant message

DB work runs on the threadpool (sync SQLAlchemy), LLM I/O stays on the event
loop, and one turn at a time is allowed per conversation. Context assembly may
itself call the model to summarize older turns; a failure there degrades to
dropping history, never to a failed chat.

Tool activity rides the same SSE stream as ``tool`` / ``confirm`` events. Only
the *final* assistant message is persisted — tool rounds live in its
``meta['tools']`` — so the history the model sees next turn stays clean
(providers reject a ``tool_calls`` message whose results are missing).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from luxion.config.settings import Settings, get_settings
from luxion.context import (
    BuiltContext,
    ContextStats,
    HistoryRecord,
    SummaryState,
    build_context,
)
from luxion.database.session import get_session_factory
from luxion.llm.base import LLMProvider
from luxion.llm.errors import LLMError
from luxion.llm.registry import get_provider
from luxion.llm.system_prompt import build_system_prompt
from luxion.llm.types import ChatMessage, StreamDelta, StreamDone, TokenUsage, ToolCall
from luxion.memory.extraction import schedule_extraction
from luxion.services.conversations import (
    ConversationNotFound,
    append_message,
    apply_auto_title,
    get_conversation,
    history_records,
    read_summary_state,
    write_summary_state,
)
from luxion.tools.base import ToolSpec
from luxion.tools.executor import ToolExecutor, get_executor
from luxion.tools.router import select_tools

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- wire events
class ChatDelta(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class ChatTool(BaseModel):
    """One tool lifecycle step: ``start`` then a terminal phase (PRD §43)."""

    type: Literal["tool"] = "tool"
    id: str
    name: str
    risk: str
    phase: Literal["start", "ok", "error", "denied", "timeout", "invalid_args"]
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    error: str | None = None
    duration_ms: float | None = None


class ChatConfirm(BaseModel):
    """Ask the user before running a ``confirm``-level tool (PRD §21)."""

    type: Literal["confirm"] = "confirm"
    id: str
    name: str
    risk: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    description: str = ""
    expires_in_s: float = 0.0


class ChatDone(BaseModel):
    type: Literal["done"] = "done"
    conversation_id: str
    message_id: int | None = None
    title: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    model: str | None = None
    interrupted: bool = False
    #: Estimated prompt composition for this turn (PRD §14).
    context: ContextStats | None = None
    #: Compact record of every tool that ran this turn (PRD §43).
    tools: list[dict[str, Any]] | None = None


class ChatError(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False
    message_id: int | None = None


ChatStreamEvent = ChatDelta | ChatDone | ChatError | ChatTool | ChatConfirm


@dataclass(slots=True)
class _PreparedTurn:
    records: list[HistoryRecord]
    summary: SummaryState
    title: str | None


_locks: dict[str, asyncio.Lock] = {}


def _lock_for(conversation_id: str) -> asyncio.Lock:
    lock = _locks.get(conversation_id)
    if lock is None:
        lock = _locks[conversation_id] = asyncio.Lock()
    return lock


def _prepare_turn(conversation_id: str, user_text: str, settings: Settings) -> _PreparedTurn:
    """Persist the user turn and reload what the context manager needs.

    Assembly itself stays async (it may call the model to summarize), so only
    the DB work happens here on the threadpool.
    """
    with get_session_factory()() as session:
        conversation = get_conversation(session, conversation_id)
        apply_auto_title(conversation, user_text)
        append_message(session, conversation_id, "user", user_text)
        records = history_records(
            session, conversation_id, limit=settings.context.max_history_messages
        )
        return _PreparedTurn(
            records=records,
            summary=read_summary_state(conversation),
            title=conversation.title,
        )


def _save_summary(conversation_id: str, state: SummaryState) -> None:
    """Persist the rolling summary on its own (threadpool) session."""
    try:
        with get_session_factory()() as session:
            write_summary_state(session, conversation_id, state)
    except ConversationNotFound:
        # Conversation was deleted while the summary was being built.
        logger.info("summary_state_dropped", extra={"conversation_id": conversation_id})


def _persist_assistant(
    conversation_id: str,
    content: str,
    *,
    usage: TokenUsage | None = None,
    context: ContextStats | None = None,
    tools: list[dict[str, Any]] | None = None,
    error_code: str | None = None,
    interrupted: bool = False,
) -> int | None:
    meta: dict[str, object] = {}
    if error_code:
        meta["error"] = error_code
    if interrupted:
        meta["interrupted"] = True
    if usage and usage.cost is not None:
        # Real spend reported by the provider (OpenRouter); kept out of the
        # token columns because it is money, not tokens (PRD §45).
        meta["cost_usd"] = usage.cost
    if context is not None:
        # What actually went over the wire, so the context meter survives a reload.
        meta["context"] = context.model_dump()
    if tools:
        # Tool activity for this turn (PRD §43) — the UI re-renders it on load.
        meta["tools"] = tools
    try:
        with get_session_factory()() as session:
            message = append_message(
                session,
                conversation_id,
                "assistant",
                content,
                tokens_in=usage.prompt_tokens if usage else None,
                tokens_out=usage.completion_tokens if usage else None,
                meta=meta,
            )
            return message.id
    except ConversationNotFound:
        # Conversation was deleted while the model was still talking.
        logger.info("assistant_message_dropped", extra={"conversation_id": conversation_id})
        return None


def _tool_runtime(
    settings: Settings, user_text: str
) -> tuple[list[ToolSpec], list[dict[str, Any]], ToolExecutor | None]:
    """Pick the tools exposed to the model for this request (PRD §19)."""
    if not settings.tools.enabled:
        return [], [], None
    executor = get_executor(settings)
    if not len(executor.registry):
        return [], [], executor
    specs = select_tools(user_text, executor.registry, settings)
    return specs, [spec.as_openai() for spec in specs], executor


async def stream_reply(
    conversation_id: str,
    user_text: str,
    *,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    """Yield SSE wire events for one user turn (including any tool rounds)."""
    cfg = settings or get_settings()
    async with _lock_for(conversation_id):
        parts: list[str] = []
        usage_parts: list[TokenUsage | None] = []
        tool_summaries: list[dict[str, Any]] = []
        turn_messages: list[ChatMessage] = []
        error: LLMError | None = None
        final_done: StreamDone | None = None
        exhausted = False
        title: str | None = None
        built: BuiltContext | None = None
        summary: SummaryState

        try:
            prepared = await run_in_threadpool(_prepare_turn, conversation_id, user_text, cfg)
            title = prepared.title
            summary = prepared.summary
        except ConversationNotFound:
            yield ChatError(
                code="conversation_not_found",
                message=f"Conversation '{conversation_id}' no longer exists.",
            )
            return

        tool_specs: list[ToolSpec] = []
        try:
            tool_specs, tool_schemas, executor = _tool_runtime(cfg, user_text)
            active = provider or get_provider(cfg.llm)
            model = await active.resolve_model()
            rounds = cfg.tools.max_iterations if tool_schemas else 1

            for round_index in range(rounds):
                built = await build_context(
                    system_prompt=build_system_prompt(cfg, tool_specs or None),
                    records=prepared.records,
                    summary=summary,
                    settings=cfg,
                    provider=active,
                    model=model,
                )
                if built.summary_state is not None:
                    summary = built.summary_state
                    await run_in_threadpool(_save_summary, conversation_id, built.summary_state)

                messages = [*built.messages, *turn_messages]
                done: StreamDone | None = None
                async for event in active.stream(messages, model=model, tools=tool_schemas or None):
                    if isinstance(event, StreamDelta):
                        parts.append(event.text)
                        yield ChatDelta(text=event.text)
                    else:
                        done = event

                if done is None:
                    break
                usage_parts.append(done.usage)

                calls = done.tool_calls if (tool_schemas and done.tool_calls) else None
                if not calls or executor is None:
                    final_done = done
                    break

                # The narration before a tool call is kept in `parts` (and in
                # the final message) but not repeated in the provider payload.
                turn_messages.append(ChatMessage(role="assistant", content="", tool_calls=calls))
                for call in calls:
                    async for event in _run_tool_call(
                        executor, call, cfg, conversation_id, turn_messages, tool_summaries
                    ):
                        yield event
                if round_index == rounds - 1:
                    exhausted = True
        except asyncio.CancelledError:
            content = "".join(parts).strip()
            if content or tool_summaries:
                await run_in_threadpool(
                    _persist_assistant,
                    conversation_id,
                    content,
                    usage=TokenUsage.merge(usage_parts),
                    context=built.stats if built else None,
                    tools=tool_summaries or None,
                    interrupted=True,
                )
            raise
        except LLMError as exc:
            error = exc
            logger.warning(
                "llm_stream_failed",
                extra={
                    "provider": exc.provider,
                    "code": exc.code,
                    "conversation_id": conversation_id,
                },
            )

        content = "".join(parts).strip()
        usage = TokenUsage.merge(usage_parts)
        message_id: int | None = None
        if content or tool_summaries:
            message_id = await run_in_threadpool(
                _persist_assistant,
                conversation_id,
                content,
                usage=usage,
                context=built.stats if built else None,
                tools=tool_summaries or None,
                error_code=error.code if error else ("tool_loop_exhausted" if exhausted else None),
            )

        if error is not None:
            yield ChatError(
                code=error.code,
                message=str(error),
                retryable=error.retryable,
                message_id=message_id,
            )
            return

        if exhausted:
            yield ChatError(
                code="tool_loop_exhausted",
                message=(
                    f"The model used all {cfg.tools.max_iterations} tool rounds without "
                    "giving a final answer."
                ),
                retryable=False,
                message_id=message_id,
            )
            return

        if not content:
            yield ChatError(
                code="empty_response",
                message="The model returned no content.",
                retryable=True,
            )
            return

        yield ChatDone(
            conversation_id=conversation_id,
            message_id=message_id,
            title=title,
            finish_reason=final_done.finish_reason if final_done else None,
            usage=usage,
            model=final_done.model if final_done else None,
            context=built.stats if built else None,
            tools=tool_summaries or None,
        )
        if message_id is not None:
            # Phase 5b: harvest durable memories from the turns this reply just
            # closed, without ever blocking the stream the client is reading.
            schedule_extraction(conversation_id, settings=cfg)


#: Run one tool call: permission check, optional confirmation, execution.
#: Appends the model-visible result to ``turn_messages`` and the UI record to
#: ``tool_summaries``, yielding ``start``/``confirm``/terminal SSE events.
async def _run_tool_call(
    executor: ToolExecutor,
    call: ToolCall,
    cfg: Settings,
    conversation_id: str,
    turn_messages: list[ChatMessage],
    tool_summaries: list[dict[str, Any]],
) -> AsyncIterator[ChatTool | ChatConfirm]:
    prepared = executor.prepare(call.name, call.arguments, conversation_id=conversation_id)
    risk = prepared.spec.risk if prepared.spec else "unknown"

    yield ChatTool(id=call.id, name=call.name, risk=risk, phase="start", args=dict(call.arguments))

    approved: bool | None = None
    if prepared.needs_confirmation and prepared.pending is not None:
        pending = prepared.pending
        yield ChatConfirm(
            id=pending.id,
            name=call.name,
            risk=risk,
            args=dict(call.arguments),
            reason=prepared.decision.reason,
            description=prepared.spec.description if prepared.spec else "",
            expires_in_s=cfg.tools.confirm_timeout_s,
        )
        approved = await executor.wait(prepared, timeout_s=cfg.tools.confirm_timeout_s)

    result = await executor.run(prepared, approved=approved)
    yield ChatTool(
        id=call.id,
        name=result.tool,
        risk=result.risk,
        phase=result.status,
        args=result.args,
        output=result.output,
        error=result.error,
        duration_ms=result.duration_ms,
    )
    tool_summaries.append(result.summary())
    turn_messages.append(
        ChatMessage(
            role="tool",
            content=result.as_model_payload(cfg.context.max_tool_result_chars),
            tool_call_id=call.id,
        )
    )
