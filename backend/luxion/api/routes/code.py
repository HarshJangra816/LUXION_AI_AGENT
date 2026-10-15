"""Coding-agent status + settings (PRD §34, §32 Tools → Terminal/Git, Phase 8).

``GET    /code``            platform status + effective settings (Settings card)
``PUT    /code/config``     persist Settings → Coding edits (partial overlay)
``DELETE /code/config``     back to ``.env`` defaults
"""

from __future__ import annotations

import shutil
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.code_override import clear_overrides
from luxion.config.settings import (
    CodeConfig,
    get_settings,
    reset_settings_cache,
    save_code_overrides,
)

router = APIRouter(prefix="/code", tags=["code"])


class CodeConfigBundle(BaseModel):
    """What Settings → Coding edits (effective values + defaults + status)."""

    config: CodeConfig
    defaults: CodeConfig
    status: dict[str, Any]


class CodeConfigPatch(BaseModel):
    """Partial coding settings — mirrors every field of ``CodeConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.CodeConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    command_timeout_s: float | None = None
    max_output_chars: int | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


def _status(settings) -> dict[str, Any]:
    """Live toolchain facts for the card (never raises).

    No ``supported`` flag unlike the desktop card: the coding tools are
    cross-platform by design (stdlib + the user's own git).
    """
    from luxion.security.capabilities import get_capabilities

    capability = get_capabilities(settings).check("terminal")
    workspace = settings.security.allowed_workspaces
    return {
        "platform": sys.platform,
        "git": shutil.which("git") is not None,
        "github_cli": shutil.which("gh") is not None,
        "workspace": str(workspace[0]) if workspace else None,
        "terminal_capability": capability.state,
        "terminal_capability_reason": capability.reason,
        "enabled": settings.code.enabled,
    }


def _bundle() -> CodeConfigBundle:
    settings = get_settings()
    return CodeConfigBundle(
        config=settings.code,
        defaults=CodeConfig(),
        status=_status(settings),
    )


@router.get("", response_model=CodeConfigBundle)
async def read_code() -> CodeConfigBundle:
    return _bundle()


@router.put("/config", response_model=CodeConfigBundle)
async def write_code(patch: CodeConfigPatch) -> CodeConfigBundle:
    settings = get_settings()
    try:
        save_code_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=CodeConfigBundle)
async def reset_code() -> CodeConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()
