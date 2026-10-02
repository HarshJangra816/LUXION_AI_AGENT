"""Server-sent events framing for streaming endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel


def sse_frame(event: BaseModel) -> str:
    """One ``event:``/``data:`` block (``event.type`` becomes the event name)."""
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def sse_stream(events: AsyncIterator[BaseModel]) -> AsyncIterator[str]:
    """Adapt any model-typed async iterator into an SSE byte stream."""
    async for event in events:
        yield sse_frame(event)
