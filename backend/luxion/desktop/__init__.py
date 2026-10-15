"""Desktop automation layer (PRD §5.8, §33.5, §39, Phase 7).

Four small modules behind the ``desktop`` tool category:

``windows``
    enumerate / resolve / focus top-level windows — the read-only app control
    that works without any UI Automation dependency.
``uia``
    inspect a window's accessibility tree and click a control by name
    (pywinauto's UIA backend, imported lazily).
``input``
    keyboard chords, unicode typing and coordinate clicks via ``SendInput``
    (import it as ``luxion.desktop.input`` — it is deliberately not re-exported
    under the name ``input``).
``controls``
    master volume (Core Audio) and display brightness (WMI).

Everything raises :class:`DesktopError`, which the tool layer turns into a
``ToolError`` the model can react to. Non-Windows hosts get a clean
``unsupported_platform`` error instead of an ImportError.
"""

from __future__ import annotations

from luxion.desktop import controls, uia, windows
from luxion.desktop.errors import DesktopError
from luxion.desktop.windows import AppWindow, enumerate_windows, find_window, focus_window

__all__ = [
    "AppWindow",
    "DesktopError",
    "controls",
    "enumerate_windows",
    "find_window",
    "focus_window",
    "uia",
    "windows",
]
