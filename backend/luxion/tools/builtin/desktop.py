"""Desktop automation tools (PRD §33.5, §39, §5.8, Phase 7).

Ten tools in four groups:

======================  ==========================================
application control     ``list_applications``, ``focus_application``
system control          ``list_processes``, ``control_volume``,
                        ``control_brightness``
UI Automation           ``inspect_window``, ``click_element``
input injection         ``press_keys``, ``type_text``, ``click_at``
======================  ==========================================

Risk follows §20: reading (listing, inspecting) is LOW and read-only,
changing system state (focus, volume, brightness, clicking a control) is
MEDIUM, and anything that types or clicks as *the user* is HIGH — which at
the default autonomy level means a confirmation prompt every time. The four
input tools additionally declare ``requires="input_control"`` so the
capability layer (§39) can hard-block them regardless of autonomy.
"""

from __future__ import annotations

import asyncio
from typing import Any

from luxion.desktop import controls as _controls
from luxion.desktop import input as _keys
from luxion.desktop import processes as _processes
from luxion.desktop import uia as _uia
from luxion.desktop import windows as _windows
from luxion.desktop.errors import DesktopError
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

#: ``list_applications`` never dumps more than this into a prompt.
MAX_APPLICATIONS = 50

#: Keys ``press_keys`` documents (the rest of the table lives in
#: :data:`luxion.desktop.input.NAMED_KEYS`).
NAMES_HINT = "enter, tab, esc, space, arrows, home/end, page up/down, delete, f1-f24, media keys"


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one desktop call, mapping :class:`DesktopError` → ``ToolError``."""
    try:
        return fn(*args, **kwargs)
    except DesktopError as exc:
        raise ToolError(str(exc), code=exc.code) from exc


def _require_enabled(ctx: ToolContext) -> None:
    if not ctx.settings.desktop.enabled:
        raise ToolError(
            "desktop automation is disabled — turn it on in Settings → Desktop",
            code="disabled",
        )


def _require_uia(ctx: ToolContext) -> None:
    if not ctx.settings.desktop.ui_automation:
        raise ToolError(
            "UI Automation is turned off in Settings → Desktop "
            "(only window focus and coordinate clicks are left)",
            code="disabled",
        )


def _require_coordinates(ctx: ToolContext) -> None:
    if not ctx.settings.desktop.coordinate_fallback:
        raise ToolError(
            "coordinate clicking is turned off in Settings → Desktop — "
            "use inspect_window + click_element instead",
            code="disabled",
        )


async def _focus(
    ctx: ToolContext,
    window: str | None,
    *,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Focus ``window`` (if given) and give it ``focus_delay_s`` to arrive.

    ``strict=True`` is for input injection: if Windows refuses to give the
    target the foreground, keystrokes would land in whatever window is really
    in front, so the tool aborts instead of typing into the wrong app.
    """
    if not window:
        return None
    target = await asyncio.to_thread(_call, _windows.find_window, window)
    focused = await asyncio.to_thread(_call, _windows.focus_window, target.hwnd)
    if strict and not focused.focused:
        raise ToolError(
            f"could not bring '{focused.title}' to the front — sending input now "
            "would land in the wrong window, so nothing was sent",
            code="focus_failed",
        )
    delay = ctx.settings.desktop.focus_delay_s
    if delay > 0:
        await asyncio.sleep(delay)
    return {
        "title": focused.title,
        "pid": focused.pid,
        "process": focused.process,
        "foreground": focused.focused,
    }


def _lines(rows: list[str], *, header: str, empty: str, limit: int = 12) -> str:
    if not rows:
        return empty
    body = "\n".join(rows[:limit])
    more = len(rows) - limit
    tail = f"\n... and {more} more" if more > 0 else ""
    return f"{header}\n{body}{tail}"


