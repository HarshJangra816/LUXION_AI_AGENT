"""One persisted conversation row as the context manager sees it.

Kept outside :mod:`luxion.services.conversations` so the context package has
no dependency on the service layer (and the service layer can depend on it).
"""

from __future__ import annotations

from dataclasses import dataclass

from luxion.llm.types import ChatMessage, Role


@dataclass(slots=True)
class HistoryRecord:
    """A stored message: same as :class:`ChatMessage` plus its row id."""

    id: int
    role: Role
    content: str

    def as_message(self) -> ChatMessage:
        return ChatMessage(role=self.role, content=self.content)
