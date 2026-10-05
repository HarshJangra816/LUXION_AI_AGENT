"""Indexed content (PRD §16 chunking, §17 repository intelligence).

A *chunk* is one retrievable piece of a source: a paragraph range from a
document, a code block, or (from Phase 5b) a memory. The row holds the text
**and** its float32 vector, so the sqlite-vec table is a rebuildable
accelerator rather than the source of truth — swapping the embedding model
rewrites ``embedding`` and re-creates the index without losing content.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from luxion.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Absolute path for indexed files, ``memory:<id>`` for Phase 5b entries.
    source: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    #: ``doc`` | ``code`` | ``memory`` — decides how the hit is presented.
    source_type: Mapped[str] = mapped_column(String(16), default="doc")
    language: Mapped[str] = mapped_column(String(32), default="")
    start_line: Mapped[int] = mapped_column(Integer, default=0)
    end_line: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    #: sha1 of ``text`` — lets the indexer skip unchanged content.
    hash: Mapped[str] = mapped_column(String(40), default="", index=True)
    #: L2-normalised float32 vector (``dim * 4`` bytes), ``NULL`` = not embedded.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: Model that produced ``embedding``; differs from the config after a switch.
    embedding_model: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RagMeta(Base):
    """Single-row bookkeeping for the index (always ``id = 1``)."""

    __tablename__ = "rag_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    #: Model the stored vectors were produced with.
    model: Mapped[str] = mapped_column(String(256), default="")
    #: Width of those vectors — the ``chunks_vec`` table is built with it.
    dim: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Set when the configured model no longer matches ``model``: the index
    #: still answers with the old vectors until the user re-embeds.
    pending_model: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


__all__ = ["Chunk", "RagMeta"]
