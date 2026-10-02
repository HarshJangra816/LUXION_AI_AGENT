"""Context assembly (PRD §13-14): budgets, truncation, rolling summaries."""

from __future__ import annotations

import asyncio

from luxion.config.settings import Settings
from luxion.context import (
    ContextBudget,
    HistoryRecord,
    SummaryState,
    build_context,
    estimate_message_tokens,
    estimate_tokens,
    state_from_meta,
    state_to_meta,
    truncate_to_tokens,
)
from luxion.llm.providers.mock import MockProvider
from luxion.llm.types import ChatMessage

SYSTEM = "SYS"
TRUNCATION_MARK = "\n…[truncated]"


def _settings(**overrides) -> Settings:
    """Small, deterministic budget so compression happens in a few messages."""
    context = {
        "total_budget_tokens": 1_000,
        "reserve_tokens": 100,
        "keep_recent_messages": 2,
        "summary_enabled": False,
        "summary_min_messages": 2,
    }
    context.update(overrides)
    return Settings(llm={"provider": "mock", "model": "mock-1"}, context=context)


def _records(count: int, *, chars: int = 400, marker: str = "") -> list[HistoryRecord]:
    return [
        HistoryRecord(
            id=index + 1,
            role="user" if index % 2 == 0 else "assistant",
            content=f"{marker}msg-{index + 1} " + "x" * chars,
        )
        for index in range(count)
    ]


def _build(
    records: list[HistoryRecord],
    settings: Settings,
    *,
    summary: SummaryState | None = None,
    allow_summarize: bool = True,
):
    provider = MockProvider(settings.llm)
    return asyncio.run(
        build_context(
            system_prompt=SYSTEM,
            records=records,
            summary=summary or SummaryState.empty(),
            settings=settings,
            provider=provider,
            model="mock-1",
            allow_summarize=allow_summarize,
        )
    )


# --------------------------------------------------------------------- tokens
def test_token_estimation_rounds_up_and_counts_framing() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("a" * 8) == 2
    # Content plus the per-message framing overhead.
    assert estimate_message_tokens(ChatMessage(role="user", content="")) == 4


def test_truncate_keeps_the_head_and_marks_the_cut() -> None:
    text = "y" * 400
    out = truncate_to_tokens(text, 10)
    assert out.startswith("yyyy")
    assert out.endswith(TRUNCATION_MARK)
    assert len(out) <= 10 * 4
    assert truncate_to_tokens(text, 1_000) == text
    # Prompt clipping never starves a message down to a useless fragment.
    assert len(truncate_to_tokens(text, 10, min_chars=80)) == 80 + len(TRUNCATION_MARK)


# -------------------------------------------------------------------- budget
def test_budget_clamps_reserve_and_response_out_of_the_window() -> None:
    settings = Settings(context={"total_budget_tokens": 1_000, "reserve_tokens": 999_999})
    budget = ContextBudget.from_settings(settings)
    assert budget.reserve == 500
    assert budget.response <= 250
    assert budget.spendable == 250
    assert budget.history_allowance(system_tokens=100, summary_tokens=50) == 100


def test_default_budget_matches_settings() -> None:
    budget = ContextBudget.from_settings(Settings())
    assert budget.total == 32_000
    assert budget.reserve == 4_000
    assert budget.response == 2_048
    assert budget.spendable == 32_000 - 4_000 - 2_048


# ------------------------------------------------------------------ assembly
def test_short_history_is_sent_verbatim() -> None:
    settings = _settings(total_budget_tokens=32_000, reserve_tokens=100)
    built = _build(_records(4, chars=40), settings)

    assert built.messages[0].role == "system"
    assert built.messages[0].content == SYSTEM
    assert len(built.messages) == 5
    assert built.stats.compression == "none"
    assert built.stats.history_sent == 4
    assert built.stats.history_dropped == 0
    assert built.summary_state is None
    assert (
        built.stats.estimated_tokens
        == built.stats.system_tokens + built.stats.summary_tokens + built.stats.history_tokens
    )


def test_oldest_messages_are_dropped_when_the_budget_fills() -> None:
    settings = _settings()
    built = _build(_records(10), settings)
    stats = built.stats

    assert stats.compression == "dropped"
    assert stats.history_sent == 6
    assert stats.history_dropped == 4
    assert stats.summarized == 0
    assert built.summary_state is None

    contents = [message.content for message in built.messages]
    assert any("msg-10 " in content for content in contents)
    assert any("msg-5 " in content for content in contents)
    assert not any("msg-4 " in content for content in contents)
    assert stats.history_tokens <= stats.spendable_tokens - stats.system_tokens


