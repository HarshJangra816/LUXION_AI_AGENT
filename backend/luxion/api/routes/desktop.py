"""Desktop automation status + settings (PRD §32, §5.8, Phase 7).

``GET    /desktop``        platform status + effective settings (Settings card)
``PUT    /desktop/config`` persist Settings → Desktop edits (partial overlay)
``DELETE /desktop/config`` back to ``.env`` defaults
"""

from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.desktop_override import clear_overrides
from luxion.config.settings import (
    DesktopConfig,
    get_settings,
    reset_settings_cache,
    save_desktop_overrides,
)

router = APIRouter(prefix="/desktop", tags=["desktop"])


class DesktopConfigBundle(BaseModel):
    """What Settings → Desktop edits (effective values + defaults + status)."""

    config: DesktopConfig
    defaults: DesktopConfig
    status: dict[str, Any]


class DesktopConfigPatch(BaseModel):
    """Partial desktop settings — mirrors every field of ``DesktopConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.DesktopConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    ui_automation: bool | None = None
    coordinate_fallback: bool | None = None
    max_elements: int | None = None
    max_processes: int | None = None
    focus_delay_s: float | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


def _status(settings) -> dict[str, Any]:
    """Live platform facts for the card (never raises)."""
    from luxion.desktop import uia as _uia
    from luxion.desktop import windows as _windows
    from luxion.security.capabilities import get_capabilities

    supported = sys.platform == "win32"
    windows_visible = 0
    if supported:
        try:
            windows_visible = len(_windows.enumerate_windows())
        except Exception:  # noqa: BLE001 - a desktop hiccup must not 500 Settings
            windows_visible = 0
    capability = get_capabilities(settings).check("input_control")
    return {
        "supported": supported,
        "platform": sys.platform,
        "ui_automation": _uia.available(),
        "windows": windows_visible,
        "input_capability": capability.state,
        "input_capability_reason": capability.reason,
        "enabled": settings.desktop.enabled,
    }


def _bundle() -> DesktopConfigBundle:
    settings = get_settings()
    return DesktopConfigBundle(
        config=settings.desktop,
        defaults=DesktopConfig(),
        status=_status(settings),
    )


@router.get("", response_model=DesktopConfigBundle)
async def read_desktop() -> DesktopConfigBundle:
    return _bundle()


@router.put("/config", response_model=DesktopConfigBundle)
async def write_desktop(patch: DesktopConfigPatch) -> DesktopConfigBundle:
    settings = get_settings()
    try:
        save_desktop_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=DesktopConfigBundle)
async def reset_desktop() -> DesktopConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()
