"""Email failures surfaced to the tools as ToolError (Phase 10)."""

from __future__ import annotations


class MailError(RuntimeError):
    """Configuration, SMTP or IMAP failure with a user-readable message."""
