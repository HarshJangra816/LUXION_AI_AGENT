"""Browser agent status + settings (PRD §32, §5.7, Phase 6).

``GET    /browser``        session status + effective settings (Settings card)
``PUT    /browser/config`` persist Settings → Browser edits (partial overlay)
``DELETE /browser/config`` back to ``.env`` defaults
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.browser.manager import close_browser_manager, get_browser_manager
from luxion.config.browser_override import clear_overrides
from luxion.config.settings import (
    BrowserConfig,
    get_settings,
    reset_settings_cache,
    save_browser_overrides,
)

router = APIRouter(prefix="/browser", tags=["browser"])


class BrowserConfigBundle(BaseModel):
    """What Settings → Browser edits (effective values + defaults + status)."""

    config: BrowserConfig
    defaults: BrowserConfig
    status: dict[str, Any]


class BrowserConfigPatch(BaseModel):
    """Partial browser settings — mirrors every field of ``BrowserConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.BrowserConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    headless: bool | None = None
    search_engine: str | None = None
    navigation_timeout_s: float | None = None
    action_timeout_s: float | None = None
    extract_max_chars: int | None = None
    user_agent: str | None = None
    download_dir: str | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


def _bundle() -> BrowserConfigBundle:
    settings = get_settings()
    return BrowserConfigBundle(
        config=settings.browser,
        defaults=BrowserConfig(),
        status=get_browser_manager(settings).status(),
    )


@router.get("", response_model=BrowserConfigBundle)
async def read_browser() -> BrowserConfigBundle:
    return _bundle()


@router.put("/config", response_model=BrowserConfigBundle)
async def write_browser(patch: BrowserConfigPatch) -> BrowserConfigBundle:
    settings = get_settings()
    try:
        save_browser_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A running session was launched with the old knobs — drop it so the next
    # tool call relaunches with the new ones.
    await close_browser_manager()
    return _bundle()


@router.delete("/config", response_model=BrowserConfigBundle)
async def reset_browser() -> BrowserConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    await close_browser_manager()
    return _bundle()
