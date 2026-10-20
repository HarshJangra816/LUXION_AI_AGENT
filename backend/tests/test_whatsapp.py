"""WhatsApp automation (Phase 10, PRD §33.3): protocol, manager, DOM ops, tools, API.

Hermetic — a fake launcher (the manager's test seam) hands out canned pages,
so no browser launches and no WhatsApp account is needed. The DOM operations
are exercised against the tiny page surface ``luxion.whatsapp.web`` uses.
"""

from __future__ import annotations

import asyncio
import os
import sys
import webbrowser

import pytest
from fastapi.testclient import TestClient

from luxion.config import whatsapp_override
from luxion.config.settings import (
    Settings,
    WhatsAppConfig,
    get_settings,
    reset_settings_cache,
)
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.whatsapp_tools import (
    CATEGORY,
    WhatsappOpen,
    WhatsappRead,
    WhatsappSend,
)
from luxion.tools.registry import build_registry
from luxion.whatsapp.errors import WhatsAppError
from luxion.whatsapp.manager import (
    WhatsAppManager,
    WhatsAppSession,
    reset_whatsapp_manager,
    set_whatsapp_launcher,
)
from luxion.whatsapp.protocol import build_deep_link, normalize_phone, open_deep_link
from luxion.whatsapp.web import SELECTOR_HINT, grab_qr, probe_login, read_messages, send_message

TIMEOUT = 30_000.0


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


# ------------------------------------------------------------------- fake page
class FakePage:
    """The exact page surface whatsapp/web.py touches."""

    def __init__(self, *, qr: bool = False, search: bool = True, fail_waits: bool = False):
        self.url = "https://web.whatsapp.com/"
        self.qr = qr
        self.search = search
        self.fail_waits = fail_waits
        self.calls: list[tuple] = []
        self.messages = [
            {"text": "hey, are we on for 6?", "outgoing": False},
            {"text": "yes, see you there", "outgoing": True},
        ]

    async def query_selector(self, selector):  # noqa: ANN001
        if "canvas" in selector:
            return object() if self.qr else None
        if "contenteditable" in selector or "textbox" in selector:
            return object() if self.search else None
        return None

    async def wait_for_selector(self, selector, *, timeout=None, state=None):  # noqa: ANN001
        if self.fail_waits:
            raise RuntimeError("Timeout 2000ms exceeded")
        if "canvas" in selector:
            ok = self.qr
        elif "contenteditable" in selector or "textbox" in selector:
            ok = self.search
        else:
            ok = True
        if not ok:
            raise RuntimeError("Timeout 2000ms exceeded")
        self.calls.append(("wait", selector))
        return object()

    async def fill(self, selector, text, *, timeout=None):  # noqa: ANN001
        self.calls.append(("fill", selector, text))

    async def press(self, selector, key, *, timeout=None):  # noqa: ANN001
        self.calls.append(("press", selector, key))

    async def eval_on_selector(self, selector, js):  # noqa: ANN001
        return "data:image/png;base64,AAAA"

    async def eval_on_selector_all(self, selector, js):  # noqa: ANN001
        return list(self.messages)


class FakeContext:
    async def close(self) -> None:
        pass


class FakePlaywright:
    async def stop(self) -> None:
        pass


def install(page: FakePage) -> list:
    """Install a fake launcher returning ``page``; returns the launch log."""
    launches: list[str] = []

    async def launcher(config, profile_dir):  # noqa: ANN001
        launches.append(str(profile_dir))
        return WhatsAppSession(page=page, context=FakeContext(), playwright=FakePlaywright())

    set_whatsapp_launcher(launcher)
    return launches


@pytest.fixture(autouse=True)
def clean_manager():
    reset_whatsapp_manager()
    yield
    reset_whatsapp_manager()


