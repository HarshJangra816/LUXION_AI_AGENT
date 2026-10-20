"""Financial quotes & indicators (PRD §37 "Finance", §38, Phase 9).

One keyless source, :func:`fetch_quote`'s Yahoo Finance **v8 chart** endpoint,
which already carries everything Luxion needs in a single request:

- ``meta`` — live price, day high/low, volume, 52-week high/low, exchange,
  currency and the daily change (all straight from Yahoo, so they are correct
  even for a short ``period``);
- ``indicators.quote[0]`` — a full year of daily OHLCV bars, from which
  Luxion computes its own descriptive indicators (moving averages, period
  returns, volatility, range position).

No API key, no ``yfinance`` dependency (FOSS-first: stdlib + ``httpx``).

**Why Yahoo alone**: a second free feed (Stooq's ``q/l`` CSV) was planned as a
cross-check, but it answers HTTP 404 to this project's network for every
parameter variant — see :func:`parse_chart`. Yahoo's chart returns strictly
more (OHLCV *plus* 52-week range *plus* volume), so one request replaces two
and nothing is lost.

**PRD §38**: this module deliberately offers *analysis, not prophecy*. Every
number is descriptive (what already happened) and :func:`format_quote` states
the uncertainty explicitly — a moving average is not a forecast. Fields that
need a paid/keyed feed (market cap, financial statements) are reported as
unavailable rather than guessed.
"""

from __future__ import annotations

import json
import math
from typing import Any

from luxion.web.errors import WebError
from luxion.web.http import get_text

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

RANGES = ("5d", "1mo", "3mo", "6mo", "1y", "5y", "max")


def normalize_symbol(symbol: str) -> str:
    """Clean a user ticker for the URL path (``aapl`` → ``AAPL``, ``^spx`` kept).

    Yahoo is case-insensitive and understands a leading ``^`` for indexes and a
    market suffix (``aapl.us``), so the only real job is stripping whitespace
    and refusing an empty request before any HTTP goes out.
    """
    cleaned = (symbol or "").strip()
    if not cleaned:
        raise WebError("symbol must not be empty", source="finance.yahoo.com")
    if any(char.isspace() for char in cleaned):
        raise WebError(f"symbol {symbol!r} must be a single ticker", source="finance.yahoo.com")
    return cleaned


def _last(values: list[Any]) -> Any:
    """Last non-``None`` entry (bars are right-aligned to the present)."""
    for value in reversed(values):
        if value is not None:
            return value
    return None


def parse_chart(text: str) -> dict[str, Any]:
    """Parse a Yahoo v8 chart body into ``{meta, closes, last_bar}``.

    Pure function (no I/O) so it is directly testable. Raises
    :class:`WebError` for invalid JSON or a "result: []" answer (an unknown
    ticker), which is the honest failure a bad symbol should produce.
    """
    try:
        chart = json.loads(text)
    except ValueError as exc:
        raise WebError("yahoo returned invalid JSON", source="finance.yahoo.com") from exc

    results = (chart.get("chart") or {}).get("result") or []
    if not results or not isinstance(results[0], dict):
        raise WebError("no market data for that symbol", source="finance.yahoo.com")

    result = results[0]
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = quote.get("close") or []
    return {
        "meta": meta,
        "closes": closes,
        "last_bar": {
            "open": _last(quote.get("open") or []),
            "high": _last(quote.get("high") or []),
            "low": _last(quote.get("low") or []),
            "close": _last(closes),
            "volume": _last(quote.get("volume") or []),
        },
    }


def build_snapshot(meta: dict[str, Any], last_bar: dict[str, Any]) -> dict[str, Any]:
    """The "right now" facts, preferring Yahoo's meta over the last bar."""
    return {
        "price": meta.get("regularMarketPrice"),
        "previous_close": meta.get("chartPreviousClose"),
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume") or last_bar.get("volume"),
        "change_pct": meta.get("fulldayChangePercent", meta.get("regularMarketChangePercent")),
        "high_52w": meta.get("fiftyTwoWeekHigh"),
        "low_52w": meta.get("fiftyTwoWeekLow"),
        "market_time": meta.get("regularMarketTime"),
    }


