"""Capabilities & consents (PRD §21, §39, §55).

``GET  /api/capabilities``          every capability with its live state
``POST /api/capabilities/{id}``     probe / grant / deny / reset /
                                    open_settings / connect / disconnect
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from luxion.api.schemas import CapabilityAction, CapabilityReport
from luxion.calendar.sources import CalendarError
from luxion.config.settings import get_settings
from luxion.security.capabilities import (
    CAPABILITIES,
    CapabilityStore,
    get_capabilities,
    open_os_settings,
)

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

_BY_ID = {cap.id: cap for cap in CAPABILITIES}


def _calendar_registry(store: CapabilityStore):
    from luxion.calendar.registry import get_calendar_registry

    return get_calendar_registry(store.settings)


def _connect(store: CapabilityStore, body: CapabilityAction) -> CapabilityReport:
    if not body.source:
        raise HTTPException(
            status_code=400, detail="source is required (local_ics | ics_subscription)"
        )
    try:
        _calendar_registry(store).add(body.source, target=body.target, label=body.label)
    except CalendarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.report()


def _disconnect(store: CapabilityStore, body: CapabilityAction) -> CapabilityReport:
    removed = _calendar_registry(store).remove(body.id)
    if body.id and removed == 0:
        raise HTTPException(status_code=404, detail="Calendar source not found")
    return store.report()


@router.get("", response_model=CapabilityReport)
def list_capabilities() -> CapabilityReport:
    """Every capability with its live state and available actions."""
    return get_capabilities(get_settings()).report()


@router.post("/{capability_id}", response_model=CapabilityReport)
def capability_action(capability_id: str, body: CapabilityAction) -> CapabilityReport:
    cap = _BY_ID.get(capability_id)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Unknown capability '{capability_id}'")
    if body.action not in cap.actions:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{body.action}' is not available for '{capability_id}' "
                f"(expects one of: {', '.join(cap.actions)})"
            ),
        )
    store = get_capabilities(get_settings())

    if body.action == "probe":
        return store.report()
    if body.action in ("grant", "deny", "reset"):
        state = {"grant": "granted", "deny": "denied", "reset": None}[body.action]
        store.set(capability_id, state)  # type: ignore[arg-type]
        return store.report()
    if body.action == "open_settings":
        if cap.os_settings is None or not open_os_settings(cap.os_settings):
            raise HTTPException(
                status_code=400,
                detail=f"Could not open Windows Settings for {cap.label} on this system",
            )
        return store.report()
    if body.action == "connect":
        return _connect(store, body)
    return _disconnect(store, body)
