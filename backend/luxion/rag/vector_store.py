"""Vector + keyword index (PRD §16 ``Vector Database → Semantic Search``).

Storage layout inside the existing Luxion SQLite file:

=====================  ==================================================
``chunks`` (ORM)       text + float32 vector — **the source of truth**
``chunks_vec`` (vec0)  ANN accelerator over those vectors, rebuildable
``chunks_fts`` (fts5)  keyword index for hybrid search
=====================  ==================================================

Both virtual tables are derived: losing them costs a rebuild, never data.
That is what makes the embedding model swappable from Settings → Memory —
changing it rewrites ``chunks.embedding`` and re-creates ``chunks_vec`` at the
new width (see :func:`rebuild_vector_index`).

Search is **hybrid**: euclidean k-NN over normalised vectors (equivalent to
cosine ranking) fused with FTS5 bm25 by reciprocal-rank fusion, so a query
that names an identifier wins even when the embedding is weak at code, and a
paraphrase still wins when the words differ.

If ``sqlite-vec`` cannot be loaded, everything still works: the vector half
falls back to a numpy scan over the stored blobs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import Engine, delete, event, select, text
from sqlalchemy.orm import Session

from luxion.rag.models import Chunk, RagMeta

logger = logging.getLogger(__name__)

#: Always ``id = 1``.
META_ID = 1

_FTS_TABLE = "chunks_fts"
_VEC_TABLE = "chunks_vec"
_SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

#: ``engine.url -> sqlite-vec loaded?`` — probed once, cleared on dispose.
_vec_state: dict[str, bool] = {}
#: ``engine.url -> connect hook installed?``
_installed: set[str] = set()

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


# --------------------------------------------------------------------------- #
# extension plumbing
# --------------------------------------------------------------------------- #
def install_vector_extension(engine: Engine) -> None:
    """Load sqlite-vec on every connection of a SQLite engine (idempotent)."""
    key = str(engine.url)
    if key in _installed:
        return
    _installed.add(key)
    if not str(engine.url).startswith("sqlite"):
        return

    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_connection, _record) -> None:  # noqa: ANN001 - DBAPI conn
        try:
            import sqlite_vec  # noqa: PLC0415 - optional dependency

            dbapi_connection.enable_load_extension(True)
            try:
                sqlite_vec.load(dbapi_connection)
            finally:
                dbapi_connection.enable_load_extension(False)
        except Exception as exc:  # noqa: BLE001 - numpy fallback covers this
            logger.debug("sqlite_vec_not_loaded error=%s", exc)


def reset_extension_state() -> None:
    """Forget per-engine probes (called when the engine is disposed)."""
    _vec_state.clear()
    _installed.clear()


def _engine_of(session: Session) -> Engine | None:
    """The engine behind a session (``None`` for a connection-bound session)."""
    bind = session.get_bind()
    if isinstance(bind, Engine):
        return bind
    engine = getattr(bind, "engine", None)
    return engine if isinstance(engine, Engine) else None


def vec_available(engine: Engine | None) -> bool:
    """True when the ``vec0`` module is loaded on this engine's connections."""
    if engine is None or not str(engine.url).startswith("sqlite"):
        return False
    key = str(engine.url)
    if key in _vec_state:
        return _vec_state[key]
    available = False
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT vec_version()")).scalar()
        available = version is not None
        logger.info("sqlite_vec_version version=%s", version)
    except Exception as exc:  # noqa: BLE001 - absence is a supported state
        logger.warning("sqlite_vec_unavailable reason=%s (falling back to numpy scan)", exc)
    _vec_state[key] = available
    return available


def _vec_ddl(dim: int) -> str:
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {_VEC_TABLE} USING vec0(embedding float[{int(dim)}])"
    )