def compute_indicators(closes: list[float]) -> dict[str, Any]:
    """Descriptive indicators from a newest-last series of daily closes.

    Pure function (no I/O) so it is directly testable. Percentages are plain
    percentages; ``volatility_annual_pct`` is the stdev of daily log returns
    scaled by √252 — a historical measure, never a prediction.
    """
    prices = [float(c) for c in closes if c is not None]
    out: dict[str, Any] = {}
    if not prices:
        return out
    last = prices[-1]
    out["last"] = last

    def change_over(bars: int) -> float | None:
        if len(prices) <= bars or prices[-1 - bars] == 0:
            return None
        return round((last / prices[-1 - bars] - 1) * 100, 2)

    out["change_1d_pct"] = change_over(1)
    out["change_5d_pct"] = change_over(5)
    out["change_1mo_pct"] = change_over(21)
    out["change_3mo_pct"] = change_over(63)
    out["change_1y_pct"] = change_over(min(252, len(prices) - 1))

    def sma(window: int) -> float | None:
        if len(prices) < window:
            return None
        return round(sum(prices[-window:]) / window, 4)

    out["sma_20"] = sma(20)
    out["sma_50"] = sma(50)
    out["sma_200"] = sma(200)

    year = prices[-min(252, len(prices)) :]
    out["high_52w"] = round(max(year), 4)
    out["low_52w"] = round(min(year), 4)
    spread = out["high_52w"] - out["low_52w"]
    out["pct_of_52w_range"] = round((last - out["low_52w"]) / spread * 100, 1) if spread else None

    returns = [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i] > 0 and prices[i - 1] > 0
    ]
    if len(returns) > 2:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        out["volatility_annual_pct"] = round(math.sqrt(var) * math.sqrt(252) * 100, 1)
    return out


def read_trend(indicators: dict[str, Any]) -> str:
    """A neutral, explicitly-historical reading of the computed indicators."""
    last = indicators.get("last")
    sma20, sma50 = indicators.get("sma_20"), indicators.get("sma_50")
    bits: list[str] = []
    if last and sma50:
        bits.append("above its 50-day average" if last > sma50 else "below its 50-day average")
    if sma20 and sma50:
        bits.append(
            "20-day above 50-day (short-term up)"
            if sma20 > sma50
            else "20-day below 50-day (short-term down)"
        )
    if not bits:
        return "not enough history for a trend reading"
    return "; ".join(bits)


