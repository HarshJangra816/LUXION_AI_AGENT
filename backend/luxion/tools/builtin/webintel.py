"""Web-intelligence tools (PRD §37, §38, Phase 9).

Seven read-only tools, every source **keyless** and reached through
:mod:`luxion.web`:

===============  ==================  =========================================
Tool             Source              PRD §37 line
===============  ==================  =========================================
``web_search``     DuckDuckGo HTML    Search
``get_weather``    Open-Meteo         Weather
``get_news``       RSS/Atom + HN      News
``movie_lookup``   TVMaze             Movies
``stock_quote``    Yahoo v8 chart    Finance
``internet_speed`` Cloudflare         Internet speed
``world_clock``    zoneinfo           Time (the local get_time stays in Phase 3)
===============  ==================  =========================================

All are ``risk: low`` + ``read_only`` and gated by the ``web.enabled`` master
switch (a config policy, not a capability — reading public web data needs no
consent). Every result is provenance-stamped (PRD §37) so the model can tell
live retrieval from its own training knowledge.
"""

from __future__ import annotations

from typing import Any

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.web import clock, finance, movies, news, search, speed, weather
from luxion.web.errors import WebError
from luxion.web.provenance import provenance_dict, stamp

SOURCE_LABELS = {
    "web_search": "duckduckgo.com",
    "get_weather": "open-meteo.com",
    "get_news": "news feeds",
    "movie_lookup": "tvmaze.com",
    "stock_quote": "finance.yahoo.com",
    "internet_speed": "speed.cloudflare.com",
    "world_clock": "system time zones",
}

#: Common category so the tool router and the system prompt can recognise the
#: family, and so provenance guidance is added exactly when these are exposed.
CATEGORY = "web_intel"

WEB_TOOLS: set[str] = set(SOURCE_LABELS)


def _require_enabled(ctx: ToolContext) -> None:
    if not ctx.settings.web.enabled:
        raise ToolError(
            "web intelligence is disabled — enable it in Settings → Web to use "
            "search, weather, news, movies, finance, speed and the world clock"
        )


async def _guard(ctx: ToolContext, source_key: str, fn, *args, **kwargs):
    """Run a ``luxion.web`` coroutine with the enabled gate + error mapping.

    Must be awaited (not a plain wrapper): the ``WebError`` surfaces when the
    coroutine runs, so the ``try`` has to span the ``await`` to convert it into
    the ``ToolError`` the executor expects.
    """
    _require_enabled(ctx)
    try:
        return await fn(*args, settings=ctx.settings, **kwargs)
    except WebError as exc:
        raise ToolError(f"{source_key} failed: {exc}") from exc


def _stamp_data(source_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "provenance": provenance_dict(SOURCE_LABELS[source_key])}


