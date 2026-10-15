"""UI Automation — inspect and act on another app's controls (PRD §5.8, §33.5).

pywinauto's **UIA** backend is the first choice (accessibility tree, stable
names/automation ids); screen coordinates are only ever a fallback, and then
only through ``click_at`` (PRD §5.8: "Screen-coordinate automation should
only be a fallback").

The heavy import is lazy so a box without pywinauto still runs every other
tool, and every failure surfaces as a :class:`DesktopError` the model can
react to ("run inspect_window first").
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any

from luxion.desktop import windows as _windows
from luxion.desktop.errors import DesktopError

#: Elements returned by ``inspect_window`` when the config does not say more.
DEFAULT_MAX_ELEMENTS = 80


def available() -> bool:
    """True when UI Automation can be used on this host (never raises)."""
    if sys.platform != "win32":
        return False
    try:
        import pywinauto  # noqa: F401 - presence probe
    except Exception:  # noqa: BLE001 - any import failure means "unavailable"
        return False
    return True


def _require() -> None:
    _windows.require_windows()
    try:
        from pywinauto import Desktop  # noqa: F401 - presence probe
    except Exception as exc:  # noqa: BLE001 - missing dependency / broken COM
        raise DesktopError(
            f"UI Automation is unavailable on this machine: {exc}",
            code="uia_unavailable",
        ) from exc


def _desktop():
    import warnings

    from pywinauto import Desktop

    # pywinauto nags about COM threading when it is imported from a worker
    # thread; the UIA backend works fine in either mode.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return Desktop(backend="uia")


def resolve(window: str | None) -> Any:
    """Open window → pywinauto wrapper. ``None`` means the focused window."""
    _require()
    if window:
        target = _windows.find_window(window)
        wanted_hwnd, label = target.hwnd, target.title
    else:
        active = _windows.active_window()
        if active is None:
            raise DesktopError("no focused window with a title to act on", code="not_found")
        wanted_hwnd, label = active.hwnd, active.title

    try:
        for candidate in _desktop().windows(visible_only=True, title_re=".*"):
            if int(candidate.handle) == int(wanted_hwnd):
                return candidate
    except Exception as exc:  # noqa: BLE001 - COM/automation failures
        raise DesktopError(
            f"could not open the UI tree of '{label}': {exc}", code="uia_failed"
        ) from exc
    raise DesktopError(
        f"'{label}' has no accessible UI tree (run inspect_window to check)",
        code="not_found",
    )


def _describe(element: Any) -> dict[str, Any]:
    """One control row — only the fields that survive a round trip to the LLM."""
    try:
        rect = element.rectangle
        bounds = [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]
    except Exception:  # noqa: BLE001 - a stale element has no rectangle
        bounds = [0, 0, 0, 0]
    try:
        text = element.window_text() or ""
    except Exception:  # noqa: BLE001
        text = ""
    try:
        control_type = element.element_info.control_type or ""
    except Exception:  # noqa: BLE001
        control_type = ""
    try:
        automation_id = element.element_info.automation_id or ""
    except Exception:  # noqa: BLE001
        automation_id = ""
    try:
        enabled = bool(element.is_enabled())
    except Exception:  # noqa: BLE001
        enabled = True
    return {
        "name": text[:120],
        "control_type": control_type,
        "automation_id": automation_id,
        "class_name": element.class_name(),
        "enabled": enabled,
        "bounds": bounds,
    }


def describe_window(
    window: str | None = None,
    *,
    max_elements: int = DEFAULT_MAX_ELEMENTS,
) -> dict[str, Any]:
    """The first ``max_elements`` controls of a window, breadth-first.

    Truncation is reported rather than hidden — the model needs to know there
    is more of the tree before it claims a control does not exist.
    """
    root = resolve(window)
    meta = {
        "title": root.window_text(),
        "class_name": root.class_name(),
        "handle": int(root.handle),
    }
    elements: list[dict[str, Any]] = []
    truncated = False
    try:
        for element in root.iter_descendants():
            if len(elements) >= max_elements:
                truncated = True
                break
            elements.append(_describe(element))
    except Exception as exc:  # noqa: BLE001 - tree can die half-way (app closed)
        if not elements:
            raise DesktopError(
                f"could not read the controls of '{meta['title']}': {exc}",
                code="uia_failed",
            ) from exc
    return {"window": meta, "elements": elements, "truncated": truncated}


def _match_score(element: Any, target: str) -> int:
    """How well one control matches ``target`` (0 = not a match, higher = better).

    A long blob of text (a document's content) *contains* most short queries by
    coincidence, so oversized names never match a short needle — otherwise
    clicking ``"File"`` would happily click the whole file.
    """
    needle = target.strip().lower()
    if not needle:
        return 0
    try:
        name = (element.window_text() or "").strip()
        automation_id = (element.element_info.automation_id or "").strip()
        class_name = (element.class_name() or "").strip()
    except Exception:  # noqa: BLE001 - element vanished mid-scan
        return 0
    if len(name) > 120 and len(needle) < 40:
        return 0
    lowered_name, lowered_id, lowered_class = (
        name.lower(),
        automation_id.lower(),
        class_name.lower(),
    )
    if needle in (lowered_name, lowered_id, lowered_class):
        return 3
    if needle in lowered_id or needle in lowered_class:
        return 2
    if needle in lowered_name:
        return 1
    return 0


def find_elements(root: Any, target: str) -> list[Any]:
    """Controls in ``root`` matching ``target`` (name / id / class), best first."""
    scored: list[tuple[int, int, Any]] = []
    try:
        for order, element in enumerate(root.iter_descendants()):
            score = _match_score(element, target)
            if score:
                scored.append((score, order, element))
                if len(scored) >= 50:
                    break
    except Exception as exc:  # noqa: BLE001
        if not scored:
            raise DesktopError(
                f"could not search the window's controls: {exc}",
                code="uia_failed",
            ) from exc
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [element for _score, _order, element in scored[:25]]


def click_element(
    target: str,
    *,
    window: str | None = None,
    index: int = 0,
) -> dict[str, Any]:
    """Click one control.

    ``invoke()`` (UIA InvokePattern) is preferred — it does not move the
    cursor — and ``click_input()`` at the control's centre is the fallback
    for everything else. Both are driven by the accessibility tree, so there
    are no magic screen coordinates involved.
    """
    root = resolve(window)
    hits = find_elements(root, target)
    if not hits:
        raise DesktopError(
            f"no control matching '{target}' in '{root.window_text()}' — run inspect_window first",
            code="not_found",
        )
    position = index if 0 <= index < len(hits) else 0
    element = hits[position]
    label = element.window_text() or element.element_info.automation_id or target

    with contextlib.suppress(Exception):  # not focusable, fine
        element.set_focus()

    used = "invoke"
    try:
        element.invoke()
    except Exception:  # noqa: BLE001 - no InvokePattern (or not permitted)
        used = "click"
        try:
            element.click_input()
        except Exception as exc:  # noqa: BLE001
            raise DesktopError(
                f"could not click '{label}': {exc}",
                code="click_failed",
            ) from exc

    return {
        "clicked": label,
        "control_type": element.element_info.control_type,
        "method": used,
        "match_count": len(hits),
        "window": root.window_text(),
    }
