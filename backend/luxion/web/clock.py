"""World clock (PRD §37 "Time", Phase 9).

Phase 3's ``get_time`` / ``get_date`` cover the *local* machine. This adds the
time-zone side: given a list of IANA zones (or common city names, mapped
through :data:`CITY_ALIASES`), it reports each place's current local time, UTC
offset and day/night.

Pure stdlib — ``zoneinfo`` plus the already-installed ``tzdata`` (Windows has
no system IANA database, which is exactly why ``tzdata`` is a dependency).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from luxion.web.errors import WebError

#: Convenience mapping so the model can say "Tokyo" instead of "Asia/Tokyo".
CITY_ALIASES: dict[str, str] = {
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "rome": "Europe/Rome",
    "moscow": "Europe/Moscow",
    "dubai": "Asia/Dubai",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong",
    "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "tokyo": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "new york": "America/New_York",
    "chicago": "America/Chicago",
    "denver": "America/Denver",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "toronto": "America/Toronto",
    "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "honolulu": "Pacific/Honolulu",
    "utc": "UTC",
}


def resolve_zone(name: str) -> str:
    """Map a city alias to its IANA zone, else pass the zone name through."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise WebError("timezone must not be empty", source="world clock")
    alias = CITY_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    return cleaned.replace(" ", "_") if " " in cleaned and "/" not in cleaned else cleaned


def zone_entry(name: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Current time facts for one zone (raises ``WebError`` when unknown)."""
    zone_name = resolve_zone(name)
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise WebError(
            f"unknown time zone {name!r} — use an IANA name like 'Asia/Tokyo'", source="world clock"
        ) from exc

    moment = (now or datetime.now(UTC)).astimezone(zone)
    offset = moment.utcoffset() or UTC.utcoffset(None)
    offset_h = (offset.total_seconds() / 3600) if offset else 0.0
    hour = moment.hour
    return {
        "query": name,
        "zone": zone_name,
        "local_time": moment.strftime("%Y-%m-%d %H:%M"),
        "weekday": moment.strftime("%A"),
        "utc_offset": f"{'+' if offset_h >= 0 else '-'}{abs(offset_h):g}h",
        "day_night": "day" if 6 <= hour < 18 else "night",
    }


async def world_clock(zones: list[str], *, settings: Any = None) -> list[dict[str, Any]]:
    """Resolve each requested zone (``settings`` accepted for API symmetry)."""
    del settings  # no network involved
    if not zones:
        raise WebError("provide at least one city or time zone", source="world clock")
    return [zone_entry(name) for name in zones[:12]]


def format_clock(entries: list[dict[str, Any]]) -> str:
    lines = ["World clock:"]
    for entry in entries:
        lines.append(
            f"- {entry['query']} → {entry['local_time']} {entry['weekday']} "
            f"(UTC{entry['utc_offset']}, {entry['day_night']})"
        )
    return "\n".join(lines)
