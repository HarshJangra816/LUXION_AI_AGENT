"""Capability & consent layer (PRD §21, §39, §55).

The permission engine (``luxion.tools.permissions``) answers "may the *model*
run this tool right now?". Capabilities answer the prior question — "is
Luxion allowed to use this hardware or feature *at all*?" A denied capability
blocks execution **regardless of autonomy level** (PRD §39: "Hardware access
must be permission-controlled"), so the executor checks it *before* the
engine.

Three kinds of truth:

``os``
    Windows privacy gates (microphone, camera, location). Probed **read-only**
    from ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\
    CapabilityAccessManager\\ConsentStore`` — Luxion never writes them; it
    only opens the Settings page for the user (PRD §55).
``app``
    In-app consents (speak aloud, screen capture, notifications) persisted in
    ``<data_dir>/capabilities.json``.
``account``
    Derived from connected integrations (calendar sources), never persisted
    here — the integration itself is the record.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from luxion.config.settings import Settings

logger = logging.getLogger(__name__)

CapabilityKind = Literal["os", "app", "account"]
CapabilityState = Literal["granted", "denied", "blocked_by_os", "unavailable", "not_connected"]
#: What the OS privacy gate reports. Luxion only ever *reads* this.
OsConsent = Literal["allow", "deny", "unknown"]

_ACTIONS: dict[CapabilityKind, tuple[str, ...]] = {
    "os": ("probe", "open_settings"),
    "app": ("probe", "grant", "deny", "reset"),
    "account": ("probe", "connect", "disconnect"),
}


class Capability:
    """Static description of one capability (PRD §39 hardware list)."""

    __slots__ = ("id", "label", "kind", "group", "description", "os_key", "os_settings", "default")

    def __init__(
        self,
        id: str,
        label: str,
        kind: CapabilityKind,
        group: str,
        description: str,
        *,
        os_key: str | None = None,
        os_settings: str | None = None,
        default: bool | None = None,
    ) -> None:
        self.id = id
        self.label = label
        self.kind = kind
        self.group = group
        self.description = description
        self.os_key = os_key
        self.os_settings = os_settings
        self.default = default

    @property
    def actions(self) -> tuple[str, ...]:
        return _ACTIONS[self.kind]

    def __repr__(self) -> str:
        return f"Capability({self.id!r}, kind={self.kind!r})"


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "microphone",
        "Microphone",
        "os",
        "Privacy",
        "Listen for voice input and the wake word.",
        os_key="microphone",
        os_settings="ms-settings:privacy-microphone",
    ),
    Capability(
        "camera",
        "Camera",
        "os",
        "Privacy",
        "See through the webcam for vision tasks.",
        os_key="webcam",
        os_settings="ms-settings:privacy-webcam",
    ),
    Capability(
        "location",
        "Location",
        "os",
        "Privacy",
        "Approximate location for weather and local answers.",
        os_key="location",
        os_settings="ms-settings:privacy-location",
    ),
    Capability(
        "speaker",
        "Speaker",
        "app",
        "Consent",
        "Let Luxion talk, announce results and answer aloud.",
        default=True,
    ),
    Capability(
        "screen_capture",
        "Screen capture",
        "app",
        "Consent",
        "Let tools capture what is on the screen.",
        default=True,
    ),
    Capability(
        "notifications",
        "Notifications",
        "app",
        "Consent",
        "Show desktop notifications on your behalf.",
        default=True,
    ),
    Capability(
        "calendar",
        "Calendar",
        "account",
        "Accounts",
        "Read and create events through a connected calendar source.",
    ),
)

_BY_ID: dict[str, Capability] = {cap.id: cap for cap in CAPABILITIES}


# ----------------------------------------------------------------- OS probing
def probe_os_consent(os_key: str) -> OsConsent:
    """Read a Windows privacy gate. Never writes it.

    The ``NonPackaged`` subkey gates classic desktop apps (which Luxion is);
    the top-level value is the packaged-app gate. Probe desktop first, fall
    back to packaged, and report ``unknown`` anywhere else (non-Windows, or a
    policy-managed key we cannot read).
    """
    try:
        import winreg  # noqa: PLC0415 - Windows-only import
    except ImportError:
        return "unknown"
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
    for sub in (os_key + r"\NonPackaged", os_key):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{base}\\{sub}") as key:
                value, _ = winreg.QueryValueEx(key, "Value")
        except OSError:
            continue
        if isinstance(value, str) and value.lower() in ("allow", "deny"):
            return "allow" if value.lower() == "allow" else "deny"
    return "unknown"


def open_os_settings(uri: str) -> bool:
    """Deep-link the Windows Settings page for a gate. Best-effort only."""
    if sys.platform != "win32":
        return False
    try:
        os.startfile(uri)  # type: ignore[attr-defined]  # Windows-only API
    except OSError:
        return False
    return True


# -------------------------------------------------------------------- reports
class CapabilityDecision(BaseModel):
    """One capability resolved to a state the executor can act on."""

    capability: str
    state: CapabilityState
    allowed: bool
    reason: str


class CapabilityInfo(BaseModel):
    """Settings-page view of one capability (PRD §32 Permissions)."""

    id: str
    label: str
    kind: CapabilityKind
    group: str
    description: str
    state: CapabilityState
    reason: str
    actions: list[str] = []
    #: ``kind="account"`` — the connected sources behind the state.
    sources: list[dict[str, Any]] = []


class CapabilityReport(BaseModel):
    capabilities: list[CapabilityInfo] = []


# --------------------------------------------------------------------- store
class CapabilityStore:
    """Resolves capability states; persists only the ``app``-kind consents."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.settings.app.data_dir / "capabilities.json"

    # storage -------------------------------------------------------------
    def _stored(self) -> dict[str, CapabilityState]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): value  # type: ignore[misc]
            for key, value in raw.items()
            if value in ("granted", "denied")
        }

    def set(self, capability_id: str, state: Literal["granted", "denied"] | None) -> None:
        """Persist an ``app``-kind consent (``None`` resets to the default)."""
        with self._lock:
            current = self._stored()
            if state is None:
                current.pop(capability_id, None)
            else:
                current[capability_id] = state
            if not current:
                if self.path.exists():
                    self.path.unlink()
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")

    # resolution -----------------------------------------------------------
    def check(self, capability_id: str) -> CapabilityDecision:
        cap = _BY_ID.get(capability_id)
        if cap is None:
            return CapabilityDecision(
                capability=capability_id,
                state="unavailable",
                allowed=False,
                reason=f"unknown capability '{capability_id}'",
            )
        state, reason = self._resolve(cap)
        return CapabilityDecision(
            capability=cap.id, state=state, allowed=state == "granted", reason=reason
        )

    def _resolve(self, cap: Capability) -> tuple[CapabilityState, str]:
        if cap.kind == "os":
            assert cap.os_key is not None
            consent = probe_os_consent(cap.os_key)
            if consent == "allow":
                return "granted", f"Windows allows Luxion to use the {cap.label.lower()}"
            if consent == "deny":
                return "blocked_by_os", f"{cap.label} is blocked in Windows privacy settings"
            return "unavailable", f"could not read the Windows {cap.label.lower()} setting"
        if cap.kind == "app":
            stored = self._stored().get(cap.id)
            if stored is None:
                stored = "granted" if cap.default else "denied"
            if stored == "granted":
                return "granted", f"you allow Luxion to use the {cap.label.lower()}"
            return "denied", f"you turned {cap.label} off in Luxion"
        return self._account_state(cap)

    def _account_state(self, cap: Capability) -> tuple[CapabilityState, str]:
        if cap.id == "calendar":
            from luxion.calendar.registry import get_calendar_registry  # noqa: PLC0415

            infos = get_calendar_registry(self.settings).list()
            if infos:
                labels = ", ".join(info.label for info in infos)
                return "granted", f"connected: {labels}"
            return "not_connected", "no calendar source connected yet"
        return "not_connected", f"{cap.label} is not connected"

    # views ----------------------------------------------------------------
    def report(self) -> CapabilityReport:
        from luxion.calendar.registry import get_calendar_registry  # noqa: PLC0415

        calendar_sources: list[dict[str, Any]] = []
        try:
            calendar_sources = [
                info.model_dump() for info in get_calendar_registry(self.settings).list()
            ]
        except OSError:
            logger.warning("calendar_sources_unreadable")
        infos: list[CapabilityInfo] = []
        for cap in CAPABILITIES:
            decision = self.check(cap.id)
            infos.append(
                CapabilityInfo(
                    id=cap.id,
                    label=cap.label,
                    kind=cap.kind,
                    group=cap.group,
                    description=cap.description,
                    state=decision.state,
                    reason=decision.reason,
                    actions=list(cap.actions),
                    sources=calendar_sources if cap.id == "calendar" else [],
                )
            )
        return CapabilityReport(capabilities=infos)


_store: CapabilityStore | None = None
_store_key: tuple | None = None


def get_capabilities(settings: Settings | None = None) -> CapabilityStore:
    global _store, _store_key
    from luxion.config.settings import get_settings

    resolved = settings or get_settings()
    key = (str(resolved.app.data_dir),)
    if _store is None or _store_key != key:
        _store = CapabilityStore(resolved)
        _store_key = key
    return _store


def reset_capabilities() -> None:
    global _store, _store_key
    _store = None
    _store_key = None
