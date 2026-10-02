"""Permission engine (PRD §21).

    LLM requests tool → allowed | ask the user | denied

The decision is the **stricter** of two layers:

1. the autonomy-level matrix (PRD §22) — level 0/1 never execute anything,
2. the ``require_confirmation_high/critical`` guardrails.

The user can then override either layer per tool (or per category) with a
stored override in ``<data_dir>/tool_permissions.json``. Overrides are the
only mutable layer — they never *loosen* a guardrail below ``confirm`` unless
the user explicitly picks ``allow``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from luxion.config.settings import Settings
from luxion.tools.base import PermissionLevel, ToolRisk, ToolSpec

#: Where a decision came from. ``capability`` = hard-blocked before this
#: engine ever ran (see ``luxion.security.capabilities``).
Source = Literal["override", "category", "autonomy", "capability"]

#: autonomy level → risk → default decision (PRD §22).
AUTONOMY_MATRIX: dict[int, dict[ToolRisk, PermissionLevel]] = {
    0: {"low": "deny", "medium": "deny", "high": "deny", "critical": "deny"},
    1: {"low": "deny", "medium": "deny", "high": "deny", "critical": "deny"},
    2: {"low": "allow", "medium": "confirm", "high": "deny", "critical": "deny"},
    3: {"low": "allow", "medium": "allow", "high": "confirm", "critical": "confirm"},
    4: {"low": "allow", "medium": "allow", "high": "confirm", "critical": "deny"},
    5: {"low": "allow", "medium": "allow", "high": "allow", "critical": "confirm"},
}

STRICTNESS: dict[PermissionLevel, int] = {"allow": 0, "confirm": 1, "deny": 2}
_LEVELS: tuple[PermissionLevel, ...] = ("allow", "confirm", "deny")


class PermissionDecision(BaseModel):
    tool: str
    level: PermissionLevel
    source: Source
    reason: str


class PermissionEngine:
    """Resolves the effective permission for a tool and persists overrides."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    # storage
    @property
    def path(self) -> Path:
        return self.settings.app.data_dir / "tool_permissions.json"

    @property
    def overrides(self) -> dict[str, PermissionLevel]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(name): level
            for name, level in raw.items()
            if isinstance(level, str) and level in _LEVELS
        }

    def set_override(self, name: str, level: PermissionLevel | None) -> dict[str, PermissionLevel]:
        """Set (or with ``None``, clear) one override and persist the file."""
        with self._lock:
            current = self.overrides
            if level is None:
                current.pop(name, None)
            else:
                current[name] = level
            if not current:
                if self.path.exists():
                    self.path.unlink()
                return {}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            return current

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                self.path.unlink()

    # decisions
    def decide(self, spec: ToolSpec) -> PermissionDecision:
        level, source, reason = self._resolve(spec)
        return PermissionDecision(tool=spec.name, level=level, source=source, reason=reason)

    def _resolve(self, spec: ToolSpec) -> tuple[PermissionLevel, Source, str]:
        overrides = self.overrides
        if spec.name in overrides:
            level = overrides[spec.name]
            return level, "override", f"you set {spec.name} to {level}"

        category_key = f"category:{spec.category}"
        if category_key in overrides:
            level = overrides[category_key]
            return level, "category", f"you set {spec.category} tools to {level}"

        matrix = AUTONOMY_MATRIX.get(self.settings.security.autonomy_level, AUTONOMY_MATRIX[3])
        base = matrix[spec.risk]
        guardrail = self._guardrail(spec.risk)
        level = max((base, guardrail), key=lambda value: STRICTNESS[value])
        if level == base == guardrail:
            reason = f"autonomy level {self.settings.security.autonomy_level} allows {spec.risk}"
        elif STRICTNESS[guardrail] > STRICTNESS[base]:
            reason = f"{spec.risk} risk requires confirmation (PRD §20)"
        else:
            reason = f"autonomy level {self.settings.security.autonomy_level} denies {spec.risk}"
        return level, "autonomy", reason

    def _guardrail(self, risk: ToolRisk) -> PermissionLevel:
        security = self.settings.security
        if risk == "high":
            return "confirm" if security.require_confirmation_high else "allow"
        if risk == "critical":
            return "confirm" if security.require_confirmation_critical else "allow"
        return "allow"

    # views
    def defaults(self) -> list[dict[str, str]]:
        """Per-risk defaults for the Settings page (before overrides)."""
        matrix = AUTONOMY_MATRIX.get(self.settings.security.autonomy_level, AUTONOMY_MATRIX[3])
        return [
            {
                "risk": risk,
                "level": max((matrix[risk], self._guardrail(risk)), key=STRICTNESS.get),  # type: ignore[arg-type]
            }
            for risk in ("low", "medium", "high", "critical")
        ]


_engine: PermissionEngine | None = None
_engine_key: tuple | None = None


def _engine_cache_key(settings: Settings) -> tuple:
    return (
        str(settings.app.data_dir),
        settings.security.autonomy_level,
        settings.security.require_confirmation_high,
        settings.security.require_confirmation_critical,
    )


def get_engine(settings: Settings | None = None) -> PermissionEngine:
    global _engine, _engine_key
    from luxion.config.settings import get_settings

    resolved = settings or get_settings()
    key = _engine_cache_key(resolved)
    if _engine is None or _engine_key != key:
        _engine = PermissionEngine(resolved)
        _engine_key = key
    return _engine


def reset_engine() -> None:
    global _engine, _engine_key
    _engine = None
    _engine_key = None
