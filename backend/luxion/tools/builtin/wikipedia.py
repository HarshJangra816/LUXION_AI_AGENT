"""Wikipedia tools (PRD §33.8, Phase 6).

Straight HTTP against the public MediaWiki API — no browser session, so they
stay fast and work even while the user has browser automation disabled.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

API_BASE = "https://en.wikipedia.org"
TIMEOUT_S = 15.0
USER_AGENT = "Luxion/0.1 (personal AI agent; https://github.com/HarshJangra816/LUXION_AI_AGENT)"
#: Keep summaries prompt-sized.
MAX_SUMMARY_CHARS = 6000


async def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ToolError(f"wikipedia request failed: {exc}") from exc
    if response.status_code >= 400:
        raise ToolError(f"wikipedia answered HTTP {response.status_code} for {url}")
    data = response.json()
    if not isinstance(data, dict):
        raise ToolError("wikipedia returned an unexpected payload")
    return data


class WikipediaSearch(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wikipedia_search",
            description=(
                "Search Wikipedia for articles matching a query; returns titles + snippets."
            ),
            risk="low",
            category="web",
            tags=[
                "wikipedia",
                "encyclopedia",
                "search",
                "article",
                "wiki",
                "lookup",
                "research",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."},
                    "limit": {
                        "type": "integer",
                        "description": "How many articles to return (default 5).",
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

        data = await _get_json(
            f"{API_BASE}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "srprop": "snippet",
            },
        )
        hits = ((data.get("query") or {}).get("search")) or []
        results = [
            {
                "title": str(hit.get("title", "")),
                # The API ships HTML highlights (<span class=searchmatch>).
                "snippet": _strip_tags(str(hit.get("snippet", ""))),
            }
            for hit in hits
            if hit.get("title")
        ]
        if not results:
            return ToolResult(
                ok=False,
                output=f"no wikipedia articles matched {query!r}",
                error="no results",
            )
        lines = [
            f"{index}. {item['title']} — {item['snippet']}" for index, item in enumerate(results, 1)
        ]
        return ToolResult(
            output=f"{len(results)} wikipedia article(s) for {query!r}:\n" + "\n".join(lines),
            data={"results": results},
        )


class WikipediaArticle(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wikipedia_article",
            description=(
                "Retrieve the summary of a Wikipedia article by title "
                "(use the exact title from wikipedia_search)."
            ),
            risk="low",
            category="web",
            tags=["wikipedia", "article", "read", "summary", "wiki", "encyclopedia", "fetch"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Exact article title."}},
                "required": ["title"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        title = str(args["title"]).strip()
        if not title:
            raise ToolError("title must not be empty")

        data = await _get_json(f"{API_BASE}/api/rest_v1/page/summary/{quote(title, safe='')}")
        extract = str(data.get("extract", "")).strip()
        if not extract:
            raise ToolError(f"wikipedia has no summary for {title!r}")
        extract = extract[:MAX_SUMMARY_CHARS]
        page_url = str((data.get("content_urls") or {}).get("desktop", {}).get("page", ""))
        return ToolResult(
            output=f"{data.get('title', title)}\n{extract}\n{page_url}".strip(),
            data={
                "title": str(data.get("title", title)),
                "description": str(data.get("description", "")),
                "extract": extract,
                "url": page_url,
            },
        )


def _strip_tags(html: str) -> str:
    out: list[str] = []
    inside = False
    for char in html:
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
        elif not inside:
            out.append(char)
    return "".join(out).strip()


BUILTIN_TOOLS: list[Tool] = [
    WikipediaSearch(),
    WikipediaArticle(),
]