def test_keep_recent_tail_is_truncated_instead_of_dropped() -> None:
    settings = _settings(reserve_tokens=500, keep_recent_messages=6)
    built = _build(_records(6), settings)
    stats = built.stats

    assert stats.history_sent == 6
    assert stats.history_dropped == 0
    assert stats.truncated is True
    assert stats.history_tokens <= stats.spendable_tokens - stats.system_tokens
    assert any(
        TRUNCATION_MARK in message.content for message in built.messages if message.role != "system"
    )


def test_preview_can_skip_summarization_side_effects() -> None:
    settings = _settings(summary_enabled=True)
    built = _build(_records(10), settings, allow_summarize=False)

    assert built.summary_state is None
    assert built.stats.compression == "dropped"


# ------------------------------------------------------------------ summaries
def test_dropped_history_is_summarized_and_prepended() -> None:
    settings = _settings(summary_enabled=True)
    built = _build(_records(10), settings)
    stats = built.stats

    assert stats.compression == "summary"
    assert stats.summarized == 4
    assert built.summary_state is not None
    assert built.summary_state.covered_through == 4
    assert built.summary_state.present

    system_messages = [m for m in built.messages if m.role == "system"]
    assert len(system_messages) == 2
    assert system_messages[1].content.startswith("Conversation summary so far")
    assert stats.messages_sent == 8


def test_messages_already_in_the_summary_are_not_sent_twice() -> None:
    settings = _settings(
        total_budget_tokens=32_000,
        reserve_tokens=100,
        summary_enabled=True,
    )
    summary = SummaryState(text="older stuff", tokens=3, covered_through=6)
    built = _build(_records(10), settings, summary=summary)

    contents = [message.content for message in built.messages]
    assert not any("msg-6 " in content for content in contents)
    assert any("msg-7 " in content for content in contents)
    # Nothing new was dropped, so the stored summary stays untouched.
    assert built.summary_state is None
    assert built.stats.compression == "none"


def test_summary_falls_back_to_a_heuristic_when_the_provider_fails() -> None:
    settings = _settings(summary_enabled=True)
    built = _build(_records(8, marker="FAIL "), settings)

    assert built.summary_state is not None
    assert built.stats.summarized == 2
    # Deterministic roll-up: a bullet per folded message, no model involved.
    assert built.summary_state.text.startswith("- ")
    assert "FAIL msg-1" in built.summary_state.text
    assert built.stats.compression == "summary"


def test_summary_state_round_trips_through_conversation_meta() -> None:
    state = SummaryState(text="rolled up", tokens=4, covered_through=12)
    assert state_from_meta(state_to_meta(state)) == state
    assert state_from_meta({}).present is False
    assert state_from_meta(None).present is False
    assert state_from_meta({"context": "corrupted"}).present is False


# ---------------------------------------------------------------- integration
def test_summary_state_is_persisted_on_the_conversation(client) -> None:
    from luxion.database.models import Conversation
    from luxion.database.session import get_session_factory
    from luxion.services.conversations import (
        create_conversation,
        read_summary_state,
        write_summary_state,
    )

    with get_session_factory()() as session:
        conversation_id = create_conversation(session, "summary persistence").id

    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        assert read_summary_state(conversation).present is False
        write_summary_state(
            session,
            conversation_id,
            SummaryState(text="rolled up", tokens=4, covered_through=12),
        )

    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        state = read_summary_state(conversation)
        assert state.present
        assert state.covered_through == 12
        assert conversation.meta["context"]["text"] == "rolled up"


def test_stream_reply_reports_and_persists_context_stats(client) -> None:
    from luxion.database.session import get_session_factory
    from luxion.services.chat import stream_reply
    from luxion.services.conversations import (
        append_message,
        create_conversation,
        get_conversation,
        read_summary_state,
    )

    with get_session_factory()() as session:
        conversation_id = create_conversation(session, "context stats").id
        for index in range(10):
            append_message(
                session,
                conversation_id,
                "user" if index % 2 == 0 else "assistant",
                f"seed-{index} " + "y" * 400,
            )

    settings = _settings(summary_enabled=True)

    async def run():
        return [
            event
            async for event in stream_reply(conversation_id, "please continue", settings=settings)
        ]

    done = next(event for event in asyncio.run(run()) if event.type == "done")
    assert done.context is not None
    assert done.context.budget_tokens == 1_000
    assert done.context.compression == "summary"
    assert done.context.summarized > 0

    with get_session_factory()() as session:
        conversation = get_conversation(session, conversation_id)
        assert read_summary_state(conversation).present
        assistants = [m for m in conversation.messages if m.role == "assistant"]
        assert assistants[-1].meta["context"]["summarized"] == done.context.summarized
