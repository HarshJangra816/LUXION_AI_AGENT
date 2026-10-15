"""Top-level window / application control (PRD §33.5, §5.8, Phase 7).

``list_applications`` and ``focus_application`` live here: enumerate the
visible top-level windows, resolve a free-text name to one of them and bring
it to the front. Deliberately **not** pywinauto — enumerating and focusing
needs only Win32, which keeps the read-only tools working even when UI
Automation is switched off in Settings.

Every entry point guards ``sys.platform`` so a non-Windows host gets a clear
:class:`~luxion.desktop.errors.DesktopError` instead of an ImportError.
"""

from __future__ import annotations

import contextlib
import sys
import time
from dataclasses import dataclass

from luxion.desktop.errors import DesktopError

#: How long ``focus_window`` waits before judging whether it got the
#: foreground (Windows may refuse a background process the right to steal it).
FOCUS_POLL_S = 0.35


@dataclass(frozen=True)
class AppWindow:
    """One visible top-level window."""

    hwnd: int
    title: str
    process: str = ""
    pid: int = 0
    focused: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "process": self.process,
            "pid": self.pid,
            "focused": self.focused,
        }


def require_windows() -> None:
    """Raise unless this host can drive Win32 windows."""
    if sys.platform != "win32":
        raise DesktopError(
            f"desktop automation requires Windows (this host is {sys.platform})",
            code="unsupported_platform",
        )


def _process_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name() or ""
    except Exception:  # noqa: BLE001 - process may have exited mid-walk
        return ""


def _is_cloaked(hwnd: int) -> bool:
    """True for shell-cloaked (hidden) UWP windows that still claim visible."""
    try:
        import ctypes

        DWMWA_CLOAKED = 14
        value = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(  # type: ignore[attr-defined]
            hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
        )
        return bool(value.value)
    except Exception:  # noqa: BLE001 - no DWM (remote session, odd hardware)
        return False


#: Desktop shell surfaces — always "visible", never useful to the agent.
_SHELL_CLASSES = {"Progman", "WorkerW"}


def enumerate_windows(*, visible_only: bool = True) -> list[AppWindow]:
    """Every top-level window with a title, front-to-back.

    Cloaked (hidden-but-alive) windows and the desktop shell window are
    skipped: Windows reports them as visible, which would otherwise fill the
    list with ghost "Settings" entries the model can never actually act on.
    """
    require_windows()
    import win32gui

    focused_hwnd = 0
    with contextlib.suppress(Exception):  # never fatal for a read-only listing
        focused_hwnd = win32gui.GetForegroundWindow()

    rows: list[AppWindow] = []

    def visit(hwnd: int, _acc: list[AppWindow]) -> None:
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return
        try:
            if win32gui.GetClassName(hwnd) in _SHELL_CLASSES:
                return
        except Exception:  # noqa: BLE001 - window vanished mid-walk
            return
        if _is_cloaked(hwnd):
            return
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return
        pid = window_pid(hwnd)
        _acc.append(
            AppWindow(
                hwnd=hwnd,
                title=title,
                process=_process_name(pid),
                pid=pid,
                focused=hwnd == focused_hwnd,
            )
        )

    win32gui.EnumWindows(visit, rows)
    return rows


def window_pid(hwnd: int) -> int:
    try:
        import win32process

        return int(win32process.GetWindowThreadProcessId(hwnd)[1])
    except Exception:  # noqa: BLE001 - window may have closed
        return 0


def active_window() -> AppWindow | None:
    """The window that currently has the foreground, if it has a title."""
    require_windows()
    import win32gui

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    title = (win32gui.GetWindowText(hwnd) or "").strip()
    if not title:
        return None
    pid = window_pid(hwnd)
    return AppWindow(hwnd=hwnd, title=title, process=_process_name(pid), pid=pid, focused=True)


def matches(window: AppWindow, query: str) -> bool:
    """Case-insensitive substring match on the title **or** the process name."""
    needle = query.strip().lower()
    if not needle:
        return False
    return needle in window.title.lower() or needle in window.process.lower()


