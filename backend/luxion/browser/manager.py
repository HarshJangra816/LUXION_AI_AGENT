"""Browser automation session (PRD §5.7, Phase 6).

One Playwright Chromium per process, launched lazily on the first
``browser_*`` / ``youtube_*`` tool call and torn down at shutdown
(:func:`close_browser_manager` from the app lifespan).

The tools never import Playwright: they ask :func:`get_browser_manager` for a
session and call page methods on it. Tests swap the launcher
(:func:`set_browser_launcher`) for a fake that returns canned pages, so the
suite never needs a real browser or the Chromium download.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luxion.config.settings import BrowserConfig, Settings, get_settings

logger = logging.getLogger(__name__)


class BrowserError(RuntimeError):
    """Launch / navigation / action failure surfaced to the tools as ToolError."""


@dataclass
class BrowserSession:
    """The live Playwright objects (or their fakes in tests)."""

    page: Any
    context: Any
    browser: Any
    playwright: Any

    @property
    def url(self) -> str:
        return str(getattr(self.page, "url", "") or "")

    async def close(self) -> None:
        """Close everything, oldest first; never raises (shutdown path)."""
        for closer in (
            getattr(self.context, "close", None),
            getattr(self.browser, "close", None),
            getattr(self.playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # noqa: BLE001 - shutdown must not explode
                logger.debug("browser_close_step_failed", exc_info=True)


#: A launcher turns config into a live session (tests inject fakes here).
Launcher = Callable[[BrowserConfig], Awaitable[BrowserSession]]


async def playwright_launcher(config: BrowserConfig) -> BrowserSession:
    """Real launch: start Playwright and open one Chromium context + page."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BrowserError(
            "playwright is not installed — run `pip install playwright` and "
            "`python -m playwright install chromium`"
        ) from exc

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=config.headless)
        context = await browser.new_context(
            user_agent=config.user_agent or None,
            accept_downloads=True,
        )
        context.set_default_timeout(config.action_timeout_s * 1000)
        page = await context.new_page()
    except Exception as exc:  # noqa: BLE001 - map to a ToolError-friendly message
        with contextlib.suppress(Exception):
            await pw.stop()
        raise BrowserError(
            f"could not launch Chromium ({exc}) — if this is a fresh install, "
            "run `python -m playwright install chromium`"
        ) from exc
    return BrowserSession(page=page, context=context, browser=browser, playwright=pw)


class BrowserManager:
    """Owns the one session; serialises launch/close across tool calls."""

    def __init__(self, settings: Settings, *, launcher: Launcher | None = None) -> None:
        self.settings = settings
        self._launcher = launcher
        self._session: BrowserSession | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ session
    async def session(self) -> BrowserSession:
        """The live session, launching it on first use."""
        async with self._lock:
            if self._session is None:
                config = self.settings.browser
                if not config.enabled:
                    raise BrowserError(
                        "browser automation is disabled (LUXION_BROWSER__ENABLED=false)"
                    )
                launcher = self._launcher or playwright_launcher
                self._session = await launcher(config)
                logger.info(
                    "browser_launched",
                    extra={"headless": config.headless, "engine": config.search_engine},
                )
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None
                logger.info("browser_closed")

    @property
    def running(self) -> bool:
        return self._session is not None

    def status(self) -> dict[str, Any]:
        """Settings → Browser card + ``GET /api/browser`` payload."""
        config = self.settings.browser
        return {
            "enabled": config.enabled,
            "running": self.running,
            "headless": config.headless,
            "search_engine": config.search_engine,
            "navigation_timeout_s": config.navigation_timeout_s,
            "action_timeout_s": config.action_timeout_s,
            "extract_max_chars": config.extract_max_chars,
            "url": self._session.url if self._session else None,
            "download_dir": str(self.resolve_download_dir()),
        }

    def resolve_download_dir(self) -> Path:
        configured = self.settings.browser.download_dir
        if configured is not None:
            return Path(configured)
        return Path(self.settings.app.data_dir) / "downloads"

    def navigation_timeout_ms(self) -> float:
        return self.settings.browser.navigation_timeout_s * 1000

    def action_timeout_ms(self) -> float:
        return self.settings.browser.action_timeout_s * 1000


# ------------------------------------------------------------------- singleton
_manager: BrowserManager | None = None


def get_browser_manager(
    settings: Settings | None = None, *, launcher: Launcher | None = None
) -> BrowserManager:
    """Process-wide manager (tools + routes share the one Chromium)."""
    global _manager
    if _manager is None:
        _manager = BrowserManager(settings or get_settings(), launcher=launcher)
    return _manager


def set_browser_launcher(launcher: Launcher | None) -> None:
    """Test seam: install a fake launcher (and reset the manager first)."""
    global _manager
    _manager = None
    if launcher is not None:
        _manager = BrowserManager(get_settings(), launcher=launcher)


def reset_browser_manager() -> None:
    """Drop the cached manager without closing it (tests: use fakes only)."""
    global _manager
    _manager = None


async def close_browser_manager() -> None:
    """App-shutdown hook: close the browser if one was launched."""
    global _manager
    if _manager is not None:
        await _manager.close()
        _manager = None
