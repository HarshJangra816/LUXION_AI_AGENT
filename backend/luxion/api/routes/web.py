"""Web-intelligence status + settings + live source probe (PRD §37, Phase 9).

``GET    /web``          effective config + defaults + status (Settings card)
``PUT    /web/config``   persist Settings → Web edits (partial overlay)
``DELETE /web/config``   back to ``.env`` defaults
``POST   /web/probe``    hit every keyless source once and report reachability

The probe exists because these sources are free public endpoints with no key
to validate at save time — the only honest way to show "reachable" is to call
each one. It is opt-in (a button on the card), never automatic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.settings import (
    WebConfig,
    get_settings,
    reset_settings_cache,
    save_web_overrides,
)
from luxion.config.web_override import clear_overrides
from luxion.web import clock, finance, movies, news, search, weather
from luxion.web.errors import WebError

router = APIRouter(prefix="/web", tags=["web"])


class WebConfigBundle(BaseModel):
    """What Settings → Web edits (effective values + defaults + status)."""

    config: WebConfig
    defaults: WebConfig
    status: dict[str, Any]
    catalog: dict[str, Any]


class WebConfigPatch(BaseModel):
    """Partial web settings — mirrors every field of ``WebConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.WebConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    timeout_s: float | None = None
    max_results: int | None = None
    news_items: int | None = None
    search_region: str | None = None
    temperature_unit: str | None = None
    wind_unit: str | None = None
    speed_enabled: bool | None = None
    speed_download_bytes: int | None = None
    speed_upload_bytes: int | None = None
    user_agent: str | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class ProbeOut(BaseModel):
    results: dict[str, str]


def _status(settings) -> dict[str, Any]:
    """Static facts for the card — no network, never raises."""
    return {
        "enabled": settings.web.enabled,
        "speed_enabled": settings.web.speed_enabled,
        "keyless": True,
        "browser_independent": True,
    }


def _catalog() -> dict[str, Any]:
    return {
        "news_topics": news.TOPICS,
        "finance_ranges": list(finance.RANGES),
        "temperature_units": ["celsius", "fahrenheit"],
        "wind_units": ["kmh", "mph"],
        "timezone_examples": ["Tokyo", "America/New_York", "Europe/London"],
    }


def _bundle() -> WebConfigBundle:
    settings = get_settings()
    return WebConfigBundle(
        config=settings.web,
        defaults=WebConfig(),
        status=_status(settings),
        catalog=_catalog(),
    )


@router.get("", response_model=WebConfigBundle)
async def read_web() -> WebConfigBundle:
    return _bundle()


@router.put("/config", response_model=WebConfigBundle)
async def write_web(patch: WebConfigPatch) -> WebConfigBundle:
    settings = get_settings()
    try:
        save_web_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=WebConfigBundle)
async def reset_web() -> WebConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.post("/probe", response_model=ProbeOut)
async def probe_sources() -> ProbeOut:
    """Reachability check for every keyless source (one tiny call each)."""
    settings = get_settings()
    results: dict[str, str] = {}

    async def check(name: str, coro) -> None:
        try:
            await coro
            results[name] = "ok"
        except WebError as exc:
            results[name] = f"error: {exc}"
        except Exception as exc:  # noqa: BLE001 - a probe must never 500
            results[name] = f"error: {exc}"

    import asyncio

    await asyncio.gather(
        check("search", search.search("luxion", limit=1, settings=settings)),
        check("weather", weather.geocode("London", count=1, settings=settings)),
        check("news", news.fetch_news("top", limit=1, settings=settings)),
        check("movies", movies.search_shows("breaking bad", limit=1, settings=settings)),
        check("clock", clock.world_clock(["Tokyo"], settings=settings)),
    )
    return ProbeOut(results=results)
