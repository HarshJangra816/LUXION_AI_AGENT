"""Movies & TV shows via TVMaze (PRD §37 "Movies", Phase 9).

TVMaze is free, keyless and unrate-limited, and covers both series and films.
Two shapes:

- :func:`search_shows` — several candidates for an ambiguous title;
- :func:`lookup` — one resolved show with status, rating, network/streaming
  home, genres and (optionally) its episode list so the model can answer
  "what should I watch next?" or "when does it return?".

Summaries arrive as HTML and are de-tagged; the aggregate ``rating.average``
is passed through as a *community* score, not a guarantee (PRD §38's
uncertainty rule applies to reception numbers too).
"""

from __future__ import annotations

from typing import Any

from luxion.web._html import strip_tags
from luxion.web.errors import WebError
from luxion.web.http import get_json

SEARCH_URL = "https://api.tvmaze.com/search/shows"
SINGLE_URL = "https://api.tvmaze.com/singlesearch/shows"
SHOW_URL = "https://api.tvmaze.com/shows"


def _year(show: dict[str, Any]) -> str:
    premiered = str(show.get("premiered") or "")
    ended = show.get("ended")
    if not premiered:
        return "unknown year"
    start = premiered[:4]
    if ended:
        return f"{start}–{ended[:4]}"
    return f"{start}–"


def _home(show: dict[str, Any]) -> str:
    network = show.get("network") or {}
    web = show.get("webChannel") or {}
    if network.get("name"):
        country = (network.get("country") or {}).get("name")
        return f"{network['name']}" + (f" ({country})" if country else "")
    if web.get("name"):
        return str(web["name"])
    return "unknown"


def _brief(show: dict[str, Any]) -> dict[str, Any]:
    rating = (show.get("rating") or {}).get("average")
    return {
        "id": show.get("id"),
        "name": str(show.get("name") or ""),
        "year": _year(show),
        "type": str(show.get("type") or "unknown"),
        "status": str(show.get("status") or "unknown"),
        "rating": rating,
        "home": _home(show),
        "genres": [str(g) for g in show.get("genres") or []],
    }


async def search_shows(query: str, *, limit: int = 5, settings: Any = None) -> list[dict[str, Any]]:
    """Up to ``limit`` candidate shows matching ``query``."""
    data = await get_json(SEARCH_URL, params={"q": query}, settings=settings)
    if not isinstance(data, list):
        raise WebError("tvmaze returned an unexpected payload", source="tvmaze.com")
    briefs = [_brief(row["show"]) for row in data if isinstance(row, dict) and row.get("show")]
    return briefs[: max(1, min(int(limit), 10))]


async def lookup(query: str, *, episodes: bool = True, settings: Any = None) -> dict[str, Any]:
    """Resolve one show by title (or ``id:<n>``) and enrich with episodes."""
    if query.lower().startswith("id:"):
        raw_id = query[3:].strip()
        if not raw_id.isdigit():
            raise WebError("show lookup by id must look like 'id:169'", source="tvmaze.com")
        url, params = f"{SHOW_URL}/{raw_id}", ({"embed": "episodes"} if episodes else None)
    else:
        url = SINGLE_URL
        params = {"q": query, **({"embed": "episodes"} if episodes else {})}

    data = await get_json(url, params=params, settings=settings)
    if not isinstance(data, dict) or not data.get("name"):
        raise WebError(f"tvmaze has no show matching {query!r}", source="tvmaze.com")

    show = _brief(data)
    show["summary"] = strip_tags(str(data.get("summary") or ""))[:1200]
    show["official_site"] = str(data.get("officialSite") or "") or None
    show["image"] = (data.get("image") or {}).get("medium")

    embedded = (data.get("_embedded") or {}).get("episodes") or []
    if embedded:
        latest = embedded[-1]
        show["episode_count"] = len(embedded)
        show["latest_episode"] = {
            "season": latest.get("season"),
            "number": latest.get("number"),
            "name": str(latest.get("name") or ""),
            "airdate": latest.get("airdate"),
        }
    return show


def format_show(show: dict[str, Any]) -> str:
    """Render one resolved show as prompt-ready text."""
    genres = ", ".join(show.get("genres") or []) or "—"
    rating = show.get("rating")
    lines = [
        f"{show.get('name')} ({show.get('year')}) — {show.get('type')}",
        f"Status: {show.get('status')} · Home: {show.get('home')} · Genres: {genres}",
    ]
    if rating is not None:
        lines.append(
            f"Community rating: {rating}/10 (TVMaze average — crowd-sourced, not a critic score)"
        )
    if show.get("episode_count"):
        latest = show.get("latest_episode") or {}
        season, number = latest.get("season"), latest.get("number")
        lines.append(
            f"Episodes: {show['episode_count']} · Latest: S{season}E{number} "
            f"{latest.get('name')} ({latest.get('airdate')})"
        )
    if show.get("summary"):
        lines.append(show["summary"])
    if show.get("official_site"):
        lines.append(show["official_site"])
    return "\n".join(lines)
