"""WhatsApp settings, session and QR login (PRD §33.3, Phase 10).

``GET    /whatsapp``          effective config + defaults + status (Settings card)
``PUT    /whatsapp/config``   persist Settings → WhatsApp edits (partial overlay)
``DELETE /whatsapp/config``   back to ``.env`` defaults
``POST   /whatsapp/session``  launch the persistent session and wait for login
                              (returns the QR as a data-URL while waiting)
``POST   /whatsapp/close``    tear the session down

The session POST is the login flow: with ``wait=false`` it starts the session
and returns the current QR (if logged out); polling it again after the scan
flips ``logged_in`` to true. No DOM automation runs here — only session
lifecycle — so a card refresh never types into anybody's chat.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.settings import (
    WhatsAppConfig,
    get_settings,
    reset_settings_cache,
    save_whatsapp_overrides,
)
from luxion.config.whatsapp_override import clear_overrides
from luxion.whatsapp.errors import WhatsAppError
from luxion.whatsapp.manager import close_whatsapp_manager, get_whatsapp_manager
from luxion.whatsapp.web import grab_qr, probe_login

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class WhatsAppConfigBundle(BaseModel):
    """What Settings → WhatsApp edits (effective values + defaults + status)."""

    config: WhatsAppConfig
    defaults: WhatsAppConfig
    status: dict[str, Any]


class WhatsAppConfigPatch(BaseModel):
    """Partial WhatsApp settings — mirrors every field of ``WhatsAppConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with
    :class:`luxion.config.settings.WhatsAppConfig` so a new knob can never be
    silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    headless: bool | None = None
    profile_dir: str | None = None
    timeout_s: float | None = None
    login_timeout_s: float | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class SessionOut(BaseModel):
    """Result of launching/waiting on the login session."""

    running: bool
    logged_in: bool | None
    qr: str | None = None
    url: str | None = None


def _bundle() -> WhatsAppConfigBundle:
    settings = get_settings()
    manager = get_whatsapp_manager(settings)
    return WhatsAppConfigBundle(
        config=settings.whatsapp,
        defaults=WhatsAppConfig(),
        status=manager.status(),
    )


@router.get("", response_model=WhatsAppConfigBundle)
async def read_whatsapp() -> WhatsAppConfigBundle:
    return _bundle()


@router.put("/config", response_model=WhatsAppConfigBundle)
async def write_whatsapp(patch: WhatsAppConfigPatch) -> WhatsAppConfigBundle:
    settings = get_settings()
    try:
        save_whatsapp_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=WhatsAppConfigBundle)
async def reset_whatsapp() -> WhatsAppConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.post("/session", response_model=SessionOut)
async def open_session() -> SessionOut:
    """Launch the persistent session; return the QR while logged out.

    Deliberately short-lived: it never waits past the QR appearing, so the UI
    can poll without blocking. Login completion is observed on later polls
    (status flips once the search box shows up).
    """
    settings = get_settings()
    manager = get_whatsapp_manager(settings)
    try:
        session = await manager.session()
        logged_in = await probe_login(session)
        qr = None if logged_in else await grab_qr(session, timeout_ms=8000)
    except WhatsAppError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SessionOut(
        running=manager.running,
        logged_in=logged_in,
        qr=qr,
        url=session.url or None,
    )


@router.post("/status", response_model=SessionOut)
async def refresh_status() -> SessionOut:
    """Re-check the live session for login (poll after scanning the QR)."""
    manager = get_whatsapp_manager(get_settings())
    if not manager.running:
        return SessionOut(running=False, logged_in=None)
    session = manager._session  # noqa: SLF001 - same package-level singleton
    try:
        logged_in = await probe_login(session)
    except WhatsAppError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SessionOut(running=True, logged_in=logged_in, url=session.url or None)


@router.post("/close", response_model=dict[str, Any])
async def close_session() -> dict[str, Any]:
    await close_whatsapp_manager()
    return {"running": False}
