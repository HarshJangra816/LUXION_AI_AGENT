"""Vector + keyword index: write, hybrid search, rebuild, fallback (PRD §16).

Uses the ``hash`` embedding provider (see ``conftest.py``) so the suite never
downloads a model, and unique source URIs so the shared test database stays
deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from luxion.database.session import get_engine, get_session_factory, init_db
from luxion.rag import chunking, embeddings, vector_store
from luxion.rag.models import Chunk

_DOCS = {
    "tests://store.md": (
        "# Retrieval\n\n"
        "The retriever fuses vector and keyword results with rank fusion.\n\n"
        "Lexicon is the codename of the indexer.\n"
    ),
    "tests://other.md": (
        "# Storage\n\n"
        "Chunks are stored as float32 blobs in sqlite and indexed with vec0.\n\n"
        "The word carburetor only appears in this document.\n"
    ),
}


@pytest.fixture()
def store():
    init_db()
    session = get_session_factory()()
    provider = embeddings.get_embedding_provider()

    def index(docs: dict[str, str] | None = None) -> int:
        written = 0
        for source, doc in (docs or _DOCS).items():
            drafts = chunking.chunk_prose(doc, max_chars=120, overlap=30, language="markdown")
            vectors = provider.embed([draft.text for draft in drafts])
            written += vector_store.write_chunks(
                session,
                source=source,
                source_type="doc",
                chunks=drafts,
                vectors=vectors,
                model=provider.model,
            )
        vector_store.sync_meta(session, model=provider.model, dim=provider.dim)
        session.commit()
        return written

    try:
        yield SimpleNamespace(session=session, provider=provider, index=index)
    finally:
        for source in [*_DOCS, "tests://gone.md", "tests://self.md", "tests://bad.md"]:
            vector_store.delete_source(session, source)
        vector_store.sync_meta(session, model=provider.model, dim=provider.dim)
        session.commit()
        session.close()


def _chunk_count(session) -> int:
    return int(session.execute(select(func.count(Chunk.id))).scalar() or 0)


def test_vec_extension_and_index_tables_are_available() -> None:
    init_db()
    engine = get_engine()
    assert vector_store.vec_available(engine) is True
    first = vector_store.ensure_index_tables(engine, dim_hint=384)
    second = vector_store.ensure_index_tables(engine, dim_hint=384)
    assert first == second == {"vec": True, "dim": 384}


def test_write_then_hybrid_search(store) -> None:
    written = store.index()
    assert written >= 2
    assert _chunk_count(store.session) >= 2

    query = store.provider.embed_query("vector keyword rank fusion")
    hits = vector_store.hybrid_search(store.session, query, "rank fusion retriever", k=3)
    assert hits, "hybrid search should return something"
    assert hits[0].source in _DOCS
    assert 0.0 < hits[0].score <= 1.0
    assert "fusion" in hits[0].text or "retriever" in hits[0].text
    assert hits[0].chunk_id > 0
    assert hits[0].language == "markdown"
    assert hits[0].snippet
    assert hits[0].end_line >= hits[0].start_line


def test_keyword_search_finds_unique_term(store) -> None:
    store.index()
    hits = vector_store.hybrid_search(store.session, None, "carburetor", k=3)
    assert [hit.source for hit in hits] == ["tests://other.md"]


def test_min_score_filters_weak_vector_matches(store) -> None:
    store.index()
    unrelated = store.provider.embed_query("quantum tunnelling spectroscopy notes")
    loose = vector_store.hybrid_search(store.session, unrelated, "", k=5, min_score=0.0)
    strict = vector_store.hybrid_search(store.session, unrelated, "", k=5, min_score=0.99)
    assert loose, "min_score=0 should keep vector hits"
    assert strict == [], "min_score=0.99 should drop unrelated vectors"


def test_delete_source_clears_every_index(store) -> None:
    store.index({"tests://gone.md": "# Temp\n\nThis source will be removed.\n"})
    before = _chunk_count(store.session)

    removed = vector_store.delete_source(store.session, "tests://gone.md")
    store.session.commit()

    assert removed >= 1
    assert _chunk_count(store.session) == before - removed
    remaining = store.session.execute(
        text("SELECT count(*) FROM chunks WHERE source = :s"), {"s": "tests://gone.md"}
    ).scalar()
    assert remaining == 0
    assert vector_store.hybrid_search(store.session, None, "removed", k=5) == []


def test_malformed_keyword_query_is_not_an_error(store) -> None:
    store.index()
    for raw in ("AND OR NOT (", 'NEAR("', '""', "   ", "\\", "foo*"):
        assert isinstance(vector_store.keyword_search(store.session, raw, k=3), list)


def test_numpy_fallback_agrees_with_vec0(store) -> None:
    store.index()
    engine = get_engine()
    query = store.provider.embed_query("float32 blobs in sqlite")
    with_vec = vector_store.vector_search(store.session, query, 3)

    key = str(engine.url)
    previous = vector_store._vec_state.get(key)
    vector_store._vec_state[key] = False
    try:
        without_vec = vector_store.vector_search(store.session, query, 3)
    finally:
        if previous is None:
            vector_store._vec_state.pop(key, None)
        else:
            vector_store._vec_state[key] = previous

    assert [chunk_id for chunk_id, _ in without_vec] == [chunk_id for chunk_id, _ in with_vec]
    assert without_vec[0][1] == pytest.approx(with_vec[0][1], rel=1e-6)


def test_stored_width_wins_over_the_configured_hint(store) -> None:
    store.index()
    assert vector_store.ensure_index_tables(get_engine(), dim_hint=768) == {
        "vec": True,
        "dim": store.provider.dim,
    }


def test_sync_meta_reports_pending_model(store) -> None:
    store.index()
    provider = store.provider
    meta = vector_store.sync_meta(store.session, model=provider.model, dim=provider.dim)
    store.session.commit()
    assert meta.model == provider.model
    assert meta.dim == provider.dim
    assert meta.pending_model == ""
    assert meta.chunk_count >= 2
    assert meta.vector_count == meta.chunk_count

    stale = vector_store.sync_meta(store.session, model="other/model-768", dim=768)
    store.session.commit()
    assert stale.model == provider.model, "stored model must not change until re-embedded"
    assert stale.dim == provider.dim
    assert stale.pending_model == "other/model-768"

    restored = vector_store.sync_meta(store.session, model=provider.model, dim=provider.dim)
    store.session.commit()
    assert restored.pending_model == ""


def test_rebuild_vector_index_restores_every_row(store) -> None:
    store.index()
    session = store.session
    expected = _chunk_count(session)
    rebuilt = vector_store.rebuild_vector_index(session, dim=store.provider.dim)
    session.commit()
    assert rebuilt == expected
    hits = vector_store.hybrid_search(
        session, store.provider.embed_query("vector keyword rank fusion"), "retriever", k=3
    )
    assert hits and hits[0].score > 0


def test_rebuild_skips_vectors_of_a_different_width(store) -> None:
    store.index()
    session = store.session
    try:
        assert vector_store.rebuild_vector_index(session, dim=999) == 0
        session.commit()
        hits = vector_store.hybrid_search(
            session, store.provider.embed_query("float32 blobs in sqlite"), "float32", k=3
        )
        assert hits, "keyword-only retrieval must keep working without a vector index"
    finally:
        vector_store.rebuild_vector_index(session, dim=store.provider.dim)
        session.commit()


def test_write_chunks_rejects_misaligned_input(store) -> None:
    import numpy as np

    with pytest.raises(ValueError, match="align 1:1"):
        vector_store.write_chunks(
            store.session,
            source="tests://bad.md",
            source_type="doc",
            chunks=[object(), object()],
            vectors=[np.zeros(4, dtype=np.float32)],
            model="hash",
        )


def test_a_stored_vector_matches_itself(store) -> None:
    doc = "# Self\n\nsignal detection theory primer\n"
    store.index({"tests://self.md": doc})
    expected = chunking.chunk_prose(doc, max_chars=120, overlap=0, language="markdown")[0]
    exact = store.provider.embed_query(expected.text)
    chunk_id, cosine = vector_store.vector_search(store.session, exact, 1)[0]
    assert cosine > 0.99, "a stored vector must match itself"
    assert cosine <= 1.0
    row = store.session.get(Chunk, chunk_id)
    assert row is not None and row.text == expected.text
