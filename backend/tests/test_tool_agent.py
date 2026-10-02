"""Agent loop tests: tool rounds, confirmations, exhaustion (PRD §3.1, §19-21)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from luxion.config.settings import Settings, get_settings
from luxion.services.chat import (
    ChatConfirm,
    ChatDelta,
    ChatDone,
    ChatError,
    ChatStreamEvent,
    ChatTool,
    stream_reply,
)
from luxion.tools.permissions import PermissionEngine
from luxion.tools.registry import build_registry


def _new_conversation(client: TestClient) -> str:
    return client.post("/api/conversations", json={"title": "tools"}).json()["id"]


async def _collect(
    conversation_id: str,
    text: str,
    *,
    settings: Settings | None = None,
    on_event: Callable[[ChatStreamEvent], None] | None = None,
) -> list[ChatStreamEvent]:
    events: list[ChatStreamEvent] = []
    async for event in stream_reply(conversation_id, text, settings=settings):
        events.append(event)
        if on_event is not None:
            on_event(event)
    return events


def _run(coro) -> list[ChatStreamEvent]:  # noqa: ANN001
    return asyncio.run(coro)


def _phases(events: list[ChatStreamEvent]) -> list[tuple[str, str]]:
    return [(e.name, e.phase) for e in events if isinstance(e, ChatTool)]


@pytest.fixture(autouse=True)
def clean_tool_overrides():
    """Permission overrides live in the shared data dir — keep tests hermetic."""
    from luxion.tools.confirmations import reset_confirmations
    from luxion.tools.executor import reset_executor

    engine = PermissionEngine(get_settings())
    engine.clear()
    reset_confirmations()
    reset_executor()
    yield
    engine.clear()
    reset_confirmations()
    reset_executor()


# --------------------------------------------------------- happy path
def test_tool_round_runs_and_is_summarised(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    events = _run(_collect(conversation_id, "USE_TOOL get_time"))

    phases = _phases(events)
    assert phases[0] == ("get_time", "start")
    assert phases[-1] == ("get_time", "ok")

    done = events[-1]
    assert isinstance(done, ChatDone)
    assert done.tools and done.tools[0]["name"] == "get_time"
    assert done.tools[0]["status"] == "ok"
    assert done.tools[0]["duration_ms"] is not None

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    # Only the final assistant message is stored — no orphaned tool turns.
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["tools"][0]["name"] == "get_time"
    # The model saw the tool result: its reply quotes it back.
    assert "Tool said:" in detail["messages"][1]["content"]


def test_tool_turn_reports_usage_and_activity_in_done(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    events = _run(_collect(conversation_id, "USE_TOOL get_date {}"))

    done = events[-1]
    assert isinstance(done, ChatDone)
    assert done.usage is not None and done.usage.total_tokens > 0
    assert any(isinstance(e, ChatDelta) for e in events)


def test_unknown_tool_is_reported_not_fatal(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    events = _run(_collect(conversation_id, "USE_TOOL no_such_tool"))

    assert _phases(events)[-1] == ("no_such_tool", "error")
    done = events[-1]
    assert isinstance(done, ChatDone)
    assert done.tools and done.tools[0]["status"] == "error"
    assert "unknown tool" in done.tools[0]["error"]


def test_tool_session_writes_an_audit_entry(client: TestClient) -> None:
    from luxion.tools.audit import read_log

    conversation_id = _new_conversation(client)
    _run(_collect(conversation_id, "USE_TOOL system_stats"))

    entries = read_log(get_settings(), limit=1)
    assert entries and entries[0].tool == "system_stats"
    assert entries[0].result == "success"


# --------------------------------------------------------- permissions
def test_autonomy_zero_never_executes_anything(tmp_path: Path) -> None:
    conversation_id = _new_conversation_direct()
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 0})
    events = _run(_collect(conversation_id, "USE_TOOL get_time", settings=settings))

    assert _phases(events) == [("get_time", "start"), ("get_time", "denied")]
    assert isinstance(events[-1], ChatDone)
    assert events[-1].tools[0]["status"] == "denied"


def test_deny_override_blocks_a_tool_that_would_otherwise_run(tmp_path: Path) -> None:
    conversation_id = _new_conversation_direct()
    settings = Settings(app={"data_dir": tmp_path})
    PermissionEngine(settings).set_override("get_time", "deny")

    events = _run(_collect(conversation_id, "USE_TOOL get_time", settings=settings))
    assert _phases(events)[-1] == ("get_time", "denied")


# --------------------------------------------------------- confirmation
def _confirmation_settings(tmp_path: Path) -> Settings:
    return Settings(
        app={"data_dir": tmp_path},
        security={"autonomy_level": 3, "allowed_workspaces": [tmp_path]},
    )


def _answer(approved: bool) -> Callable[[ChatStreamEvent], None]:
    from luxion.tools.confirmations import get_confirmations

    def _handle(event: ChatStreamEvent) -> None:
        if isinstance(event, ChatConfirm):
            get_confirmations().resolve(event.id, approved)

    return _handle


def test_user_approval_runs_the_tool(tmp_path: Path) -> None:
    conversation_id = _new_conversation_direct()
    settings = _confirmation_settings(tmp_path)
    PermissionEngine(settings).set_override("write_file", "confirm")

    events = _run(
        _collect(
            conversation_id,
            'USE_TOOL write_file {"path": "approved.txt", "content": "yes"}',
            settings=settings,
            on_event=_answer(approved=True),
        )
    )

    confirm = next(e for e in events if isinstance(e, ChatConfirm))
    assert confirm.name == "write_file"
    assert confirm.risk == "medium"
    assert confirm.expires_in_s > 0
    assert _phases(events)[-1] == ("write_file", "ok")
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "yes"


def test_user_decline_never_touches_the_disk(tmp_path: Path) -> None:
    conversation_id = _new_conversation_direct()
    settings = _confirmation_settings(tmp_path)
    PermissionEngine(settings).set_override("write_file", "confirm")

    events = _run(
        _collect(
            conversation_id,
            'USE_TOOL write_file {"path": "declined.txt", "content": "no"}',
            settings=settings,
            on_event=_answer(approved=False),
        )
    )

    assert _phases(events)[-1] == ("write_file", "denied")
    assert not (tmp_path / "declined.txt").exists()
    assert any(isinstance(e, ChatConfirm) for e in events)


def test_confirmation_prompt_is_dropped_after_the_turn(tmp_path: Path) -> None:
    from luxion.tools.confirmations import get_confirmations

    conversation_id = _new_conversation_direct()
    settings = _confirmation_settings(tmp_path)
    PermissionEngine(settings).set_override("write_file", "confirm")

    _run(
        _collect(
            conversation_id,
            'USE_TOOL write_file {"path": "x.txt", "content": "1"}',
            settings=settings,
            on_event=_answer(approved=True),
        )
    )
    assert get_confirmations().pending() == []


# --------------------------------------------------------- loop guard
def test_iteration_cap_emits_tool_loop_exhausted(tmp_path: Path) -> None:
    conversation_id = _new_conversation_direct()
    settings = Settings(app={"data_dir": tmp_path}, tools={"max_iterations": 1})

    events = _run(_collect(conversation_id, "USE_TOOL get_time", settings=settings))

    assert any(isinstance(e, ChatTool) for e in events)
    error = events[-1]
    assert isinstance(error, ChatError)
    assert error.code == "tool_loop_exhausted"
    assert error.message_id is not None


def test_tools_disabled_offer_no_rounds(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    settings = Settings(tools={"enabled": False})
    assert not build_registry(settings)

    events = _run(_collect(conversation_id, "USE_TOOL get_time", settings=settings))
    assert _phases(events) == []
    assert isinstance(events[-1], ChatDone)
    assert not events[-1].tools


# ------------------------------------------------------------------ helpers
def _new_conversation_direct() -> str:
    """The DB is shared with the session-scoped TestClient fixture."""
    from luxion.database.session import get_session_factory
    from luxion.services.conversations import create_conversation

    with get_session_factory()() as session:
        conversation = create_conversation(session, title="tools")
        session.flush()
        return conversation.id
