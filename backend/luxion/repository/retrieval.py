"""Repository retrieval (PRD §17 ``User Problem → Semantic Search → Relevant
files → functions/classes → lines → LLM``).

Retrieval answers with *where* the answer lives, not only what it says: every
hit carries the file path and the 1-based line range the chunk covers, which
is what lets the model (or the UI) jump straight to the function instead of
re-reading the file.

The same hybrid search as memories is used, narrowed to ``doc``/``code``, so a
workspace question never surfaces a stored memory and vice versa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from luxion.config.settings import get_settings
from luxion.rag.embeddings import EmbeddingError, get_embedding_provider
from luxion.rag.vector_store import SearchHit, hybrid_search
from luxion.repository.scanner import REPO_SOURCE_TYPES

logger = logging.getLogger(__name__)

#: Chunk excerpts kept per file — enough to show the function, not the file.
HITS_PER_FILE = 3


@dataclass(slots=True)
class RepoHit:
    """One retrieved chunk, addressed the way PRD §17 asks: file + lines."""

    path: str
    source_type: str
    language: str
    start_line: int
    end_line: int
    #: Cosine similarity when the index had a vector, else a rank-derived value.
    score: float
    text: str

    @classmethod
    def from_search_hit(cls, hit: SearchHit) -> RepoHit:
        return cls(
            path=hit.source,
            source_type=hit.source_type,
            language=hit.language,
            start_line=hit.start_line,
            end_line=hit.end_line,
            score=hit.score,
            text=hit.text,
        )

    @property
    def range(self) -> str:
        """``12`` for a one-line chunk, ``12-30`` otherwise."""
        if self.start_line <= 0 or self.end_line <= self.start_line:
            return str(max(1, self.start_line))
        return f"{self.start_line}-{self.end_line}"

    @property
    def snippet(self) -> str:
        return self.text if len(self.text) <= 400 else f"{self.text[:400]}…"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "source_type": self.source_type,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "score": round(float(self.score), 4),
            "text": self.text,
        }


@dataclass(slots=True)
class FileMatch:
    """One file the answer probably lives in, with its best hit first."""

    path: str
    source_type: str
    language: str
    #: Best score among its hits — files are ordered by this.
    score: float
    hits: list[RepoHit] = field(default_factory=list)

    @property
    def range(self) -> str:
        return self.hits[0].range if self.hits else ""

    @property
    def preview(self) -> str:
        """First non-blank line of the best hit — the "why this file" line."""
        if not self.hits:
            return ""
        for line in self.hits[0].text.splitlines():
            if line.strip():
                return line.strip()[:160]
        return ""


def _embed_query(query: str):
    """Query vector, or ``None`` when the model is unavailable (keyword path)."""
    try:
        return get_embedding_provider().embed_query(query)
    except EmbeddingError as exc:
        logger.warning("repository_query_not_embedded error=%s", exc)
        return None


def search_repository(
    session: Session,
    query: str,
    *,
    k: int = 6,
    min_score: float | None = None,
) -> list[RepoHit]:
    """Best chunks for ``query``, ranked. Never raises on a model failure.

    ``min_score=None`` takes the configured cosine floor (``rag.min_score``);
    without it a nonsense query would "match" every file the vector index can
    see. Keyword hits survive the floor, which is what keeps exact identifiers
    like ``flush_stream`` retrievable from code.
    """
    text = (query or "").strip()
    if not text:
        return []
    floor = get_settings().rag.min_score if min_score is None else min_score
    hits = hybrid_search(
        session,
        _embed_query(text),
        text,
        k=max(1, k),
        min_score=floor,
        source_types=set(REPO_SOURCE_TYPES),
    )
    return [RepoHit.from_search_hit(hit) for hit in hits]


def files_relevant_to(
    session: Session,
    query: str,
    *,
    k: int = 8,
    min_score: float | None = None,
    max_files: int = 5,
) -> list[FileMatch]:
    """Group hits into files — "start here", best file first.

    The hit count is widened before grouping so one chatty file cannot crowd
    every other candidate out of the answer.
    """
    hits = search_repository(session, query, k=max(k, max_files * 2), min_score=min_score)
    grouped: dict[str, FileMatch] = {}
    for hit in hits:
        match = grouped.get(hit.path)
        if match is None:
            match = FileMatch(
                path=hit.path,
                source_type=hit.source_type,
                language=hit.language,
                score=hit.score,
            )
            grouped[hit.path] = match
        match.hits.append(hit)
        match.score = max(match.score, hit.score)
    for match in grouped.values():
        del match.hits[HITS_PER_FILE:]
    ordered = sorted(grouped.values(), key=lambda match: match.score, reverse=True)
    return ordered[: max(1, max_files)]


def format_repo_context(files: list[FileMatch], *, max_chars: int = 1500) -> str:
    """The ``Relevant Files`` block of the prompt (PRD §16 context integration)."""
    parts: list[str] = []
    used = 0
    for match in files:
        if not match.hits:
            continue
        heading = f"- {match.path}:{match.range} [{match.source_type}]"
        body = f"\n  {match.preview}" if match.preview else ""
        line = f"{heading}{body}"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


def relative_path(path: str, roots: list[Path] | tuple[Path, ...]) -> str:
    """Shortest display form of ``path`` under an approved root (else absolute)."""
    candidate = Path(path)
    best = str(candidate)
    for root in roots:
        try:
            relative = candidate.relative_to(Path(root).expanduser().resolve())
        except (ValueError, OSError):
            continue
        if len(str(relative)) < len(best):
            best = str(relative)
    return best


__all__ = [
    "FileMatch",
    "RepoHit",
    "files_relevant_to",
    "format_repo_context",
    "relative_path",
    "search_repository",
]