def find_window(query: str, *, windows: list[AppWindow] | None = None) -> AppWindow:
    """Resolve free text to exactly one window.

    Ambiguity is an error, not a guess: the message lists the candidates so
    the model can refine its query instead of typing into the wrong app.
    """
    require_windows()
    needle = query.strip()
    if not needle:
        raise DesktopError("window name must not be empty", code="invalid_query")
    pool = windows if windows is not None else enumerate_windows()
    hits = [window for window in pool if matches(window, needle)]
    if not hits:
        known = ", ".join(w.title for w in pool[:8]) or "no titled windows"
        raise DesktopError(
            f"no window matches '{needle}' (open windows: {known})", code="not_found"
        )
    if len(hits) > 1:
        active = next((w for w in hits if w.focused), None)
        if active is not None:
            return active
        titles = ", ".join(w.title for w in hits[:6])
        raise DesktopError(
            f"'{needle}' matches {len(hits)} windows ({titles}); be more specific",
            code="ambiguous",
        )
    return hits[0]


def _attempt_foreground(hwnd: int) -> None:
    """Try every legal way to make ``hwnd`` the foreground window.

    Windows normally refuses to let a background process steal the foreground,
    so three strategies are tried in order:

    1. **AttachThreadInput** — borrow the current foreground thread's input
       queue, which is what makes ``SetForegroundWindow`` legal (and is what
       pywinauto/Win32 automation tools do in practice);
    2. the **ALT-key trick** — holding Alt while asking unlocks the same door;
    3. plain **z-order raise** — the window comes to the top even if another
       window keeps the keyboard focus.
    """
    import win32api
    import win32con
    import win32gui
    import win32process

    attached = False
    current_tid = 0
    foreground_tid = 0
    try:
        foreground = win32gui.GetForegroundWindow()
        foreground_tid = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
        current_tid = win32api.GetCurrentThreadId()
        if foreground_tid and foreground_tid != current_tid:
            win32process.AttachThreadInput(current_tid, foreground_tid, True)
            attached = True
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        with contextlib.suppress(Exception):  # top-level windows only, cosmetic
            win32gui.SetActiveWindow(hwnd)
        return
    except Exception:  # noqa: BLE001 - fall through to the next strategy
        pass
    finally:
        if attached:
            with contextlib.suppress(Exception):  # a stuck input queue is worse
                win32process.AttachThreadInput(current_tid, foreground_tid, False)

    alt_pressed = False
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        alt_pressed = True
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception:  # noqa: BLE001
        pass
    finally:
        if alt_pressed:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)

    try:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOP,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
        win32gui.BringWindowToTop(hwnd)
    except Exception as exc:  # noqa: BLE001 - report, never crash
        raise DesktopError(f"could not raise window {hwnd}: {exc}", code="focus_failed") from exc


def focus_window(hwnd: int) -> AppWindow:
    """Restore (if minimised) and raise a window to the front.

    The result reports ``focused`` — whether it genuinely became the
    *foreground* window. Input tools check that flag and refuse to type when
    it is false, because keystrokes would land in whatever window is really
    in front.
    """
    require_windows()
    import win32con
    import win32gui

    if not win32gui.IsWindow(hwnd):
        raise DesktopError(f"window {hwnd} no longer exists", code="not_found")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    _attempt_foreground(hwnd)

    deadline = time.monotonic() + FOCUS_POLL_S
    foreground = False
    while time.monotonic() < deadline:
        try:
            foreground = win32gui.GetForegroundWindow() == hwnd
        except Exception:  # noqa: BLE001
            break
        if foreground:
            break
        time.sleep(0.05)

    title = (win32gui.GetWindowText(hwnd) or "").strip()
    pid = window_pid(hwnd)
    return AppWindow(
        hwnd=hwnd,
        title=title,
        process=_process_name(pid),
        pid=pid,
        focused=foreground,
    )
