"""Context budget: how much of the window may go to each source (PRD §13).

The window is split::

    total = reserve  +  response  +  system  +  summary  +  history

``reserve`` absorbs estimator error, ``response`` leaves room for the model's
reply (``llm.max_tokens``), and the rest is distributed by the manager.
"""

from __future__ import annotations

from dataclasses import dataclass

from luxion.config.settings import Settings


@dataclass(frozen=True, slots=True)
class ContextBudget:
    total: int
    reserve: int
    response: int

    @property
    def spendable(self) -> int:
        """Tokens available for system prompt + summary + history."""
        return max(0, self.total - self.reserve - self.response)

    def history_allowance(self, *, system_tokens: int, summary_tokens: int) -> int:
        """Tokens the transcript may occupy once the fixed parts are placed."""
        return max(0, self.spendable - system_tokens - summary_tokens)

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "reserve": self.reserve,
            "response": self.response,
            "spendable": self.spendable,
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> ContextBudget:
        cfg = settings.context
        total = cfg.total_budget_tokens
        # Clamp: a misconfigured reserve/response must never eat the whole window.
        reserve = min(cfg.reserve_tokens, total // 2)
        response = min(settings.llm.max_tokens, max(1, total // 4))
        return cls(total=total, reserve=reserve, response=response)
