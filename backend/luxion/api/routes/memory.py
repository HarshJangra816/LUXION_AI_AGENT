"""Memory CRUD + search (PRD §33.14 ``Remember…`` / ``What did I tell you…``).

The Settings → Memory page talks to these endpoints; the chat surface uses the
``remember`` / ``recall`` / ``forget`` tools instead (same store, same index).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from luxion.api.schemas import (
    MemoryCreate,
    MemoryListOut,
    MemoryOut,
    MemorySearchOut,
    MemorySearchRequest,
)
from luxion.database.session import get_db
from luxion.memory.models import MEMORY_KINDS
from luxion.memory.recall import format_memories, recall
from luxion.memory.store import clear_memories, count_memories, forget, list_memories, remember

router = APIRouter(prefix="/memory", tags=["memory"])

DbSession = Annotated[Session, Depends(get_db)]


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=MemoryListOut)
def get_memories(
    db: DbSession,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> MemoryListOut:
    """List stored memories, newest first (``?kind=preference`` to filter)."""
    if kind is not None and kind not in MEMORY_KINDS:
        raise HTTPException(
            status_code=400, detail=f"Unknown kind '{kind}'. Known: {', '.join(MEMORY_KINDS)}"
        )
    items = list_memories(db, kind=kind, limit=limit, offset=offset)
    return MemoryListOut(
        items=[MemoryOut.from_model(memory) for memory in items],
        total=count_memories(db, kind=kind),
        kind=kind,
    )


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(db: DbSession, payload: MemoryCreate) -> MemoryOut:
    """Store one statement from the UI (``created`` is implied by 201)."""
    try:
        memory, _created = remember(
            db,
            payload.text,
            kind=payload.kind,
            source="user",
            importance=payload.importance,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return MemoryOut.from_model(memory)


@router.post("/search", response_model=MemorySearchOut)
def search_memories(db: DbSession, payload: MemorySearchRequest) -> MemorySearchOut:
    """Hybrid (vector + keyword) search over stored memories (PRD §16)."""
    kinds = None
    if payload.kinds:
        unknown = [item for item in payload.kinds if item not in MEMORY_KINDS]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown kind(s): {', '.join(unknown)}. Known: {', '.join(MEMORY_KINDS)}",
            )
        kinds = set(payload.kinds)
    hits = recall(
        db,
        payload.query,
        k=payload.k,
        min_score=payload.min_score,
        kinds=kinds,
    )
    return MemorySearchOut(
        query=payload.query,
        hits=[MemoryOut.from_model(hit.memory, score=hit.score) for hit in hits],
        preview=format_memories([hit.memory for hit in hits]),
    )


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: int, db: DbSession) -> None:
    """Forget one memory (and its indexed copy)."""
    if not forget(db, memory_id):
        raise HTTPException(status_code=404, detail=f"Memory #{memory_id} not found")


@router.delete("", status_code=200)
def delete_all_memories(db: DbSession) -> dict[str, int]:
    """Settings → Memory → "Clear all"."""
    return {"deleted": clear_memories(db)}
