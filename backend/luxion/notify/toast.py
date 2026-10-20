"""Desktop notifications (Phase 10, PRD §33 "Notifications").

Windows toast notifications raised through a **stdlib-only** PowerShell call
into the WinRT toast API — the user's confirmed choice, and in keeping with
the project's FOSS-first rule (no new Python dependencies, no BurntToast
module, no app registration required).

The script is handed to ``powershell.exe`` as ``-EncodedCommand`` (UTF-16LE
base64), which sidesteps every quoting hazard around user-supplied titles and
messages. ``powershell.exe`` (5.1) is used rather than ``pwsh`` because it is
present on every Windows 10/11 install and its WinRT projection is guaranteed.

Toast identity: WinRT requires an AppUserModelID that exists on the machine.
Luxion is not a packaged app, so the toast is raised under the AUMID of the
PowerShell shortcut every Windows install ships — the well-known trick that
works without registering anything. The visible title carries the configured
``app_name`` instead.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import subprocess
import threading
import time
from typing import Any

from luxion.config.settings import NotificationConfig, Settings

logger = logging.getLogger(__name__)

#: The AUMID of ``%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe`` —
#: present on every install, so the toast always has an identity to show under.
POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

#: Windows only honours ``short`` (~7 s) and ``long`` (~25 s) durations.
LONG_DURATION_THRESHOLD_S = 15


class ToastError(RuntimeError):
    """Toast could not be raised (PowerShell missing, WinRT refused, cooldown)."""


def _xml_escape(value: str) -> str:
    """Escape user text for the toast's XML payload."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_script(
    title: str,
    message: str,
    *,
    app_name: str = "Luxion",
    duration_s: int = 7,
    sound: bool = True,
) -> str:
    """The PowerShell source that raises one toast (pure function, unit-tested).

    The script is assembled from short pieces so no source line blows past the
    linter's limit; the emitted PowerShell stays one statement per line. Only
    the escaped title and message vary, and every user value lands inside a
    single-quoted PS string after XML escaping (which also neutralises the
    quote character itself).
    """
    duration = "long" if duration_s >= LONG_DURATION_THRESHOLD_S else "short"
    audio = (
        '<audio src="ms-winsoundevent:Notification.Default" />'
        if sound
        else '<audio silent="true" />'
    )
    label = _xml_escape(app_name or "Luxion")
    heading = _xml_escape(title)
    body = _xml_escape(message)

    type_toast = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType = WindowsRuntime]"
    )
    type_xml = (
        "[Windows.Data.Xml.Dom.XmlDocument, "
        "Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]"
    )
    template = (
        f'<toast duration="{duration}"><visual>'
        f'<binding template="ToastGeneric">'
        f"<text>{label}: {heading}</text><text>{body}</text>"
        f"</binding></visual>{audio}</toast>"
    )
    notifier = (
        "$notifier = [Windows.UI.Notifications.ToastNotificationManager]"
        f"::CreateToastNotifier('{POWERSHELL_AUMID}')"
    )
    return "\n".join(
        [
            f"{type_toast} | Out-Null",
            f"{type_xml} | Out-Null",
            f"$template = '{template}'",
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument",
            "$xml.LoadXml($template)",
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)",
            notifier,
            "$notifier.Show($toast)",
        ]
    )


def encode_script(script: str) -> str:
    """UTF-16LE base64 for ``powershell -EncodedCommand`` (no BOM, no quoting)."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def run_script(script: str, *, timeout_s: float = 15.0) -> None:
    """Execute one PowerShell script synchronously. Test seam for the tools.

    Raises :class:`ToastError` with the subprocess' stderr folded in — a
    WinRT refusal (blocked notifications, weird policy) must reach the model
    as a clear message, not a silent no-op.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable, encoded script
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encode_script(script),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToastError("powershell.exe not found — toast notifications need Windows") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToastError(f"the toast script timed out after {timeout_s:.0f}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ToastError(
            f"Windows refused the toast (exit {completed.returncode})"
            + (f": {detail}" if detail else "")
        )


# ------------------------------------------------------------------- cooldown
_cooldown_lock = threading.Lock()
_last_toast_at: float = 0.0


def _check_cooldown(config: NotificationConfig) -> None:
    """Reject a toast that would land right on top of the previous one."""
    global _last_toast_at
    with _cooldown_lock:
        elapsed = time.monotonic() - _last_toast_at
        if _last_toast_at and elapsed < config.cooldown_s:
            raise ToastError(
                f"another notification was shown {elapsed:.1f}s ago — "
                f"the cooldown is {config.cooldown_s:.0f}s "
                "(Settings -> Integrations -> Notifications)"
            )


def _mark_shown() -> None:
    global _last_toast_at
    with _cooldown_lock:
        _last_toast_at = time.monotonic()


def reset_cooldown() -> None:
    """Test seam: forget when the last toast fired."""
    global _last_toast_at
    with _cooldown_lock:
        _last_toast_at = 0.0


# ---------------------------------------------------------------------- send
async def send_toast(
    title: str,
    message: str,
    *,
    settings: Settings,
    duration_s: int | None = None,
) -> dict[str, Any]:
    """Raise one desktop toast. Returns ``{"shown": True, ...}`` or raises.

    The cooldown is checked *before* the (slow) PowerShell call and the clock
    is only marked once the toast actually showed, so a failed send never
    blocks the next attempt.
    """
    config = settings.notify
    if not config.enabled:
        raise ToastError(
            "notifications are disabled — enable them in Settings → Integrations → Notifications"
        )
    title = (title or "").strip()
    message = (message or "").strip()
    if not title and not message:
        raise ToastError("a notification needs at least a title or a message")

    _check_cooldown(config)
    script = build_script(
        title or config.app_name,
        message or title,
        app_name=config.app_name,
        duration_s=duration_s if duration_s is not None else config.default_duration_s,
        sound=config.sound,
    )
    await asyncio.to_thread(run_script, script)
    _mark_shown()
    logger.info("toast_shown", extra={"title": title, "chars": len(message)})
    return {
        "shown": True,
        "title": title or config.app_name,
        "duration_s": duration_s if duration_s is not None else config.default_duration_s,
    }