def _current_vec_dim(engine: Engine) -> int | None:
    """Width of the existing vec0 table, parsed out of its DDL."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE name = :name"),
                {"name": _VEC_TABLE},
            ).scalar()
    except Exception:  # noqa: BLE001 - treated as "no table"
        return None
    if not row:
        return None
    match = re.search(r"float\[\s*(\d+)\s*\]", row)
    return int(match.group(1)) if match else None


def ensure_index_tables(engine: Engine, *, dim_hint: int) -> dict[str, object]:
    """Create the FTS/vec tables and keep the vec width in sync with the data.

    The width comes from ``rag_meta`` (what the stored vectors actually are),
    not from the currently configured model — a model switch only *pending*
    until the user re-embeds, and dropping the index early would break search
    in the meantime.
    """
    with engine.begin() as conn:
        conn.execute(text(_SCHEMA_SQL))

    available = vec_available(engine)
    if not available:
        return {"vec": False, "dim": 0}

    stored_dim = 0
    try:
        with engine.connect() as conn:
            stored_dim = int(
                conn.execute(
                    text("SELECT dim FROM rag_meta WHERE id = :id"), {"id": META_ID}
                ).scalar()
                or 0
            )
    except Exception:  # noqa: BLE001 - table may not exist yet
        stored_dim = 0
    dim = stored_dim or int(dim_hint) or 384

    existing = _current_vec_dim(engine)
    if existing != dim:
        with engine.begin() as conn:
            if existing is not None:
                conn.execute(text(f"DROP TABLE IF EXISTS {_VEC_TABLE}"))
                logger.info("vec_index_recreated old_dim=%s new_dim=%s", existing, dim)
            conn.execute(text(_vec_ddl(dim)))
    return {"vec": True, "dim": dim}


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
def get_meta(session: Session) -> RagMeta:
    """The single ``rag_meta`` row (created on first use)."""
    meta = session.get(RagMeta, META_ID)
    if meta is None:
        meta = RagMeta(id=META_ID)
        session.add(meta)
        session.flush()
    return meta


def sync_meta(session: Session, *, model: str, dim: int) -> RagMeta:
    """Record what the index holds and whether the configured model is stale.

    ``model``/``dim`` describe the **stored vectors** (they are only updated
    once every chunk carries ``model``); ``pending_model`` is set when the
    configured model has not been applied yet — the signal Settings → Memory
    uses for the "re-embed" button.
    """
    meta = get_meta(session)
    stored = {
        str(row)
        for row in session.execute(text("SELECT DISTINCT embedding_model FROM chunks")).scalars()
    }
    stored.discard("")
    if not stored:
        # nothing indexed: no re-embed owed, and the recorded width (which is
        # also the vec0 table width) stays put
        meta.pending_model = ""
    elif stored == {model}:
        meta.model = model
        meta.dim = dim
        meta.pending_model = ""
    else:
        # the configured model is missing from the data — partly or wholly
        if not meta.model:
            meta.model = sorted(stored)[0]
        meta.pending_model = model
    meta.chunk_count = int(session.execute(text("SELECT count(*) FROM chunks")).scalar() or 0)
    meta.vector_count = int(
        session.execute(text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")).scalar()
        or 0
    )
    session.flush()
    return meta


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
def delete_source(session: Session, source: str) -> int:
    """Drop every chunk of one source (file, or ``memory:<id>``)."""
    ids = [
        int(row)
        for row in session.execute(
            text("SELECT id FROM chunks WHERE source = :source"), {"source": source}
        ).scalars()
    ]
    if not ids:
        return 0
    _delete_indexes(session, ids)
    session.execute(delete(Chunk).where(Chunk.source == source))
    session.flush()
    return len(ids)


def write_chunks(
    session: Session,
    *,
    source: str,
    source_type: str,
    chunks: list[object],
    vectors: list[np.ndarray | None],
    model: str,
) -> int:
    """Replace ``source``'s chunks (drafts + their vectors) and index them.

    ``chunks`` are :class:`luxion.rag.chunking.ChunkDraft` instances and
    ``vectors`` align with them 1:1 (a ``None`` entry stores the chunk without
    a vector — it stays reachable through FTS5 until it is embedded).
    """
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must align 1:1")
    # A blank chunk can never match anything and embeds to a zero vector, which
    # the vector index scores above genuine matches. Never store one.
    aligned = [
        (draft, vector)
        for draft, vector in zip(chunks, vectors, strict=True)
        if str(getattr(draft, "text", "")).strip()
    ]
    delete_source(session, source)
    if not aligned:
        return 0

    rows: list[Chunk] = []
    for draft, vector in aligned:
        blob = None if vector is None else np.asarray(vector, dtype=np.float32).reshape(-1)
        text_of = str(getattr(draft, "text", ""))
        rows.append(
            Chunk(
                source=source,
                source_type=source_type,
                language=getattr(draft, "language", "") or "",
                start_line=int(getattr(draft, "start_line", 0)),
                end_line=int(getattr(draft, "end_line", 0)),
                text=text_of,
                tokens=_estimate_tokens(text_of),
                hash=_sha1(text_of),
                embedding=None if blob is None else blob.tobytes(),
                embedding_model=model,
            )
        )
    session.add_all(rows)
    session.flush()

    fts_rows = [{"text": row.text, "chunk_id": row.id} for row in rows if row.id is not None]
    session.execute(
        text(f"INSERT INTO {_FTS_TABLE} (text, chunk_id) VALUES (:text, :chunk_id)"),
        fts_rows,
    )

    engine = _engine_of(session)
    if engine is not None and vec_available(engine):
        table_dim = _current_vec_dim(engine)
        vec_rows = []
        for row in rows:
            blob = row.embedding or b""
            if not row.id or not blob:
                continue
            if table_dim is None or len(blob) != table_dim * 4:
                # stored at a different width: keyword-searchable only until
                # the re-embed job rewrites it
                continue
            vec_rows.append({"rowid": row.id, "embedding": bytes(blob)})
        if vec_rows:
            session.execute(
                text(f"INSERT INTO {_VEC_TABLE} (rowid, embedding) VALUES (:rowid, :embedding)"),
                vec_rows,
            )
        elif any(row.embedding for row in rows):
            logger.warning("chunks_not_vectorized source=%s reason=width_mismatch", source)
    session.flush()
    return len(rows)


def _delete_indexes(session: Session, ids: list[int]) -> None:
    placeholders = ", ".join(str(int(chunk_id)) for chunk_id in ids)
    session.execute(text(f"DELETE FROM {_FTS_TABLE} WHERE chunk_id IN ({placeholders})"))
    if vec_available(_engine_of(session)):
        session.execute(text(f"DELETE FROM {_VEC_TABLE} WHERE rowid IN ({placeholders})"))


def rebuild_vector_index(session: Session, *, dim: int) -> int:
    """Re-create ``chunks_vec`` at ``dim`` and refill it from stored blobs.

    Returns the number of vectors written. Chunks whose stored vector width
    does not match are left unindexed (they belong to another model and are
    picked up by the re-embed job).
    """
    engine = _engine_of(session)
    if engine is None or not vec_available(engine):
        return 0

    connection = session.connection()
    connection.execute(text(f"DROP TABLE IF EXISTS {_VEC_TABLE}"))
    connection.execute(text(_vec_ddl(dim)))

    rows = session.execute(
        text("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL")
    ).all()
    payload = []
    for chunk_id, blob in rows:
        if not blob or len(blob) != dim * 4:
            continue
        # the stored blob already is sqlite-vec's raw float32 format
        payload.append({"rowid": int(chunk_id), "embedding": bytes(blob)})
    if payload:
        session.execute(
            text(f"INSERT INTO {_VEC_TABLE} (rowid, embedding) VALUES (:rowid, :embedding)"),
            payload,
        )
    session.flush()
    logger.info("vec_index_rebuilt dim=%s vectors=%s", dim, len(payload))
    return len(payload)


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SearchHit:
    """One retrieved chunk, ready to be shown or injected into context."""

    chunk_id: int
    #: Cosine similarity (0..1) when the vector index had it, else a
    #: keyword-rank estimate — see :func:`hybrid_search`.
    score: float
    source: str
    source_type: str
    language: str
    start_line: int
    end_line: int
    text: str

    @property
    def snippet(self) -> str:
        return self.text if len(self.text) <= 400 else f"{self.text[:400]}…"


def _cosine(distance: float) -> float:
    """Convert euclidean distance between unit vectors to cosine similarity."""
    value = 1.0 - (distance * distance) / 2.0
    return float(min(1.0, max(0.0, value)))


def vector_search(
    session: Session, query: np.ndarray, k: int, *, dim: int | None = None
) -> list[tuple[int, float]]:
    """Top-``k`` (chunk_id, cosine) — vec0 k-NN, numpy scan as the fallback."""
    engine = _engine_of(session)
    if engine is not None and vec_available(engine):
        import sqlite_vec  # noqa: PLC0415 - only needed when searching

        blob = sqlite_vec.serialize_float32(np.asarray(query, dtype=np.float32).reshape(-1))
        try:
            rows = session.execute(
                text(
                    f"SELECT rowid, distance FROM {_VEC_TABLE} "
                    "WHERE embedding MATCH :embedding AND k = :k ORDER BY distance"
                ),
                {"embedding": blob, "k": int(k)},
            ).all()
        except Exception as exc:  # noqa: BLE001 - width mismatch etc.
            logger.warning("vec_search_failed error=%s", exc)
            rows = []
        if rows:
            return [(int(rowid), _cosine(float(distance))) for rowid, distance in rows]
        if _table_has_rows(session, _VEC_TABLE):
            return []

    # numpy fallback: scan the stored blobs (correct, just slower)
    width = dim or (len(query) if query is not None else 0)
    if not width:
        return []
    rows = session.execute(
        text("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL")
    ).all()
    candidates: list[tuple[int, float]] = []
    for chunk_id, blob in rows:
        if not blob or len(blob) != width * 4:
            continue
        vector = np.frombuffer(blob, dtype=np.float32)
        candidates.append((int(chunk_id), float(np.dot(vector, query))))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[: max(1, k)]


def _table_has_rows(session: Session, table: str) -> bool:
    try:
        return bool(session.execute(text(f"SELECT count(*) FROM {table}")).scalar())
    except Exception:  # noqa: BLE001 - missing table == empty
        return False


def keyword_search(session: Session, query: str, k: int) -> list[int]:
    """FTS5 hits (best first). A malformed query is a no-op, never an error."""
    expression = _fts_expression(query)
    if not expression:
        return []
    try:
        rows = session.execute(
            text(
                f"SELECT chunk_id FROM {_FTS_TABLE} WHERE {_FTS_TABLE} MATCH :q "
                "ORDER BY bm25(chunks_fts) LIMIT :k"
            ),
            {"q": expression, "k": int(k)},
        ).all()
    except Exception as exc:  # noqa: BLE001 - user input reaches the parser
        logger.debug("fts_query_rejected query=%r error=%s", query, exc)
        return []
    return [int(chunk_id) for (chunk_id,) in rows]


def _fts_expression(raw: str) -> str | None:
    """Quote every token so user text can never be read as FTS5 syntax."""
    terms = _WORD.findall(raw.casefold())[:16]
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)


def hybrid_search(
    session: Session,
    query: np.ndarray | None,
    query_text: str,
    *,
    k: int = 6,
    min_score: float = 0.0,
    dim: int | None = None,
    source_types: set[str] | None = None,
) -> list[SearchHit]:
    """Fuse vector and keyword results (reciprocal-rank fusion, k = 60).

    ``min_score`` filters on **cosine** for anything the vector index knows
    about; keyword-only hits are kept (their ``score`` is derived from rank),
    which is what makes exact identifiers retrievable from code.

    ``source_types`` narrows the answer to one kind of content — ``{"memory"}``
    for Phase 5b recall, ``{"doc", "code"}`` for the repository index. The
    candidate pool is widened so the filter still returns ``k`` hits.
    """
    k = max(1, k)
    breadth = k * 4 if source_types else k
    fused: dict[int, float] = {}
    cosine_by_id: dict[int, float] = {}
    keyword_rank: dict[int, int] = {}

    if query is not None and len(query):
        for rank, (chunk_id, cosine) in enumerate(
            vector_search(session, query, breadth * 2, dim=dim), start=1
        ):
            if cosine < min_score:
                continue
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60.0 + rank)
            cosine_by_id[chunk_id] = cosine

    for rank, chunk_id in enumerate(keyword_search(session, query_text, breadth * 2), start=1):
        if chunk_id in fused:
            fused[chunk_id] += 1.0 / (60.0 + rank)
        else:
            fused[chunk_id] = 1.0 / (60.0 + rank)
        keyword_rank.setdefault(chunk_id, rank)

    if not fused:
        return []

    ordered = sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)[:breadth]
    if not ordered:
        return []
    statement = select(
        Chunk.id,
        Chunk.source,
        Chunk.source_type,
        Chunk.language,
        Chunk.start_line,
        Chunk.end_line,
        Chunk.text,
    ).where(Chunk.id.in_(ordered))
    if source_types:
        statement = statement.where(Chunk.source_type.in_(set(source_types)))
    rows = session.execute(statement).all()
    by_id = {int(row[0]): row for row in rows}

    hits: list[SearchHit] = []
    for chunk_id in ordered:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        if chunk_id in cosine_by_id:
            score = cosine_by_id[chunk_id]
        else:
            score = 1.0 / (1.0 + keyword_rank.get(chunk_id, 1))
        hits.append(
            SearchHit(
                chunk_id=chunk_id,
                score=round(float(score), 4),
                source=str(row[1]),
                source_type=str(row[2]),
                language=str(row[3]),
                start_line=int(row[4]),
                end_line=int(row[5]),
                text=str(row[6]),
            )
        )
    return hits[:k]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sha1(value: str) -> str:
    import hashlib  # noqa: PLC0415 - tiny helper

    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _estimate_tokens(value: str) -> int:
    from luxion.context.tokens import estimate_tokens  # noqa: PLC0415 - avoid cycle

    return estimate_tokens(value)


__all__ = [
    "SearchHit",
    "delete_source",
    "ensure_index_tables",
    "get_meta",
    "hybrid_search",
    "install_vector_extension",
    "keyword_search",
    "rebuild_vector_index",
    "reset_extension_state",
    "sync_meta",
    "vec_available",
    "vector_search",
    "write_chunks",
]
