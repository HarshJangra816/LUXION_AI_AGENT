"""Conversation CRUD and the streaming chat endpoint."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from luxion.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    MessageCreate,
)
from luxion.api.sse import STREAM_HEADERS, sse_stream
from luxion.database.session import get_db, get_session_factory
from luxion.services import chat as chat_service
from luxion.services import conversations as conversation_service
from luxion.services.conversations import ConversationNotFound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

DbSession = Annotated[Session, Depends(get_db)]


def _or_404(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found")


@router.get("", response_model=list[ConversationSummary])
def list_conversations(db: DbSession) -> list[ConversationSummary]:
    return [
        ConversationSummary.from_model(conversation)
        for conversation in conversation_service.list_conversations(db)
    ]


@router.post("", response_model=ConversationSummary, status_code=201)
def create_conversation(
    db: DbSession,
    payload: ConversationCreate | None = None,
) -> ConversationSummary:
    title = payload.title if payload else None
    conversation = conversation_service.create_conversation(db, title)
    return ConversationSummary.from_model(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: DbSession) -> ConversationDetail:
    try:
        conversation = conversation_service.get_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise _or_404(conversation_id) from exc
    return ConversationDetail.from_model(conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: DbSession) -> None:
    try:
        conversation_service.delete_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise _or_404(conversation_id) from exc


@router.post("/{conversation_id}/messages")
async def send_message(conversation_id: str, payload: MessageCreate) -> StreamingResponse:
    """Stream one assistant turn as ``text/event-stream``.

    Frames: ``delta`` (incremental text) → exactly one ``done`` or ``error``.
    """
    try:
        with get_session_factory()() as session:
            conversation_service.get_conversation(session, conversation_id)
    except ConversationNotFound as exc:
        raise _or_404(conversation_id) from exc

    logger.info(
        "chat_turn_started",
        extra={"conversation_id": conversation_id, "chars": len(payload.content)},
    )
    return StreamingResponse(
        sse_stream(chat_service.stream_reply(conversation_id, payload.content)),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
