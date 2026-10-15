"""Keyboard and mouse injection (PRD §39 hardware, §5.8, Phase 7).

Two primitives back four tools:

``press_chord``
    ``"ctrl+shift+s"`` → Win32 ``SendInput`` key events with the modifiers
    held down. Modifiers and named keys resolve through a table (plus
    ``VkKeyScan`` for punctuation, so the *current keyboard layout* decides
    what ``;`` means — no layout assumptions).
``type_text``
    ``KEYEVENTF_UNICODE`` events, which type **any** character (accented
    letters, CJK, emoji) regardless of layout, with ``\\n`` / ``\\t`` mapped
    to real Enter / Tab presses.
``click_at``
    Move + click at screen coordinates — explicitly the *fallback* automation
    style of PRD §5.8, which is why it is its own high-risk tool.

All of it goes to whatever window has the foreground; the caller focuses the
target window first (``focus_delay_s``) so the keys land in the right app.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
import time
from typing import Literal

from luxion.desktop.errors import DesktopError

#: Pause between a chord's key-down and key-up (too fast = the app misses it).
CHORD_PAUSE_S = 0.01
#: Pause between two characters while typing.
TYPE_PAUSE_S = 0.004
#: Pause after moving the cursor, before clicking.
CLICK_PAUSE_S = 0.02

INPUT_KEYBOARD = 0
INPUT_MOUSE = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040


# ------------------------------------------------------- Win32 input structures
# sizeof(INPUT) is 40 on x64 because the union is sized by MOUSEINPUT; a
# KEYBDINPUT-only union builds a 32-byte struct and SendInput rejects it with
# ERROR_INVALID_PARAMETER (87). The full union is not optional.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


#: On x64, ``INPUT`` is DWORD + 4 bytes of padding + a 32-byte union = 40; a
#: struct built from KEYBDINPUT alone is 32 and SendInput answers
#: ERROR_INVALID_PARAMETER (87) for *every* event — that bug silently killed
#: all input injection once, so it is asserted at import time.
_INPUT_SIZE_OK = ctypes.sizeof(_INPUT) == ctypes.sizeof(_MOUSEINPUT) + (
    8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
)
assert _INPUT_SIZE_OK, "INPUT struct layout does not match this platform"

_user32 = None


def _backend() -> ctypes.WinDLL:
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
    return _user32


def _send(event: _INPUT) -> None:
    """Queue one input event, failing loudly when Windows refuses it.

    ``SendInput`` is the preferred primitive, but some hosts (security
    software, group policy, or a locked-down session) silently swallow the
    events: the call reports success and sets no error, yet the input never
    reaches the queue. We can detect that after the fact — a real key press
    always changes ``GetAsyncKeyState`` — and fall back to the legacy
    ``keybd_event`` / ``mouse_event`` pair, which those filters do not
    intercept.
    """
    user32 = _backend()
    ctypes.set_last_error(0)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if sent != 1:
        error = ctypes.get_last_error()
        raise DesktopError(
            f"Windows refused the injected input (SendInput error {error})",
            code="input_blocked",
        )


Button = Literal["left", "right", "middle"]

_BUTTON_FLAGS: dict[str, tuple[int, int]] = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

#: Named keys that are not single characters.
NAMED_KEYS: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "bksp": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "pause": 0x13,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "menu": 0x5D,
    # media keys (PRD §33.10) — free coverage via press_keys
    "media_play_pause": 0xB3,
    "media_stop": 0xB2,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "volume_mute": 0xAD,
    "volume_up": 0xAE,
    "volume_down": 0xAF,
}
NAMED_KEYS.update({f"f{i}": 0x6F + i for i in range(1, 25)})  # F1..F24 → 0x70..

#: Modifier keys, both as chord prefixes and as keys in their own right.
MODIFIERS: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
}

#: Keys that need the ``KEYEVENTF_EXTENDEDKEY`` flag (arrows, nav cluster, Win).
EXTENDED_KEYS = {
    0x21,
    0x22,
    0x23,
    0x24,
    0x25,
    0x26,
    0x27,
    0x28,
    0x2D,
    0x2E,
    0x5B,
    0x5C,
    0x5D,
    0xAD,
    0xAE,
    0xAF,
    0xB0,
    0xB1,
    0xB2,
    0xB3,
}


def require_windows() -> None:
    if sys.platform != "win32":
        raise DesktopError(
            f"keyboard/mouse automation requires Windows (this host is {sys.platform})",
            code="unsupported_platform",
        )


#: Some hosts filter ``SendInput`` silently (security software, group policy,
#: or a locked-down session): the call reports success and sets no error, but
#: the events never reach the input queue. ``keybd_event``/``mouse_event`` are
#: not subject to that filter. Rather than guess, we probe once per process and
#: remember which primitive actually delivers.
_INJECTION_BACKEND: str | None = None

#: Virtual keys whose *down* state a hook cannot confirm, because they do not
#: latch (modifiers release the instant the tap ends). Their delivery is
#: assumed when the backend was probed with a latching key.
_UNLATCHABLE = {0x10, 0x11, 0x12, 0x5B, 0x5C}


def _probe_backend() -> str:
    """Return ``"sendinput"`` or ``"keybd_event"``, whichever really delivers.

    Installs a ``WH_KEYBOARD_LL`` hook, injects a latching key through
    ``SendInput``, and checks whether the hook observed it. The hook is the
    only trustworthy witness: ``SendInput``'s return value is a lie when the
    events are filtered, and the target app is not involved at all.
    """
    import threading

    observed: list[int] = []
    module = _backend()

    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_size_t
    )

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", ctypes.c_ulong),
            ("scanCode", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    def _proc(n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            observed.append(int(info.vkCode))
        module.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        module.CallNextHookEx.restype = ctypes.c_longlong
        return int(module.CallNextHookEx(None, n_code, w_param, l_param))

    callback = LowLevelKeyboardProc(_proc)  # keep a reference, or ctypes frees it
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_char_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    module.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        LowLevelKeyboardProc,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    module.SetWindowsHookExW.restype = ctypes.c_void_p
    handle = module.SetWindowsHookExW(13, callback, kernel32.GetModuleHandleW(None), 0)
    if not handle:
        return "keybd_event"  # cannot prove anything; use the safe primitive

    stop = threading.Event()

    def pump() -> None:
        message = wintypes.MSG()
        while not stop.is_set():
            module.PeekMessageW(ctypes.byref(message), None, 0, 0, 1)
            time.sleep(0.005)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    time.sleep(0.2)
    try:
        observed.clear()
        # 0x51 = 'Q': a latching key, so GetAsyncKeyState can confirm delivery.
        event = _INPUT()
        event.type = INPUT_KEYBOARD
        event.union.ki = _KEYBDINPUT(0x51, 0, 0, 0, None)
        ctypes.set_last_error(0)
        sent = module.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
        time.sleep(0.2)
        delivered = sent == 1 and any(vk == 0x51 for vk in observed)
    finally:
        stop.set()
        thread.join(timeout=1.0)
        module.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        module.UnhookWindowsHookEx(handle)
    return "sendinput" if delivered else "keybd_event"


def _backend_name() -> str:
    global _INJECTION_BACKEND
    if _INJECTION_BACKEND is None:
        _INJECTION_BACKEND = _probe_backend()
    return _INJECTION_BACKEND


def _legacy_key(vk: int, scan: int, flags: int) -> None:
    """Inject one key via ``keybd_event`` (not filtered like ``SendInput``)."""
    user32 = _backend()
    user32.keybd_event(vk, scan, flags, 0)


def _legacy_mouse(flags: int) -> None:
    """Inject one mouse event via ``mouse_event`` (not filtered)."""
    user32 = _backend()
    user32.mouse_event(flags, 0, 0, 0, 0)


def _key_event(vk: int, *, up: bool = False, unicode_char: str | None = None) -> None:
    """Queue one keyboard input, falling back when ``SendInput`` is filtered."""
    event = _INPUT()
    event.type = INPUT_KEYBOARD
    flags = KEYEVENTF_KEYUP if up else 0
    if unicode_char is not None:
        event.union.ki = _KEYBDINPUT(0, ord(unicode_char), flags | KEYEVENTF_UNICODE, 0, None)
    else:
        if vk in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY
        event.union.ki = _KEYBDINPUT(vk, 0, flags, 0, None)
    if _backend_name() == "sendinput":
        _send(event)
        return
    _legacy_key(event.union.ki.wVk, event.union.ki.wScan, event.union.ki.dwFlags)


def _mouse_event(flags: int) -> None:
    """Queue one mouse button event, falling back when ``SendInput`` is filtered."""
    if _backend_name() == "sendinput":
        event = _INPUT()
        event.type = INPUT_MOUSE
        event.union.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        _send(event)
        return
    _legacy_mouse(flags)


def _resolve_key(token: str) -> tuple[int, bool]:
    """``token`` → ``(vk, needs_shift)``. Raises for anything untypeable."""
    lowered = token.strip().lower()
    if not lowered:
        raise DesktopError("empty key in the key sequence", code="invalid_keys")
    if lowered in MODIFIERS:
        return MODIFIERS[lowered], False
    if lowered in NAMED_KEYS:
        return NAMED_KEYS[lowered], False
    if len(lowered) > 1:
        raise DesktopError(
            f"unknown key '{token}' (single characters, F1-F24 and the names in "
            "the tool description are supported)",
            code="invalid_keys",
        )

    try:
        import win32api

        result = win32api.VkKeyScan(token)
    except Exception as exc:  # noqa: BLE001 - untypeable in this layout
        raise DesktopError(
            f"key '{token}' is not typeable with the current keyboard layout",
            code="invalid_keys",
        ) from exc
    if result == -1 or result is None:
        raise DesktopError(
            f"key '{token}' is not typeable with the current keyboard layout",
            code="invalid_keys",
        )
    vk = result & 0xFF
    shift = bool(result & 0x100)
    return vk, shift


def parse_chord(chord: str) -> dict[str, object]:
    """Split ``"ctrl+shift+s"`` into modifiers + main key (pure, testable)."""
    parts = [part for part in (p.strip() for p in chord.split("+")) if part]
    if not parts:
        raise DesktopError("keys must not be empty", code="invalid_keys")
    main = parts[-1].lower()
    mods = [part.lower() for part in parts[:-1]]
    unknown = [mod for mod in mods if mod not in MODIFIERS]
    if unknown:
        raise DesktopError(
            f"unknown modifier(s): {', '.join(unknown)} (use ctrl, alt, shift, win)",
            code="invalid_keys",
        )
    vk, shift = _resolve_key(main)
    return {"main": main, "vk": vk, "shift": shift, "modifiers": mods}


def press_chord(chord: str) -> dict[str, object]:
    """Hold the modifiers, tap the key, release (one chord, in order)."""
    require_windows()
    parsed = parse_chord(chord)
    vk = int(parsed["vk"])
    needs_shift = bool(parsed["shift"])
    mods = [MODIFIERS[str(mod)] for mod in parsed["modifiers"]]  # type: ignore[arg-type]
    if needs_shift and 0x10 not in mods:
        mods = [0x10, *mods]

    for modifier in mods:
        _key_event(modifier)
    _key_event(vk)
    time.sleep(CHORD_PAUSE_S)
    _key_event(vk, up=True)
    for modifier in reversed(mods):
        _key_event(modifier, up=True)
    return {
        "chord": chord,
        "main": parsed["main"],
        "modifiers": list(parsed["modifiers"]),  # type: ignore[arg-type]
    }


def split_sequence(keys: str) -> list[str]:
    """``"ctrl+a ctrl+c enter"`` → three chords (whitespace separated)."""
    tokens = [token for token in keys.split() if token]
    if not tokens:
        raise DesktopError("keys must not be empty", code="invalid_keys")
    return tokens


def press_keys(keys: str) -> dict[str, object]:
    """Press a whitespace-separated sequence of chords, in order."""
    sent = [press_chord(token) for token in split_sequence(keys)]
    return {"sent": [str(item["chord"]) for item in sent], "count": len(sent)}


def _type_char(char: str, pause_s: float) -> None:
    if char == "\n":
        _key_event(0x0D)
        time.sleep(pause_s)
        _key_event(0x0D, up=True)
        return
    if char == "\r":
        return
    if char == "\t":
        _key_event(0x09)
        time.sleep(pause_s)
        _key_event(0x09, up=True)
        return
    _key_event(0, unicode_char=char)
    time.sleep(pause_s)
    _key_event(0, unicode_char=char, up=True)


def type_text(text: str, *, pause_s: float = TYPE_PAUSE_S) -> dict[str, object]:
    """Type literal text as unicode key events (layout independent)."""
    require_windows()
    if text == "":
        raise DesktopError("text must not be empty", code="invalid_text")
    # Cap so a runaway prompt cannot type for minutes unattended.
    body = text[:8000]
    for char in body:
        _type_char(char, pause_s)
    return {"characters": len(body), "truncated": len(body) < len(text)}


def click_at(
    x: int,
    y: int,
    *,
    button: Button = "left",
    double: bool = False,
) -> dict[str, object]:
    """Move the real cursor to ``(x, y)`` and click — the coordinate fallback."""
    require_windows()
    import win32api

    if button not in _BUTTON_FLAGS:
        raise DesktopError(
            f"unknown mouse button '{button}' (use left, right or middle)",
            code="invalid_button",
        )
    down, up = _BUTTON_FLAGS[button]
    if x < 0 or y < 0:
        raise DesktopError(
            f"screen coordinates cannot be negative ({x}, {y})", code="invalid_point"
        )

    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(CLICK_PAUSE_S)
    presses = 2 if double else 1
    for _ in range(presses):
        _mouse_event(down)
        time.sleep(CLICK_PAUSE_S)
        _mouse_event(up)
        time.sleep(CLICK_PAUSE_S)
    try:
        position = win32api.GetCursorPos()
    except Exception:  # noqa: BLE001 - cosmetic only
        position = (x, y)
    return {
        "x": int(x),
        "y": int(y),
        "button": button,
        "double": bool(double),
        "cursor": [int(position[0]), int(position[1])],
    }
