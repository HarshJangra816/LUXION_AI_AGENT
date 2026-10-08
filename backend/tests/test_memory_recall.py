"""Phase 5b read side: hybrid recall, recency and the prompt block (PRD §15, §16)."""

from __future__ import annotations

import importlib

import pytest

from luxion.database.session import get_session_factory, init_db
from luxion.memory import store
from luxion.memory.models import Memory
from luxion.memory.recall import MemoryHit, format_memories, recall, recent_memories
from luxion.rag.embeddings import EmbeddingError

#: ``luxion.memory.__init__`` re-exports the ``recall`` *function*, so the module
#: itself has to be fetched by name to monkeypatch it.
recall_mod = importlib.import_module("luxion.memory.recall")

_PRODUCTION = "Postgres is the production database for the API"
_PIZZA = "The user likes pineapple on pizza"
_TINNED = "The backup lives on the fileserver in /mnt/backup"


@pytest.fixture()
def session():  # noqa: ANN201
    init_db()
    db = get_session_factory()()
    store.clear_memories(db)
    try:
        yield db
    finally:
        store.clear_memories(db)
        db.close()


# ------------------------------------------------------------------- retrieval
def test_recall_finds_a_memory_by_an_exact_phrase(session) -> None:
    memory, _ = store.remember(session, _PRODUCTION)

    hits = recall(session, "production database")

    assert [hit.memory.id for hit in hits] == [memory.id]
    assert hits[0].chunk_id > 0
    assert 0.0 < hits[0].score <= 1.0


def test_recall_ranks_the_relevant_memory_first(session) -> None:
    store.remember(session, _PRODUCTION)
    store.remember(session, _PIZZA)
    store.remember(session, _TINNED)

    hits = recall(session, "postgres production database")

    assert hits
    assert hits[0].memory.text == _PRODUCTION


def test_recall_respects_k(session) -> None:
    store.remember(session, _PRODUCTION)
    store.remember(session, _PIZZA)
    store.remember(session, _TINNED)

    assert len(recall(session, "database", k=1)) == 1
    assert 1 <= len(recall(session, "database", k=2)) <= 2


def test_recall_returns_nothing_for_a_blank_query(session) -> None:
    store.remember(session, _PRODUCTION)
    assert recall(session, "") == []
    assert recall(session, "   ") == []


def test_recall_reports_nothing_for_an_unrelated_query(session) -> None:
    store.remember(session, _PIZZA)
    # A strict min_score empties the vector side, and the words match nothing.
    assert recall(session, "quantum chromodynamics lattice gauge", min_score=0.99) == []


def test_recall_filters_by_kind(session) -> None:
    store.remember(session, "Zebra preference: likes tabs", kind="preference")
    store.remember(session, "Zebra fact: uses vim", kind="fact")

    everything = recall(session, "zebra")
    assert len(everything) == 2, "both rows must be retrievable for the filter to matter"

    only_preferences = recall(session, "zebra", kinds={"preference"})
    assert [hit.memory.kind for hit in only_preferences] == ["preference"]
    assert recall(session, "zebra", kinds={"episode"}) == []


def test_recall_never_raises_when_the_embedding_model_is_down(session, monkeypatch) -> None:
    memory, _ = store.remember(session, _TINNED)

    def _boom() -> None:
        raise EmbeddingError("model unavailable")

    monkeypatch.setattr(recall_mod, "get_embedding_provider", _boom)

    assert [hit.memory.id for hit in recall(session, "fileserver backup")] == [memory.id]


def test_min_score_never_hides_an_exact_keyword_hit(session) -> None:
    """``min_score`` gates the vector side only — identifiers stay findable."""
    memory, _ = store.remember(session, "The WAL directory sits next to the database")

    assert [hit.memory.id for hit in recall(session, "wal directory", min_score=0.99)] == [
        memory.id
    ]


# --------------------------------------------------------------------- payload
def test_memory_hit_payload_carries_the_ranked_score(session) -> None:
    store.remember(session, _PRODUCTION, importance=0.9)

    hit = recall(session, "production database")[0]

    assert isinstance(hit, MemoryHit)
    payload = hit.as_dict()
    assert payload["score"] == pytest.approx(round(float(hit.score), 4))
    assert payload["importance"] == 0.9
    assert payload["kind"] == "fact"
    assert payload["conversation_id"] is None


# --------------------------------------------------------------------- recency
def test_recent_memories_returns_the_freshest_rows_first(session) -> None:
    store.remember(session, "Oldest note")
    store.remember(session, "Middle note")
    store.remember(session, "Newest note")

    recent = recent_memories(session, k=2)

    assert [memory.text for memory in recent] == ["Newest note", "Middle note"]
    assert len(recent_memories(session, k=99)) == 3
    assert recent_memories(session, k=2, kinds={"episode"}) == []


# --------------------------------------------------------------- prompt block
def test_format_memories_renders_the_prompt_block(session) -> None:
    first, _ = store.remember(session, _PRODUCTION, kind="fact")
    second, _ = store.remember(session, "Prefers concise answers", kind="preference")

    block = format_memories([first, second])

    assert block.splitlines() == [
        f"- [fact] {_PRODUCTION}",
        "- [preference] Prefers concise answers",
    ]


def test_format_memories_respects_the_character_budget(session) -> None:
    memory, _ = store.remember(session, "A very long statement that fills the budget " * 4)

    assert format_memories([memory], max_chars=10) == ""
    assert format_memories([]) == ""
    assert format_memories([memory], max_chars=2000).startswith("- [fact] ")


def test_format_memories_accepts_detached_rows() -> None:
    detached = Memory(kind="task", text="Ship the release", hash="x", source="user")
    assert format_memories([detached]) == "- [task] Ship the release"
