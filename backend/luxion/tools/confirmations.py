"""Interactive confirmations (PRD §21 "Confirmation → Ask User").

When the permission engine says ``confirm``, the agent turn parks until the
user answers from the UI (``POST /api/tools/confirmations/{id}``) or the window
expires. Only one process-wide manager exists, because the SSE stream that
owns the wait and the HTTP request that resolves it are different requests on
the same event loop.

The answer is stored on the pending entry *and* on a future, so an answer that
arrives before :meth:`wait` is awaited is not lost.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingConfirmation:
    id: str
    tool: str
    risk: str
    args: dict[str, Any]
    reason: str
    description: str
    created_at: float = field(default_factory=time.monotonic)
    conversation_id: str | None = None
    #: Set by :meth:`ConfirmationManager.resolve` before a waiter attaches.
    approved: bool | None = None
    future: asyncio.Future[bool] | None = None

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.created_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "risk": self.risk,
            "args": self.args,
            "reason": self.reason,
            "description": self.description,
            "conversation_id": self.conversation_id,
            "age_s": round(self.age_s, 2),
        }


class ConfirmationManager:
    def __init__(self, timeout_s: float = 180.0) -> None:
        self.timeout_s = timeout_s
        self._pending: dict[str, PendingConfirmation] = {}

    def create(
        self,
        *,
        tool: str,
        risk: str,
        args: dict[str, Any],
        reason: str,
        description: str,
        conversation_id: str | None = None,
    ) -> PendingConfirmation:
        """Register a prompt. Safe to call with or without a running loop —
        the future is created lazily by :meth:`wait`."""
        pending = PendingConfirmation(
            id=uuid.uuid4().hex,
            tool=tool,
            risk=risk,
            args=args,
            reason=reason,
            description=description,
            conversation_id=conversation_id,
        )
        self._pending[pending.id] = pending
        return pending

    def get(self, confirmation_id: str) -> PendingConfirmation | None:
        return self._pending.get(confirmation_id)

    def pending(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in list(self._pending.values())]

    def resolve(self, confirmation_id: str, approved: bool) -> bool:
        """Answer a pending prompt. Returns ``False`` when it is unknown.

        The entry is left in place so a waiter that has not attached yet (or
        attaches a tick later) still sees the answer; ``wait``/``forget``/
        ``ToolExecutor._finish`` are responsible for removing it.
        """
        pending = self._pending.get(confirmation_id)
        if pending is None or pending.approved is not None:
            return False
        pending.approved = approved
        future = pending.future
        if future is not None and not future.done():
            self._deliver(pending, approved)
        return True

    @staticmethod
    def _deliver(pending: PendingConfirmation, approved: bool) -> None:
        future = pending.future
        if future is None or future.done():
            return
        loop = future.get_loop()
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            future.set_result(approved)
            return
        try:
            loop.call_soon_threadsafe(lambda: future.done() or future.set_result(approved))
        except RuntimeError:
            # Loop already closed — the waiter timed out and cleaned up.
            pending.future = None

    async def wait(self, confirmation_id: str, *, timeout_s: float | None = None) -> bool:
        """Block until the user answers (``True``) or the prompt expires."""
        pending = self._pending.get(confirmation_id)
        if pending is None:
            return False
        if pending.approved is not None:
            self._pending.pop(confirmation_id, None)
            return pending.approved

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        pending.future = future
        try:
            return await asyncio.wait_for(future, timeout=timeout_s or self.timeout_s)
        except TimeoutError:
            self._pending.pop(confirmation_id, None)
            return False
        except asyncio.CancelledError:
            self._pending.pop(confirmation_id, None)
            raise
        finally:
            pending.future = None

    def forget(self, confirmation_id: str) -> None:
        self._pending.pop(confirmation_id, None)


_manager: ConfirmationManager | None = None


def get_confirmations(timeout_s: float | None = None) -> ConfirmationManager:
    global _manager
    if _manager is None:
        from luxion.config.settings import get_settings

        _manager = ConfirmationManager(
            timeout_s if timeout_s is not None else get_settings().tools.confirm_timeout_s
        )
    return _manager


def reset_confirmations() -> None:
    global _manager
    _manager = None