@pytest.fixture()
def clean_whatsapp(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep whatsapp.json hermetic."""
    data_dir = get_settings().app.data_dir
    whatsapp_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    whatsapp_override.clear_overrides(data_dir)
    reset_settings_cache()


def _session(page: FakePage) -> WhatsAppSession:
    return WhatsAppSession(page=page, context=FakeContext(), playwright=FakePlaywright())


# -------------------------------------------------------------------- protocol
def test_build_deep_link_shapes() -> None:
    assert (
        build_deep_link(phone="+44 7700 900123", text="Hi there")
        == "whatsapp://send?phone=447700900123&text=Hi%20there"
    )
    assert build_deep_link(phone="55 11 99999-0000") == "whatsapp://send?phone=5511999990000"
    assert build_deep_link(text="Hello World") == "whatsapp://send?text=Hello%20World"
    assert build_deep_link() == "whatsapp://send"


def test_normalize_phone_rejects_junk() -> None:
    assert normalize_phone("+1 (555) 123-4567") == "15551234567"
    for bad in ("call me later", "12", "++1234567", ""):
        with pytest.raises(WhatsAppError, match="not a usable phone number"):
            normalize_phone(bad)


def test_open_deep_link_hands_the_uri_to_windows(monkeypatch) -> None:  # noqa: ANN001
    seen = []
    monkeypatch.setattr(os, "startfile", lambda uri: seen.append(uri), raising=False)
    outcome = open_deep_link("whatsapp://send?text=hey")
    assert outcome == {"opened": "protocol", "uri": "whatsapp://send?text=hey"}
    assert seen == ["whatsapp://send?text=hey"]


def test_open_deep_link_refuses_foreign_uris() -> None:
    with pytest.raises(WhatsAppError, match="refusing to open"):
        open_deep_link("https://evil.example")


def test_open_deep_link_falls_back_to_wa_me_when_unregistered(monkeypatch) -> None:  # noqa: ANN001
    def raise_os_error(uri):  # noqa: ANN001, ANN201
        raise OSError("no association")

    opened = []
    monkeypatch.setattr(os, "startfile", raise_os_error, raising=False)
    monkeypatch.setattr(webbrowser, "open", lambda url, new=2: opened.append(url) or True)
    outcome = open_deep_link("whatsapp://send?phone=447700900123&text=hi there")
    assert outcome["opened"] == "web"
    # The web equivalent is wa.me/<phone>?text=…, not a literal copy of the
    # protocol query.
    assert outcome["uri"] == "https://wa.me/447700900123?text=hi%20there"
    assert opened == [outcome["uri"]]


def test_open_deep_link_needs_a_browser_to_fall_back_to(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(webbrowser, "open", lambda url, new=2: False)
    monkeypatch.setattr(sys, "platform", "linux")  # skips the startfile branch
    with pytest.raises(WhatsAppError, match="no handler for whatsapp://"):
        open_deep_link("whatsapp://send")


# ---------------------------------------------------------------------- manager
def test_manager_launches_once_and_reports_status(tmp_path) -> None:  # noqa: ANN001
    page = FakePage()
    launches: list[str] = []

    async def launcher(config, profile_dir):  # noqa: ANN001
        launches.append(str(profile_dir))
        return _session(page)

    manager = WhatsAppManager(Settings(app={"data_dir": str(tmp_path)}), launcher=launcher)
    assert manager.running is False
    first = run(manager.session())
    second = run(manager.session())
    assert first is second
    assert launches == [str(tmp_path / "whatsapp_profile")]  # one launch, default profile

    status = manager.status()
    assert set(status) == {
        "enabled",
        "running",
        "headless",
        "logged_in",
        "url",
        "profile_dir",
        "timeout_s",
        "login_timeout_s",
    }
    assert status["running"] is True
    assert status["logged_in"] is None  # nobody looked yet
    assert status["url"] == "https://web.whatsapp.com/"

    run(manager.close())
    assert manager.running is False
    assert manager.status()["logged_in"] is None


def test_manager_honours_a_configured_profile_dir(tmp_path) -> None:  # noqa: ANN001
    custom = tmp_path / "elsewhere"
    manager = WhatsAppManager(
        Settings(app={"data_dir": str(tmp_path)}, whatsapp={"profile_dir": str(custom)}),
        launcher=None,
    )
    assert manager.resolve_profile_dir() == custom


def test_manager_refuses_to_launch_when_disabled() -> None:
    async def launcher(config, profile_dir):  # noqa: ANN001
        raise AssertionError("launcher must not run while disabled")

    manager = WhatsAppManager(Settings(whatsapp={"enabled": False}), launcher=launcher)
    with pytest.raises(WhatsAppError, match="disabled"):
        run(manager.session())


# ------------------------------------------------------------------ DOM ops
def test_probe_login_reads_the_page_state() -> None:
    logged_out = _session(FakePage(qr=True, search=False))
    assert run(probe_login(logged_out)) is False
    assert logged_out.logged_in is False

    logged_in = _session(FakePage(qr=False, search=True))
    assert run(probe_login(logged_in)) is True
    assert logged_in.logged_in is True


def test_grab_qr_returns_a_data_url() -> None:
    session = _session(FakePage(qr=True, search=False))
    qr = run(grab_qr(session, timeout_ms=500))
    assert qr == "data:image/png;base64,AAAA"
    assert session.logged_in is False


def test_selector_drift_says_where_to_fix_it() -> None:
    session = _session(FakePage(qr=True, search=False, fail_waits=True))
    with pytest.raises(WhatsAppError) as excinfo:
        run(grab_qr(session, timeout_ms=2000))
    assert SELECTOR_HINT in str(excinfo.value)
    assert "redesign" in str(excinfo.value)
    assert "luxion/whatsapp/web.py" in str(excinfo.value)


def test_send_message_chats_then_types_then_enter() -> None:
    page = FakePage()
    session = _session(page)
    outcome = run(send_message(session, "Dad", "on my way", timeout_ms=TIMEOUT))
    assert outcome == {"sent": True, "contact": "Dad", "chars": len("on my way")}
    assert session.logged_in is True

    fills = [c for c in page.calls if c[0] == "fill"]
    assert ("fill", fills[0][1], "Dad") in fills  # search box got the contact
    assert fills[-1][2] == "on my way"  # composer got the message
    presses = [c for c in page.calls if c[0] == "press"]
    assert len(presses) == 2 and all(c[2] == "Enter" for c in presses)


def test_send_message_refuses_while_logged_out() -> None:
    session = _session(FakePage(qr=True, search=False))
    with pytest.raises(WhatsAppError, match="scan the QR"):
        run(send_message(session, "Dad", "hi", timeout_ms=TIMEOUT))


def test_read_messages_directions_and_limit() -> None:
    session = _session(FakePage())
    rows = run(read_messages(session, "Dad", limit=1, timeout_ms=TIMEOUT))
    assert rows == [{"text": "yes, see you there", "direction": "out"}]  # limit=1 keeps newest

    rows = run(read_messages(session, "Dad", limit=10, timeout_ms=TIMEOUT))
    assert [r["direction"] for r in rows] == ["in", "out"]


# ------------------------------------------------------------------------ tools
def test_all_three_tools_registered_with_expected_risk() -> None:
    registry = build_registry(Settings())
    expectations = {
        "whatsapp_send": ("high", False),
        "whatsapp_read": ("medium", True),
        "whatsapp_open": ("medium", False),
    }
    for name, (risk, read_only) in expectations.items():
        spec = registry.spec(name)
        assert spec.risk == risk, name
        assert spec.read_only is read_only, name
        assert spec.category == CATEGORY, name
        assert spec.requires is None, name  # login state gates, not a capability


def test_every_whatsapp_tool_refuses_when_disabled() -> None:
    ctx = ToolContext(Settings(whatsapp={"enabled": False}))
    cases = [
        (WhatsappSend(), {"contact": "Dad", "text": "hi"}),
        (WhatsappRead(), {"contact": "Dad"}),
        (WhatsappOpen(), {"text": "hi"}),
    ]
    for tool, args in cases:
        with pytest.raises(ToolError, match="disabled"):
            run(tool.run(args, ctx))


def test_whatsapp_send_tool_reports_delivery() -> None:
    page = FakePage()
    install(page)
    result = run(
        WhatsappSend().run(
            {"contact": "Dad", "text": "on my way"},
            ToolContext(Settings()),
        )
    )
    assert "WhatsApp message sent to Dad" in result.output
    assert result.data["whatsapp"]["sent"] is True


def test_whatsapp_send_tool_maps_login_required(monkeypatch) -> None:  # noqa: ANN001
    install(FakePage(qr=True, search=False))
    with pytest.raises(ToolError, match="scan the QR"):
        run(WhatsappSend().run({"contact": "Dad", "text": "hi"}, ToolContext(Settings())))


def test_whatsapp_send_validates_arguments() -> None:
    install(FakePage())
    with pytest.raises(ToolError, match="contact is required"):
        run(WhatsappSend().run({"contact": " ", "text": "hi"}, ToolContext(Settings())))
    with pytest.raises(ToolError, match="text is required"):
        run(WhatsappSend().run({"contact": "Dad", "text": ""}, ToolContext(Settings())))


def test_whatsapp_read_tool_formats_both_directions() -> None:
    install(FakePage())
    result = run(WhatsappRead().run({"contact": "Dad", "limit": 5}, ToolContext(Settings())))
    assert "last 2 message(s) with Dad" in result.output
    assert "them: hey, are we on for 6?" in result.output
    assert "you: yes, see you there" in result.output
    assert result.data["messages"][0]["direction"] == "in"


def test_whatsapp_read_empty_chat_is_honest() -> None:
    page = FakePage()
    page.messages = []
    install(page)
    result = run(WhatsappRead().run({"contact": "Dad"}, ToolContext(Settings())))
    assert result.ok is False
    assert result.error == "no results"


def test_whatsapp_open_hands_off_to_the_desktop_app(monkeypatch) -> None:  # noqa: ANN001
    seen = []
    monkeypatch.setattr(os, "startfile", lambda uri: seen.append(uri), raising=False)
    result = run(
        WhatsappOpen().run(
            {"contact": "+44 7700 900123", "text": "see you at 6"},
            ToolContext(Settings()),
        )
    )
    assert "WhatsApp desktop" in result.output
    assert seen == ["whatsapp://send?phone=447700900123&text=see%20you%20at%206"]
    assert result.data["whatsapp"]["opened"] == "protocol"


# --------------------------------------------------------------------------- API
def test_config_read_reports_defaults_and_status(clean_whatsapp: TestClient) -> None:
    bundle = clean_whatsapp.get("/api/whatsapp").json()
    assert set(bundle) == {"config", "defaults", "status"}
    assert bundle["defaults"] == WhatsAppConfig().model_dump()
    assert set(bundle["config"]) == set(WhatsAppConfig.model_fields)
    status = bundle["status"]
    assert status["enabled"] is True
    assert status["running"] is False
    assert status["logged_in"] is None
    assert status["profile_dir"].endswith("whatsapp_profile")


def test_config_patch_covers_every_whatsapp_knob() -> None:
    from luxion.api.routes.whatsapp import WhatsAppConfigPatch

    assert set(WhatsAppConfigPatch.model_fields) == set(WhatsAppConfig.model_fields)


def test_put_merges_and_delete_resets(clean_whatsapp: TestClient) -> None:
    first = clean_whatsapp.put("/api/whatsapp/config", json={"headless": False}).json()
    assert first["config"]["headless"] is False
    reset_settings_cache()
    assert get_settings().whatsapp.headless is False

    clean_whatsapp.put("/api/whatsapp/config", json={"timeout_s": 45})
    reset_settings_cache()
    again = get_settings().whatsapp
    assert again.timeout_s == 45
    assert again.headless is False  # earlier edit survives

    assert clean_whatsapp.put("/api/whatsapp/config", json={"nonsense": 1}).status_code == 422

    clean_whatsapp.delete("/api/whatsapp/config")
    reset_settings_cache()
    assert get_settings().whatsapp == WhatsAppConfig()
    assert not whatsapp_override.whatsapp_path(get_settings().app.data_dir).exists()


def test_session_endpoint_returns_qr_while_logged_out(clean_whatsapp: TestClient) -> None:
    page = FakePage(qr=True, search=False)
    launches = install(page)

    response = clean_whatsapp.post("/api/whatsapp/session")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is True
    assert body["logged_in"] is False
    assert body["qr"] == "data:image/png;base64,AAAA"
    assert len(launches) == 1

    # After the scan, the same session reports logged in.
    page.qr = False
    page.search = True
    status = clean_whatsapp.post("/api/whatsapp/status").json()
    assert status["logged_in"] is True

    assert clean_whatsapp.post("/api/whatsapp/close").json() == {"running": False}
    assert clean_whatsapp.get("/api/whatsapp").json()["status"]["running"] is False


def test_session_endpoint_when_already_logged_in(clean_whatsapp: TestClient) -> None:
    install(FakePage(qr=False, search=True))
    body = clean_whatsapp.post("/api/whatsapp/session").json()
    assert body["logged_in"] is True
    assert body["qr"] is None


def test_session_endpoint_409_when_disabled(clean_whatsapp: TestClient) -> None:
    clean_whatsapp.put("/api/whatsapp/config", json={"enabled": False})
    install(FakePage())  # manager built from the now-disabled settings
    response = clean_whatsapp.post("/api/whatsapp/session")
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_status_endpoint_without_a_session_is_calm(clean_whatsapp: TestClient) -> None:
    body = clean_whatsapp.post("/api/whatsapp/status").json()
    assert body == {"running": False, "logged_in": None, "qr": None, "url": None}