def _range_position(indicators: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Fill 52-week range fields, preferring Yahoo's meta over computed values.

    ``period='6mo'`` would otherwise cap the "52-week" range at six months;
    meta's ``fiftyTwoWeekHigh/Low`` is authoritative regardless of the window
    the user asked the history for.
    """
    high = snapshot.get("high_52w")
    low = snapshot.get("low_52w")
    if high is not None:
        indicators["high_52w"] = high
    if low is not None:
        indicators["low_52w"] = low
    last = indicators.get("last") or snapshot.get("price")
    high, low = indicators.get("high_52w"), indicators.get("low_52w")
    if last is None or high is None or low is None:
        return
    indicators["last"] = last
    spread = high - low
    indicators["pct_of_52w_range"] = round((last - low) / spread * 100, 1) if spread else None


async def fetch_quote(symbol: str, *, period: str = "1y", settings: Any = None) -> dict[str, Any]:
    """One Yahoo chart request → snapshot + computed indicators + a trend line."""
    period = period if period in RANGES else "1y"
    ticker = normalize_symbol(symbol)

    text = await get_text(
        f"{YAHOO_CHART_URL}{ticker}",
        params={"range": period, "interval": "1d"},
        settings=settings,
    )
    chart = parse_chart(text)
    meta, last_bar = chart["meta"], chart["last_bar"]

    snapshot = build_snapshot(meta, last_bar)
    indicators = compute_indicators(chart["closes"])
    if not indicators and snapshot.get("price") is None:
        raise WebError(f"no market data for {symbol!r}", source="finance.yahoo.com")
    if not indicators and snapshot.get("price") is not None:
        indicators["last"] = snapshot["price"]
    _range_position(indicators, snapshot)

    return {
        "symbol": meta.get("symbol") or ticker.upper(),
        "name": meta.get("shortName") or meta.get("longName") or "",
        "currency": meta.get("currency") or "",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "market_time": snapshot.get("market_time"),
        "snapshot": snapshot,
        "period": period,
        "indicators": indicators,
        "trend": read_trend(indicators),
        "available": {
            "price": snapshot.get("price") is not None,
            "volume": snapshot.get("volume") is not None,
            "52_week_range": snapshot.get("high_52w") is not None,
            "market_cap": False,
            "financial_statements": False,
        },
    }


def _price(value: Any) -> str:
    """Display a monetary value without Yahoo's float noise (``342.4599914…``)
    and without erasing sub-dollar precision (penny stocks, FX, crypto)."""
    number = float(value)
    places = 4 if abs(number) < 1 else 2
    return f"{number:.{places}f}"


def format_quote(quote: dict[str, Any]) -> str:
    """Prompt-ready quote that separates fact from interpretation (§38)."""
    ind = quote.get("indicators") or {}
    snap = quote.get("snapshot") or {}
    currency = quote.get("currency") or ""
    header = f"{quote.get('name') or quote.get('symbol')} ({quote.get('symbol')})"
    lines = [f"{header} on {quote.get('exchange')}"]

    price = ind.get("last") or snap.get("price")
    if price is not None:
        lines.append(f"Last close: {_price(price)} {currency}".strip())
    change = snap.get("change_pct")
    if change is not None:
        lines.append(f"Latest session: {change:+.2f}%")
    if snap.get("volume") is not None:
        lines.append(f"Volume (latest session): {int(snap['volume']):,}")
    if snap.get("day_high") is not None and snap.get("day_low") is not None:
        lines.append(
            f"Day range: {_price(snap['day_low'])} – {_price(snap['day_high'])} {currency}"
        )
    if snap.get("high_52w") is not None and snap.get("low_52w") is not None:
        through = ind.get("pct_of_52w_range")
        lines.append(
            f"52-week range: {_price(snap['low_52w'])} – {_price(snap['high_52w'])} {currency}"
            + (f" (currently {through}% through it)" if through is not None else "")
        )

    for label, key in (
        ("1 day", "change_1d_pct"),
        ("5 day", "change_5d_pct"),
        ("1 month", "change_1mo_pct"),
        ("3 month", "change_3mo_pct"),
        ("1 year", "change_1y_pct"),
    ):
        value = ind.get(key)
        if value is not None:
            lines.append(f"{label}: {value:+.2f}%")

    averages = [
        f"{name.upper()} {_price(ind[key])}"
        for name, key in (("sma20", "sma_20"), ("sma50", "sma_50"), ("sma200", "sma_200"))
        if ind.get(key) is not None
    ]
    if averages:
        lines.append("Moving averages: " + ", ".join(averages))
    if ind.get("volatility_annual_pct") is not None:
        lines.append(f"Historical volatility (annualised): {ind['volatility_annual_pct']}%")

    lines.append(f"Reading: {quote.get('trend')}.")
    missing = [label for label, present in (quote.get("available") or {}).items() if not present]
    if missing:
        lines.append("Not available from the free feed: " + ", ".join(missing) + ".")
    lines.append(
        "These are descriptive statistics from past prices, not a prediction — "
        "markets can move against any reading."
    )
    return "\n".join(lines)