class WebSearch(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web (DuckDuckGo) and get current titles, URLs and snippets. "
                "Use for live facts, recent events or anything newer than your training data."
            ),
            risk="low",
            category=CATEGORY,
            tags=["search", "web", "internet", "google", "look up", "query", "current", "news"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "limit": {
                        "type": "integer",
                        "description": "How many results (default from settings).",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = str(args["query"]).strip()
        if not query:
            raise ToolError("query must not be empty")
        limit = int(args.get("limit") or ctx.settings.web.max_results)
        region = ctx.settings.web.search_region

        results = await _guard(ctx, "web_search", search.search, query, limit=limit, region=region)
        if not results:
            return ToolResult(
                ok=False,
                output=f"no web results for {query!r}",
                error="no results",
                data=_stamp_data("web_search", {"query": query, "results": []}),
            )
        lines = [
            f"{index}. {row['title']}\n   {row['url']}"
            + (f"\n   {row['snippet']}" if row.get("snippet") else "")
            for index, row in enumerate(results, 1)
        ]
        body = f"{len(results)} web result(s) for {query!r}:\n" + "\n".join(lines)
        return ToolResult(
            output=f"{body}\n{stamp(SOURCE_LABELS['web_search'])}",
            data=_stamp_data("web_search", {"query": query, "results": results}),
        )


class GetWeather(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_weather",
            description=(
                "Current weather and a short forecast for a city or place (Open-Meteo). "
                "Resolves the place to coordinates first, so it names the town it found."
            ),
            risk="low",
            category=CATEGORY,
            tags=["weather", "forecast", "temperature", "rain", "outside", "climate", "wind"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "place": {
                        "type": "string",
                        "description": "City or place name, e.g. 'London'.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Forecast days to include (default 3).",
                        "minimum": 1,
                        "maximum": 7,
                    },
                },
                "required": ["place"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        place = str(args["place"]).strip()
        if not place:
            raise ToolError("place must not be empty")
        days = int(args.get("days") or 3)
        cfg = ctx.settings.web

        matches = await _guard(ctx, "get_weather", weather.geocode, place, count=1)
        if not matches:
            raise ToolError(f"could not find a place called {place!r}")
        resolved = matches[0]
        payload = await _guard(
            ctx,
            "get_weather",
            weather.forecast,
            float(resolved["latitude"]),
            float(resolved["longitude"]),
            days=days,
            temperature_unit=cfg.temperature_unit,
            wind_unit=cfg.wind_unit,
        )
        body = weather.format_report(
            place,
            resolved,
            payload,
            temperature_unit=cfg.temperature_unit,
            wind_unit=cfg.wind_unit,
        )
        data = _stamp_data(
            "get_weather",
            {
                "place": resolved.get("name", place),
                "latitude": resolved.get("latitude"),
                "longitude": resolved.get("longitude"),
                "current": payload.get("current"),
                "daily": payload.get("daily"),
            },
        )
        return ToolResult(output=f"{body}\n{stamp(SOURCE_LABELS['get_weather'])}", data=data)


class GetNews(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_news",
            description=(
                "Latest news headlines by topic (BBC/Guardian/The Verge RSS, or Hacker News). "
                "Topic: top, world, business, technology, science or hackernews."
            ),
            risk="low",
            category=CATEGORY,
            tags=["news", "headlines", "current", "stories", "press", "updates", "hn"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "News topic.",
                        "enum": news.TOPICS,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many headlines (default from settings).",
                        "minimum": 1,
                        "maximum": 25,
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        topic = str(args.get("topic") or "top")
        limit = int(args.get("limit") or ctx.settings.web.news_items)
        articles = await _guard(ctx, "get_news", news.fetch_news, topic, limit=limit)
        body = news.format_headlines(topic, articles)
        return ToolResult(
            output=f"{body}\n{stamp(SOURCE_LABELS['get_news'])}",
            data=_stamp_data("get_news", {"topic": topic, "articles": articles}),
        )


class MovieLookup(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="movie_lookup",
            description=(
                "Look up a TV show or movie (TVMaze): status, network/streaming home, "
                "genres, community rating and latest episode. Use web_search for films "
                "TVMaze does not index."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "movie",
                "movies",
                "film",
                "tv",
                "show",
                "series",
                "watch",
                "episode",
                "entertainment",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Show or movie title, or 'id:<n>' for a known TVMaze id.",
                    },
                    "search_only": {
                        "type": "boolean",
                        "description": "Return candidate matches instead of resolving one title.",
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = str(args["query"]).strip()
        if not query:
            raise ToolError("query must not be empty")

        if args.get("search_only"):
            candidates = await _guard(ctx, "movie_lookup", movies.search_shows, query)
            if not candidates:
                return ToolResult(
                    ok=False,
                    output=f"no TVMaze entries matched {query!r}",
                    error="no results",
                    data=_stamp_data("movie_lookup", {"query": query, "candidates": []}),
                )
            lines = [
                f"{index}. {row['name']} ({row['year']}) — {row['status']}, {row['home']}"
                for index, row in enumerate(candidates, 1)
            ]
            body = f"{len(candidates)} match(es) for {query!r}:\n" + "\n".join(lines)
            return ToolResult(
                output=f"{body}\n{stamp(SOURCE_LABELS['movie_lookup'])}",
                data=_stamp_data("movie_lookup", {"query": query, "candidates": candidates}),
            )

        show = await _guard(ctx, "movie_lookup", movies.lookup, query, episodes=True)
        return ToolResult(
            output=f"{movies.format_show(show)}\n{stamp(SOURCE_LABELS['movie_lookup'])}",
            data=_stamp_data("movie_lookup", {"query": query, "show": show}),
        )


class StockQuote(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="stock_quote",
            description=(
                "Descriptive stock/ETF quote (Yahoo chart): price, volume, 52-week range, "
                "period returns, moving averages and volatility. Analysis of past data, "
                "never a prediction."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "stock",
                "stocks",
                "price",
                "market",
                "finance",
                "ticker",
                "quote",
                "investing",
                "shares",
                "etf",
                "nasdaq",
                "nyse",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker, e.g. 'AAPL', 'MSFT', or 'aapl.us' / '^spx'.",
                    },
                    "period": {
                        "type": "string",
                        "description": "History window for indicators.",
                        "enum": list(finance.RANGES),
                    },
                },
                "required": ["symbol"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        symbol = str(args["symbol"]).strip()
        if not symbol:
            raise ToolError("symbol must not be empty")
        period = str(args.get("period") or "1y")
        quote = await _guard(ctx, "stock_quote", finance.fetch_quote, symbol, period=period)
        return ToolResult(
            output=f"{finance.format_quote(quote)}\n{stamp(SOURCE_LABELS['stock_quote'])}",
            data=_stamp_data("stock_quote", {"quote": quote}),
        )


class InternetSpeed(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="internet_speed",
            description=(
                "Measure this machine's internet download (and optionally upload) speed "
                "and latency via Cloudflare. Consumes real bandwidth — the user may have "
                "turned it off in Settings → Web."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "speed",
                "internet",
                "bandwidth",
                "download",
                "upload",
                "latency",
                "ping",
                "network",
            ],
            read_only=True,
            parameters={"type": "object", "properties": {}, "required": []},
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        del args
        cfg = ctx.settings.web
        if not cfg.speed_enabled:
            raise ToolError(
                "the internet-speed test is turned off in Settings → Web "
                "(it downloads a real payload) — enable it there first"
            )
        result = await _guard(
            ctx,
            "internet_speed",
            speed.speed_test,
            download_bytes=cfg.speed_download_bytes,
            upload_bytes=cfg.speed_upload_bytes,
        )
        return ToolResult(
            output=f"{speed.format_result(result)}\n{stamp(SOURCE_LABELS['internet_speed'])}",
            data=_stamp_data("internet_speed", {"result": result}),
        )


class WorldClock(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="world_clock",
            description=(
                "Current local time in other cities or IANA time zones (e.g. 'Tokyo', "
                "'America/New_York'). Use get_time for this machine's own clock."
            ),
            risk="low",
            category=CATEGORY,
            tags=["time", "clock", "timezone", "zone", "world", "country", "city", "difference"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "zones": {
                        "type": "array",
                        "description": "Cities or IANA zones, e.g. ['Tokyo', 'America/New_York'].",
                        "items": {"type": "string"},
                    }
                },
                "required": ["zones"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw = args.get("zones") or []
        zones = [str(z).strip() for z in raw if str(z).strip()]
        entries = await _guard(ctx, "world_clock", clock.world_clock, zones)
        return ToolResult(
            output=f"{clock.format_clock(entries)}\n{stamp(SOURCE_LABELS['world_clock'])}",
            data=_stamp_data("world_clock", {"zones": entries}),
        )


BUILTIN_TOOLS: list[Tool] = [
    WebSearch(),
    GetWeather(),
    GetNews(),
    MovieLookup(),
    StockQuote(),
    InternetSpeed(),
    WorldClock(),
]
