"""Calendar sources: local .ics + read-only iCal subscriptions (PRD §54).

Credential-free by design so any calendar app participates: Google, Apple
and Outlook all publish a *secret iCal address* for subscription, and
Luxion owns a local ``.ics`` it can write to. OAuth-backed sources
(Google/Outlook) slot in later as new ``kind``s without touching the
registry or the capability layer.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel

SourceKind = Literal["local_ics", "ics_subscription"]


class CalendarError(Exception):
    """Expected source failure (bad URL, read-only write, malformed file)."""


class CalendarEvent(BaseModel):
    id: str
    title: str
    start: datetime
    #: For all-day events this is the **exclusive** end date (RFC 5545).
    end: datetime | None = None
    all_day: bool = False
    description: str = ""
    location: str = ""
    rrule: str = ""
    #: Id of the source the event came from.
    source: str = ""


class CalendarSourceInfo(BaseModel):
    id: str
    kind: SourceKind
    label: str
    target: str
    writable: bool


@runtime_checkable
class CalendarSource(Protocol):
    info: CalendarSourceInfo

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        *,
        all_day: bool = False,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent: ...


# ----------------------------------------------------------------- iCalendar
def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC  # type: ignore[return-value]


def _zone(tzid: str) -> tzinfo:
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return _local_tz()


_UNESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)


def _unescape(value: str) -> str:
    """Single pass — chained replaces are order-fragile (``\\\\n`` would
    otherwise lose the literal backslash before the ``n`` is handled)."""

    def _sub(match: re.Match[str]) -> str:
        char = match.group(1)
        return "\n" if char in ("n", "N") else char

    return _UNESCAPE_RE.sub(_sub, value)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def unfold(text: str) -> list[str]:
    """RFC 5545 §3.1 line unfolding (continuation lines start with a space)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _split_line(line: str) -> tuple[str, dict[str, str], str]:
    head, sep, value = line.partition(":")
    if not sep:
        return line.upper().strip(), {}, ""
    name, *parts = head.split(";")
    params: dict[str, str] = {}
    for part in parts:
        key, eq, val = part.partition("=")
        if eq:
            params[key.upper()] = val.strip('"')
    return name.upper().strip(), params, value


_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def _parse_duration(value: str) -> timedelta | None:
    match = _DURATION_RE.match(value.strip())
    if not match or not any(match.group(name) for name in ("days", "hours", "minutes", "seconds")):
        return None
    delta = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=int(match.group("seconds") or 0),
    )
    return -delta if match.group("sign") == "-" else delta


def _parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool] | None:
    """``(moment, all_day)`` — normalises every RFC 5545 date-time form to an
    aware datetime so filtering can compare zones safely."""
    value = value.strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
        if "T" in value:
            try:
                moment = datetime.strptime(value, "%Y%m%dT%H%M%S")
            except ValueError:
                moment = datetime.strptime(value, "%Y%m%dT%H%M")
            tzid = params.get("TZID")
            zone = _zone(tzid) if tzid else _local_tz()
            return moment.replace(tzinfo=zone), False
        if len(value) == 8:
            day = datetime.strptime(value, "%Y%m%d").date()
            return datetime.combine(day, time.min, tzinfo=_local_tz()), True
    except ValueError:
        return None
    return None


def _overlaps(event: CalendarEvent, start: datetime, end: datetime) -> bool:
    moment_end = event.end or event.start
    return event.start < end and moment_end > start


def parse_events(text: str, *, source: str = "") -> list[CalendarEvent]:
    """Minimal VEVENT reader: unfold → props → aware datetimes.

    Handles UID/SUMMARY/DTSTART/DTEND/DURATION/DESCRIPTION/LOCATION/RRULE in
    DATE, floating, UTC and TZID forms; unknown properties are ignored.
    """
    events: list[CalendarEvent] = []
    in_event = False
    props: dict[str, tuple[str, dict[str, str]]] = {}
    for line in unfold(text):
        marker = line.strip().upper()
        if marker == "BEGIN:VEVENT":
            in_event, props = True, {}
            continue
        if marker == "END:VEVENT":
            if in_event:
                event = _event_from_props(props, source)
                if event is not None:
                    events.append(event)
            in_event, props = False, {}
            continue
        if not in_event:
            continue
        name, params, value = _split_line(line)
        props[name] = (value, params)
    return events


