"""Browser agent session (Phase 6, PRD §5.7)."""

from luxion.browser.manager import (
    BrowserError,
    BrowserManager,
    BrowserSession,
    close_browser_manager,
    get_browser_manager,
    reset_browser_manager,
    set_browser_launcher,
)

__all__ = [
    "BrowserError",
    "BrowserManager",
    "BrowserSession",
    "close_browser_manager",
    "get_browser_manager",
    "reset_browser_manager",
    "set_browser_launcher",
]
