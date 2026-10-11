"""Phase 5d: retrieved knowledge injected into the system prompt (PRD §58, §16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from luxion.config.settings import Settings, get_settings
from luxion.context.knowledge import (
    MIN_REPO_QUERY_CHARS,
    knowledge_context,
    memory_context,
    repository_context,
)
from luxion.database.session import get_session_factory, init_db
from luxion.llm.system_prompt import build_system_prompt
from luxion.memory import store as memory_store
from luxion.rag import vector_store
from luxion.rag.models import Chunk
from luxion.repository import indexer
from luxion.repository.scanner import REPO_SOURCE_TYPES

_PRODUCTION = "Postgres is the production database for the API"


@pytest.fixture()
def session():  # noqa: ANN201
    """Isolated store + index: the suite shares one database."""
    init_db()
    db = get_session_factory()()
    _clear_repo(db)
    memory_store.clear_memories(db)
    try:
        yield db
    finally:
        _clear_repo(db)
        memory_store.clear_memories(db)
        db.close()


def _clear_repo(db) -> None:  # noqa: ANN001
    sources = list(
        db.execute(
            select(Chunk.source).where(Chunk.source_type.in_(REPO_SOURCE_TYPES)).distinct()
        ).scalars()
    )
    for source in sources:
        vector_store.delete_source(db, source)
    db.commit()


def _settings(**rag: object) -> Settings:
    """A copy of the suite settings with per-test RAG overrides."""
    settings = get_settings().model_copy(deep=True)
    for key, value in rag.items():
        setattr(settings.rag, key, value)
    return settings


def _workspace(session, tmp_path: Path) -> Path:
    (tmp_path / "backoff.py").write_text(
        "def retry_with_backoff(operation, attempts=5):\n"
        '    """Retry the operation with exponential backoff."""\n'
        "    for attempt in range(attempts):\n"
        "        operation(attempt)\n",
        encoding="utf-8",
    )
    root = tmp_path.resolve()
    settings = _settings()
    settings.rag.index_extensions = [".py"]
    settings.rag.exclude = []
    report = indexer.sync_workspaces(session, roots=[root], settings=settings)
    assert report.indexed >= 1
    return root


# --------------------------------------------------------------- memory half
def test_memory_context_recalls_by_query(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    block = memory_context(session, _settings(), query="production database")

    assert block.startswith("- [")
    assert "Postgres" in block


def test_memory_context_falls_back_to_recent_memories(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    block = memory_context(session, _settings(), query="")

    assert "Postgres" in block, "no query must still inject the freshest memories"


def test_memory_context_falls_back_when_nothing_matches(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    block = memory_context(session, _settings(), query="zzz quantum banana xyz")

    assert "Postgres" in block, "zero hits falls back to recents, not to nothing"


def test_memory_context_respects_max_chars(session) -> None:
    memory_store.remember(session, _PRODUCTION)
    memory_store.remember(session, "The user likes pineapple on pizza")

    block = memory_context(session, _settings(), query="", max_chars=40)

    assert len(block) <= 40


def test_memory_context_is_off_when_inject_memory_is_false(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    assert memory_context(session, _settings(inject_memory=False), query="database") == ""


def test_memory_context_is_off_when_rag_is_disabled(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    assert memory_context(session, _settings(enabled=False), query="database") == ""


def test_memory_context_swallows_retrieval_failures(session, monkeypatch) -> None:
    memory_store.remember(session, _PRODUCTION)
    knowledge_mod = __import__("luxion.context.knowledge", fromlist=["x"])

    def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("boom")

    monkeypatch.setattr(knowledge_mod, "recall", _boom)

    assert memory_context(session, _settings(), query="database") == ""


def test_memory_context_is_empty_on_an_empty_store(session) -> None:
    assert memory_context(session, _settings(), query="anything at all") == ""


# ---------------------------------------------------------- repository half
def test_repository_context_points_at_the_matching_file(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)

    block = repository_context(session, _settings(), query="retry backoff")

    assert "backoff.py" in block


def test_repository_context_skips_a_too_short_query(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)

    assert repository_context(session, _settings(), query="a") == ""
    assert len("ab") < MIN_REPO_QUERY_CHARS


def test_repository_context_is_off_when_inject_repository_is_false(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)

    block = repository_context(session, _settings(inject_repository=False), query="retry backoff")
    assert block == ""


def test_repository_context_swallows_retrieval_failures(session, monkeypatch) -> None:
    knowledge_mod = __import__("luxion.context.knowledge", fromlist=["x"])
    monkeypatch.setattr(
        knowledge_mod,
        "files_relevant_to",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert repository_context(session, _settings(), query="anything long enough") == ""


# -------------------------------------------------------------- both halves
def test_knowledge_context_orders_memory_before_repository(session, tmp_path: Path) -> None:
    memory_store.remember(session, _PRODUCTION)
    _workspace(session, tmp_path)

    block = knowledge_context(session, _settings(), query="production database backoff")

    assert "Relevant memories:" in block
    assert "Relevant files:" in block
    assert block.index("Relevant memories:") < block.index("Relevant files:")


def test_knowledge_context_is_empty_when_everything_is_off(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    block = knowledge_context(
        session, _settings(inject_memory=False, inject_repository=False), query="database"
    )
    assert block == ""


def test_knowledge_context_is_empty_when_rag_is_disabled(session) -> None:
    memory_store.remember(session, _PRODUCTION)

    assert knowledge_context(session, _settings(enabled=False), query="database") == ""


def test_knowledge_context_is_empty_when_the_budget_is_zero(session) -> None:
    memory_store.remember(session, _PRODUCTION)
    settings = _settings()
    settings.context = settings.context.model_copy(update={"knowledge_max_chars": 0})

    assert knowledge_context(session, settings, query="database") == ""


def test_knowledge_context_reports_nothing_on_an_empty_store(session) -> None:
    assert knowledge_context(session, _settings(), query="anything at all") == ""


def test_knowledge_context_splits_the_budget_between_both_halves(session, tmp_path: Path) -> None:
    memory_store.remember(session, _PRODUCTION)
    memory_store.remember(session, "The user likes pineapple on pizza")
    memory_store.remember(session, "The backup lives on the fileserver in /mnt/backup")
    _workspace(session, tmp_path)
    settings = _settings()
    settings.context = settings.context.model_copy(update={"knowledge_max_chars": 200})

    block = knowledge_context(session, settings, query="postgres production backoff retry")

    # Each half is capped at its share, so the joined block cannot balloon.
    assert len(block) <= 200 + len("Relevant memories:\n") + len("\n\nRelevant files:\n") + 5


# ------------------------------------------------------------- system prompt
def test_build_system_prompt_appends_the_knowledge_block() -> None:
    prompt = build_system_prompt(
        _settings(), knowledge="Relevant memories:\n- [fact] Postgres is production"
    )

    assert "Context retrieved for this turn:" in prompt
    assert "- [fact] Postgres is production" in prompt
    assert prompt.index("Context retrieved for this turn:") > prompt.index("Autonomy:")


def test_build_system_prompt_ignores_blank_knowledge() -> None:
    plain = build_system_prompt(_settings())
    assert "Context retrieved for this turn:" not in plain


def test_custom_system_prompt_stays_verbatim_with_knowledge() -> None:
    settings = _settings()
    settings.llm = settings.llm.model_copy(update={"system_prompt": "You are Bob."})

    prompt = build_system_prompt(settings, knowledge="Relevant memories:\n- [fact] x")

    assert prompt == "You are Bob."


# ------------------------------------------------------------- end to end
def test_chat_turn_sends_the_injected_knowledge(
    session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real streamed turn must carry the knowledge block in its system message."""
    memory_store.remember(session, _PRODUCTION)
    _workspace(session, tmp_path)

    import asyncio

    from luxion.llm.types import StreamDelta, StreamDone
    from luxion.services import chat as chat_service
    from luxion.services.conversations import create_conversation

    seen: list[str] = []

    class _Recorder:
        """Fake provider that records the system prompt and answers instantly."""

        async def resolve_model(self) -> str:  # noqa: ANN201
            return "recorder"

        async def stream(self, messages, *, model=None, tools=None):  # noqa: ANN001, ANN202
            seen.append(messages[0].content)
            yield StreamDelta(text="The production database is Postgres.")
            yield StreamDone(model="recorder", finish_reason="stop")

    monkeypatch.setattr(chat_service, "get_provider", lambda _cfg: _Recorder())

    with get_session_factory()() as db:
        conversation = create_conversation(db, title=None)

    events = asyncio.run(
        _collect(chat_service.stream_reply(conversation.id, "where is the production database?"))
    )

    assert any(getattr(event, "type", "") == "done" for event in events)
    assert seen, "the provider must have been called"
    assert "Context retrieved for this turn:" in seen[0]
    assert "Relevant memories:" in seen[0]
    assert "Postgres" in seen[0]


async def _collect(stream):  # noqa: ANN001, ANN202
    events = []
    async for event in stream:
        events.append(event)
    return events
