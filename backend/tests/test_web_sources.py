"""Web-intelligence source layer (PRD §37/§38, Phase 9) — offline.

Every network call is patched at the single :mod:`luxion.web.http` seam, so
these tests prove the parsing, formatting, indicator maths and provenance
stamping without touching the internet (and without flaking when a free feed
changes).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from luxion.web import clock, finance, movies, news, search, speed, weather
from luxion.web.errors import WebError
from luxion.web.provenance import iso_now, provenance_dict, stamp


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


# ------------------------------------------------------------------- provenance
def test_stamp_carries_source_and_a_zulu_timestamp() -> None:
    line = stamp("open-meteo.com", retrieved_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC))
    assert line == "[source: open-meteo.com, retrieved: 2026-10-19T12:00:00Z]"


def test_iso_now_is_utc_even_for_offset_input() -> None:
    assert iso_now(datetime(2026, 10, 19, 12, 0, tzinfo=UTC)).endswith("Z")
    assert provenance_dict("x")["kind"] == "current"


# ---------------------------------------------------------------------- search
def test_unwrap_resolves_the_ddg_redirect() -> None:
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert search.unwrap(wrapped) == "https://example.com/page"


def test_unwrap_passthrough_for_real_links() -> None:
    assert search.unwrap("https://example.com/x") == "https://example.com/x"
    assert search.unwrap("http://other.test") == "http://other.test"


def test_search_parses_results_and_snippets(monkeypatch) -> None:
    html = """
    <a rel="nofollow" class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fopen-meteo.com%2F">Open-Meteo</a>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Free weather <b>API</b>.</a>
    <a rel="nofollow" class="result__a" href="https://direct.test/y">Direct</a>
    <a class="result__snippet">Second snippet</a>
    """
    monkeypatch.setattr("luxion.web.search.get_text", _async(html))
    results = run(search.search("weather api", limit=5))
    assert results[0]["url"] == "https://open-meteo.com/"
    assert results[0]["title"] == "Open-Meteo"
    assert results[0]["snippet"] == "Free weather API."
    assert results[1]["url"] == "https://direct.test/y"


def _async(value):  # noqa: ANN201
    """An async function that ignores its args and resolves to ``value``."""

    async def _inner(*_args, **_kwargs):
        return value

    return _inner


# --------------------------------------------------------------------- weather
@pytest.mark.parametrize(
    ("code", "wording"), [(0, "clear sky"), (95, "thunderstorm"), (63, "moderate rain")]
)
def test_describe_maps_wmo_codes(code, wording) -> None:
    assert weather.describe(code) == wording


def test_describe_unknown_code_falls_back_to_the_number() -> None:
    assert weather.describe(1234) == "weather code 1234"
    assert weather.describe(None) == "weather code None"


def test_wind_direction_name() -> None:
    assert weather.wind_direction_name(0) == "N"
    assert weather.wind_direction_name(90) == "E"
    assert weather.wind_direction_name(183) == "S"
    assert weather.wind_direction_name(350) == "N"


def test_geocode_and_forecast_use_the_patched_seam(monkeypatch) -> None:
    geocode_payload = {
        "results": [
            {
                "name": "London",
                "latitude": 51.5,
                "longitude": -0.12,
                "country": "United Kingdom",
                "admin1": "England",
            }
        ]
    }
    forecast_payload = {
        "current": {
            "temperature_2m": 12.0,
            "weather_code": 3,
            "apparent_temperature": 11.0,
            "relative_humidity_2m": 80,
            "precipitation": 0,
            "wind_speed_10m": 10,
            "wind_direction_10m": 90,
        },
        "daily": {
            "time": ["2026-10-19"],
            "temperature_2m_max": [14.0],
            "temperature_2m_min": [8.0],
            "weather_code": [3],
            "precipitation_probability_max": [40],
        },
    }

    async def fake(url, **_kwargs):
        if "geocoding" in url:
            return geocode_payload
        return forecast_payload

    monkeypatch.setattr("luxion.web.weather.get_json", fake)
    matches = run(weather.geocode("London"))
    assert matches[0]["name"] == "London"
    payload = run(weather.forecast(51.5, -0.12, days=3))
    assert payload["current"]["temperature_2m"] == 12.0


def test_format_report_names_the_town_and_renders_days() -> None:
    resolved = {"name": "London", "admin1": "England", "country": "United Kingdom"}
    payload = {
        "current": {
            "temperature_2m": 12.0,
            "weather_code": 3,
            "apparent_temperature": 11.0,
            "relative_humidity_2m": 80,
            "precipitation": 0,
            "wind_speed_10m": 10,
            "wind_direction_10m": 90,
        },
        "daily": {
            "time": ["2026-10-19", "2026-10-20"],
            "temperature_2m_max": [14.0, 15.0],
            "temperature_2m_min": [8.0, 9.0],
            "weather_code": [3, 1],
            "precipitation_probability_max": [40, 10],
        },
    }
    text = weather.format_report(
        "London", resolved, payload, temperature_unit="celsius", wind_unit="kmh"
    )
    assert "London (England, United Kingdom)" in text
    assert "overcast" in text
    assert "2026-10-19" in text and "8.0/14.0°C" in text


# ------------------------------------------------------------------------ news
def test_parse_date_handles_rfc822_and_iso() -> None:
    assert news.parse_date("Mon, 19 Oct 2026 12:00:00 GMT") == datetime(
        2026, 10, 19, 12, 0, tzinfo=UTC
    )
    assert news.parse_date("2026-10-19T12:00:00Z") == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert news.parse_date("not a date") is None


def test_parse_feed_rss_and_atom() -> None:
    rss = """<rss><channel>
      <item><title>RSS headline</title><link>https://a.test/1</link>
        <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate>
        <description>Body &amp; more</description></item>
    </channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom headline</title>
        <link href="https://b.test/2" rel="alternate"/>
        <published>2026-10-19T10:00:00Z</published></entry>
    </feed>"""
    rss_items = news.parse_feed(rss, outlet="BBC")
    atom_items = news.parse_feed(atom, outlet="Verge")
    assert rss_items[0]["title"] == "RSS headline"
    assert rss_items[0]["url"] == "https://a.test/1"
    assert rss_items[0]["summary"] == "Body & more"
    assert atom_items[0]["url"] == "https://b.test/2"
    assert atom_items[0]["published_at"] == datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


def test_parse_feed_rejects_invalid_xml() -> None:
    with pytest.raises(WebError):
        news.parse_feed("<not-valid", outlet="Junk")


def test_dedupe_drops_the_same_story_by_url_or_by_title() -> None:
    articles = [
        # same story, same link (the BBC's own double-listed headline)
        {"title": "Uefa deadline", "outlet": "A", "url": "https://x/1"},
        {"title": "Uefa deadline", "outlet": "B", "url": "https://x/1"},
        # syndicated wire piece: different links, identical headline
        {"title": "Markets rally", "outlet": "C", "url": "https://x/2"},
        {"title": "Markets rally", "outlet": "D", "url": "https://x/3"},
        # genuinely distinct
        {"title": "Other news", "outlet": "E", "url": "https://x/4"},
    ]
    kept = news._dedupe(articles)
    assert [row["outlet"] for row in kept] == ["A", "C", "E"]


def test_format_headlines_orders_and_dates() -> None:
    articles = [
        {
            "title": "Newest",
            "outlet": "BBC",
            "published_at": datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
        },
        {
            "title": "Oldest",
            "outlet": "Guardian",
            "published_at": datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
            "points": 5,
            "comments": 2,
        },
    ]
    text = news.format_headlines("world", articles)
    assert "1. Newest — BBC (2026-10-19 12:00 UTC)" in text
    assert "5 points, 2 comments" in text


# ---------------------------------------------------------------------- movies
def test_year_and_home_rendering() -> None:
    assert movies._year({"premiered": "2019-01-01", "ended": "2022-01-01"}) == "2019–2022"
    assert movies._year({"premiered": "2020-01-01"}) == "2020–"
    assert movies._year({}) == "unknown year"
    assert (
        movies._home({"network": {"name": "HBO", "country": {"name": "United States"}}})
        == "HBO (United States)"
    )
    assert movies._home({"webChannel": {"name": "Netflix"}}) == "Netflix"


def test_lookup_resolves_and_embeds_episodes(monkeypatch) -> None:
    payload = {
        "id": 169,
        "name": "Breaking Bad",
        "premiered": "2008-01-20",
        "ended": "2013-09-29",
        "status": "Ended",
        "genres": ["Drama", "Crime"],
        "rating": {"average": 9.2},
        "network": {"name": "AMC"},
        "summary": "<p>A <b>chemistry</b> teacher.</p>",
        "_embedded": {
            "episodes": [{"season": 1, "number": 1, "name": "Pilot", "airdate": "2008-01-20"}]
        },
    }
    monkeypatch.setattr("luxion.web.movies.get_json", _async(payload))
    show = run(movies.lookup("breaking bad"))
    assert show["name"] == "Breaking Bad"
    assert show["rating"] == 9.2
    assert show["summary"] == "A chemistry teacher."
    assert show["episode_count"] == 1
    assert show["latest_episode"]["name"] == "Pilot"


def test_lookup_by_bad_id_refuses_before_fetching() -> None:
    with pytest.raises(WebError):
        run(movies.lookup("id:not-a-number"))


# --------------------------------------------------------------------- finance
def test_normalize_symbol_cleans_and_refuses_junk() -> None:
    assert finance.normalize_symbol("  aapl  ") == "aapl"
    assert finance.normalize_symbol("aapl.us") == "aapl.us"
    assert finance.normalize_symbol("^spx") == "^spx"
    with pytest.raises(WebError):
        finance.normalize_symbol("   ")
    with pytest.raises(WebError):
        finance.normalize_symbol("AAP L")


def _chart_body() -> str:
    """A minimal Yahoo v8 chart body: meta + three daily bars (last unclosed)."""
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "AAPL",
                            "currency": "USD",
                            "fullExchangeName": "NasdaqGS",
                            "shortName": "Apple Inc.",
                            "regularMarketPrice": 253.8,
                            "regularMarketVolume": 12345678,
                            "regularMarketDayHigh": 255.5,
                            "regularMarketDayLow": 252.1,
                            "chartPreviousClose": 250.0,
                            "fulldayChangePercent": -0.5,
                            "fiftyTwoWeekHigh": 260.0,
                            "fiftyTwoWeekLow": 180.0,
                            "regularMarketTime": 1792425089,
                        },
                        "timestamp": [1, 2, 3],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [250.0, 251.0, 254.0],
                                    "high": [252.0, 253.0, 255.5],
                                    "low": [249.0, 250.0, 252.1],
                                    "close": [251.0, 252.0, None],
                                    "volume": [10, 20, 12345678],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    )


def test_parse_chart_reads_meta_and_the_last_closed_bar() -> None:
    chart = finance.parse_chart(_chart_body())
    assert chart["meta"]["symbol"] == "AAPL"
    assert chart["closes"][-1] is None  # today's bar is still open
    # the last *closed* close wins over the open bar
    assert chart["last_bar"]["close"] == 252.0
    assert chart["last_bar"]["volume"] == 12345678


def test_parse_chart_rejects_bad_json_and_unknown_tickers() -> None:
    with pytest.raises(WebError, match="invalid JSON"):
        finance.parse_chart("{nope")
    with pytest.raises(WebError, match="no market data"):
        finance.parse_chart(json.dumps({"chart": {"result": [], "error": None}}))


def test_build_snapshot_prefers_meta_and_falls_back_to_the_bar() -> None:
    meta = json.loads(_chart_body())["chart"]["result"][0]["meta"]
    bar = {"close": 301.0, "volume": 999}
    snap = finance.build_snapshot(meta, bar)
    assert snap["price"] == 253.8
    assert snap["volume"] == 12345678  # meta beats the bar
    assert snap["high_52w"] == 260.0
    assert snap["change_pct"] == -0.5
    assert finance.build_snapshot({}, bar)["volume"] == 999  # bar fallback


def test_range_position_prefers_meta_52w_over_a_short_window() -> None:
    indicators: dict = {"last": 250.0}
    finance._range_position(indicators, {"high_52w": 260.0, "low_52w": 180.0, "price": 250.0})
    assert indicators["high_52w"] == 260.0
    assert indicators["pct_of_52w_range"] == 87.5


def test_compute_indicators_on_a_known_series() -> None:
    closes = [100.0] * 20 + [110.0] * 30  # flat then a step up
    ind = finance.compute_indicators(closes)
    assert ind["last"] == 110.0
    assert ind["sma_20"] == 110.0
    assert ind["high_52w"] == 110.0
    assert ind["low_52w"] == 100.0
    assert ind["pct_of_52w_range"] == 100.0
    assert ind["change_1d_pct"] == 0.0  # last two are both 110


def test_compute_indicators_empty_series() -> None:
    assert finance.compute_indicators([]) == {}


def test_read_trend_describes_above_or_below_the_50_day() -> None:
    assert "above its 50-day" in finance.read_trend({"last": 120, "sma_20": 118, "sma_50": 110})
    assert "below its 50-day" in finance.read_trend({"last": 90, "sma_50": 110})
    assert finance.read_trend({}) == "not enough history for a trend reading"


def test_format_quote_states_uncertainty_and_missing_fields() -> None:
    quote = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "currency": "USD",
        "exchange": "NASDAQ",
        "snapshot": {
            "price": 253.8,
            "volume": 12345678,
            "high_52w": 260.0,
            "low_52w": 180.0,
            "change_pct": -0.42,
        },
        "indicators": {
            "last": 253.8,
            "high_52w": 260.0,
            "low_52w": 180.0,
            "pct_of_52w_range": 92.0,
            "sma_50": 250.0,
        },
        "trend": "above its 50-day average",
        "available": {"market_cap": False, "financial_statements": False},
    }
    text = finance.format_quote(quote)
    assert "not a prediction" in text
    assert "Not available from the free feed: market_cap, financial_statements" in text
    assert "52-week range" in text
    assert "Last close: 253.80 USD" in text  # float noise rounded for display


def test_format_quote_rounds_float_noise_but_keeps_sub_dollar_precision() -> None:
    base = {"symbol": "X", "snapshot": {}, "available": {}, "trend": "flat"}
    noisy = finance.format_quote({**base, "indicators": {"last": 342.4599914550781}})
    assert "Last close: 342.46" in noisy
    penny = finance.format_quote({**base, "indicators": {"last": 0.0012345}})
    assert "Last close: 0.0012" in penny


# ----------------------------------------------------------------------- speed
def test_mbps_math() -> None:
    assert speed.mbps(1_250_000, 1.0) == 10.0  # 1.25 MB over 1s = 10 Mbps
    assert speed.mbps(100, 0) == 0.0


def test_colo_name_handles_string_and_dict_shapes() -> None:
    # Legacy payloads returned a bare IATA string; current /meta returns a dict.
    assert speed._colo_name("DEL") == "DEL"
    assert speed._colo_name({"iata": "DEL", "lat": 28.5, "city": "Delhi"}) == "DEL"
    assert speed._colo_name({"city": "Delhi"}) == "Delhi"
    assert speed._colo_name({}) == ""
    assert speed._colo_name(None) == ""


def test_connection_info_sends_speed_headers_and_normalises_colo(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _fake_get_json(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _async(
            {
                "asOrganization": "Test ISP",
                "clientIp": "1.2.3.4",
                "colo": {"iata": "DEL", "lat": 28.5, "city": "Delhi"},
                "city": "Delhi",
                "httpProtocol": "HTTP/3",
            }
        )()

    monkeypatch.setattr("luxion.web.speed.get_json", _fake_get_json)
    info = run(speed.connection_info())
    # Cloudflare 403s /meta without an Origin/Referer from speed.cloudflare.com.
    assert seen["headers"] == speed.SPEED_HEADERS
    assert info["colo"] == "DEL"
    assert info["isp"] == "Test ISP"


def test_speed_test_measures_download_and_skips_upload_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "luxion.web.speed.get_json",
        _async(
            {
                "asOrganization": "Test ISP",
                "clientIp": "1.2.3.4",
                "colo": "XYZ",
                "city": "Town",
                "country": "TC",
            }
        ),
    )
    monkeypatch.setattr("luxion.web.speed.get_bytes", _async(b"\0" * 1_250_000))
    monkeypatch.setattr(
        "luxion.web.speed.post_bytes", lambda *a, **k: pytest.fail("upload should be skipped")
    )
    result = run(speed.speed_test(download_bytes=1_250_000, upload_bytes=0))
    assert result["download_mbps"] > 0
    assert "upload_mbps" not in result
    assert result["isp"] == "Test ISP"


# ----------------------------------------------------------------------- clock
def test_resolve_zone_maps_cities_and_passthrough() -> None:
    assert clock.resolve_zone("Tokyo") == "Asia/Tokyo"
    assert clock.resolve_zone("new york") == "America/New_York"
    assert clock.resolve_zone("Europe/Paris") == "Europe/Paris"
    assert clock.resolve_zone("Asia/Tokyo") == "Asia/Tokyo"


def test_zone_entry_reports_time_offset_and_day_night() -> None:
    moment = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    tokyo = clock.zone_entry("Tokyo", now=moment)
    assert tokyo["zone"] == "Asia/Tokyo"
    assert tokyo["local_time"] == "2026-10-19 21:00"
    assert tokyo["utc_offset"] == "+9h"
    assert tokyo["day_night"] == "night"


def test_world_clock_rejects_unknown_zone_and_empty() -> None:
    with pytest.raises(WebError):
        run(clock.world_clock([]))
    with pytest.raises(WebError):
        run(clock.world_clock(["Not/AZone"]))


def test_get_json_maps_bad_json_to_web_error(monkeypatch) -> None:
    import luxion.web.http as http_mod

    monkeypatch.setattr(http_mod, "get_text", _async("{not json"))
    with pytest.raises(WebError):
        run(http_mod.get_json("https://x.test/"))
