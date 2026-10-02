"""Web tools (PRD §20: open_url is MEDIUM — it hands control to the browser)."""

from __future__ import annotations

import asyncio
import webbrowser

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

ALLOWED_SCHEMES = ("http://", "https://")
BLOCKED_SCHEMES = ("javascript:", "file:", "data:", "vbscript:")


class OpenUrl(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_url",
            description="Open a web page in the user's default browser.",
            risk="medium",
            category="web",
            tags=["url", "link", "website", "browse", "open", "web", "http", "page"],
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully-qualified http(s) URL."}
                },
                "required": ["url"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = str(args["url"]).strip()
        lowered = url.lower()
        if lowered.startswith(BLOCKED_SCHEMES):
            raise ToolError(f"blocked URL scheme: {url.split(':', 1)[0]}")
        if not lowered.startswith(ALLOWED_SCHEMES):
            url = f"https://{url}"

        opened = await asyncio.to_thread(webbrowser.open, url, new=2)
        if not opened:
            raise ToolError(f"no browser could open {url}")
        return ToolResult(output=f"opened {url}", data={"url": url})


BUILTIN_TOOLS: list[Tool] = [OpenUrl()]
