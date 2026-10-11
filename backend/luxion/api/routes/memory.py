"""Memory CRUD + search (PRD §33.14 ``Remember…`` / ``What did I tell you…``).

The Settings → Memory page talks to these endpoints; the chat surface uses the
``remember`` / ``recall`` / ``forget`` tools instead (same store, same index).

``GET    /memory/config``   effective RAG/memory settings + defaults + index
                            health (counts, re-embed owed, model catalogue)
``PUT    /memory/config``   persist the Settings → Memory edits
``DELETE /memory/config``   back to ``.env`` defaults
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from luxion.api.schemas import (
    MemoryCreate,
    MemoryListOut,
    MemoryOut,
    MemorySearchOut,
    MemorySearchRequest,
)
from luxion.config.rag_override import clear_overrides
from luxion.config.settings import (
    EMBEDDING_MODELS,
    RAGConfig,
    get_settings,
    reset_settings_cache,
    save_rag_overrides,
)
from luxion.database.session import get_db
from luxion.memory.models import MEMORY_KINDS
from luxion.memory.recall import format_memories, recall
from luxion.memory.store import clear_memories, count_memories, forget, list_memories, remember
from luxion.rag import vector_store
from luxion.rag.embeddings import reset_embedding_provider

router = APIRouter(prefix="/memory", tags=["memory"])

DbSession = Annotated[Session, Depends(get_db)]


class RAGConfigBundle(BaseModel):
    """What Settings → Memory edits (effective values + defaults + health)."""

    config: RAGConfig
    defaults: RAGConfig
    #: The index was built with a different embedding model — offer re-embed.
    needs_reembed: bool = False
    chunks: int = 0
    vectors: int = 0
    #: Curated fastembed models the dropdown offers (PRD §16 embedding step).
    embedding_models: list[dict[str, Any]] = []


class RAGConfigPatch(BaseModel):
    """Partial RAG settings — mirrors every field of ``RAGConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.RAGConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    provider: str | None = None
    embedding_model: str | None = None
    chunk_chars: int | None = None
    chunk_overlap: int | None = None
    top_k: int | None = None
    min_score: float | None = None
    index_extensions: list[str] | None = None
    exclude: list[str] | None = None
    max_file_bytes: int | None = None
    max_files: int | None = None
    index_on_start: bool | None = None
    reembed_batch: int | None = None
    memory_extraction: bool | None = None
    memory_max: int | None = None
    inject_memory: bool | None = None
    inject_repository: bool | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _bundle(db: Session) -> RAGConfigBundle:
    settings = get_settings()
    meta = vector_store.sync_meta(
        db,
        model=settings.rag.embedding_model,
        dim=settings.embedding_dim,
    )
    return RAGConfigBundle(
        config=settings.rag,
        defaults=RAGConfig(),
        needs_reembed=bool(meta.pending_model),
        chunks=int(meta.chunk_count or 0),
        vectors=int(meta.vector_count or 0),
        embedding_models=[spec.model_dump() for spec in EMBEDDING_MODELS],
    )


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


@router.get("/config", response_model=RAGConfigBundle)
def read_rag_config(db: DbSession) -> RAGConfigBundle:
    """Effective memory/RAG settings (defaults → `.env` → `rag.json`) + health."""
    return _bundle(db)


@router.put("/config", response_model=RAGConfigBundle)
def update_rag_config(db: DbSession, payload: RAGConfigPatch) -> RAGConfigBundle:
    """Persist the Settings → Memory edits (embedding model included)."""
    values = payload.values()
    if not values:
        raise HTTPException(status_code=400, detail="No memory settings were provided")
    save_rag_overrides(get_settings(), values)
    # A new embedding model only takes effect once the cached provider is
    # dropped; the *index* still holds the old vectors (needs_reembed=True
    # until the user runs the re-embed job).
    reset_embedding_provider()
    return _bundle(db)


@router.delete("/config", response_model=RAGConfigBundle)
def reset_rag_config(db: DbSession) -> RAGConfigBundle:
    """Drop ``rag.json`` so ``.env`` / built-in defaults win again."""
    clear_overrides(get_settings().app.data_dir)
    reset_settings_cache()
    reset_embedding_provider()
    return _bundle(db)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: int, db: DbSession) -> None:
    """Forget one memory (and its indexed copy)."""
    if not forget(db, memory_id):
        raise HTTPException(status_code=404, detail=f"Memory #{memory_id} not found")


@router.delete("", status_code=200)
def delete_all_memories(db: DbSession) -> dict[str, int]:
    """Settings → Memory → "Clear all"."""
    return {"deleted": clear_memories(db)}
