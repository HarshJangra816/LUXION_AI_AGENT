"""The ``memories`` table — durable, extracted long-term memory (PRD §15).

One row is one standalone statement ("The user prefers SQLite over Postgres"),
never a transcript: PRD §58 rule 5 says the conversation itself must not be
stored as permanent memory. The searchable copy of the statement lives in
``luxion.rag`` under ``source = "memory:<id>"`` / ``source_type = "memory"``,
so :func:`luxion.memory.recall` can reuse the hybrid index built in Phase 5a
and ``forget`` only has to drop one extra chunk.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from luxion.database.base import Base

#: PRD §15 memory kinds, used verbatim by Settings → Memory and the tools.
MEMORY_KINDS = ("fact", "preference", "task", "project", "episode")

DEFAULT_KIND = "fact"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: One of :data:`MEMORY_KINDS`.
    kind: Mapped[str] = mapped_column(String(16), default=DEFAULT_KIND, index=True)
    #: The standalone statement. Its normalised sha1 is the dedupe key.
    text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    #: ``user`` (said it), ``assistant`` (agreed), ``extracted`` (from turns).
    source: Mapped[str] = mapped_column(String(16), default="extracted")
    #: 0..1 — how much the retrieval budget should favour it.
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    #: Conversation the memory came from (``None`` for a typed-in note).
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    @property
    def chunk_source(self) -> str:
        """Where the indexed copy of this statement lives in ``chunks``."""
        return f"memory:{self.id}"

    def as_dict(self) -> dict[str, object]:
        """Flat payload for the API and for tool results."""
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "source": self.source,
            "importance": round(float(self.importance), 3),
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


__all__ = ["DEFAULT_KIND", "MEMORY_KINDS", "Memory"]
