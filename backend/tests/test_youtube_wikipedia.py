"""Phase 6 unit tests: YouTube (browser session) + Wikipedia (HTTP) tools."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from test_browser_tools import FakePage, make_fake_session

from luxion.browser.manager import reset_browser_manager, set_browser_launcher
from luxion.config.settings import get_settings
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin import wikipedia as wikipedia_module
from luxion.tools.builtin.browser import _YOUTUBE_CONTROL_JS, _YOUTUBE_SEARCH_JS
from luxion.tools.builtin.youtube import (
    YouTubeControl,
    YouTubeOpen,
    YouTubeSearch,
    video_id_from,
)

VIDEO_RESULTS = [
    {"title": "Intro to Luxion", "href": "https://www.youtube.com/watch?v=abc123def45"},
    {"title": "Duplicate", "href": "https://www.youtube.com/watch?v=abc123def45"},
    {"title": "No id here", "href": "https://www.youtube.com/playlist?list=PL123"},
    {"title": "Second video", "href": "https://www.youtube.com/watch?v=zzz987yyy65&t=10s"},
]


def ctx() -> ToolContext:
    return ToolContext(get_settings())


@pytest.fixture()
def fake_session():
    page = FakePage()
    session, page, context = make_fake_session(page)

    async def launcher(config) -> Any:  # noqa: ANN001, ANN202
        return session

    set_browser_launcher(launcher)
    yield session, page, context
    reset_browser_manager()


# ------------------------------------------------------------------- youtube
def test_video_id_from_urls() -> None:
    assert video_id_from("https://www.youtube.com/watch?v=abc123def45") == "abc123def45"
    assert video_id_from("https://youtube.com/watch?v=abc&t=1") == "abc"
    assert video_id_from("https://www.youtube.com/playlist?list=PL1") is None


def test_youtube_search_parses_and_dedupes(fake_session) -> None:
    session, page, _ = fake_session
    page.evaluate_results[_YOUTUBE_SEARCH_JS] = VIDEO_RESULTS
    result = asyncio.run(YouTubeSearch().run({"query": "luxion demo"}, ctx()))
    assert result.ok
    assert [item["video_id"] for item in result.data["results"]] == ["abc123def45", "zzz987yyy65"]
    assert result.data["results"][0]["url"].endswith("watch?v=abc123def45")
    assert page.calls[0][0] == "goto"
    assert "search_query=luxion+demo" in page.calls[0][1]["url"]


def test_youtube_search_requires_query(fake_session) -> None:
    with pytest.raises(ToolError, match="empty"):
        asyncio.run(YouTubeSearch().run({"query": ""}, ctx()))


def test_youtube_open_accepts_url_and_bare_id(fake_session) -> None:
    session, page, _ = fake_session
    page.title_text = "Intro to Luxion - YouTube"
    result = asyncio.run(
        YouTubeOpen().run({"url": "https://www.youtube.com/watch?v=abc123def45"}, ctx())
    )
    assert result.ok
    gotos = [call for call in page.calls if call[0] == "goto"]
    assert gotos[-1][1]["url"].endswith("watch?v=abc123def45")

    result = asyncio.run(YouTubeOpen().run({"url": "abc123def45"}, ctx()))
    assert result.ok
    assert result.data["video_id"] == "abc123def45"


def test_youtube_open_rejects_garbage(fake_session) -> None:
    with pytest.raises(ToolError, match="watch URL"):
        asyncio.run(YouTubeOpen().run({"url": "https://example.com/video"}, ctx()))


def test_youtube_control_play_pause_seek_volume(fake_session) -> None:
    session, page, _ = fake_session
    page.evaluate_results[_YOUTUBE_CONTROL_JS] = {
        "ok": True,
        "action": "play",
        "currentTime": 12.5,
        "volume": 0.8,
        "paused": False,
    }
    result = asyncio.run(YouTubeControl().run({"action": "play"}, ctx()))
    assert result.ok
    assert result.data["current_time"] == 12.5

    asyncio.run(YouTubeControl().run({"action": "seek", "value": 42}, ctx()))
    call = page.calls[-1]
    assert call[0] == "evaluate"
    assert call[1]["arg"] == {"action": "seek", "value": 42.0}

    asyncio.run(YouTubeControl().run({"action": "volume", "value": 3.0}, ctx()))
    assert page.calls[-1][1]["arg"]["value"] == 1.0  # clamped


def test_youtube_control_validates_action_and_value(fake_session) -> None:
    with pytest.raises(ToolError, match="unknown action"):
        asyncio.run(YouTubeControl().run({"action": "rewind"}, ctx()))
    with pytest.raises(ToolError, match="requires a value"):
        asyncio.run(YouTubeControl().run({"action": "seek"}, ctx()))


def test_youtube_control_maps_missing_video(fake_session) -> None:
    session, page, _ = fake_session
    page.evaluate_results[_YOUTUBE_CONTROL_JS] = {
        "ok": False,
        "error": "no <video> element on this page",
    }
    with pytest.raises(ToolError, match="no <video>"):
        asyncio.run(YouTubeControl().run({"action": "pause"}, ctx()))


# ----------------------------------------------------------------- wikipedia
SEARCH_PAYLOAD = {
    "query": {
        "search": [
            {"title": "Luxion", "snippet": 'A <span class="searchmatch">light</span> engine'},
            {"title": "Luxembourg", "snippet": "A country"},
        ]
    }
}


def test_wikipedia_search_calls_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    async def fake_get_json(url: str, params: dict | None = None) -> dict:  # noqa: ANN201
        return handler(httpx.Request("GET", url, params=params)).json()

    monkeypatch.setattr(wikipedia_module, "_get_json", fake_get_json)
    result = asyncio.run(wikipedia_module.WikipediaSearch().run({"query": "luxion"}, ctx()))
    assert result.ok
    assert [item["title"] for item in result.data["results"]] == ["Luxion", "Luxembourg"]
    # HTML highlights are stripped.
    assert result.data["results"][0]["snippet"] == "A light engine"
    assert captured["params"]["list"] == "search"
    assert captured["params"]["srsearch"] == "luxion"


def test_wikipedia_search_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_json(url: str, params: dict | None = None) -> dict:  # noqa: ANN201, ANN001
        return {"query": {"search": []}}

    monkeypatch.setattr(wikipedia_module, "_get_json", fake_get_json)
    result = asyncio.run(wikipedia_module.WikipediaSearch().run({"query": "zzzz"}, ctx()))
    assert result.ok is False


def test_wikipedia_article_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_json(url: str, params: dict | None = None) -> dict:  # noqa: ANN201, ANN001
        assert "/api/rest_v1/page/summary/Luxion" in url
        return {
            "title": "Luxion",
            "description": "Rendering engine",
            "extract": "Luxion is a real-time ray tracer.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Luxion"}},
        }

    monkeypatch.setattr(wikipedia_module, "_get_json", fake_get_json)
    result = asyncio.run(wikipedia_module.WikipediaArticle().run({"title": "Luxion"}, ctx()))
    assert result.ok
    assert "real-time ray tracer" in result.data["extract"]
    assert result.data["url"].endswith("/wiki/Luxion")


def test_wikipedia_article_http_errors_become_tool_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_json(url: str, params: dict | None = None) -> dict:  # noqa: ANN201, ANN001
        raise ToolError("wikipedia answered HTTP 404 for x")

    monkeypatch.setattr(wikipedia_module, "_get_json", fake_get_json)
    with pytest.raises(ToolError, match="404"):
        asyncio.run(wikipedia_module.WikipediaArticle().run({"title": "Nope"}, ctx()))


def test_wikipedia_tools_are_read_only_and_low_risk() -> None:
    for tool in wikipedia_module.BUILTIN_TOOLS:
        assert tool.spec.risk == "low"
        assert tool.spec.read_only is True
