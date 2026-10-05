"""Memory + RAG (PRD §15 Conversation Memory, §16 RAG, §17 Repository
Intelligence — Phase 5).

Layout follows the PRD's own tree (prd.md §58):

* :mod:`luxion.rag.chunking`     — source → retrievable chunks
* :mod:`luxion.rag.embeddings`   — chunk → normalised vector
* :mod:`luxion.rag.vector_store` — vectors/keywords → ranked hits
* :mod:`luxion.memory`           — extraction, retrieval and the remember /
  recall / forget tools (Phase 5b)

The package is import-safe: nothing here opens a database or downloads a model
until :func:`init_rag` or a search call asks for it.
"""

from __future__ import annotations

from luxion.rag.chunking import ChunkDraft, chunk_file, chunk_prose, language_of
from luxion.rag.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    get_embedding_provider,
    reset_embedding_provider,
)
from luxion.rag.models import Chunk, RagMeta
from luxion.rag.vector_store import (
    SearchHit,
    ensure_index_tables,
    hybrid_search,
    install_vector_extension,
    reset_extension_state,
    write_chunks,
)


def init_rag(engine, *, dim_hint: int) -> dict[str, object]:
    """Install the vector extension and create the derived index tables.

    Called from :func:`luxion.database.session.init_db` right after
    ``create_all`` so the ORM tables (``chunks``, ``rag_meta``) exist first —
    the stored vector width is read from ``rag_meta`` before anything else.
    """
    install_vector_extension(engine)
    return ensure_index_tables(engine, dim_hint=dim_hint)


__all__ = [
    "Chunk",
    "ChunkDraft",
    "EmbeddingError",
    "EmbeddingProvider",
    "RagMeta",
    "SearchHit",
    "chunk_file",
    "chunk_prose",
    "get_embedding_provider",
    "hybrid_search",
    "init_rag",
    "install_vector_extension",
    "language_of",
    "reset_embedding_provider",
    "reset_extension_state",
    "write_chunks",
]
