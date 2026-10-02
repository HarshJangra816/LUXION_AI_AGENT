"""Calendar integration (PRD §54 future feature, wired now at the source level)."""

from luxion.calendar.registry import (
    CalendarRegistry,
    get_calendar_registry,
    reset_calendar_registry,
)
from luxion.calendar.sources import (
    CalendarError,
    CalendarEvent,
    CalendarSource,
    CalendarSourceInfo,
    IcsSubscriptionSource,
    LocalIcsSource,
    SourceKind,
    parse_events,
    serialize_document,
)

__all__ = [
    "CalendarError",
    "CalendarEvent",
    "CalendarRegistry",
    "CalendarSource",
    "CalendarSourceInfo",
    "IcsSubscriptionSource",
    "LocalIcsSource",
    "SourceKind",
    "get_calendar_registry",
    "parse_events",
    "reset_calendar_registry",
    "serialize_document",
]
