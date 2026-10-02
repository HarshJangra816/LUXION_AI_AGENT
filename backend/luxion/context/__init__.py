"""Context management (PRD §13-14): tokens, budget, compression, assembly."""

from luxion.context.budget import ContextBudget
from luxion.context.manager import BuiltContext, ContextStats, build_context
from luxion.context.records import HistoryRecord
from luxion.context.summary import SummaryState, state_from_meta, state_to_meta
from luxion.context.tokens import (
    estimate_message_tokens,
    estimate_tokens,
    truncate_to_tokens,
)

__all__ = [
    "BuiltContext",
    "ContextBudget",
    "ContextStats",
    "HistoryRecord",
    "SummaryState",
    "build_context",
    "estimate_message_tokens",
    "estimate_tokens",
    "state_from_meta",
    "state_to_meta",
    "truncate_to_tokens",
]
