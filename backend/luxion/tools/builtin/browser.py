"""Browser automation tools (PRD §5.7, §33.6, Phase 6).

Eight tools drive one shared Playwright session owned by
:mod:`luxion.browser.manager`. Risk follows the open_url precedent (§20):
navigation and form interaction are MEDIUM (they can change state on remote
sites), while search and extraction only read. Every Playwright failure is
mapped to a ``ToolError`` the model can react to.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from luxion.browser.manager import BrowserError, get_browser_manager
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.tools.builtin.web import ALLOWED_SCHEMES, BLOCKED_SCHEMES

#: Search engines ``browser_search`` knows (PRD §33.6 "search").
SEARCH_URLS = {
    "duckduckgo": "https://duckduckgo.com/html/?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
}

#: Collect every visible anchor with text; the tool filters in Python so the
#: same expression works on any engine's markup.
_COLLECT_LINKS_JS = """() => Array.from(document.querySelectorAll('a[href]'))
  .map((a) => ({ title: (a.innerText || '').trim(), href: a.href }))
  .filter((r) => r.title && r.href)"""

#: YouTube search result anchors (PRD §33.7 "Search").
_YOUTUBE_SEARCH_JS = """() => Array.from(document.querySelectorAll('a#video-title'))
  .map((a) => ({
    title: (a.getAttribute('title') || a.textContent || '').trim(),
    href: a.href,
  }))
  .filter((r) => r.href)"""

#: Play/pause/seek/volume on the page's <video> (PRD §33.7).
_YOUTUBE_CONTROL_JS = """(args) => {
  const video = document.querySelector('video');
  if (!video) return { ok: false, error: 'no <video> element on this page' };
  const { action, value } = args;
  if (action === 'play') video.play();
  else if (action === 'pause') video.pause();
  else if (action === 'seek') video.currentTime = Number(value) || 0;
  else if (action === 'volume') {
    video.volume = Math.min(1, Math.max(0, Number(value) || 0));
  }
  return {
    ok: true,
    action,
    currentTime: video.currentTime,
    volume: video.volume,
    paused: video.paused,
  };
}"""

_ENGINE_HOSTS = ("google.com", "duckduckgo.com", "bing.com", "googleusercontent.com")


def normalize_url(raw: str) -> str:
    """Validate + normalise a URL the same way ``open_url`` does."""
    url = str(raw).strip()
    lowered = url.lower()
    if lowered.startswith(BLOCKED_SCHEMES):
        raise ToolError(f"blocked URL scheme: {url.split(':', 1)[0]}")
    if not lowered.startswith(ALLOWED_SCHEMES):
        url = f"https://{url}"
    return url


def unwrap_result(href: str) -> str:
    """Follow one hop of a search-engine redirect (google /url?q=, ddg /l/?uddg=)."""
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    host = parsed.netloc.lower()
    if parsed.path == "/url" and query.get("q"):
        return str(query["q"][0])
    if "duckduckgo.com" in host and parsed.path.startswith("/l/") and query.get("uddg"):
        return str(unquote(query["uddg"][0]))
    return href


def is_result_link(href: str, engine: str) -> bool:
    """Drop engine-internal navigation (settings, accounts, caches, …)."""
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.lower()
    if any(host == domain or host.endswith(f".{domain}") for domain in _ENGINE_HOSTS):
        return False
    return bool(engine)  # engine kept for future per-engine rules


async def _act(coro: Any, what: str) -> Any:
    """Run one Playwright call, mapping its errors to ``ToolError``."""
    try:
        return await coro
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - playwright errors vary by version
        raise ToolError(f"{what} failed: {exc}") from exc


def _manager(ctx: ToolContext):
    try:
        return get_browser_manager(ctx.settings)
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc


def _config(ctx: ToolContext):
    return ctx.settings.browser


class BrowserOpen(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_open",
            description=(
                "Open a web page in the agent's browser session and report its "
                "title and URL. Use this before click/type/extract."
            ),
            risk="medium",
            category="web",
            tags=["browser", "open", "navigate", "visit", "url", "page", "website", "web"],
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully-qualified http(s) URL."}
                },
                "required": ["url"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = normalize_url(str(args["url"]))
        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        response = await _act(
            session.page.goto(url, timeout=manager.navigation_timeout_ms()),
            f"opening {url}",
        )
        status = getattr(response, "status", None)
        title = await _act(session.page.title(), "reading the page title")
        output = f"opened {title or url} ({url})"
        if status is not None and int(status) >= 400:
            return ToolResult(
                ok=False,
                output=output,
                error=f"{url} answered HTTP {status}",
                data={"url": session.url, "title": title, "status": int(status)},
            )
        return ToolResult(output=output, data={"url": session.url, "title": title})


class BrowserSearch(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_search",
            description=(
                "Search the web with the configured engine and return the top "
                "results (title + URL). Read-only; does not open a visible page."
            ),
            risk="low",
            category="web",
            tags=[
                "search",
                "web",
                "query",
                "find",
                "look up",
                "internet",
                "engine",
                "results",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms."},
                    "limit": {
                        "type": "integer",
                        "description": "How many results to return (default 5).",
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
        engine = _config(ctx).search_engine
        target = SEARCH_URLS.get(engine, SEARCH_URLS["duckduckgo"]).format(query=quote_plus(query))

        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        await _act(
            session.page.goto(target, timeout=manager.navigation_timeout_ms()),
            f"searching for {query!r}",
        )
        anchors = await _act(session.page.evaluate(_COLLECT_LINKS_JS), "collecting results")

        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in anchors or []:
            href = unwrap_result(str(anchor.get("href", "")))
            title = str(anchor.get("title", "")).strip()
            if not title or href in seen or not is_result_link(href, engine):
                continue
            seen.add(href)
            results.append({"title": title[:200], "url": href})
            if len(results) >= limit:
                break

        if not results:
            return ToolResult(
                ok=False,
                output=f"no results for {query!r} on {engine}",
                error="the search page returned no usable links (layout change or blocked)",
            )
        lines = [
            f"{index}. {item['title']} — {item['url']}" for index, item in enumerate(results, 1)
        ]
        return ToolResult(
            output=f"{len(results)} result(s) for {query!r} on {engine}:\n" + "\n".join(lines),
            data={"engine": engine, "results": results},
        )


class BrowserClick(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_click",
            description=(
                "Click an element on the current page by CSS selector or visible "
                "text (links, buttons). The page must already be open."
            ),
            risk="medium",
            category="web",
            tags=["browser", "click", "press", "tap", "link", "button", "select"],
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector, e.g. 'button.submit' or '#login'.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Visible text to click when no selector is given.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        selector = str(args.get("selector") or "").strip()
        text = str(args.get("text") or "").strip()
        if not selector and not text:
            raise ToolError("provide a selector or a text")
        if selector and text:
            raise ToolError("provide either a selector or a text, not both")
        path = selector or f"text={text}"

        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        await _act(
            session.page.click(path, timeout=manager.action_timeout_ms()),
            f"clicking {path}",
        )
        return ToolResult(
            output=f"clicked {path}",
            data={"clicked": path, "url": session.url},
        )


class BrowserType(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_type",
            description=(
                "Type text into an input/textarea/contenteditable on the current "
                "page (replaces existing content). Optionally press Enter after."
            ),
            risk="medium",
            category="web",
            tags=["browser", "type", "write", "input", "fill", "form", "text", "enter"],
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the field, e.g. 'input[name=q]'.",
                    },
                    "text": {"type": "string", "description": "Text to type."},
                    "submit": {
                        "type": "boolean",
                        "description": "Press Enter after typing (default false).",
                    },
                },
                "required": ["selector", "text"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        selector = str(args["selector"]).strip()
        if not selector:
            raise ToolError("selector must not be empty")
        text = str(args["text"])
        submit = bool(args.get("submit", False))

        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        timeout = manager.action_timeout_ms()
        await _act(session.page.fill(selector, text, timeout=timeout), f"typing into {selector}")
        if submit:
            await _act(session.page.press(selector, "Enter", timeout=timeout), "pressing Enter")
        verb = "typed and submitted" if submit else "typed"
        return ToolResult(
            output=f"{verb} into {selector}",
            data={"selector": selector, "submitted": submit, "url": session.url},
        )


class BrowserExtract(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_extract",
            description=(
                "Read the current page: title, URL and visible text (clipped). "
                "Optionally also the first links. Read-only."
            ),
            risk="low",
            category="web",
            tags=[
                "browser",
                "extract",
                "read",
                "scrape",
                "text",
                "content",
                "page",
                "parse",
                "html",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "include_links": {
                        "type": "boolean",
                        "description": "Also return the page's links (default false).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        include_links = bool(args.get("include_links", False))
        limit = _config(ctx).extract_max_chars

        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        title = await _act(session.page.title(), "reading the page title")
        text = await _act(session.page.inner_text("body"), "reading the page text")
        text = str(text or "")[:limit]
        data: dict[str, Any] = {"url": session.url, "title": title, "text": text}
        if include_links:
            anchors = await _act(session.page.evaluate(_COLLECT_LINKS_JS), "collecting links")
            data["links"] = [
                {"title": str(a.get("title", ""))[:200], "url": str(a.get("href", ""))}
                for a in (anchors or [])[:30]
            ]
        clipped = len(str(data["text"])) >= limit
        summary = f"{title or 'page'} ({session.url})\n{text}"
        if clipped:
            summary += "\n…(clipped)"
        return ToolResult(
            output=summary,
            data=data,
        )


class BrowserDownload(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_download",
            description=(
                "Download a file through the browser session (keeps its cookies) "
                "into the downloads folder and return the saved path."
            ),
            risk="medium",
            category="web",
            tags=["browser", "download", "fetch", "save", "file", "get"],
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Fully-qualified http(s) URL."}
                },
                "required": ["url"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = normalize_url(str(args["url"]))
        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        response = await _act(
            session.context.request.get(url, timeout=manager.navigation_timeout_ms()),
            f"downloading {url}",
        )
        if not getattr(response, "ok", False):
            raise ToolError(f"download failed: {url} answered HTTP {response.status}")
        body: bytes = await _act(response.body(), "reading the download")
        filename = _download_name(url, dict(getattr(response, "headers", {}) or {}))
        directory = manager.resolve_download_dir()
        directory.mkdir(parents=True, exist_ok=True)
        destination = _unique_path(directory / filename)
        destination.write_bytes(body)
        return ToolResult(
            output=f"saved {destination.name} ({len(body)} bytes) to {destination}",
            data={"path": str(destination), "bytes": len(body), "url": url},
        )


def _download_name(url: str, headers: dict[str, str]) -> str:
    disposition = headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    candidate = match.group(1) if match else Path(urlparse(url).path).name
    candidate = Path(str(candidate).strip()).name  # strip any directories
    return candidate or "download"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for counter in range(1, 1000):
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{path.stat().st_mtime_ns}{suffix}")


class BrowserUpload(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_upload",
            description=(
                "Upload a file from an approved workspace into a file input on the current page."
            ),
            risk="medium",
            category="web",
            tags=["browser", "upload", "attach", "file", "input", "send"],
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the file input.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File path inside an approved workspace.",
                    },
                },
                "required": ["selector", "path"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        selector = str(args["selector"]).strip()
        if not selector:
            raise ToolError("selector must not be empty")
        path = resolve_in_workspace(str(args["path"]), ctx)
        if not path.exists():
            raise ToolError(f"no such file: {path}")

        manager = _manager(ctx)
        session = await _act(manager.session(), "launching the browser")
        await _act(
            session.page.set_input_files(selector, str(path), timeout=manager.action_timeout_ms()),
            f"uploading to {selector}",
        )
        return ToolResult(
            output=f"attached {path.name} to {selector}",
            data={"selector": selector, "path": str(path)},
        )


class BrowserClose(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_close",
            description="Close the agent's browser session (frees memory; state on sites is kept).",
            risk="low",
            category="web",
            tags=["browser", "close", "quit", "end", "exit"],
            parameters={"type": "object", "properties": {}, "required": []},
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        manager = _manager(ctx)
        await manager.close()
        return ToolResult(output="browser closed", data={"running": False})


BUILTIN_TOOLS: list[Tool] = [
    BrowserOpen(),
    BrowserSearch(),
    BrowserClick(),
    BrowserType(),
    BrowserExtract(),
    BrowserDownload(),
    BrowserUpload(),
    BrowserClose(),
]
