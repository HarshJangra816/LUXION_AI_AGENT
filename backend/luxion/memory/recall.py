"""Recall — Phase 5b's read side (PRD §15 + the §16 process, applied to memory).

Retrieval is the same hybrid search the document index uses, narrowed to
``source_type="memory"``, so a memory can be found by meaning *and* by an
exact phrase (someone saying "SQLite" remembers the note that says it).

``score`` is the vector cosine when the index had one and a rank-derived value
for keyword-only hits — it orders results, while ``Memory.importance`` stays a
separate, user-visible weight (a pinned preference is not "more similar").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from luxion.memory.models import Memory
from luxion.rag import vector_store
from luxion.rag.embeddings import EmbeddingError, get_embedding_provider

logger = logging.getLogger(__name__)

MEMORY_SOURCE_TYPE = "memory"


@dataclass(slots=True)
class MemoryHit:
    """One retrieved memory, ready for a tool result or the context block."""

    memory: Memory
    #: 0..1 — cosine similarity, or a rank-derived value for keyword hits.
    score: float
    chunk_id: int

    def as_dict(self) -> dict[str, object]:
        payload = self.memory.as_dict()
        payload["score"] = round(float(self.score), 4)
        return payload


def _embed_query(query: str):
    """Query vector, or ``None`` when the model is unavailable (keyword path)."""
    try:
        return get_embedding_provider().embed_query(query)
    except EmbeddingError as exc:
        logger.warning("memory_query_not_embedded error=%s", exc)
        return None


def recall(
    session: Session,
    query: str,
    *,
    k: int = 6,
    min_score: float = 0.0,
    kinds: set[str] | None = None,
) -> list[MemoryHit]:
    """Search stored memories, best first. Never raises on a model failure."""
    text = (query or "").strip()
    if not text:
        return []
    hits = vector_store.hybrid_search(
        session,
        _embed_query(text),
        text,
        k=max(1, k) * 3,
        min_score=min_score,
        source_types={MEMORY_SOURCE_TYPE},
    )
    # rank order first, rows second: the index decides the order, not the table
    ordered_ids: list[int] = []
    score_by_id: dict[int, float] = {}
    chunk_by_id: dict[int, int] = {}
    for hit in hits:
        prefix, _, raw_id = hit.source.partition(":")
        if prefix != "memory" or not raw_id.isdigit():
            continue
        memory_id = int(raw_id)
        score_by_id.setdefault(memory_id, hit.score)
        chunk_by_id.setdefault(memory_id, hit.chunk_id)
        if memory_id not in ordered_ids:
            ordered_ids.append(memory_id)
    if not ordered_ids:
        return []

    rows = session.execute(select(Memory).where(Memory.id.in_(ordered_ids))).scalars()
    by_id = {memory.id: memory for memory in rows}

    results: list[MemoryHit] = []
    for memory_id in ordered_ids:
        memory = by_id.get(memory_id)
        if memory is None:
            continue
        if kinds and memory.kind not in kinds:
            continue
        results.append(
            MemoryHit(
                memory=memory,
                score=score_by_id.get(memory_id, 0.0),
                chunk_id=chunk_by_id.get(memory_id, 0),
            )
        )
        if len(results) >= k:
            break
    return results


def recent_memories(
    session: Session,
    *,
    k: int = 5,
    kinds: set[str] | None = None,
) -> list[Memory]:
    """Freshest memories first — what the context manager injects unasked."""
    statement = select(Memory)
    if kinds:
        statement = statement.where(Memory.kind.in_(set(kinds)))
    statement = statement.order_by(Memory.updated_at.desc(), Memory.id.desc()).limit(max(1, k))
    return list(session.execute(statement).scalars())


def format_memories(memories: list[Memory], *, max_chars: int = 1200) -> str:
    """Render memories as the ``Relevant Memory`` block of the prompt (PRD §58)."""
    parts: list[str] = []
    used = 0
    for memory in memories:
        line = f"- [{memory.kind}] {memory.text}"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


__all__ = [
    "MEMORY_SOURCE_TYPE",
    "MemoryHit",
    "format_memories",
    "recall",
    "recent_memories",
]
