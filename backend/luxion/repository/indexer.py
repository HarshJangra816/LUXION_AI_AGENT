"""Index a workspace: walk → read → chunk → embed → write (PRD §17).

The pass is incremental, which is what makes it cheap enough to run often:

* a file whose chunk hashes are already stored is skipped **before** the
  embedding model is touched (the model is the expensive part, not the read);
* a changed file replaces its chunks in place;
* a file that is gone — or that no longer sits under any approved workspace —
  has its chunks pruned.

One unreadable file never aborts the pass: it is logged, counted as ``failed``
and the walk continues.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from luxion.config.settings import Settings, get_settings
from luxion.rag import vector_store
from luxion.rag.chunking import ChunkDraft, chunk_file, kind_of, language_of
from luxion.rag.embeddings import EmbeddingError, EmbeddingProvider, get_embedding_provider
from luxion.rag.models import Chunk
from luxion.repository.scanner import REPO_SOURCE_TYPES, iter_files

logger = logging.getLogger(__name__)

#: Outcomes of indexing a single file.
INDEXED = "indexed"
UNCHANGED = "unchanged"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(slots=True)
class IndexReport:
    """What one sync pass did — the ``POST /api/repository/index`` payload."""

    roots: list[str] = field(default_factory=list)
    #: Files the scanner handed to the indexer.
    scanned: int = 0
    #: Files re-read and re-written (new or changed).
    indexed: int = 0
    #: Files left alone because their chunks already matched.
    unchanged: int = 0
    #: Binary, oversized, empty or otherwise not worth indexing.
    skipped: int = 0
    #: Read/chunk/embed failures — the file is simply left unindexed.
    failed: int = 0
    #: Sources pruned because the file no longer exists.
    removed: int = 0
    #: Chunks written this pass (``chunks`` below is the total afterwards).
    written: int = 0
    #: Total repository chunks in the index after the pass.
    chunks: int = 0
    #: Total distinct files in the index after the pass.
    files: int = 0

    @property
    def changed(self) -> int:
        """How much of the index this pass actually touched."""
        return self.indexed + self.removed

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {name: getattr(self, name) for name in self.__slots__}
        payload["changed"] = self.changed
        return payload


# ---------------------------------------------------------------------- read
def read_text(path: Path, *, max_bytes: int) -> str | None:
    """File content, or ``None`` when it is too big, binary or unreadable.

    A NUL byte in the first 8 KiB means "not a text file" — that is how a PNG
    or a compiled blob is rejected without having to trust the extension list.
    """
    try:
        if path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def draft_hashes(drafts: list[ChunkDraft]) -> list[str]:
    """sha1 per chunk — the same value :func:`write_chunks` stores, so the two
    lists can be compared directly to detect an unchanged file."""
    return [hashlib.sha1(draft.text.encode("utf-8")).hexdigest() for draft in drafts]


def stored_hashes(session: Session, source: str) -> list[str]:
    """Chunk hashes already in the index for ``source``, in id order."""
    rows = session.execute(
        select(Chunk.hash).where(Chunk.source == source).order_by(Chunk.id)
    ).scalars()
    return [str(value) for value in rows]


def index_file(
    session: Session,
    path: Path,
    *,
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
) -> tuple[str, int]:
    """Index one file. Returns ``(outcome, chunks written)``.

    ``unchanged`` never calls the embedding model — that is the whole point of
    the hash comparison.
    """
    cfg = settings or get_settings()
    text = read_text(path, max_bytes=cfg.rag.max_file_bytes)
    if text is None:
        return SKIPPED, 0

    language = language_of(path)
    drafts = chunk_file(
        path,
        text,
        max_chars=cfg.rag.chunk_chars,
        overlap=cfg.rag.chunk_overlap,
    )
    if not drafts:
        return SKIPPED, 0

    source = str(path)
    if drafts and draft_hashes(drafts) == stored_hashes(session, source):
        return UNCHANGED, 0

    vectors, model = _embed_drafts(drafts, cfg, provider)
    written = vector_store.write_chunks(
        session,
        source=source,
        source_type=kind_of(language),
        chunks=drafts,
        vectors=vectors,
        model=model,
    )
    session.commit()
    return INDEXED, written


def _embed_drafts(
    drafts: list[ChunkDraft],
    cfg: Settings,
    provider: EmbeddingProvider | None,
) -> tuple[list, str]:
    """Vectors for every draft, or ``None`` for every draft when the model is
    down — an unembedded file stays reachable through FTS5."""
    texts = [draft.text for draft in drafts]
    batch_size = cfg.rag.reembed_batch
    try:
        active = provider or get_embedding_provider(cfg)
        vectors: list = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(active.embed(texts[start : start + batch_size]))
    except EmbeddingError as exc:
        logger.warning("repository_not_embedded chunks=%s error=%s", len(texts), exc)
        return [None] * len(texts), ""
    return vectors, active.model


# --------------------------------------------------------------------- prune
def count_repo_chunks(session: Session) -> int:
    return int(
        session.execute(
            select(func.count(Chunk.id)).where(Chunk.source_type.in_(REPO_SOURCE_TYPES))
        ).scalar()
        or 0
    )


def count_repo_files(session: Session) -> int:
    return int(
        session.execute(
            select(func.count(func.distinct(Chunk.source))).where(
                Chunk.source_type.in_(REPO_SOURCE_TYPES)
            )
        ).scalar()
        or 0
    )


def prune_missing(
    session: Session,
    *,
    roots: list[Path] | tuple[Path, ...],
) -> int:
    """Drop chunks whose file is gone, or that left every approved workspace.

    A removed workspace must not leave its content retrievable — that would be
    a privacy leak as well as stale results (PRD §42).
    """
    resolved = []
    for root in roots:
        try:
            resolved.append(Path(root).expanduser().resolve())
        except OSError:  # pragma: no cover - unreadable root
            continue

    sources = session.execute(
        select(Chunk.source)
        .where(Chunk.source_type.in_(REPO_SOURCE_TYPES))
        .distinct()
        .order_by(Chunk.source)
    ).scalars()

    removed = 0
    for source in list(sources):
        path = Path(source)
        keep = path.is_file() and any(_within(path, root) for root in resolved)
        if keep:
            continue
        vector_store.delete_source(session, source)
        removed += 1
    if removed:
        session.commit()
        logger.info("repository_pruned sources=%s", removed)
    return removed


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


# ----------------------------------------------------------------------- run
def sync_workspaces(
    session: Session,
    *,
    roots: list[Path] | tuple[Path, ...] | None = None,
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
) -> IndexReport:
    """One incremental sync over ``roots`` (default: the approved workspaces).

    Returns a report even when RAG is off — that is the signal that nothing
    happened, rather than an exception.
    """
    cfg = settings or get_settings()
    active_roots = list(roots) if roots is not None else list(cfg.security.allowed_workspaces)
    report = IndexReport(roots=[str(Path(root).expanduser()) for root in active_roots])
    if not cfg.rag.enabled:
        logger.info("repository_index_disabled")
        return report

    for path in iter_files(
        active_roots,
        extensions=cfg.rag.index_extensions,
        exclude=cfg.rag.exclude,
        max_files=cfg.rag.max_files,
        max_bytes=cfg.rag.max_file_bytes,
    ):
        report.scanned += 1
        try:
            outcome, written = index_file(session, path, settings=cfg, provider=provider)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the pass
            logger.warning("repository_index_failed path=%s error=%s", path, exc)
            session.rollback()
            report.failed += 1
            continue
        if outcome == INDEXED:
            report.indexed += 1
            report.written += written
        elif outcome == UNCHANGED:
            report.unchanged += 1
        else:
            report.skipped += 1

    report.removed = prune_missing(session, roots=active_roots)
    report.chunks = count_repo_chunks(session)
    report.files = count_repo_files(session)
    logger.info(
        "repository_indexed",
        extra={
            "scanned": report.scanned,
            "indexed": report.indexed,
            "unchanged": report.unchanged,
            "removed": report.removed,
            "failed": report.failed,
            "chunks": report.chunks,
        },
    )
    return report


def sync_blocking(
    settings: Settings | None = None,
    *,
    roots: list[Path] | tuple[Path, ...] | None = None,
) -> IndexReport:
    """Open a session and sync — the entry point for background work."""
    from luxion.database.session import get_session_factory

    cfg = settings or get_settings()
    with get_session_factory()() as session:
        return sync_workspaces(session, roots=roots, settings=cfg)


# ---------------------------------------------------------------- scheduling
_tasks: set[asyncio.Task] = set()


def schedule_index(
    *,
    settings: Settings | None = None,
    roots: list[Path] | tuple[Path, ...] | None = None,
) -> asyncio.Task | None:
    """Fire-and-forget sync; never blocks or fails the caller."""
    cfg = settings or get_settings()
    if not cfg.rag.enabled:
        return None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _run() -> None:
        try:
            await run_in_threadpool(sync_blocking, cfg, roots=roots)
        except Exception as exc:  # noqa: BLE001 - background work, nobody to tell
            logger.warning("repository_index_failed error=%s", exc)

    task = asyncio.get_running_loop().create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


__all__ = [
    "FAILED",
    "INDEXED",
    "IndexReport",
    "SKIPPED",
    "UNCHANGED",
    "count_repo_chunks",
    "count_repo_files",
    "draft_hashes",
    "index_file",
    "prune_missing",
    "read_text",
    "schedule_index",
    "stored_hashes",
    "sync_blocking",
    "sync_workspaces",
]
