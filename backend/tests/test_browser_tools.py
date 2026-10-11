"""Phase 6 unit tests: browser manager + browser tools (PRD §5.7, §33.6).

Everything runs against a fake Playwright session — no real browser, no
Chromium download, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from luxion.browser.manager import (
    BrowserError,
    BrowserManager,
    BrowserSession,
    close_browser_manager,
    get_browser_manager,
    reset_browser_manager,
    set_browser_launcher,
)
from luxion.config.settings import get_settings
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.browser import (
    BUILTIN_TOOLS,
    BrowserClick,
    BrowserClose,
    BrowserDownload,
    BrowserExtract,
    BrowserOpen,
    BrowserSearch,
    BrowserType,
    BrowserUpload,
    is_result_link,
    normalize_url,
    unwrap_result,
)


# ------------------------------------------------------------------- fakes
class FakeResponse:
    def __init__(
        self, status: int = 200, *, url: str = "", headers: dict | None = None, body: bytes = b""
    ) -> None:
        self.status = status
        self.url = url
        self.headers = headers or {}
        self._body = body

    @property
    def ok(self) -> bool:
        return self.status < 400

    async def body(self) -> bytes:
        return self._body


class FakeRequestContext:
    def __init__(self, page: FakePage) -> None:  # noqa: F821
        self._page = page
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        self.calls.append({"url": url, "timeout": timeout})
        return self._page.download_response or FakeResponse(200, url=url, body=b"file-bytes")


class FakePage:
    """Records every call the tools make; canned responses per method."""

    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.title_text = "Fake Page"
        self.inner_text_value = "hello world"
        self.evaluate_results: dict[str, Any] = {}
        self.goto_status = 200
        self.download_response: FakeResponse | None = None
        self.click_error: Exception | None = None

    def _record(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))

    async def goto(self, url: str, timeout: float | None = None) -> FakeResponse:
        self._record("goto", url=url, timeout=timeout)
        self.url = url
        return FakeResponse(self.goto_status, url=url)

    async def title(self) -> str:
        self._record("title")
        return self.title_text

    async def inner_text(self, selector: str) -> str:
        self._record("inner_text", selector=selector)
        return self.inner_text_value

    async def click(self, path: str, timeout: float | None = None) -> None:
        self._record("click", path=path, timeout=timeout)
        if self.click_error is not None:
            raise self.click_error

    async def fill(self, selector: str, text: str, timeout: float | None = None) -> None:
        self._record("fill", selector=selector, text=text, timeout=timeout)

    async def press(self, selector: str, key: str, timeout: float | None = None) -> None:
        self._record("press", selector=selector, key=key, timeout=timeout)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        self._record("evaluate", expression=expression, arg=arg)
        return self.evaluate_results.get(expression)

    async def set_input_files(self, selector: str, path: str, timeout: float | None = None) -> None:
        self._record("set_input_files", selector=selector, path=path, timeout=timeout)


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.request = FakeRequestContext(page)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def make_fake_session(page: FakePage | None = None) -> tuple[BrowserSession, FakePage, FakeContext]:
    page = page or FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)
    session = BrowserSession(page=page, context=context, browser=browser, playwright=playwright)
    return session, page, context


@pytest.fixture()
def fake_session(monkeypatch: pytest.MonkeyPatch):
    """Install a manager whose launcher returns one canned session."""
    session, page, context = make_fake_session()

    async def launcher(config) -> BrowserSession:  # noqa: ANN001, ANN202
        return session

    set_browser_launcher(launcher)
    yield session, page, context
    reset_browser_manager()


def ctx() -> ToolContext:
    return ToolContext(get_settings())


# ------------------------------------------------------------------ manager
def test_manager_refuses_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    settings.browser.enabled = False
    manager = BrowserManager(settings)
    with pytest.raises(BrowserError, match="disabled"):
        asyncio_run(manager.session())
    settings.browser.enabled = True


def asyncio_run(coro):  # noqa: ANN001, ANN201
    import asyncio

    return asyncio.run(coro)


def test_manager_launches_lazily_and_reuses_session() -> None:
    async def scenario() -> None:
        launches: list[int] = []

        async def launcher(config) -> BrowserSession:  # noqa: ANN001, ANN202
            launches.append(1)
            session, _, _ = make_fake_session()
            return session

        manager = BrowserManager(get_settings(), launcher=launcher)
        first = await manager.session()
        second = await manager.session()
        assert first is second
        assert len(launches) == 1
        assert manager.running is True
        await manager.close()
        assert manager.running is False

    asyncio_run(scenario())


def test_close_is_idempotent_and_never_raises() -> None:
    async def scenario() -> None:
        session, _, context = make_fake_session()

        async def launcher(config) -> BrowserSession:  # noqa: ANN001, ANN202
            return session

        manager = BrowserManager(get_settings(), launcher=launcher)
        await manager.session()
        await manager.close()
        await manager.close()
        assert context.closed is True

    asyncio_run(scenario())


def test_status_reports_config_and_session() -> None:
    manager = BrowserManager(get_settings())
    status = manager.status()
    assert status["enabled"] is True
    assert status["running"] is False
    assert status["url"] is None
    assert status["search_engine"] in ("duckduckgo", "google", "bing")
    assert status["download_dir"]


def test_singleton_helpers_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_browser_manager()
    manager = get_browser_manager(get_settings())
    assert get_browser_manager() is manager
    close_browser_manager_fn = close_browser_manager

    async def scenario() -> None:
        await close_browser_manager_fn()

    asyncio_run(scenario())
    reset_browser_manager()


# -------------------------------------------------------------------- tools
def test_tool_names_and_specs() -> None:
    names = [t.spec.name for t in BUILTIN_TOOLS]
    assert names == [
        "browser_open",
        "browser_search",
        "browser_click",
        "browser_type",
        "browser_extract",
        "browser_download",
        "browser_upload",
        "browser_close",
    ]
    for tool_ in BUILTIN_TOOLS:
        assert tool_.spec.description
        assert set(tool_.spec.parameters.get("required", [])) <= set(
            tool_.spec.parameters.get("properties", {})
        )


def test_normalize_url_blocks_dangerous_schemes() -> None:
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://example.com") == "http://example.com"
    for scheme in ("javascript:", "file:", "data:", "vbscript:"):
        with pytest.raises(ToolError, match="blocked"):
            normalize_url(f"{scheme}alert(1)")


def test_unwrap_and_filter_search_results() -> None:
    google = "https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fpage&sa=U"
    ddg = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&t=h"
    assert unwrap_result(google) == "https://example.com/page"
    assert unwrap_result(ddg) == "https://python.org/"
    assert is_result_link("https://example.com", "duckduckgo") is True
    assert is_result_link("https://www.google.com/search?q=x", "google") is False
    assert is_result_link("javascript:void(0)", "google") is False


def test_browser_open_navigates_and_reports(fake_session) -> None:
    session, page, _ = fake_session
    page.title_text = "Example Domain"
    result = asyncio_run(BrowserOpen().run({"url": "example.com"}, ctx()))
    assert result.ok
    assert "Example Domain" in result.output
    assert page.calls[0][0] == "goto"
    assert page.calls[0][1]["url"] == "https://example.com"


def test_browser_open_surfaces_http_errors(fake_session) -> None:
    session, page, _ = fake_session
    page.goto_status = 404
    result = asyncio_run(BrowserOpen().run({"url": "https://example.com/missing"}, ctx()))
    assert result.ok is False
    assert "404" in (result.error or "")


def test_browser_search_filters_and_limits(fake_session) -> None:
    session, page, _ = fake_session
    # The page returns engine-internal + real links; the tool must keep only
    # the real ones (after unwrapping redirects).
    from luxion.tools.builtin.browser import _COLLECT_LINKS_JS

    page.evaluate_results[_COLLECT_LINKS_JS] = [
        {"title": "DuckDuckGo", "href": "https://duckduckgo.com/settings"},
        {"title": "Python", "href": "https://www.google.com/url?q=https%3A%2F%2Fpython.org%2F"},
        {"title": "Rust", "href": "https://www.rust-lang.org/"},
        {"title": "Empty href", "href": ""},
    ]
    result = asyncio_run(BrowserSearch().run({"query": "programming", "limit": 5}, ctx()))
    assert result.ok
    urls = [item["url"] for item in result.data["results"]]
    assert urls == ["https://python.org/", "https://www.rust-lang.org/"]


def test_browser_search_requires_a_query(fake_session) -> None:
    with pytest.raises(ToolError, match="empty"):
        asyncio_run(BrowserSearch().run({"query": "   "}, ctx()))


def test_browser_click_selector_or_text(fake_session) -> None:
    session, page, _ = fake_session
    asyncio_run(BrowserClick().run({"selector": "button#go"}, ctx()))
    method, kwargs = page.calls[-1]
    assert method == "click"
    assert kwargs["path"] == "button#go"
    asyncio_run(BrowserClick().run({"text": "Sign in"}, ctx()))
    assert page.calls[-1][1]["path"] == "text=Sign in"
    with pytest.raises(ToolError):
        asyncio_run(BrowserClick().run({}, ctx()))
    with pytest.raises(ToolError, match="not both"):
        asyncio_run(BrowserClick().run({"selector": "a", "text": "b"}, ctx()))


def test_browser_type_fills_and_submits(fake_session) -> None:
    session, page, _ = fake_session
    asyncio_run(BrowserType().run({"selector": "input[name=q]", "text": "hi"}, ctx()))
    assert ("fill", {"selector": "input[name=q]", "text": "hi", "timeout": 10000.0}) in page.calls
    asyncio_run(
        BrowserType().run({"selector": "input[name=q]", "text": "hi", "submit": True}, ctx())
    )
    assert (
        "press",
        {"selector": "input[name=q]", "key": "Enter", "timeout": 10000.0},
    ) in page.calls


def test_browser_extract_clips_text(fake_session) -> None:
    session, page, _ = fake_session
    page.inner_text_value = "x" * 20000
    result = asyncio_run(BrowserExtract().run({}, ctx()))
    assert result.ok
    assert len(result.data["text"]) == get_settings().browser.extract_max_chars
    assert "(clipped)" in result.output


def test_browser_extract_include_links(fake_session) -> None:
    session, page, _ = fake_session
    from luxion.tools.builtin.browser import _COLLECT_LINKS_JS

    page.evaluate_results[_COLLECT_LINKS_JS] = [{"title": "One", "href": "https://a.example/"}]
    result = asyncio_run(BrowserExtract().run({"include_links": True}, ctx()))
    assert result.data["links"] == [{"title": "One", "url": "https://a.example/"}]


def test_browser_download_saves_bytes(fake_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, page, context = fake_session
    page.download_response = FakeResponse(
        200,
        headers={"content-disposition": 'attachment; filename="report.pdf"'},
        body=b"%PDF",
    )
    downloads = get_settings().app.data_dir / "downloads-test"
    get_settings().browser.download_dir = downloads
    try:
        result = asyncio_run(
            BrowserDownload().run({"url": "https://example.com/report.pdf"}, ctx())
        )
        assert result.ok
        saved = downloads / "report.pdf"
        assert saved.exists()
        assert saved.read_bytes() == b"%PDF"
        saved.unlink()
    finally:
        get_settings().browser.download_dir = None


def test_browser_download_maps_http_errors(fake_session) -> None:
    session, page, _ = fake_session
    page.download_response = FakeResponse(403, url="https://example.com/x")
    with pytest.raises(ToolError, match="403"):
        asyncio_run(BrowserDownload().run({"url": "https://example.com/x"}, ctx()))


def test_browser_upload_checks_workspace(tmp_path, fake_session) -> None:
    session, page, _ = fake_session
    inside = tmp_path / "upload.txt"
    inside.write_text("payload", encoding="utf-8")
    settings = get_settings()
    original = list(settings.security.allowed_workspaces)
    settings.security.allowed_workspaces = [tmp_path]
    try:
        result = asyncio_run(
            BrowserUpload().run({"selector": "input[type=file]", "path": str(inside)}, ctx())
        )
        assert result.ok
        assert (
            "set_input_files",
            {"selector": "input[type=file]", "path": str(inside), "timeout": 10000.0},
        ) in page.calls
        with pytest.raises(ToolError):
            asyncio_run(
                BrowserUpload().run(
                    {"selector": "input", "path": str(tmp_path / "missing.txt")}, ctx()
                )
            )
    finally:
        settings.security.allowed_workspaces = original


def test_browser_close_shuts_the_session(fake_session) -> None:
    session, page, context = fake_session
    # The session only exists after something launches it.
    asyncio_run(BrowserOpen().run({"url": "https://example.com"}, ctx()))
    assert context.closed is False
    result = asyncio_run(BrowserClose().run({}, ctx()))
    assert result.ok
    assert context.closed is True


def test_tools_error_clearly_when_browser_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_browser_manager()
    settings = get_settings()
    settings.browser.enabled = False

    async def launcher(config) -> BrowserSession:  # noqa: ANN001, ANN202
        raise AssertionError("launcher must not run while disabled")

    set_browser_launcher(launcher)
    try:
        from luxion.tools.builtin.youtube import YouTubeSearch

        cases = [
            (BrowserOpen(), {"url": "https://example.com"}),
            (BrowserSearch(), {"query": "x"}),
            (YouTubeSearch(), {"query": "x"}),
        ]
        for tool_, args in cases:
            with pytest.raises(ToolError, match="disabled"):
                asyncio_run(tool_.run(args, ctx()))
    finally:
        settings.browser.enabled = True
        reset_browser_manager()
