"""Errors raised by the desktop automation layer (PRD §5.8, Phase 7).

Every failure the model can act on ("not on Windows", "no window named X")
is a :class:`DesktopError`; the tool layer maps it straight to ``ToolError``
so the agent sees a clean message instead of a traceback.
"""

from __future__ import annotations


class DesktopError(Exception):
    """Expected desktop-automation failure."""

    def __init__(self, message: str, *, code: str = "desktop_error") -> None:
        super().__init__(message)
        self.code = code
