"""Web-intelligence tools (PRD §37/§38, Phase 9) — hermetic.

The seven tools are exercised exactly as the agent loop would call them, with
every ``luxion.web`` source function monkeypatched so no HTTP leaves the box.
Proves: the enabled gate, the ``WebError`` → ``ToolError`` mapping, argument
validation, provenance stamping and the ``speed_enabled`` sub-gate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from luxion.config.settings import Settings
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.webintel import (
    CATEGORY,
    GetNews,
    GetWeather,
    InternetSpeed,
    MovieLookup,
    StockQuote,
    WebSearch,
    WorldClock,
)
from luxion.tools.registry import build_registry

WEB_TOOL_NAMES = {
    "web_search",
    "get_weather",
    "get_news",
    "movie_lookup",
    "stock_quote",
    "internet_speed",
    "world_clock",
}


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def _ctx(web: dict | None = None) -> ToolContext:
    settings = Settings(web=web or {})
    return ToolContext(settings)


def _async(value):  # noqa: ANN201
    """An async function that ignores its args and resolves to ``value``."""

    async def _inner(*_a, **_k):
        return value

    return _inner


# --------------------------------------------------------------------- registry
def test_all_seven_tools_registered_low_and_read_only() -> None:
    registry = build_registry(Settings())
    assert set(registry.names()) >= WEB_TOOL_NAMES
    for name in WEB_TOOL_NAMES:
        spec = registry.spec(name)
        assert spec.risk == "low", name
        assert spec.read_only is True, name
        assert spec.category == CATEGORY, name
        assert spec.requires is None, name  # no capability — public data


# --------------------------------------------------------------------- enabled gate
def test_every_tool_refuses_when_web_intelligence_is_disabled() -> None:
    ctx = _ctx({"enabled": False})
    cases = [
        (WebSearch(), {"query": "x"}),
        (GetWeather(), {"place": "London"}),
        (GetNews(), {}),
        (MovieLookup(), {"query": "x"}),
        (StockQuote(), {"symbol": "AAPL"}),
        (InternetSpeed(), {}),
        (WorldClock(), {"zones": ["Tokyo"]}),
    ]
    for tool, args in cases:
        with pytest.raises(ToolError, match="web intelligence is disabled"):
            run(tool.run(args, ctx))


# -------------------------------------------------------------------- web_search
def test_web_search_formats_results_with_provenance(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.search.search",
        _async(
            [
                {
                    "title": "Open-Meteo",
                    "url": "https://open-meteo.com",
                    "snippet": "Free weather API",
                }
            ]
        ),
    )
    result = run(WebSearch().run({"query": "weather api"}, _ctx()))
    assert result.ok
    assert "Open-Meteo" in result.output
    assert "https://open-meteo.com" in result.output
    assert "[source: duckduckgo.com" in result.output
    assert result.data["provenance"]["source"] == "duckduckgo.com"
    assert result.data["provenance"]["kind"] == "current"


def test_web_search_empty_results_is_an_honest_failure(monkeypatch) -> None:
    monkeypatch.setattr("luxion.web.search.search", _async([]))
    result = run(WebSearch().run({"query": "zzzz"}, _ctx()))
    assert result.ok is False
    assert result.error == "no results"


def test_web_search_blank_query_rejected() -> None:
    with pytest.raises(ToolError):
        run(WebSearch().run({"query": "   "}, _ctx()))


def test_web_search_maps_web_error_to_tool_error(monkeypatch) -> None:
    from luxion.web.errors import WebError

    async def boom(*_a, **_k):
        raise WebError("ddg down", source="duckduckgo.com")

    monkeypatch.setattr("luxion.web.search.search", boom)
    with pytest.raises(ToolError, match="ddg down"):
        run(WebSearch().run({"query": "x"}, _ctx()))


# ------------------------------------------------------------------- get_weather
def test_get_weather_resolves_place_and_formats(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.weather.geocode",
        _async(
            [
                {
                    "name": "London",
                    "latitude": 51.5,
                    "longitude": -0.12,
                    "country": "United Kingdom",
                    "admin1": "England",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "luxion.web.weather.forecast",
        _async({"current": {"temperature_2m": 12.0, "weather_code": 3}, "daily": {"time": []}}),
    )
    result = run(GetWeather().run({"place": "London"}, _ctx()))
    assert "London" in result.output
    assert result.data["latitude"] == 51.5


def test_get_weather_unknown_place_raises(monkeypatch) -> None:
    monkeypatch.setattr("luxion.web.weather.geocode", _async([]))
    with pytest.raises(ToolError, match="could not find a place"):
        run(GetWeather().run({"place": "Nowhereville"}, _ctx()))


# ---------------------------------------------------------------------- get_news
def test_get_news_formats_headlines(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.news.fetch_news",
        _async(
            [
                {
                    "title": "Big story",
                    "outlet": "BBC",
                    "published_at": datetime(2026, 10, 19, tzinfo=UTC),
                }
            ]
        ),
    )
    result = run(GetNews().run({"topic": "world"}, _ctx()))
    assert "Big story" in result.output
    assert result.data["topic"] == "world"


def test_get_news_defaults_topic_to_top(monkeypatch) -> None:
    seen = {}

    async def fake(topic="top", *, limit=8, settings=None):
        seen["topic"] = topic
        return []

    monkeypatch.setattr("luxion.web.news.fetch_news", fake)
    run(GetNews().run({}, _ctx()))
    assert seen["topic"] == "top"


# ------------------------------------------------------------------ movie_lookup
def test_movie_lookup_resolves_one_show(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.movies.lookup",
        _async(
            {
                "name": "Breaking Bad",
                "year": "2008–2013",
                "type": "Scripted",
                "status": "Ended",
                "home": "AMC",
                "genres": ["Drama"],
                "rating": 9.2,
            }
        ),
    )
    result = run(MovieLookup().run({"query": "breaking bad"}, _ctx()))
    assert "Breaking Bad" in result.output
    assert result.data["show"]["name"] == "Breaking Bad"


def test_movie_lookup_search_only_lists_candidates(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.movies.search_shows",
        _async([{"name": "Breaking Bad", "year": "2008–2013", "status": "Ended", "home": "AMC"}]),
    )
    result = run(MovieLookup().run({"query": "breaking", "search_only": True}, _ctx()))
    assert "match(es)" in result.output
    assert result.data["candidates"][0]["name"] == "Breaking Bad"


# -------------------------------------------------------------------- stock_quote
def test_stock_quote_formats_with_uncertainty(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.finance.fetch_quote",
        _async(
            {
                "symbol": "AAPL",
                "name": "Apple",
                "currency": "USD",
                "exchange": "NASDAQ",
                "snapshot": {
                    "price": 250.0,
                    "volume": 12345678,
                    "high_52w": 260.0,
                    "low_52w": 180.0,
                    "change_pct": -0.5,
                },
                "indicators": {"last": 250.0, "sma_50": 248.0},
                "trend": "flat",
                "available": {"market_cap": False},
            }
        ),
    )
    result = run(StockQuote().run({"symbol": "AAPL"}, _ctx()))
    assert "not a prediction" in result.output
    assert "[source: finance.yahoo.com" in result.output


def test_stock_quote_blank_symbol_rejected() -> None:
    with pytest.raises(ToolError):
        run(StockQuote().run({"symbol": " "}, _ctx()))


# --------------------------------------------------------------- internet_speed
def test_internet_speed_refuses_when_sub_gate_off(monkeypatch) -> None:
    with pytest.raises(ToolError, match="turned off"):
        run(InternetSpeed().run({}, _ctx({"speed_enabled": False})))


def test_internet_speed_runs_and_reports(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.speed.speed_test",
        _async(
            {
                "download_mbps": 100.0,
                "download_bytes": 1000,
                "download_seconds": 0.1,
                "isp": "Test ISP",
                "latency_ms": 12.0,
            }
        ),
    )
    result = run(InternetSpeed().run({}, _ctx()))
    assert "100.0 Mbps" in result.output
    assert "Test ISP" in result.output


# -------------------------------------------------------------------- world_clock
def test_world_clock_formats_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.clock.world_clock",
        _async(
            [
                {
                    "query": "Tokyo",
                    "zone": "Asia/Tokyo",
                    "local_time": "2026-10-19 21:00",
                    "weekday": "Monday",
                    "utc_offset": "+9h",
                    "day_night": "night",
                }
            ]
        ),
    )
    result = run(WorldClock().run({"zones": ["Tokyo"]}, _ctx()))
    assert "Tokyo" in result.output
    assert "+9h" in result.output


def test_world_clock_empty_zones_rejected() -> None:
    with pytest.raises(ToolError):
        run(WorldClock().run({"zones": []}, _ctx()))
