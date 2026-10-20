"""Errors raised by the web-intelligence sources.

Deliberately *not* :class:`luxion.tools.base.ToolError` — the ``luxion.web``
package sits below the tool layer and must stay importable on its own (same
layering rule as ``luxion.context`` importing ``services`` but never the
reverse). Tools convert a :class:`WebError` into a ``ToolError`` so the model
still sees a clean, honest failure.
"""

from __future__ import annotations


class WebError(Exception):
    """A source could not be reached or answered something unusable."""

    def __init__(self, message: str, *, source: str = "web") -> None:
        super().__init__(message)
        self.source = source
