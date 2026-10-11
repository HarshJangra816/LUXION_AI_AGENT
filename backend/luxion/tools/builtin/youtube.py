"""YouTube tools (PRD §33.7, Phase 6).

Search / open / play / pause / seek / volume, driven through the shared
browser session (the same one ``browser_open`` uses — YouTube is a web app,
so PRD §33.7 is browser automation plus a little player JS).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from luxion.browser.manager import get_browser_manager
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.browser import (
    _YOUTUBE_CONTROL_JS,
    _YOUTUBE_SEARCH_JS,
    _act,
)

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
SEARCH_URL = "https://www.youtube.com/results?search_query={query}"
#: play / pause / seek / volume (PRD §33.7).
CONTROL_ACTIONS = ("play", "pause", "seek", "volume")


def video_id_from(url: str) -> str | None:
    """Pull the ``v`` parameter out of a watch URL, else None."""
    query = parse_qs(urlparse(url).query)
    value = query.get("v")
    return str(value[0]) if value and value[0] else None


class YouTubeSearch(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="youtube_search",
            description="Search YouTube for videos; returns titles + watch URLs.",
            risk="low",
            category="web",
            tags=["youtube", "video", "search", "find", "watch", "clip", "music"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "limit": {
                        "type": "integer",
                        "description": "How many videos to return (default 5).",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = str(args["query"]).strip()
        if not query:
            raise ToolError("query must not be empty")
        limit = min(max(int(args.get("limit", 5) or 5), 1), 10)

        manager = get_browser_manager(ctx.settings)
        session = await _act(manager.session(), "launching the browser")
        target = SEARCH_URL.format(query=quote_plus(query))
        await _act(
            session.page.goto(target, timeout=manager.navigation_timeout_ms()),
            f"searching YouTube for {query!r}",
        )
        anchors = await _act(session.page.evaluate(_YOUTUBE_SEARCH_JS), "collecting results")

        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in anchors or []:
            href = str(anchor.get("href", ""))
            video_id = video_id_from(href)
            title = str(anchor.get("title", "")).strip()
            if not video_id or not title or video_id in seen:
                continue
            seen.add(video_id)
            results.append(
                {
                    "title": title[:200],
                    "video_id": video_id,
                    "url": WATCH_URL.format(video_id=video_id),
                }
            )
            if len(results) >= limit:
                break

        if not results:
            return ToolResult(
                ok=False,
                output=f"no YouTube results for {query!r}",
                error="the results page returned no videos (layout change or blocked)",
            )
        lines = [
            f"{index}. {item['title']} — {item['url']}" for index, item in enumerate(results, 1)
        ]
        return ToolResult(
            output=f"{len(results)} video(s) for {query!r}:\n" + "\n".join(lines),
            data={"results": results},
        )


class YouTubeOpen(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="youtube_open",
            description=(
                "Open a YouTube video (by watch URL or 11-character video id) in "
                "the agent's browser so it can be played or controlled."
            ),
            risk="medium",
            category="web",
            tags=["youtube", "open", "watch", "play", "video", "url", "start"],
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Watch URL (…/watch?v=ID) or the bare video id.",
                    }
                },
                "required": ["url"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw = str(args["url"]).strip()
        if not raw:
            raise ToolError("url must not be empty")
        video_id = video_id_from(raw) if "://" in raw or raw.startswith("youtu") else None
        if video_id is None and raw.isalnum() and len(raw) == 11:
            video_id = raw
        if video_id is None:
            raise ToolError(
                "expected a YouTube watch URL (…/watch?v=ID) or an 11-character video id"
            )
        target = WATCH_URL.format(video_id=video_id)

        manager = get_browser_manager(ctx.settings)
        session = await _act(manager.session(), "launching the browser")
        await _act(
            session.page.goto(target, timeout=manager.navigation_timeout_ms()),
            f"opening {target}",
        )
        title = await _act(session.page.title(), "reading the page title")
        return ToolResult(
            output=f"opened {title or video_id} ({target})",
            data={"video_id": video_id, "url": target, "title": title},
        )


class YouTubeControl(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="youtube_control",
            description=(
                "Control the player on the currently open YouTube page: play, "
                "pause, seek (seconds) or set volume (0..1)."
            ),
            risk="medium",
            category="web",
            tags=[
                "youtube",
                "play",
                "pause",
                "seek",
                "volume",
                "resume",
                "stop",
                "player",
                "control",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(CONTROL_ACTIONS),
                        "description": "play | pause | seek | volume",
                    },
                    "value": {
                        "type": "number",
                        "description": "Required for seek (seconds) and volume (0..1).",
                    },
                },
                "required": ["action"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        action = str(args["action"]).strip().lower()
        if action not in CONTROL_ACTIONS:
            raise ToolError(f"unknown action {action!r}; use one of {', '.join(CONTROL_ACTIONS)}")
        value: Any = args.get("value")
        if action in ("seek", "volume") and value is None:
            raise ToolError(f"{action} requires a value")
        if action == "seek":
            value = max(float(value), 0.0)
        elif action == "volume":
            value = min(max(float(value), 0.0), 1.0)

        manager = get_browser_manager(ctx.settings)
        session = await _act(manager.session(), "launching the browser")
        state = await _act(
            session.page.evaluate(_YOUTUBE_CONTROL_JS, {"action": action, "value": value}),
            f"executing {action}",
        )
        if not isinstance(state, dict) or not state.get("ok"):
            error = state.get("error") if isinstance(state, dict) else "unexpected player state"
            raise ToolError(f"could not {action}: {error}")
        return ToolResult(
            output=(
                f"{action} ok — t={state.get('currentTime', 0):.1f}s "
                f"volume={state.get('volume', 0):.2f} paused={state.get('paused', True)}"
            ),
            data={
                "action": action,
                "current_time": state.get("currentTime"),
                "volume": state.get("volume"),
                "paused": state.get("paused"),
            },
        )


BUILTIN_TOOLS: list[Tool] = [
    YouTubeSearch(),
    YouTubeOpen(),
    YouTubeControl(),
]
