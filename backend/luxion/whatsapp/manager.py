"""WhatsApp Web session (PRD §33.3, Phase 10).

One **persistent** Playwright Chromium per process, launched lazily on the
first ``whatsapp_*`` call and torn down at shutdown
(:func:`close_whatsapp_manager` from the app lifespan).

Unlike :mod:`luxion.browser` (throwaway contexts), WhatsApp needs a login
that survives restarts, so this manager uses
``chromium.launch_persistent_context`` with ``<data_dir>/whatsapp_profile`` —
scan the QR once, the session cookie lives in the profile. Tests swap the
launcher (:func:`set_whatsapp_launcher`) for a fake returning canned pages,
so the suite never needs a real browser or a WhatsApp account.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from luxion.config.settings import Settings, get_settings
from luxion.whatsapp.errors import WhatsAppError

logger = logging.getLogger(__name__)

WEB_URL = "https://web.whatsapp.com/"


@dataclass
class WhatsAppSession:
    """The live Playwright objects (or their fakes in tests)."""

    page: Any
    context: Any
    playwright: Any
    #: Last observed login state; ``None`` until something checked.
    logged_in: bool | None = field(default=None)

    @property
    def url(self) -> str:
        return str(getattr(self.page, "url", "") or "")

    async def close(self) -> None:
        """Close everything, oldest first; never raises (shutdown path)."""
        for closer in (
            getattr(self.context, "close", None),
            getattr(self.playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # noqa: BLE001 - shutdown must not explode
                logger.debug("whatsapp_close_step_failed", exc_info=True)


#: A launcher turns config + profile dir into a live session (tests inject fakes).
Launcher = Callable[[Any, Path], Awaitable[WhatsAppSession]]


async def playwright_launcher(config: Any, profile_dir: Path) -> WhatsAppSession:
    """Real launch: persistent Chromium context parked on WhatsApp Web."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise WhatsAppError(
            "playwright is not installed — run `pip install playwright` and "
            "`python -m playwright install chromium`"
        ) from exc

    profile_dir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=config.headless,
        )
        context.set_default_timeout(config.timeout_s * 1000)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(WEB_URL, timeout=config.timeout_s * 1000)
    except Exception as exc:  # noqa: BLE001 - map to a friendly message
        with contextlib.suppress(Exception):
            await pw.stop()
        raise WhatsAppError(
            f"could not open WhatsApp Web ({exc}) — if this is a fresh install, "
            "run `python -m playwright install chromium`"
        ) from exc
    return WhatsAppSession(page=page, context=context, playwright=pw)


class WhatsAppManager:
    """Owns the one session; serialises launch/close across tool calls."""

    def __init__(self, settings: Settings, *, launcher: Launcher | None = None) -> None:
        self.settings = settings
        self._launcher = launcher
        self._session: WhatsAppSession | None = None
        self._lock = asyncio.Lock()

    def resolve_profile_dir(self) -> Path:
        configured = self.settings.whatsapp.profile_dir
        if configured:
            return Path(configured)
        return Path(self.settings.app.data_dir) / "whatsapp_profile"

    # ------------------------------------------------------------------ session
    async def session(self) -> WhatsAppSession:
        """The live session, launching it on first use."""
        async with self._lock:
            if self._session is None:
                config = self.settings.whatsapp
                if not config.enabled:
                    raise WhatsAppError(
                        "WhatsApp automation is disabled — enable it in "
                        "Settings → Integrations → WhatsApp"
                    )
                launcher = self._launcher or playwright_launcher
                self._session = await launcher(config, self.resolve_profile_dir())
                logger.info(
                    "whatsapp_launched",
                    extra={"headless": config.headless},
                )
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None
                logger.info("whatsapp_closed")

    @property
    def running(self) -> bool:
        return self._session is not None

    def status(self) -> dict[str, Any]:
        """Settings → WhatsApp card + ``GET /api/whatsapp`` payload.

        ``logged_in`` is the last *observed* state (login checks are async);
        ``None`` means "nobody looked yet" and the UI says "unknown".
        """
        config = self.settings.whatsapp
        return {
            "enabled": config.enabled,
            "running": self.running,
            "headless": config.headless,
            "logged_in": self._session.logged_in if self._session else None,
            "url": self._session.url if self._session else None,
            "profile_dir": str(self.resolve_profile_dir()),
            "timeout_s": config.timeout_s,
            "login_timeout_s": config.login_timeout_s,
        }


# ------------------------------------------------------------------- singleton
_manager: WhatsAppManager | None = None


def get_whatsapp_manager(
    settings: Settings | None = None, *, launcher: Launcher | None = None
) -> WhatsAppManager:
    """Process-wide manager (tools + routes share the one session)."""
    global _manager
    if _manager is None:
        _manager = WhatsAppManager(settings or get_settings(), launcher=launcher)
    return _manager


def set_whatsapp_launcher(launcher: Launcher | None) -> None:
    """Test seam: install a fake launcher (and reset the manager first)."""
    global _manager
    _manager = None
    if launcher is not None:
        _manager = WhatsAppManager(get_settings(), launcher=launcher)


def reset_whatsapp_manager() -> None:
    """Drop the cached manager without closing it (tests: use fakes only)."""
    global _manager
    _manager = None


async def close_whatsapp_manager() -> None:
    """App-shutdown hook: close the session if one was launched."""
    global _manager
    if _manager is not None:
        await _manager.close()
        _manager = None
