"""DuckDuckGo HTML search (PRD §37 "Search", Phase 9).

Keyless and fast: ``html.duckduckgo.com`` serves plain result markup with no
JavaScript, API key or rate-limit agreement, so ``web_search`` is a single GET
and keeps working even while Playwright browser automation (Phase 6) is off.
``browser_search`` still exists for the minority of queries that truly need a
rendered page.

Results are unwrapped from DDG's ``/l/?uddg=`` redirect so the model sees the
real destination URL, and snippets are de-tagged to plain text.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from luxion.web._html import strip_tags
from luxion.web.http import get_text

#: The no-JS results endpoint (``kl`` selects the region; ``wt-wt`` = world).
SEARCH_URL = "https://html.duckduckgo.com/html/"

_RESULT_A = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET = re.compile(
    r'<(?:a[^>]*class="result__snippet"|td[^>]*class="result-snippet")[^>]*>(.*?)</(?:a|td)>',
    re.IGNORECASE | re.DOTALL,
)


def unwrap(href: str) -> str:
    """Resolve DuckDuckGo's ``/l/?uddg=`` redirect to the real target URL.

    Non-redirect links are returned untouched, so a relative or malformed href
    never turns into a silent ``duckduckgo.com`` result.
    """
    if href.startswith("//"):
        href = f"https:{href}"
    parts = urlsplit(href)
    if "duckduckgo.com" in parts.netloc and parts.path.startswith("/l/"):
        target = (parse_qs(parts.query).get("uddg") or [""])[0]
        if target:
            return target
    return href


async def search(
    query: str,
    *,
    limit: int = 5,
    region: str = "wt-wt",
    settings: Any = None,
) -> list[dict[str, str]]:
    """Return up to ``limit`` results as ``{title, url, snippet}`` dicts."""
    html = await get_text(
        SEARCH_URL, params={"q": query, "kl": region or "wt-wt"}, settings=settings
    )
    anchors = _RESULT_A.findall(html)
    snippets = _SNIPPET.findall(html)

    results: list[dict[str, str]] = []
    for index, (href, title_html) in enumerate(anchors):
        title = strip_tags(title_html)
        url = unwrap(href)
        if not title or not url or url.startswith("/l/") or url.startswith("/?"):
            continue
        snippet_html = snippets[index] if index < len(snippets) else ""
        results.append({"title": title, "url": url, "snippet": strip_tags(snippet_html)})
        if len(results) >= limit:
            break
    return results