def _event_from_props(
    props: dict[str, tuple[str, dict[str, str]]], source: str
) -> CalendarEvent | None:
    start_prop = props.get("DTSTART")
    if start_prop is None:
        return None
    parsed_start = _parse_dt(start_prop[0], start_prop[1])
    if parsed_start is None:
        return None
    start, all_day = parsed_start

    end: datetime | None = None
    if "DTEND" in props:
        parsed_end = _parse_dt(props["DTEND"][0], props["DTEND"][1])
        if parsed_end is not None:
            end = parsed_end[0]
    elif "DURATION" in props:
        delta = _parse_duration(props["DURATION"][0])
        if delta is not None:
            end = start + delta

    def value_of(name: str) -> str:
        prop = props.get(name)
        return prop[0] if prop else ""

    return CalendarEvent(
        id=value_of("UID") or uuid.uuid4().hex,
        title=_unescape(value_of("SUMMARY")) or "(untitled)",
        start=start,
        end=end,
        all_day=all_day,
        description=_unescape(value_of("DESCRIPTION")),
        location=_unescape(value_of("LOCATION")),
        rrule=value_of("RRULE").strip(),
        source=source,
    )


def _fmt_dt(moment: datetime, all_day: bool) -> str:
    if all_day:
        return moment.strftime("%Y%m%d")
    if moment.tzinfo is not None:
        return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return moment.strftime("%Y%m%dT%H%M%S")


def _fold(line: str) -> str:
    """RFC 5545 §3.1 content-line folding at 75 UTF-8 octets."""
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks: list[str] = []
    current = ""
    budget = 74  # continuation lines spend one octet on the leading space
    for char in line:
        if len((current + char).encode("utf-8")) > budget:
            chunks.append(current)
            current, budget = char, 74
        else:
            current += char
    chunks.append(current)
    return chunks[0] + "".join("\r\n " + chunk for chunk in chunks[1:])


def event_block(event: CalendarEvent) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.id}",
        f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART:{_fmt_dt(event.start, event.all_day)}",
    ]
    if event.end is not None:
        lines.append(f"DTEND:{_fmt_dt(event.end, event.all_day)}")
    lines.append(f"SUMMARY:{_escape(event.title)}")
    if event.description:
        lines.append(f"DESCRIPTION:{_escape(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{_escape(event.location)}")
    if event.rrule:
        lines.append(f"RRULE:{event.rrule}")
    lines.append("END:VEVENT")
    return lines


def serialize_document(events: Iterable[CalendarEvent]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Luxion//Calendar//EN",
        "CALSCALE:GREGORIAN",
    ]
    for event in events:
        lines.extend(event_block(event))
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


# ------------------------------------------------------------------- sources
class LocalIcsSource:
    """A file Luxion owns — the only read/write source in v1."""

    def __init__(self, info: CalendarSourceInfo) -> None:
        self.info = info

    @property
    def path(self) -> Path:
        return Path(self.info.target)

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise CalendarError(f"cannot read {self.path}: {exc}") from exc

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        events = parse_events(self._read(), source=self.info.id)
        return [event for event in events if _overlaps(event, start, end)]

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        *,
        all_day: bool = False,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        event = CalendarEvent(
            id=uuid.uuid4().hex,
            title=title,
            start=start,
            end=end,
            all_day=all_day,
            description=description,
            location=location,
            source=self.info.id,
        )
        text = self._read()
        block = "".join(_fold(line) + "\r\n" for line in event_block(event))
        upper = text.upper()
        if "BEGIN:VCALENDAR" in upper:
            index = upper.rfind("END:VCALENDAR")
            text = text[:index] + block + text[index:]
        else:
            text = serialize_document([event])
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            raise CalendarError(f"cannot write {self.path}: {exc}") from exc
        return event


class IcsSubscriptionSource:
    """Read-only feed (Google/Apple/Outlook secret iCal address)."""

    def __init__(self, info: CalendarSourceInfo) -> None:
        self.info = info

    def fetch(self) -> str:
        try:
            with httpx.Client(
                timeout=15.0, follow_redirects=True, headers={"User-Agent": "Luxion/0.1"}
            ) as client:
                response = client.get(self.info.target)
        except httpx.HTTPError as exc:
            raise CalendarError(f"could not fetch the calendar feed: {exc}") from exc
        if response.status_code >= 400:
            raise CalendarError(f"calendar server returned HTTP {response.status_code}")
        return response.text

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        events = parse_events(self.fetch(), source=self.info.id)
        return [event for event in events if _overlaps(event, start, end)]

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        *,
        all_day: bool = False,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        raise CalendarError(
            "this calendar is a read-only subscription — connect a local .ics file to write"
        )
