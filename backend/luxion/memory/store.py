"""Create, look up and drop memories — the write side of Phase 5b.

Every stored memory is also written into the Phase 5a hybrid index under
``source = "memory:<id>"`` / ``source_type = "memory"``, which is what makes
"What did I tell you about …" work the same way as document retrieval.
If embedding fails the statement is *still* stored: an unembedded memory stays
reachable through FTS5, so losing the model never loses the note.
"""

from __future__ import annotations

import hashlib
import logging
import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from luxion.config.settings import get_settings
from luxion.memory.models import DEFAULT_KIND, MEMORY_KINDS, Memory
from luxion.rag import vector_store
from luxion.rag.chunking import PROSE_KIND, ChunkDraft
from luxion.rag.embeddings import EmbeddingError, EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)

#: Hard ceiling on one statement — memories are statements, not paragraphs.
MAX_TEXT = 600
#: PRD §58: the assistant must not keep the whole conversation forever.
MAX_MEMORIES = 1_000

_WHITESPACE = re.compile(r"\s+")
#: "Don't forget to …" / "never store passwords" style trailing punctuation.
_TRAILING = " \t\n.,;:!?\"'"

__all__ = [
    "MAX_MEMORIES",
    "MAX_TEXT",
    "clear_memories",
    "count_memories",
    "forget",
    "get_memory",
    "index_memory",
    "list_memories",
    "memory_hash",
    "normalize_text",
    "remember",
]


def normalize_text(text: str) -> str:
    """Collapse whitespace and cap the length (the dedupe key's input)."""
    cleaned = _WHITESPACE.sub(" ", str(text)).strip(_TRAILING).strip()
    if len(cleaned) > MAX_TEXT:
        cleaned = cleaned[:MAX_TEXT].rsplit(" ", 1)[0] or cleaned[:MAX_TEXT]
    return cleaned


def memory_hash(text: str) -> str:
    """Stable identity of a statement: same words ⇒ same memory, never a twin."""
    return hashlib.sha1(normalize_text(text).casefold().encode("utf-8")).hexdigest()


def remember(
    session: Session,
    text: str,
    *,
    kind: str = DEFAULT_KIND,
    source: str = "user",
    conversation_id: str | None = None,
    importance: float = 0.5,
    index: bool = True,
    provider: EmbeddingProvider | None = None,
) -> tuple[Memory, bool]:
    """Store one statement.

    Returns ``(memory, created)`` — ``created=False`` when an identical
    statement is already known (dedupe on :func:`memory_hash`).
    """
    cleaned = normalize_text(text)
    if not cleaned:
        raise ValueError("a memory needs some text")
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind '{kind}'. Known: {', '.join(MEMORY_KINDS)}")

    digest = memory_hash(cleaned)
    existing = session.execute(select(Memory).where(Memory.hash == digest)).scalar_one_or_none()
    if existing is not None:
        return existing, False

    limit = get_settings().rag.memory_max
    if count_memories(session) >= limit:
        raise ValueError(f"memory limit reached ({limit} stored memories)")

    memory = Memory(
        kind=kind,
        text=cleaned,
        hash=digest,
        source=source,
        importance=min(1.0, max(0.0, float(importance))),
        conversation_id=conversation_id,
    )
    session.add(memory)
    session.flush()
    if index:
        index_memory(session, memory, provider=provider)
    session.commit()
    return memory, True


def get_memory(session: Session, memory_id: int) -> Memory | None:
    return session.get(Memory, memory_id)


def list_memories(
    session: Session,
    *,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Memory]:
    """Newest first (Settings → Memory lists, and the recall UI)."""
    statement = select(Memory)
    if kind:
        statement = statement.where(Memory.kind == kind)
    statement = (
        statement.order_by(Memory.updated_at.desc(), Memory.id.desc())
        .limit(max(1, min(limit, 500)))
        .offset(max(0, offset))
    )
    return list(session.execute(statement).scalars())


def count_memories(session: Session, *, kind: str | None = None) -> int:
    statement = select(func.count(Memory.id))
    if kind:
        statement = statement.where(Memory.kind == kind)
    return int(session.execute(statement).scalar() or 0)


def forget(session: Session, memory_id: int) -> bool:
    """Delete one memory and its indexed copy. Returns ``False`` if unknown."""
    memory = session.get(Memory, memory_id)
    if memory is None:
        return False
    vector_store.delete_source(session, memory.chunk_source)
    session.delete(memory)
    session.flush()
    session.commit()
    return True


def clear_memories(session: Session) -> int:
    """Drop every memory (Settings → Memory → "Clear all")."""
    ids = [int(value) for value in session.execute(select(Memory.id)).scalars()]
    if not ids:
        return 0
    for memory_id in ids:
        vector_store.delete_source(session, f"memory:{memory_id}")
    session.execute(delete(Memory))
    session.flush()
    session.commit()
    return len(ids)


def index_memory(
    session: Session,
    memory: Memory,
    *,
    provider: EmbeddingProvider | None = None,
) -> bool:
    """(Re)write the memory's chunk. ``False`` means it is keyword-only now."""
    try:
        active = provider or get_embedding_provider()
        vectors: list = [active.embed([memory.text])[0]]
        model = active.model
    except EmbeddingError as exc:
        logger.warning("memory_not_embedded id=%s error=%s", memory.id, exc)
        vectors = [None]
        model = ""

    draft = ChunkDraft(
        text=memory.text,
        start_line=1,
        end_line=1,
        kind=PROSE_KIND,
        language="text",
    )
    vector_store.write_chunks(
        session,
        source=memory.chunk_source,
        source_type="memory",
        chunks=[draft],
        vectors=vectors,
        model=model,
    )
    return vectors[0] is not None
