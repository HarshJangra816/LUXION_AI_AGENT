"""Repository index + search (PRD §16 RAG, §17 Repository Intelligence).

``GET  /api/repository``      what is indexed, from where (Knowledge page).
``POST /api/repository/index`` run one incremental sync (the "Index files" button).
``POST /api/repository/search`` the same hybrid search the ``search_code`` tool
uses, so the UI can preview results without going through a model turn.

Syncing is a normal sync ``def`` route, so FastAPI runs it on its worker
thread and a large workspace never blocks the event loop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from luxion.api.schemas import (
    RepositoryFileOut,
    RepositoryHitOut,
    RepositoryIndexOut,
    RepositorySearchOut,
    RepositorySearchRequest,
    RepositoryStatusOut,
)
from luxion.config.settings import get_settings
from luxion.database.session import get_db
from luxion.repository.indexer import count_repo_chunks, count_repo_files, sync_workspaces
from luxion.repository.retrieval import files_relevant_to, format_repo_context, search_repository

router = APIRouter(prefix="/repository", tags=["repository"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=RepositoryStatusOut)
def repository_status(db: DbSession) -> RepositoryStatusOut:
    """Index size and the walk policy behind it."""
    cfg = get_settings()
    return RepositoryStatusOut(
        enabled=cfg.rag.enabled,
        roots=[str(path) for path in cfg.security.allowed_workspaces],
        files=count_repo_files(db),
        chunks=count_repo_chunks(db),
        extensions=list(cfg.rag.index_extensions),
        exclude=list(cfg.rag.exclude),
        index_on_start=cfg.rag.index_on_start,
    )


@router.post("/index", response_model=RepositoryIndexOut)
def index_repository(db: DbSession) -> RepositoryIndexOut:
    """Walk the approved workspaces and update the index (incremental)."""
    report = sync_workspaces(db, settings=get_settings())
    return RepositoryIndexOut(
        **report.as_dict(),
        indexed_at=datetime.now(UTC).isoformat(),
    )


@router.post("/search", response_model=RepositorySearchOut)
def search_repository_index(db: DbSession, payload: RepositorySearchRequest) -> RepositorySearchOut:
    """Hybrid (vector + keyword) search over indexed project files (PRD §17)."""
    hits = search_repository(db, payload.query, k=payload.k, min_score=payload.min_score)
    grouped = (
        files_relevant_to(db, payload.query, k=payload.k, min_score=payload.min_score)
        if payload.files
        else []
    )
    return RepositorySearchOut(
        query=payload.query,
        hits=[
            RepositoryHitOut(
                path=hit.path,
                source_type=hit.source_type,
                language=hit.language,
                start_line=hit.start_line,
                end_line=hit.end_line,
                score=round(float(hit.score), 4),
                text=hit.text,
            )
            for hit in hits
        ],
        files=[
            RepositoryFileOut(
                path=match.path,
                source_type=match.source_type,
                language=match.language,
                score=round(float(match.score), 4),
                range=match.range,
                preview=match.preview,
            )
            for match in grouped
        ],
        preview=format_repo_context(grouped),
    )
