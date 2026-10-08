"""Phase 5b extraction tests: heuristics, JSON parsing and the idempotent pass."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete

from luxion.config.settings import Settings, get_settings
from luxion.database.models import Conversation, Message
from luxion.database.session import get_session_factory, init_db
from luxion.memory import extraction, store

_EXTRACTABLE = ("user", "Remember that the staging host is luxion.dev")


@pytest.fixture(autouse=True)
def clean():  # noqa: ANN201
    """The suite shares one database — start and end each test with none."""
    init_db()
    _clear_memories()
    yield
    _clear_memories()


def _clear_memories() -> None:
    with get_session_factory()() as session:
        store.clear_memories(session)


def _conversation(messages: list[tuple[str, str]]) -> str:
    with get_session_factory()() as session:
        conversation = Conversation(title="extraction")
        session.add(conversation)
        session.flush()
        for role, content in messages:
            session.add(Message(conversation_id=conversation.id, role=role, content=content))
        session.commit()
        return str(conversation.id)


def _drop(conversation_id: str) -> None:
    with get_session_factory()() as session:
        session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        session.commit()


def _marker(conversation_id: str) -> dict:
    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        meta = dict(conversation.meta) if conversation is not None else {}
        return meta if isinstance(meta, dict) else {}


def _memory_count() -> int:
    with get_session_factory()() as session:
        return store.count_memories(session)


def _run(coroutine):  # noqa: ANN001
    return asyncio.run(coroutine)


# ------------------------------------------------------------------ heuristics
def test_heuristics_catch_the_commands_from_prd_33_14() -> None:
    cases = {
        "Remember that the API runs on port 8756": ("fact", "the API runs on port 8756"),
        "Please note that invoices are due Friday": ("fact", "invoices are due Friday"),
        "My name is Harsh": ("fact", "Harsh"),
        "Call me Ashdeep": ("fact", "Ashdeep"),
        "I prefer dark mode everywhere": ("preference", "dark mode everywhere"),
        "My preferred editor is vim": ("preference", "editor is vim"),
        "Don't forget to ship the build": ("task", "ship the build"),
        "I'm working on the memory phase": ("project", "the memory phase"),
    }
    for sentence, (kind, text) in cases.items():
        found = extraction.heuristic_candidates([("user", sentence)])
        assert [(item["kind"], item["text"]) for item in found] == [(kind, text)], sentence
        assert found[0]["source"] == "user"
        assert found[0]["importance"] == 0.6


def test_heuristics_only_read_user_turns() -> None:
    assert extraction.heuristic_candidates([("assistant", "Remember that I am helpful")]) == []
    assert extraction.heuristic_candidates([("tool", "Remember that I am helpful")]) == []
    assert extraction.heuristic_candidates([("user", "hello there")]) == []


def test_heuristics_keep_statements_long_enough_to_be_useful() -> None:
    assert extraction.heuristic_candidates([("user", "Remember that ok")]) == []
    assert extraction.heuristic_candidates([("user", "Remember that yes")]) == []


def test_heuristics_stop_at_the_per_pass_cap() -> None:
    turns = [("user", f"Remember that fact number {index}") for index in range(10)]
    found = extraction.heuristic_candidates(turns)
    assert len(found) == extraction.MAX_PER_PASS


# ---------------------------------------------------------------- JSON parsing
def test_parse_candidates_reads_a_fenced_array() -> None:
    raw = (
        '```json\n[{"kind": "preference", "text": "Likes tabs over spaces",'
        ' "importance": 0.8}]\n```'
    )
    assert extraction.parse_candidates(raw) == [
        {
            "kind": "preference",
            "text": "Likes tabs over spaces",
            "importance": 0.8,
            "source": "extracted",
        }
    ]


def test_parse_candidates_reads_an_array_surrounded_by_prose() -> None:
    raw = 'Sure: [{"kind": "fact", "text": "The API keys live in .env"}] — anything else?'
    items = extraction.parse_candidates(raw)
    assert [item["text"] for item in items] == ["The API keys live in .env"]


@pytest.mark.parametrize(
    "raw",
    [
        "no json here",
        "",
        '{"kind": "fact", "text": "an object, not an array"}',
        '[{"kind": "fact", "text": "unfinished"',
        "[1, 2, 3]",
        "[[]]",
        "```json\n[]\n```",
    ],
)
def test_parse_candidates_returns_nothing_for_junk(raw: str) -> None:
    assert extraction.parse_candidates(raw) == []


def test_parse_candidates_repairs_unknown_kinds_and_clamps_importance() -> None:
    raw = (
        '[{"kind": "banana", "text": "A perfectly fine statement", "importance": 42},'
        ' {"kind": "task", "text": "Another fine statement", "importance": -3},'
        ' {"kind": "fact", "text": "Third statement", "importance": "n/a"}]'
    )
    items = extraction.parse_candidates(raw)
    assert [item["kind"] for item in items] == ["fact", "task", "fact"]
    assert [item["importance"] for item in items] == [1.0, 0.0, 0.5]


def test_parse_candidates_drops_thin_and_malformed_entries() -> None:
    raw = (
        '[{"kind": "fact", "text": "hi"},'
        ' {"kind": "fact", "text": 42},'
        ' "just a string",'
        " 7,"
        ' {"kind": "fact", "text": "kept statement"}]'
    )
    assert [item["text"] for item in extraction.parse_candidates(raw)] == ["kept statement"]


def test_parse_candidates_stops_at_the_per_pass_cap() -> None:
    items = ", ".join(
        f'{{"kind": "fact", "text": "Statement number {index}"}}' for index in range(9)
    )
    assert len(extraction.parse_candidates(f"[{items}]")) == extraction.MAX_PER_PASS


# ------------------------------------------------------------- the whole pass
def test_extract_from_conversation_stores_once_and_is_idempotent() -> None:
    conversation_id = _conversation([_EXTRACTABLE, ("assistant", "Noted.")])
    try:
        settings = get_settings()

        assert _run(extraction.extract_from_conversation(conversation_id, settings=settings)) == 1
        assert _memory_count() == 1
        assert _marker(conversation_id)["memory_extracted_through"] > 0

        # Replaying the turn never harvests the same statement twice.
        assert _run(extraction.extract_from_conversation(conversation_id, settings=settings)) == 0
        assert _memory_count() == 1
    finally:
        _drop(conversation_id)


def test_extraction_persists_the_statement_it_found() -> None:
    conversation_id = _conversation([_EXTRACTABLE, ("assistant", "Noted.")])
    try:
        _run(extraction.extract_from_conversation(conversation_id, settings=get_settings()))
        with get_session_factory()() as session:
            memories = store.list_memories(session)
        assert [memory.text for memory in memories] == ["the staging host is luxion.dev"]
        assert memories[0].kind == "fact"
        assert memories[0].conversation_id == conversation_id
        assert memories[0].source == "user"
    finally:
        _drop(conversation_id)


def test_extraction_marks_the_turn_even_when_nothing_is_worthkeeping() -> None:
    conversation_id = _conversation([("user", "hello there"), ("assistant", "hi friend")])
    try:
        settings = get_settings()
        assert _run(extraction.extract_from_conversation(conversation_id, settings=settings)) == 0
        assert _memory_count() == 0

        marker = _marker(conversation_id)["memory_extracted_through"]
        assert marker > 0
        # …and that marker is what stops a second pass.
        assert _run(extraction.extract_from_conversation(conversation_id, settings=settings)) == 0
    finally:
        _drop(conversation_id)


def test_extraction_is_skipped_when_the_feature_is_off() -> None:
    conversation_id = _conversation([_EXTRACTABLE])
    try:
        disabled = Settings(rag={"memory_extraction": False})
        assert _run(extraction.extract_from_conversation(conversation_id, settings=disabled)) == 0
        assert _memory_count() == 0
        assert "memory_extracted_through" not in _marker(conversation_id)
    finally:
        _drop(conversation_id)


def test_extraction_ignores_an_unknown_conversation() -> None:
    assert _run(extraction.extract_from_conversation("missing0000", settings=get_settings())) == 0


def test_extraction_adds_the_llm_candidates_next_to_the_heuristics(monkeypatch) -> None:
    conversation_id = _conversation([_EXTRACTABLE])
    try:

        async def _fake(turns, settings):  # noqa: ANN001, ANN201
            return [
                {
                    "kind": "project",
                    "text": "Migrating the indexer onto sqlite-vec",
                    "importance": 0.9,
                    "source": "extracted",
                }
            ]

        monkeypatch.setattr(extraction, "_llm_candidates", _fake)
        settings = Settings(llm={"provider": "ollama"})

        saved = _run(extraction.extract_from_conversation(conversation_id, settings=settings))

        assert saved == 2
        assert sorted(_memory_texts()) == sorted(
            ["the staging host is luxion.dev", "Migrating the indexer onto sqlite-vec"]
        )
    finally:
        _drop(conversation_id)


def test_extraction_falls_back_to_heuristics_when_the_llm_answers_nothing(monkeypatch) -> None:
    conversation_id = _conversation([_EXTRACTABLE])
    try:

        async def _empty(turns, settings):  # noqa: ANN001, ANN201
            return []

        monkeypatch.setattr(extraction, "_llm_candidates", _empty)
        settings = Settings(llm={"provider": "ollama"})

        assert _run(extraction.extract_from_conversation(conversation_id, settings=settings)) == 1
        assert _memory_texts() == ["the staging host is luxion.dev"]
    finally:
        _drop(conversation_id)


def _memory_texts() -> list[str]:
    with get_session_factory()() as session:
        return [memory.text for memory in store.list_memories(session)]


# --------------------------------------------------------------- scheduling
def test_schedule_extraction_needs_a_running_loop() -> None:
    conversation_id = _conversation([_EXTRACTABLE])
    try:
        assert extraction.schedule_extraction(conversation_id) is None
    finally:
        _drop(conversation_id)


def test_schedule_extraction_runs_and_marks_in_the_background() -> None:
    conversation_id = _conversation([_EXTRACTABLE])

    async def _go() -> object:
        task = extraction.schedule_extraction(conversation_id)
        assert task is not None
        await task
        return task

    try:
        assert _run(_go()) is not None
        assert _memory_count() == 1
        assert "memory_extracted_through" in _marker(conversation_id)
    finally:
        _drop(conversation_id)


def test_schedule_extraction_is_off_when_the_feature_is_off() -> None:
    conversation_id = _conversation([_EXTRACTABLE])
    try:
        disabled = Settings(rag={"memory_extraction": False})
        assert extraction.schedule_extraction(conversation_id, settings=disabled) is None
        assert _memory_count() == 0
    finally:
        _drop(conversation_id)
