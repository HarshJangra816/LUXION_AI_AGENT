"""Rolling conversation summary (PRD §14).

The summary lives in ``conversations.meta`` rather than as a real message: it
is derived state, it must never leak into the transcript, and adding it as a
column would force a migration on the live database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

META_KEY = "context"


class SummaryState(BaseModel):
    """Cumulative summary of every message older than the kept window."""

    #: Condensed text handed to the model as an extra system message.
    text: str = ""
    #: Estimated tokens of ``text`` (0 while empty).
    tokens: int = 0
    #: Id of the newest message already folded into ``text``.
    covered_through: int = 0
    updated_at: str | None = None

    @property
    def present(self) -> bool:
        return bool(self.text.strip())

    @classmethod
    def empty(cls) -> SummaryState:
        return cls()


def state_from_meta(meta: Any) -> SummaryState:
    """Rebuild the state from a stored conversation row (never raises)."""
    if not isinstance(meta, dict):
        return SummaryState.empty()
    raw = meta.get(META_KEY)
    if not isinstance(raw, dict):
        return SummaryState.empty()
    try:
        state = SummaryState.model_validate(raw)
    except Exception:  # noqa: BLE001 - corrupted meta must not break chat
        return SummaryState.empty()
    if state.tokens <= 0:
        state.tokens = len(state.text) // 4
    return state


def state_to_meta(state: SummaryState) -> dict[str, Any]:
    return {META_KEY: state.model_dump()}


def next_state(*, text: str, tokens: int, covered_through: int) -> SummaryState:
    return SummaryState(
        text=text,
        tokens=tokens,
        covered_through=covered_through,
        updated_at=datetime.now(UTC).isoformat(),
    )
