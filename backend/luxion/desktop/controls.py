"""System controls — master volume and display brightness (PRD §39, §33.10).

Volume goes through Core Audio (``pycaw``); brightness through the WMI
monitor class Windows exposes on laptops (an external desktop monitor simply
does not implement it, which is reported as a clean error, not a crash).
Everything runs on a worker thread, so the COM apartment is initialised and
released around each call.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager

from luxion.desktop.errors import DesktopError
from luxion.desktop.windows import require_windows

POWERSHELL_TIMEOUT_S = 30

_BRIGHTNESS_GET = (
    "Get-CimInstance -Namespace root/Wmi -ClassName WmiMonitorBrightness | "
    "Select-Object -ExpandProperty CurrentBrightness"
)
_BRIGHTNESS_SET = (
    "Get-CimInstance -Namespace root/Wmi -ClassName WmiMonitorBrightnessMethods | "
    "ForEach-Object { $_.WmiSetBrightness(0, {level}) | Out-Null }"
)


@contextmanager
def _com():
    """COM apartment for the duration of one call (pycaw needs it per thread)."""
    try:
        import comtypes
    except Exception as exc:  # noqa: BLE001 - dependency missing
        raise DesktopError(
            f"volume control is unavailable (comtypes not installed): {exc}",
            code="audio_unavailable",
        ) from exc
    comtypes.CoInitialize()
    try:
        yield
    finally:
        comtypes.CoUninitialize()


def _endpoint():
    """``(device name, IAudioEndpointVolume)`` for the default output."""
    try:
        from pycaw.pycaw import AudioUtilities
    except Exception as exc:  # noqa: BLE001 - dependency missing
        raise DesktopError(
            f"volume control is unavailable (pycaw not installed): {exc}",
            code="audio_unavailable",
        ) from exc
    speakers = AudioUtilities.GetSpeakers()
    if speakers is None:
        raise DesktopError("no audio output device found", code="audio_unavailable")
    return str(speakers.FriendlyName or "default output"), speakers.EndpointVolume


def volume_status() -> dict[str, object]:
    """Master volume (0-100), mute flag and the device name."""
    require_windows()
    with _com():
        try:
            name, endpoint = _endpoint()
            percent = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100, 1)
            muted = bool(endpoint.GetMute())
        except DesktopError:
            raise
        except Exception as exc:  # noqa: BLE001 - audio service hiccups
            raise DesktopError(
                f"could not read the system volume: {exc}", code="audio_failed"
            ) from exc
    return {"percent": percent, "muted": muted, "device": name}


def _write_volume(*, percent: float | None = None, muted: bool | None = None) -> dict[str, object]:
    with _com():
        try:
            _name, endpoint = _endpoint()
            if percent is not None:
                endpoint.SetMasterVolumeLevelScalar(
                    max(0.0, min(100.0, float(percent))) / 100.0, None
                )
            if muted is not None:
                endpoint.SetMute(1 if muted else 0, None)
        except DesktopError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DesktopError(
                f"could not change the system volume: {exc}", code="audio_failed"
            ) from exc
        try:
            name, endpoint_now = _endpoint()
            percent_now = round(float(endpoint_now.GetMasterVolumeLevelScalar()) * 100, 1)
            muted_now = bool(endpoint_now.GetMute())
        except Exception as exc:  # noqa: BLE001
            raise DesktopError(
                f"volume was changed but could not be verified: {exc}", code="audio_failed"
            ) from exc
    return {"percent": percent_now, "muted": muted_now, "device": name}


def set_volume(percent: float) -> dict[str, object]:
    """Set the master volume (clamped to 0-100) and report the result."""
    require_windows()
    return _write_volume(percent=percent)


def set_muted(muted: bool) -> dict[str, object]:
    """Mute or unmute the master output."""
    require_windows()
    return _write_volume(muted=muted)


def _run_powershell(script: str) -> str:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=POWERSHELL_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise DesktopError(
            "PowerShell is not available on this machine", code="no_powershell"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DesktopError("the brightness command timed out", code="brightness_failed") from exc
    if proc.returncode != 0:
        raise DesktopError(
            f"brightness control failed: {(proc.stderr or proc.stdout).strip()[:300]}",
            code="brightness_failed",
        )
    return proc.stdout.strip()


def brightness_status() -> int:
    """Current display brightness (0-100)."""
    require_windows()
    raw = _run_powershell(_BRIGHTNESS_GET)
    if not raw:
        raise DesktopError(
            "this display does not expose a brightness control "
            "(external monitors usually need their own buttons)",
            code="brightness_unsupported",
        )
    try:
        return int(raw.splitlines()[0].strip())
    except ValueError as exc:
        raise DesktopError(
            f"unexpected brightness reading: {raw[:60]}", code="brightness_failed"
        ) from exc


def set_brightness(level: int) -> int:
    """Set display brightness (0-100) and return the new reading."""
    require_windows()
    value = max(0, min(100, int(level)))
    _run_powershell(_BRIGHTNESS_SET.format(level=value))
    return brightness_status()


def control_volume(action: str, value: float | None = None) -> dict[str, object]:
    """Dispatcher for the ``control_volume`` tool (get/set/mute/unmute/toggle)."""
    if action == "get":
        return {"action": action, **volume_status()}
    if action == "set":
        if value is None:
            raise DesktopError("'set' needs a value between 0 and 100", code="invalid_value")
        return {"action": action, **set_volume(value)}
    if action == "mute":
        return {"action": action, **set_muted(True)}
    if action == "unmute":
        return {"action": action, **set_muted(False)}
    if action == "toggle_mute":
        current = bool(volume_status()["muted"])
        return {"action": action, **set_muted(not current)}
    raise DesktopError(f"unknown volume action '{action}'", code="invalid_action")


def control_brightness(action: str, value: int | None = None) -> dict[str, object]:
    """Dispatcher for the ``control_brightness`` tool (get/set)."""
    if action == "get":
        return {"action": action, "percent": brightness_status()}
    if action == "set":
        if value is None:
            raise DesktopError("'set' needs a value between 0 and 100", code="invalid_value")
        return {"action": action, "percent": set_brightness(value)}
    raise DesktopError(f"unknown brightness action '{action}'", code="invalid_action")