# ------------------------------------------------------------- applications
class ListApplications(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_applications",
            description=(
                "List the visible application windows right now (title, process, pid, "
                "which one is in front). Use before focus_application."
            ),
            risk="low",
            category="application",
            tags=[
                "applications",
                "apps",
                "windows",
                "running",
                "open",
                "foreground",
                "titles",
                "which",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional filter on title or process name.",
                    }
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        query = str(args.get("query") or "").strip()
        windows = await asyncio.to_thread(_call, _windows.enumerate_windows)
        hits = [w for w in windows if not query or _windows.matches(w, query)]
        hits = hits[:MAX_APPLICATIONS]
        rows = [
            f"{'> ' if w.focused else '  '}{w.title} — {w.process or 'unknown'} (pid {w.pid})"
            for w in hits
        ]
        return ToolResult(
            output=_lines(
                rows,
                header=f"{len(hits)} window(s):",
                empty="no visible windows with a title" + (f" match '{query}'" if query else ""),
            ),
            data={"windows": [w.as_dict() for w in hits], "total": len(windows)},
        )


class FocusApplication(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="focus_application",
            description=(
                "Bring an application window to the front (restores it if minimised) "
                "by a fragment of its title or process name. Do this before typing "
                "into another application."
            ),
            risk="medium",
            category="application",
            tags=["focus", "raise", "foreground", "switch", "activate", "bring", "front", "app"],
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Title fragment or process name, e.g. 'notepad'.",
                    }
                },
                "required": ["name"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        name = str(args["name"]).strip()
        if not name:
            raise ToolError("name must not be empty", code="invalid_arguments")
        target = await asyncio.to_thread(_call, _windows.find_window, name)
        focused = await asyncio.to_thread(_call, _windows.focus_window, target.hwnd)
        return ToolResult(
            output=(
                f"focused '{focused.title}' ({focused.process or 'unknown'}, pid {focused.pid})"
                + ("" if focused.focused else " — raised, but Windows kept another window in front")
            ),
            data=focused.as_dict(),
        )


# ---------------------------------------------------------------- processes
class ListProcesses(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_processes",
            description=(
                "List running processes with pid, CPU and memory use (sorted by CPU by default)."
            ),
            risk="low",
            category="system",
            tags=[
                "processes",
                "tasks",
                "running",
                "cpu",
                "memory",
                "pid",
                "background",
                "who",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "sort": {
                        "type": "string",
                        "enum": ["cpu", "memory", "name"],
                        "description": "Ordering (default cpu).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional filter on the process name.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        sort = str(args.get("sort") or "cpu")
        query = str(args.get("query") or "")
        limit = ctx.settings.desktop.max_processes
        report = await asyncio.to_thread(
            _call, _processes.top_processes, sort=sort, limit=limit, query=query
        )
        rows = [
            f"pid {row['pid']:>7}  {row['cpu_percent']:>5}% cpu  "
            f"{row['rss_mb']:>7} MB  {row['name']} ({row['status']})"
            for row in report["processes"]  # type: ignore[arg-type]
        ]
        return ToolResult(
            output=_lines(
                rows,
                header=f"{report['running']} processes running, top {len(rows)} by {sort}:",
                empty="no processes match that filter",
            ),
            data=report,
        )


# ------------------------------------------------------------- UI automation
class InspectWindow(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_window",
            description=(
                "Read another application's UI element tree (names, control types, "
                "automation ids, bounds) so you can click a control by name with "
                "click_element. Defaults to the window in front."
            ),
            risk="low",
            category="desktop",
            tags=[
                "inspect",
                "elements",
                "controls",
                "ui",
                "tree",
                "accessibility",
                "find",
                "buttons",
                "fields",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "window": {
                        "type": "string",
                        "description": "Title fragment or process name (default: focused window).",
                    }
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        _require_uia(ctx)
        window = str(args.get("window") or "").strip() or None
        report = await asyncio.to_thread(
            _call,
            _uia.describe_window,
            window,
            max_elements=ctx.settings.desktop.max_elements,
        )
        elements = report["elements"]  # type: ignore[assignment]
        rows = [
            f"{i:>3}. [{el['control_type'] or '?'}] {el['name'] or '(no name)'}"
            + (f"  id={el['automation_id']}" if el["automation_id"] else "")
            for i, el in enumerate(elements, start=1)  # type: ignore[union-attr]
        ]
        title = report["window"]["title"]  # type: ignore[index]
        output = _lines(
            rows,
            header=f"'{title}' exposes {len(elements)} control(s):",
            empty=f"'{title}' exposes no named controls",
        )
        if report.get("truncated"):
            output += (
                f"\n(truncated at {len(elements)} — ask for a narrower window if you need more)"
            )
        return ToolResult(output=output, data=report)


class ClickElement(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="click_element",
            description=(
                "Click a control inside an application window by its visible name, "
                "automation id or class name (e.g. 'Save', 'OK'). Uses the "
                "accessibility tree, not screen coordinates — run inspect_window "
                "first if you are unsure what is called what."
            ),
            risk="medium",
            category="desktop",
            tags=[
                "click",
                "press",
                "button",
                "element",
                "control",
                "ui",
                "select",
                "tap",
                "invoke",
            ],
            requires="input_control",
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Name, automation id or class name of the control.",
                    },
                    "window": {
                        "type": "string",
                        "description": "Title fragment or process name (default: focused window).",
                    },
                    "index": {
                        "type": "integer",
                        "description": "Which match to click when several match (default 0).",
                    },
                },
                "required": ["target"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        _require_uia(ctx)
        target = str(args["target"]).strip()
        if not target:
            raise ToolError("target must not be empty", code="invalid_arguments")
        window = str(args.get("window") or "").strip() or None
        index = int(args.get("index") or 0)
        await _focus(ctx, window)
        report = await asyncio.to_thread(
            _call, _uia.click_element, target, window=window, index=index
        )
        return ToolResult(
            output=(
                f"clicked '{report['clicked']}' ({report['control_type']}) "
                f"in '{report['window']}' via {report['method']}"
                + (
                    f" — {report['match_count']} controls matched, used match #{index + 1}"
                    if report["match_count"] > 1
                    else ""
                )
            ),
            data=report,
        )


# ------------------------------------------------------------ input injection
class PressKeys(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="press_keys",
            description=(
                "Send keyboard shortcuts to an application, e.g. 'ctrl+s', "
                "'alt+f4', 'ctrl+shift+s enter'. Several chords are separated by "
                f"spaces. Named keys: {NAMES_HINT}. This types as the user — "
                "only ever send what the user asked for."
            ),
            risk="high",
            category="desktop",
            tags=[
                "keys",
                "keyboard",
                "shortcut",
                "hotkey",
                "press",
                "combo",
                "ctrl",
                "alt",
                "typing",
            ],
            requires="input_control",
            parameters={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "string",
                        "description": "Chord(s), e.g. 'ctrl+s' or 'alt+tab ctrl+p'.",
                    },
                    "window": {
                        "type": "string",
                        "description": "Focus this window first (title fragment or process).",
                    },
                },
                "required": ["keys"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        keys = str(args.get("keys") or "").strip()
        if not keys:
            raise ToolError("keys must not be empty", code="invalid_arguments")
        window = str(args.get("window") or "").strip() or None
        await _focus(ctx, window, strict=True)
        report = await asyncio.to_thread(_call, _keys.press_keys, keys)
        sent = ", ".join(report["sent"])  # type: ignore[arg-type]
        return ToolResult(
            output=f"sent {report['count']} chord(s): {sent}"
            + (f" to '{window}'" if window else ""),
            data=report,
        )


class TypeText(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="type_text",
            description=(
                "Type literal text into whatever has focus (any script — it uses "
                "unicode key events). Newlines become Enter. Optional window "
                "focuses the target first. This types as the user: send only the "
                "text the user asked for."
            ),
            risk="high",
            category="desktop",
            tags=[
                "type",
                "write",
                "text",
                "input",
                "enter",
                "fill",
                "form",
                "paste",
                "characters",
            ],
            requires="input_control",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type."},
                    "window": {
                        "type": "string",
                        "description": "Focus this window first (title fragment or process).",
                    },
                    "press_enter": {
                        "type": "boolean",
                        "description": "Press Enter after typing (default false).",
                    },
                },
                "required": ["text"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        text = str(args.get("text") or "")
        if not text:
            raise ToolError("text must not be empty", code="invalid_arguments")
        window = str(args.get("window") or "").strip() or None
        await _focus(ctx, window, strict=True)
        report = await asyncio.to_thread(_call, _keys.type_text, text)
        entered = bool(args.get("press_enter"))
        if entered:
            await asyncio.to_thread(_call, _keys.press_keys, "enter")
        return ToolResult(
            output=(
                f"typed {report['characters']} character(s)"
                + (" and pressed Enter" if entered else "")
                + (f" into '{window}'" if window else " into the focused window")
                + (" (text was truncated)" if report.get("truncated") else "")
            ),
            data={**report, "window": window, "pressed_enter": entered},
        )


class ClickAt(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="click_at",
            description=(
                "Click at screen coordinates (x, y) — the fallback when an "
                "application exposes no UI Automation tree. Prefer "
                "inspect_window + click_element whenever they work."
            ),
            risk="high",
            category="desktop",
            tags=[
                "click",
                "mouse",
                "cursor",
                "coordinates",
                "point",
                "screen",
                "position",
                "tap",
            ],
            requires="input_control",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Screen X in pixels."},
                    "y": {"type": "integer", "description": "Screen Y in pixels."},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button (default left).",
                    },
                    "double": {
                        "type": "boolean",
                        "description": "Double-click instead of a single click.",
                    },
                },
                "required": ["x", "y"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        _require_coordinates(ctx)
        x, y = int(args["x"]), int(args["y"])
        button = str(args.get("button") or "left")
        double = bool(args.get("double"))
        report = await asyncio.to_thread(
            _call,
            _keys.click_at,
            x,
            y,
            button=button,
            double=double,  # type: ignore[arg-type]
        )
        return ToolResult(
            output=(
                f"{'double-' if double else ''}{button}-clicked at ({x}, {y}); "
                f"cursor is at {report['cursor']}"
            ),
            data=report,
        )


# ---------------------------------------------------------- system controls
class ControlVolume(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="control_volume",
            description=(
                "Read or change the system master volume: get, set (0-100), "
                "mute, unmute, toggle_mute."
            ),
            risk="medium",
            category="system",
            tags=[
                "volume",
                "sound",
                "audio",
                "loud",
                "quiet",
                "mute",
                "speakers",
                "level",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "mute", "unmute", "toggle_mute"],
                        "description": "What to do (default get).",
                    },
                    "value": {
                        "type": "number",
                        "description": "Volume 0-100 — required for action=set.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        action = str(args.get("action") or "get")
        value = args.get("value")
        report = await asyncio.to_thread(
            _call, _controls.control_volume, action, float(value) if value is not None else None
        )
        state = "muted" if report["muted"] else f"{report['percent']}%"
        if action == "get":
            output = f"volume {state} on {report['device']}"
        else:
            output = f"{action}: now {state} on {report['device']}"
        return ToolResult(output=output, data=report)


class ControlBrightness(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="control_brightness",
            description=(
                "Read or change the display brightness (0-100). Laptop panels only "
                "— external monitors usually have no software control."
            ),
            risk="medium",
            category="system",
            tags=[
                "brightness",
                "dim",
                "display",
                "screen",
                "backlight",
                "dark",
                "light",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set"],
                        "description": "What to do (default get).",
                    },
                    "value": {
                        "type": "integer",
                        "description": "Brightness 0-100 — required for action=set.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        action = str(args.get("action") or "get")
        value = args.get("value")
        report = await asyncio.to_thread(
            _call, _controls.control_brightness, action, int(value) if value is not None else None
        )
        return ToolResult(
            output=(
                f"display brightness is {report['percent']}%"
                if action == "get"
                else f"set display brightness to {report['percent']}%"
            ),
            data=report,
        )


BUILTIN_TOOLS: list[Tool] = [
    ListApplications(),
    FocusApplication(),
    ListProcesses(),
    InspectWindow(),
    ClickElement(),
    PressKeys(),
    TypeText(),
    ClickAt(),
    ControlVolume(),
    ControlBrightness(),
]
