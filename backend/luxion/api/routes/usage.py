"""Token spend, cost and context-window reporting for the Settings page."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from luxion.api.schemas import ConversationContextReport, UsageReport
from luxion.config.settings import get_settings
from luxion.database.session import get_db
from luxion.services.conversations import ConversationNotFound
from luxion.services.usage import conversation_context, usage_report

router = APIRouter(prefix="/usage", tags=["usage"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=UsageReport)
def global_usage(db: DbSession) -> UsageReport:
    """Totals, per-conversation spend and the last assistant turns."""
    return usage_report(db, get_settings())


@router.get("/{conversation_id}", response_model=ConversationContextReport)
async def conversation_usage(conversation_id: str) -> ConversationContextReport:
    """Context breakdown for one conversation, including the summary state."""
    try:
        return await conversation_context(conversation_id, get_settings())
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Conversation '{conversation_id}' not found"
        ) from exc
