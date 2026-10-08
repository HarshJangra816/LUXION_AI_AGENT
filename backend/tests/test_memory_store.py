"""Phase 5b write side: ``remember`` / ``forget`` / ``list`` + indexing (PRD §15)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from luxion.config.settings import Settings
from luxion.database.session import get_session_factory, init_db
from luxion.memory import store
from luxion.memory.models import MEMORY_KINDS, Memory
from luxion.memory.recall import recall
from luxion.rag import vector_store
from luxion.rag.embeddings import EmbeddingError


class _BrokenProvider:
    """An embedding backend that is down — the keyword path must survive it."""

    model = "broken"
    dim = 8

    def embed(self, texts):  # noqa: ANN001, ANN201
        raise EmbeddingError("model unavailable")

    def embed_query(self, text: str):  # noqa: ANN201
        raise EmbeddingError("model unavailable")


@pytest.fixture()
def session():  # noqa: ANN201
    """Isolated store: the suite shares one database, so clear around each test."""
    init_db()
    db = get_session_factory()()
    store.clear_memories(db)
    try:
        yield db
    finally:
        store.clear_memories(db)
        db.close()


# ------------------------------------------------------------------ normalise
def test_normalize_text_collapses_whitespace_and_drops_trailing_punctuation() -> None:
    assert store.normalize_text("  I   prefer\t the   dark\nmode...  ") == "I prefer the dark mode"
    assert store.normalize_text("") == ""
    assert store.normalize_text("   .,,?! ") == ""


def test_normalize_text_caps_the_statement_length() -> None:
    long = " ".join(["word"] * 400)
    cleaned = store.normalize_text(long)
    assert len(cleaned) <= store.MAX_TEXT
    assert cleaned.endswith("word"), "the cap must cut on a word boundary"


def test_memory_hash_is_stable_and_case_insensitive() -> None:
    assert store.memory_hash("Prefer the tabs key") == store.memory_hash("  prefer   the TABS key ")
    assert store.memory_hash("prefer tabs") != store.memory_hash("prefer spaces")


# ------------------------------------------------------------------- remember
def test_remember_stores_and_indexes_the_statement(session) -> None:
    memory, created = store.remember(session, "The deploy script lives in scripts/deploy.ps1")

    assert created is True
    assert memory.id > 0
    assert memory.kind == "fact"
    assert memory.source == "user"
    assert memory.importance == 0.5
    assert store.count_memories(session) == 1
    assert store.get_memory(session, memory.id) is not None

    hits = vector_store.hybrid_search(session, None, "deploy script", k=3, source_types={"memory"})
    assert [hit.source for hit in hits] == [f"memory:{memory.id}"]


def test_remember_dedupes_the_same_statement(session) -> None:
    first, created_first = store.remember(session, "Prefers Postgres over SQLite")
    second, created_second = store.remember(session, "  prefers   postgres over sqlite.  ")

    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert store.count_memories(session) == 1


def test_remember_rejects_an_empty_statement(session) -> None:
    with pytest.raises(ValueError, match="needs some text"):
        store.remember(session, "   .,,?!  ")
    assert store.count_memories(session) == 0


def test_remember_rejects_an_unknown_kind(session) -> None:
    with pytest.raises(ValueError, match="unknown memory kind") as excinfo:
        store.remember(session, "A durable statement", kind="secret")
    for kind in MEMORY_KINDS:
        assert kind in str(excinfo.value)
    assert store.count_memories(session) == 0


def test_remember_clamps_importance_into_the_0_1_range(session) -> None:
    high, _ = store.remember(session, "Critical pin", importance=5.0)
    low, _ = store.remember(session, "Background noise", importance=-2.0)
    assert high.importance == 1.0
    assert low.importance == 0.0


def test_remember_stops_at_the_configured_ceiling(session, monkeypatch) -> None:
    # ``memory_max`` is validated at >= 10, so fill the store for real.
    monkeypatch.setattr(store, "get_settings", lambda: Settings(rag={"memory_max": 10}))
    for index in range(10):
        store.remember(session, f"Ceiling statement number {index}")
    assert store.count_memories(session) == 10

    with pytest.raises(ValueError, match="memory limit reached"):
        store.remember(session, "One memory too many")
    assert store.count_memories(session) == 10


# ----------------------------------------------------------------- list / get
def test_get_list_and_count(session) -> None:
    store.remember(session, "Alpha note about routing", kind="fact")
    store.remember(session, "Beta preference for vim", kind="preference")

    everything = store.list_memories(session)
    assert len(everything) == 2
    assert store.count_memories(session) == 2
    assert store.count_memories(session, kind="preference") == 1

    only_preferences = store.list_memories(session, kind="preference")
    assert [memory.text for memory in only_preferences] == ["Beta preference for vim"]

    assert store.get_memory(session, everything[0].id) is not None
    assert store.get_memory(session, 9_999_999) is None


def test_list_memories_is_newest_first_and_honours_limit(session) -> None:
    for index in range(3):
        store.remember(session, f"Statement number {index}")
    listed = store.list_memories(session, limit=2)
    assert len(listed) == 2
    assert listed[0].text == "Statement number 2"
    assert store.list_memories(session, limit=99)  # clamped to 500, never an error


# -------------------------------------------------------------------- forget
def test_forget_removes_the_row_and_its_indexed_copy(session) -> None:
    memory, _ = store.remember(session, "Disposable statement about zebras")

    assert store.forget(session, memory.id) is True
    assert store.get_memory(session, memory.id) is None
    assert store.count_memories(session) == 0
    assert (
        session.execute(select(Memory).where(Memory.id == memory.id)).scalar_one_or_none() is None
    )
    assert vector_store.hybrid_search(session, None, "zebras", k=3, source_types={"memory"}) == []
    assert store.forget(session, memory.id) is False


def test_clear_memories_drops_every_row_and_chunk(session) -> None:
    for index in range(3):
        store.remember(session, f"Statement number {index}")
    assert store.count_memories(session) == 3

    assert store.clear_memories(session) == 3
    assert store.count_memories(session) == 0
    assert store.clear_memories(session) == 0
    assert (
        vector_store.hybrid_search(session, None, "statement number", k=5, source_types={"memory"})
        == []
    )


# -------------------------------------------------------------- embedding loss
def test_index_memory_still_indexes_when_the_model_is_down(session) -> None:
    memory, _ = store.remember(session, "The unicorn passphrase is hunter2", index=False)
    assert store.index_memory(session, memory, provider=_BrokenProvider()) is False

    hits = vector_store.hybrid_search(
        session, None, "unicorn passphrase", k=3, source_types={"memory"}
    )
    assert [hit.source for hit in hits] == [f"memory:{memory.id}"]

    # End to end: a memory without a vector is still recallable by keyword.
    assert [hit.memory.id for hit in recall(session, "unicorn passphrase")] == [memory.id]


def test_index_memory_rewrites_are_idempotent(session) -> None:
    memory, _ = store.remember(session, "Rewrite me exactly once")
    first = store.index_memory(session, memory)
    second = store.index_memory(session, memory)
    assert first is True and second is True
    hits = vector_store.hybrid_search(session, None, "rewrite", k=5, source_types={"memory"})
    assert [hit.source for hit in hits] == [f"memory:{memory.id}"]
