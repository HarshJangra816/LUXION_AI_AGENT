"""Weather via Open-Meteo (PRD §37 "Weather", Phase 9).

Two free, keyless endpoints:

- geocoding — ``geocoding-api.open-meteo.com`` resolves a place name to a
  latitude/longitude (plus country/admin area, so the answer names the town it
  actually found, not just the query);
- forecast — ``api.open-meteo.com`` returns current conditions + a daily
  forecast for those coordinates.

Units follow ``WebConfig.temperature_unit`` / ``wind_unit``; WMO weather codes
are translated to plain descriptions so the model never has to guess what
``weather_code 95`` means.
"""

from __future__ import annotations

from typing import Any

from luxion.web.errors import WebError
from luxion.web.http import get_json

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_FIELDS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
    "precipitation,weather_code,wind_speed_10m,wind_direction_10m"
)
DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
    "precipitation_probability_max"
)

#: WMO 4677 weather interpretation codes → human wording.
WEATHER_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


#: Compass point for a wind direction in degrees.
def wind_direction_name(degrees: float) -> str:
    points = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = round((float(degrees) % 360) / 22.5) % 16
    return points[index]


async def geocode(place: str, *, count: int = 1, settings: Any = None) -> list[dict[str, Any]]:
    """Resolve ``place`` to candidate locations (best match first)."""
    data = await get_json(
        GEOCODE_URL,
        params={
            "name": place,
            "count": max(1, min(int(count), 10)),
            "language": "en",
            "format": "json",
        },
        settings=settings,
    )
    results = data.get("results") if isinstance(data, dict) else None
    return [row for row in results or [] if isinstance(row, dict)]


async def forecast(
    latitude: float,
    longitude: float,
    *,
    days: int = 3,
    temperature_unit: str = "celsius",
    wind_unit: str = "kmh",
    settings: Any = None,
) -> dict[str, Any]:
    """Fetch current conditions + a daily forecast for one coordinate pair."""
    data = await get_json(
        FORECAST_URL,
        params={
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "current": CURRENT_FIELDS,
            "daily": DAILY_FIELDS,
            "temperature_unit": temperature_unit,
            "wind_speed_unit": wind_unit,
            "timezone": "auto",
            "forecast_days": max(1, min(int(days), 16)),
        },
        settings=settings,
    )
    if not isinstance(data, dict) or "current" not in data:
        raise WebError("open-meteo returned an unexpected payload", source="open-meteo.com")
    return data


def describe(code: object) -> str:
    """Human wording for a WMO code (unknown codes fall back to the number)."""
    try:
        return WEATHER_CODES.get(int(code), f"weather code {code}")
    except (TypeError, ValueError):
        return f"weather code {code}"


def format_report(
    place: str,
    resolved: dict[str, Any],
    payload: dict[str, Any],
    *,
    temperature_unit: str = "celsius",
    wind_unit: str = "kmh",
) -> str:
    """Render one location's conditions as prompt-ready text."""
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    temp_symbol = "°F" if temperature_unit == "fahrenheit" else "°C"
    wind_symbol = "mph" if wind_unit == "mph" else "km/h"

    where = place
    region = ", ".join(str(resolved.get(key)) for key in ("admin1", "country") if resolved.get(key))
    if region:
        where = f"{resolved.get('name', place)} ({region})"

    lines = [
        f"Weather for {where} — {describe(current.get('weather_code'))}",
        (
            f"Now: {current.get('temperature_2m')}{temp_symbol} "
            f"(feels like {current.get('apparent_temperature')}{temp_symbol}), "
            f"humidity {current.get('relative_humidity_2m')}%, "
            f"wind {current.get('wind_speed_10m')}{wind_symbol} "
            f"{wind_direction_name(current.get('wind_direction_10m') or 0)}, "
            f"precipitation {current.get('precipitation')} mm"
        ),
    ]

    times = daily.get("time") or []
    for index, day in enumerate(times):
        if index >= 3:
            break
        high = (daily.get("temperature_2m_max") or [None] * 7)[index]
        low = (daily.get("temperature_2m_min") or [None] * 7)[index]
        code = (daily.get("weather_code") or [None] * 7)[index]
        pop = (daily.get("precipitation_probability_max") or [None] * 7)[index]
        parts = [f"  {day}: {describe(code)}, {low}/{high}{temp_symbol}"]
        if pop is not None:
            parts.append(f"{pop}% precip")
        lines.append(" ".join(parts))
    return "\n".join(lines)
