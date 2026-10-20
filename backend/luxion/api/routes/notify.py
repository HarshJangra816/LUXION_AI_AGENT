"""Notification settings + test toast (Phase 10).

``GET    /notify``          effective config + defaults + status (Settings card)
``PUT    /notify/config``   persist Settings → Notifications edits (partial overlay)
``DELETE /notify/config``   back to ``.env`` defaults
``POST   /notify/test``     raise a real toast through the same path as the tool
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.notify_override import clear_overrides
from luxion.config.settings import (
    NotificationConfig,
    get_settings,
    reset_settings_cache,
    save_notify_overrides,
)
from luxion.notify.toast import ToastError, send_toast

router = APIRouter(prefix="/notify", tags=["notify"])


class NotifyConfigBundle(BaseModel):
    """What Settings → Notifications edits (effective values + defaults + status)."""

    config: NotificationConfig
    defaults: NotificationConfig
    status: dict[str, Any]


class NotifyConfigPatch(BaseModel):
    """Partial notification settings — mirrors every field of ``NotificationConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with
    :class:`luxion.config.settings.NotificationConfig` so a new knob can never
    be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    app_name: str | None = None
    default_duration_s: int | None = None
    sound: bool | None = None
    cooldown_s: float | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class ToastOut(BaseModel):
    shown: bool
    title: str
    duration_s: int


def _status(settings) -> dict[str, Any]:
    """Static facts for the card — no subprocess, never raises."""
    decision = _capability_decision(settings)
    return {
        "enabled": settings.notify.enabled,
        "app_name": settings.notify.app_name,
        "sound": settings.notify.sound,
        "cooldown_s": settings.notify.cooldown_s,
        "capability": decision,
        "platform": "windows-toast",
    }


def _capability_decision(settings) -> dict[str, Any]:
    from luxion.security.capabilities import get_capabilities  # noqa: PLC0415

    decision = get_capabilities(settings).check("notifications")
    return {"state": decision.state, "allowed": decision.allowed, "reason": decision.reason}


def _bundle() -> NotifyConfigBundle:
    settings = get_settings()
    return NotifyConfigBundle(
        config=settings.notify,
        defaults=NotificationConfig(),
        status=_status(settings),
    )


@router.get("", response_model=NotifyConfigBundle)
async def read_notify() -> NotifyConfigBundle:
    return _bundle()


@router.put("/config", response_model=NotifyConfigBundle)
async def write_notify(patch: NotifyConfigPatch) -> NotifyConfigBundle:
    settings = get_settings()
    try:
        save_notify_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=NotifyConfigBundle)
async def reset_notify() -> NotifyConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.post("/test", response_model=ToastOut)
async def test_toast() -> ToastOut:
    """Raise one real toast — the honest reachability check for this family."""
    settings = get_settings()
    try:
        outcome = await send_toast(
            "Notifications work",
            "This is how a Luxion notification looks.",
            settings=settings,
        )
    except ToastError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ToastOut(**outcome)
