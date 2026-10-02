"""Conversation persistence helpers (sync SQLAlchemy; see ``session.py``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from luxion.context.records import HistoryRecord
from luxion.context.summary import SummaryState, state_from_meta, state_to_meta
from luxion.database.models import Conversation, Message
from luxion.llm.types import ChatMessage, Role

MAX_TITLE_CHARS = 80


class ConversationNotFound(LookupError):
    """Raised when a conversation id does not exist (or was deleted)."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"Conversation '{conversation_id}' not found")
        self.conversation_id = conversation_id


def create_conversation(session: Session, title: str | None = None) -> Conversation:
    conversation = Conversation(title=_clean_title(title))
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def list_conversations(session: Session) -> list[Conversation]:
    stmt = select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    return list(session.scalars(stmt))


def get_conversation(session: Session, conversation_id: str) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFound(conversation_id)
    return conversation


def delete_conversation(session: Session, conversation_id: str) -> None:
    conversation = get_conversation(session, conversation_id)
    session.delete(conversation)
    session.commit()


def append_message(
    session: Session,
    conversation_id: str,
    role: Role,
    content: str,
    *,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    meta: dict | None = None,
) -> Message:
    """Persist one turn and bump ``conversations.updated_at``."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        meta=meta or {},
    )
    session.add(message)
    conversation = get_conversation(session, conversation_id)
    conversation.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(message)
    return message


def history_records(
    session: Session, conversation_id: str, *, limit: int = 50
) -> list[HistoryRecord]:
    """Last ``limit`` stored messages, oldest first (excludes the system prompt)."""
    if limit < 1:
        return []
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    messages = list(session.scalars(stmt))
    messages.reverse()
    return [
        HistoryRecord(id=message.id, role=cast(Role, message.role), content=message.content)
        for message in messages
    ]


def history(session: Session, conversation_id: str, *, limit: int = 50) -> list[ChatMessage]:
    """Same rows as :func:`history_records`, reduced to provider messages."""
    records = history_records(session, conversation_id, limit=limit)
    return [record.as_message() for record in records]


def read_summary_state(conversation: Conversation) -> SummaryState:
    """Rolling summary stored under ``conversations.meta['context']``."""
    return state_from_meta(conversation.meta)


def write_summary_state(session: Session, conversation_id: str, state: SummaryState) -> None:
    """Persist the rolling summary, preserving any other meta keys."""
    conversation = get_conversation(session, conversation_id)
    merged = dict(conversation.meta or {})
    merged.update(state_to_meta(state))
    conversation.meta = merged
    session.commit()


def apply_auto_title(conversation: Conversation, user_text: str) -> None:
    """Name an untitled conversation after its first user message."""
    if conversation.title:
        return
    conversation.title = _derive_title(user_text)


def _derive_title(user_text: str) -> str:
    compact = " ".join(user_text.split())
    return compact if len(compact) <= MAX_TITLE_CHARS else f"{compact[: MAX_TITLE_CHARS - 1]}…"


def _clean_title(title: str | None) -> str | None:
    if title is None:
        return None
    compact = " ".join(title.split())
    if not compact:
        return None
    return compact[:MAX_TITLE_CHARS]
