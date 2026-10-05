"""Engine/session management.

Sync SQLAlchemy is used deliberately: SQLite (Phase 0/5 development) is
reliable with synchronous access, FastAPI runs sync dependencies in its
threadpool, and the agent pipeline is I/O bound on LLM/tool calls rather
than on DB latency. Switching the engine to an async driver later only
touches this module and the API dependencies.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from luxion.config.settings import get_settings
from luxion.database.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.db.url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, echo=settings.db.echo, connect_args=connect_args)
        if url.startswith("sqlite"):
            # Register the sqlite-vec connect hook before any connection is
            # handed out — a hook added later would not reach pooled
            # connections that already exist.
            from luxion.rag.vector_store import (  # noqa: PLC0415 - local import
                install_vector_extension,
            )

            install_vector_extension(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Development bootstrap: create tables if they do not exist.

    Schema evolution is handled by Alembic migrations (see ``backend/alembic``);
    the RAG search indexes (FTS5 + vec0) are derived tables rebuilt from the
    ORM data, so they are created here rather than migrated.
    """
    settings = get_settings()
    settings.ensure_directories()
    from luxion.rag import init_rag
    from luxion.rag import models as _rag_models  # noqa: F401 - register tables

    Base.metadata.create_all(get_engine())
    init_rag(get_engine(), dim_hint=settings.embedding_dim)


def check_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check must never raise
        return False


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    from luxion.rag.vector_store import reset_extension_state  # noqa: PLC0415

    reset_extension_state()
