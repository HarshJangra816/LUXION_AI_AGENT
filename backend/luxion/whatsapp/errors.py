"""WhatsApp automation failures surfaced to the tools as ToolError (Phase 10)."""

from __future__ import annotations


class WhatsAppError(RuntimeError):
    """Launch, login or DOM failure with a user-readable message."""
