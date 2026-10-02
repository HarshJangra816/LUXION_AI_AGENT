"""Phase 3.5: capability layer, executor gate, calendar sources (PRD §39, §55)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from luxion.calendar.registry import CalendarRegistry, reset_calendar_registry
from luxion.calendar.sources import (
    CalendarError,
    CalendarEvent,
    CalendarSourceInfo,
    IcsSubscriptionSource,
    LocalIcsSource,
    parse_events,
    serialize_document,
)
from luxion.config.settings import Settings, get_settings
from luxion.security.capabilities import (
    CAPABILITIES,
    CapabilityStore,
    get_capabilities,
    probe_os_consent,
    reset_capabilities,
)
from luxion.tools.executor import ToolExecutor
from luxion.tools.permissions import PermissionEngine
from luxion.tools.registry import build_registry

IDS = [cap.id for cap in CAPABILITIES]


@pytest.fixture(autouse=True)
def clean_stores():
    reset_capabilities()
    reset_calendar_registry()
    yield
    reset_capabilities()
    reset_calendar_registry()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(app={"data_dir": str(tmp_path)}, security={"autonomy_level": 5})


@pytest.fixture
def store(settings: Settings) -> CapabilityStore:
    return CapabilityStore(settings)


def _touch(settings: Settings, name: str = "capabilities.json") -> Path:
    path = settings.app.data_dir / name
    if path.exists():
        path.unlink()
    return path


# ------------------------------------------------------------------- registry
def test_registry_is_well_formed() -> None:
    assert len(IDS) == len(set(IDS)), "capability ids must be unique"
    assert IDS == [
        "microphone",
        "camera",
        "location",
        "speaker",
        "screen_capture",
        "notifications",
        "calendar",
    ]
    for cap in CAPABILITIES:
        assert cap.label and cap.description
        if cap.kind == "os":
            assert cap.os_key and cap.os_settings, cap.id
            assert cap.actions == ("probe", "open_settings")
        elif cap.kind == "app":
            assert cap.default is not None, cap.id
            assert cap.actions == ("probe", "grant", "deny", "reset")
        else:
            assert cap.actions == ("probe", "connect", "disconnect")


def test_os_probe_is_read_only_and_answers(tmp_path: Path) -> None:
    consent = probe_os_consent("microphone")
    assert consent in ("allow", "deny", "unknown")


def test_os_state_follows_the_probe(
    store: CapabilityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "allow")
    allowed = store.check("microphone")
    assert allowed.state == "granted" and allowed.allowed and allowed.reason

    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "deny")
    blocked = store.check("microphone")
    assert blocked.state == "blocked_by_os" and not blocked.allowed
    assert "Windows" in blocked.reason

    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "unknown")
    unknown = store.check("camera")
    assert unknown.state == "unavailable" and not unknown.allowed


# -------------------------------------------------------------- app consents
def test_app_consent_round_trip(store: CapabilityStore, settings: Settings) -> None:
    assert store.check("speaker").state == "granted"  # default ON (decision: toggle)
    store.set("speaker", "denied")
    assert store.check("speaker").state == "denied"
    assert store.check("speaker").allowed is False

    fresh = CapabilityStore(settings)  # re-reads the persisted file
    assert fresh.check("speaker").state == "denied"
    assert store.path.exists()

    store.set("speaker", None)  # reset → back to default
    assert store.check("speaker").state == "granted"
    assert not store.path.exists()


def test_corrupt_consent_file_falls_back_to_defaults(store: CapabilityStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.check("notifications").state == "granted"
    store.path.write_text('["nope"]', encoding="utf-8")
    assert store.check("notifications").state == "granted"


def test_unknown_capability_is_not_allowed(store: CapabilityStore) -> None:
    decision = store.check("does_not_exist")
    assert decision.allowed is False and decision.state == "unavailable"
    assert "unknown capability" in decision.reason


# ------------------------------------------------------------------ calendar
def test_calendar_state_follows_sources(store: CapabilityStore, settings: Settings) -> None:
    registry = CalendarRegistry(settings)
    assert store.check("calendar").state == "not_connected"

    registry.add("local_ics")
    granted = store.check("calendar")
    assert granted.state == "granted" and granted.allowed
    assert "connected" in granted.reason

    registry.remove()
    assert store.check("calendar").state == "not_connected"


def test_report_lists_every_capability(store: CapabilityStore) -> None:
    report = store.report()
    assert [info.id for info in report.capabilities] == IDS
    for info in report.capabilities:
        assert info.reason and info.label and info.actions
        assert info.state in (
            "granted",
            "denied",
            "blocked_by_os",
            "unavailable",
            "not_connected",
        )
    calendar = next(info for info in report.capabilities if info.id == "calendar")
    assert calendar.sources == []

    CalendarRegistry(store.settings).add("local_ics", label="Test cal")
    calendar = next(info for info in store.report().capabilities if info.id == "calendar")
    assert len(calendar.sources) == 1
    assert calendar.sources[0]["writable"] is True


# --------------------------------------------------------------- executor gate
def test_capability_blocks_even_at_autonomy_5(settings: Settings, store: CapabilityStore) -> None:
    store.set("screen_capture", "denied")
    executor = ToolExecutor(
        build_registry(settings), PermissionEngine(settings), settings, capabilities=store
    )
    prepared = executor.prepare("take_screenshot", {})
    assert prepared.status == "denied"
    assert prepared.decision.level == "deny"
    assert prepared.decision.source == "capability"
    assert prepared.decision.reason

    result = asyncio.run(executor.run(prepared))
    assert result.status == "denied"
    assert "capability" in (result.error or "")


def test_capability_allows_when_granted(settings: Settings, store: CapabilityStore) -> None:
    assert store.check("screen_capture").allowed is True  # default
    executor = ToolExecutor(
        build_registry(settings), PermissionEngine(settings), settings, capabilities=store
    )
    prepared = executor.prepare("take_screenshot", {})
    assert prepared.status is None
    assert prepared.decision.level == "allow"
    assert prepared.decision.source == "autonomy"


def test_only_screenshot_declares_a_capability(settings: Settings) -> None:
    declared = {
        spec.name: spec.requires
        for spec in build_registry(settings).specs()
        if spec.requires is not None
    }
    assert declared == {"take_screenshot": "screen_capture"}


# ------------------------------------------------------------------ iCalendar
def test_parse_events_handles_every_common_form() -> None:
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            "UID:utc-1",
            "SUMMARY:Team\\, sync",
            "DTSTART:20260115T100000Z",
            "DTEND:20260115T110000Z",
            "DESCRIPTION:Discuss the roadmap\\nnext steps",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:allday-1",
            "SUMMARY:Holiday",
            "DTSTART;VALUE=DATE:20260120",
            "DTEND;VALUE=DATE:20260121",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:tz-1",
            "SUMMARY:Standup",
            "DTSTART;TZID=Europe/Paris:20260116T090000",
            "DURATION:PT30M",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:fold-1",
            "SUMMARY:Folded",
            "DTSTART:20260117T080000Z",
            "DESCRIPTION:one two three four five six seven eight nine ten eleven twe",
            " lve thirteen fourteen",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    events = {event.id: event for event in parse_events(ics, source="sub")}
    assert set(events) == {"utc-1", "allday-1", "tz-1", "fold-1"}

    utc = events["utc-1"]
    assert utc.title == "Team, sync"
    assert utc.start.tzinfo is not None and utc.start.utcoffset() == timedelta(0)
    assert utc.description == "Discuss the roadmap\nnext steps"
    assert utc.source == "sub"

    holiday = events["allday-1"]
    assert holiday.all_day and holiday.end is not None
    assert (holiday.end - holiday.start) == timedelta(days=1)  # exclusive end

    standup = events["tz-1"]
    assert not standup.all_day
    assert standup.end is not None
    assert standup.end - standup.start == timedelta(minutes=30)  # DURATION

    folded = events["fold-1"]
    assert "thirteen fourteen" in folded.description


def test_local_ics_create_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "calendar.ics"
    source = LocalIcsSource(
        CalendarSourceInfo(
            id="local-1", kind="local_ics", label="Local", target=str(path), writable=True
        )
    )
    window_start = datetime(2026, 3, 1, tzinfo=UTC)
    window_end = datetime(2026, 3, 31, tzinfo=UTC)

    created = source.create_event(
        "Dentist",
        datetime(2026, 3, 10, 9, 30, tzinfo=UTC),
        datetime(2026, 3, 10, 10, 30, tzinfo=UTC),
        location="Clinic",
    )
    assert path.exists()
    assert "BEGIN:VCALENDAR" in path.read_text(encoding="utf-8")

    events = source.list_events(window_start, window_end)
    assert [event.id for event in events] == [created.id]
    assert events[0].title == "Dentist" and events[0].location == "Clinic"
    assert (
        source.list_events(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 30, tzinfo=UTC))
        == []
    )


def test_serialize_then_parse_survives_special_characters() -> None:
    event = CalendarEvent(
        id="esc-1",
        title="A;B,C\nD",
        start=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        description="back\\slash; semicolon",
    )
    events = parse_events(serialize_document([event]))
    assert len(events) == 1
    assert events[0].title == "A;B,C\nD"
    assert events[0].description == "back\\slash; semicolon"


def test_subscription_is_read_only() -> None:
    source = IcsSubscriptionSource(
        CalendarSourceInfo(
            id="sub-1",
            kind="ics_subscription",
            label="Google",
            target="https://example.invalid/ical",
            writable=False,
        )
    )
    with pytest.raises(CalendarError, match="read-only"):
        source.create_event("x", datetime.now(UTC))


# ------------------------------------------------------------------- registry
def test_calendar_registry_persistence_and_duplicates(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)})
    registry = CalendarRegistry(settings)
    target = tmp_path / "mine.ics"

    info = registry.add("local_ics", target=str(target), label="Mine")
    assert info.writable and registry.has_sources()
    assert [item.id for item in registry.list()] == [info.id]

    with pytest.raises(CalendarError, match="already connected"):
        registry.add("local_ics", target=str(target))

    assert registry.remove(info.id) == 1
    assert registry.remove(info.id) == 0  # already gone
    assert not registry.has_sources()
    assert not registry.path.exists()  # empty registry is unlinked


def test_subscription_validation_rejects_junk(tmp_path: Path) -> None:
    registry = CalendarRegistry(Settings(app={"data_dir": str(tmp_path)}))
    with pytest.raises(CalendarError, match="http"):
        registry.add("ics_subscription", target="not-a-url")
    with pytest.raises(CalendarError, match="unknown calendar source kind"):
        registry.add("google_oauth")


def test_local_ics_rejects_non_calendar_file(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("hello", encoding="utf-8")
    registry = CalendarRegistry(Settings(app={"data_dir": str(tmp_path)}))
    with pytest.raises(CalendarError, match="iCalendar"):
        registry.add("local_ics", target=str(junk))


def test_create_event_requires_a_writable_source(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)})
    registry = CalendarRegistry(settings)
    with pytest.raises(CalendarError, match="no writable"):
        registry.create_event("x", datetime.now(UTC))

    (tmp_path / "calendar_sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "sub-only",
                        "kind": "ics_subscription",
                        "label": "Read-only",
                        "target": "https://example.invalid/feed.ics",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fresh = CalendarRegistry(settings)
    assert fresh.has_sources() and fresh.writable_source() is None
    with pytest.raises(CalendarError, match="no writable"):
        fresh.create_event("x", datetime.now(UTC))


# ----------------------------------------------------------------------- API
def test_get_capabilities_endpoint(client) -> None:
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["capabilities"]] == IDS
    for item in body["capabilities"]:
        assert item["reason"] and item["actions"]


def test_grant_deny_reset_round_trip(client) -> None:
    path = _touch(get_settings())
    try:
        denied = client.post("/api/capabilities/speaker", json={"action": "deny"})
        assert denied.status_code == 200
        speaker = _speaker(denied.json())
        assert speaker["state"] == "denied"

        granted = client.post("/api/capabilities/speaker", json={"action": "grant"})
        assert _speaker(granted.json())["state"] == "granted"

        client.post("/api/capabilities/speaker", json={"action": "reset"})
        assert not path.exists()
    finally:
        if path.exists():
            path.unlink()


def test_unknown_capability_and_wrong_action(client) -> None:
    assert client.post("/api/capabilities/nope", json={"action": "probe"}).status_code == 404
    # os-kind capabilities are not grantable in-app
    response = client.post("/api/capabilities/microphone", json={"action": "grant"})
    assert response.status_code == 400
    assert "expects one of" in response.json()["detail"]


def test_calendar_connect_and_disconnect(client) -> None:
    path = get_settings().app.data_dir / "api-test-cal.ics"
    if path.exists():
        path.unlink()
    try:
        connected = client.post(
            "/api/capabilities/calendar",
            json={
                "action": "connect",
                "source": "local_ics",
                "target": str(path),
                "label": "API test",
            },
        )
        assert connected.status_code == 200
        calendar = next(
            item for item in connected.json()["capabilities"] if item["id"] == "calendar"
        )
        assert calendar["state"] == "granted"
        assert len(calendar["sources"]) == 1
        assert path.exists()

        duplicate = client.post(
            "/api/capabilities/calendar",
            json={"action": "connect", "source": "local_ics", "target": str(path)},
        )
        assert duplicate.status_code == 400

        missing = client.post("/api/capabilities/calendar", json={"action": "connect"})
        assert missing.status_code == 400

        disconnected = client.post("/api/capabilities/calendar", json={"action": "disconnect"})
        assert disconnected.status_code == 200
        calendar = next(
            item for item in disconnected.json()["capabilities"] if item["id"] == "calendar"
        )
        assert calendar["state"] == "not_connected"
    finally:
        if path.exists():
            path.unlink()


def _speaker(report: dict) -> dict:
    return next(item for item in report["capabilities"] if item["id"] == "speaker")


def test_tools_catalog_reports_capability_denial(client) -> None:
    path = _touch(get_settings())
    try:
        client.post("/api/capabilities/screen_capture", json={"action": "deny"})
        catalog = client.get("/api/tools").json()
        screenshot = next(t for t in catalog["tools"] if t["name"] == "take_screenshot")
        assert screenshot["permission"] == "deny"
        assert screenshot["requires"] == "screen_capture"
        assert "capability" in screenshot["permission_reason"]
    finally:
        client.post("/api/capabilities/screen_capture", json={"action": "reset"})
        if path.exists():
            path.unlink()


def test_get_capabilities_is_cached_singleton() -> None:
    assert get_capabilities() is get_capabilities()
