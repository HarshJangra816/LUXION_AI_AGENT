"""News headlines (PRD §37 "News", Phase 9).

Keyless sources, parsed with the stdlib ``xml.etree`` (no feedparser dep):

- a curated set of public RSS/Atom feeds grouped by topic (world, business,
  technology, science) from the BBC and The Guardian;
- the Hacker News Algolia API (JSON) for the ``hackernews`` topic.

Feeds are fetched concurrently and merged, then sorted newest-first. A feed
that fails is skipped rather than failing the whole call — one dead outlet
must not cost the user their headlines.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from luxion.web.errors import WebError
from luxion.web.http import get_json, get_text

HN_URL = "https://hn.algolia.com/api/v1/search"

#: Curated public feeds per topic — (outlet, url).
FEEDS: dict[str, list[tuple[str, str]]] = {
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Guardian World", "https://www.theguardian.com/world/rss"),
    ],
    "business": [
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("Guardian Business", "https://www.theguardian.com/business/rss"),
    ],
    "technology": [
        ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ],
    "science": [
        ("BBC Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        ("Guardian Science", "https://www.theguardian.com/science/rss"),
    ],
    "hackernews": [],
}

#: Every selectable topic, for the tool enum and Settings.
TOPICS = [*FEEDS, "top"]
FEEDS["top"] = [
    ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Guardian", "https://www.theguardian.com/international/rss"),
]


def _text(node: ElementTree.Element, tag: str) -> str:
    """Child text by local tag name — works for RSS (bare) and Atom (namespaced)."""
    for child in node:
        if child.tag.split("}")[-1] == tag:
            return (child.text or "").strip() if child.text else ""
    return ""


def parse_date(raw: str) -> datetime | None:
    """RFC-822 (RSS) or ISO-8601 (Atom) → aware UTC datetime, else ``None``."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def parse_feed(xml_text: str, *, outlet: str) -> list[dict[str, Any]]:
    """Parse an RSS 2.0 or Atom document into normalised article dicts."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise WebError(f"{outlet} feed is not valid XML: {exc}", source=outlet) from exc

    articles: list[dict[str, Any]] = []
    # RSS: <rss><channel><item>…  Atom: <feed><entry>…  (namespaces stripped).
    items = [node for node in root.iter() if node.tag.split("}")[-1] in {"item", "entry"}]
    for item in items:
        title = _text(item, "title")
        if not title:
            continue
        link = _text(item, "link")
        if not link:
            # Atom often keeps the href on a <link rel="alternate"> child.
            for child in item:
                if child.tag.split("}")[-1] == "link":
                    link = child.get("href") or link
        published = parse_date(
            _text(item, "pubDate") or _text(item, "published") or _text(item, "updated")
        )
        articles.append(
            {
                "outlet": outlet,
                "title": title,
                "url": link,
                "published_at": published,
                "summary": _summary(item),
            }
        )
    return articles


def _summary(item: ElementTree.Element) -> str:
    for tag in ("description", "summary", "content"):
        raw = _text(item, tag)
        if raw:
            from luxion.web._html import strip_tags

            return strip_tags(raw)[:400]
    return ""


async def _one_feed(outlet: str, url: str, settings: Any) -> list[dict[str, Any]]:
    text = await get_text(url, settings=settings)
    return parse_feed(text, outlet=outlet)


async def _hackernews(limit: int, settings: Any) -> list[dict[str, Any]]:
    data = await get_json(
        HN_URL, params={"tags": "front_page", "hitsPerPage": limit}, settings=settings
    )
    hits = data.get("hits") if isinstance(data, dict) else None
    articles: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict) or not hit.get("title"):
            continue
        articles.append(
            {
                "outlet": "Hacker News",
                "title": str(hit["title"]),
                "url": str(
                    hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                ),
                "published_at": parse_date(str(hit.get("created_at") or "")),
                "summary": "",
                "points": hit.get("points"),
                "comments": hit.get("num_comments"),
            }
        )
    return _dedupe(articles)


def _dedupe(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeated stories, preserving the newest-first order.

    Two failure modes are merged away here: an outlet's own channel lists one
    headline twice (the BBC's top feed does — same title *and* link), and two
    outlets reprint the same wire piece under different links but the *same*
    title. Tracking both keys means either repetition drops the copy, so the
    model never counts one story as two.
    """
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []
    for article in articles:
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or "").strip()
        if (url and url in seen_urls) or (title and title in seen_titles):
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        unique.append(article)
    return unique


async def fetch_news(
    topic: str = "top", *, limit: int = 8, settings: Any = None
) -> list[dict[str, Any]]:
    """Fetch and merge headlines for ``topic``, newest first."""
    topic = topic if topic in FEEDS else "top"
    limit = max(1, min(int(limit), 25))

    if topic == "hackernews":
        return await _hackernews(limit, settings)

    feeds = FEEDS[topic]
    batches = await asyncio.gather(
        *(_one_feed(outlet, url, settings) for outlet, url in feeds),
        return_exceptions=True,
    )
    articles: list[dict[str, Any]] = []
    for batch in batches:
        if isinstance(batch, list):
            articles.extend(batch)
    if not articles:
        raise WebError(f"no news feed for '{topic}' returned any headlines", source="news")
    articles.sort(
        key=lambda row: row.get("published_at") or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return _dedupe(articles)[:limit]


def format_headlines(topic: str, articles: list[dict[str, Any]]) -> str:
    if not articles:
        return f"No {topic} headlines were returned."
    lines = [f"Latest {topic} headlines:"]
    for index, article in enumerate(articles, 1):
        when = (
            article["published_at"].strftime("%Y-%m-%d %H:%M UTC")
            if article.get("published_at")
            else "undated"
        )
        line = f"{index}. {article['title']} — {article['outlet']} ({when})"
        if article.get("points") is not None:
            line += f", {article['points']} points, {article.get('comments', 0)} comments"
        lines.append(line)
    return "\n".join(lines)
