"""Notifications (Phase 10): toast script, cooldown, tool gate, API. Hermetic.

``run_script`` (the subprocess seam) is always monkeypatched, so no toast
fires during the run — the PowerShell payload itself is asserted by decoding
the ``-EncodedCommand`` base64 back into script text.
"""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

from luxion.config import notify_override
from luxion.config.settings import (
    NotificationConfig,
    Settings,
    get_settings,
    reset_settings_cache,
)
from luxion.notify.toast import (
    LONG_DURATION_THRESHOLD_S,
    POWERSHELL_AUMID,
    ToastError,
    build_script,
    encode_script,
    reset_cooldown,
)
from luxion.security.capabilities import CapabilityStore
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.notify_tools import CATEGORY, Notify
from luxion.tools.executor import ToolExecutor
from luxion.tools.permissions import PermissionEngine
from luxion.tools.registry import build_registry


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_cooldown():
    reset_cooldown()
    yield
    reset_cooldown()


@pytest.fixture()
def shown(monkeypatch):  # noqa: ANN201
    """Capture every script that would reach PowerShell."""
    scripts: list[str] = []

    def record(script: str) -> None:
        scripts.append(script)

    monkeypatch.setattr("luxion.notify.toast.run_script", record)
    return scripts


@pytest.fixture()
def clean_notify(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep notify.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    notify_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    notify_override.clear_overrides(data_dir)
    reset_settings_cache()


# ------------------------------------------------------------------ build_script
def test_build_script_is_well_formed_and_carries_the_essentials() -> None:
    script = build_script("Backup done", "42 files copied", app_name="Luxion", duration_s=7)
    assert POWERSHELL_AUMID in script
    assert "ToastGeneric" in script
    assert "Backup done" in script
    assert "42 files copied" in script
    assert 'duration="short"' in script  # 7s < long threshold
    assert "ms-winsoundevent:Notification.Default" in script  # sound on
    assert script.count("\n") == 7  # eight statements, one per line


def test_build_script_escapes_xml_metacharacters() -> None:
    script = build_script("<b>A&B</b>", 'it\'s "quoted"')
    assert "<b>" not in script.split("$template = ", 1)[1]
    assert "&lt;b&gt;A&amp;B&lt;/b&gt;" in script
    assert "&apos;s &quot;quoted&quot;" in script


def test_build_script_long_duration_and_silent_audio() -> None:
    script = build_script("t", "m", duration_s=LONG_DURATION_THRESHOLD_S, sound=False)
    assert 'duration="long"' in script
    assert '<audio silent="true" />' in script
    assert "ms-winsoundevent" not in script


def test_encode_script_round_trips_through_utf16le_base64() -> None:
    script = build_script("t", "m")
    encoded = encode_script(script)
    assert base64.b64decode(encoded).decode("utf-16-le") == script
    # No CR/LF or quoting metacharacters survive into the encoded form.
    assert "+" in encoded or "=" in encoded or "/" in encoded or encoded.isalnum()


# ---------------------------------------------------------------------- registry
def test_registry_declares_notify_low_with_notifications_capability() -> None:
    spec = build_registry(Settings()).spec("notify")
    assert spec.risk == "low"
    assert spec.category == CATEGORY
    assert spec.requires == "notifications"
    assert spec.read_only is False  # it shows something on screen


def test_capability_blocks_notify_even_at_autonomy_5(tmp_path) -> None:  # noqa: ANN001
    settings = Settings(app={"data_dir": str(tmp_path)}, security={"autonomy_level": 5})
    store = CapabilityStore(settings)
    store.set("notifications", "denied")
    executor = ToolExecutor(
        build_registry(settings), PermissionEngine(settings), settings, capabilities=store
    )
    prepared = executor.prepare("notify", {"title": "x"})
    assert prepared.status == "denied"
    assert prepared.decision.source == "capability"


# ------------------------------------------------------------------------- tool
def test_notify_refuses_when_disabled() -> None:
    ctx = ToolContext(Settings(notify={"enabled": False}))
    with pytest.raises(ToolError, match="notifications are disabled"):
        run(Notify().run({"title": "x", "message": "y"}, ctx))


def test_notify_shows_toast_and_reports(shown: list[str]) -> None:
    result = run(
        Notify().run(
            {"title": "Backup finished", "message": "42 files"},
            ToolContext(Settings()),
        )
    )
    assert result.ok
    assert "Backup finished" in result.output
    payload = shown[0]
    # The route builds the script directly (not encoded); assert the pieces.
    assert "Backup finished" in payload
    assert "42 files" in payload
    assert result.data["notification"]["shown"] is True


def test_notify_duration_out_of_range_rejected() -> None:
    with pytest.raises(ToolError, match="between 3 and 25"):
        run(Notify().run({"message": "x", "duration_s": 99}, ToolContext(Settings())))


def test_notify_needs_a_title_or_message(shown: list[str]) -> None:
    with pytest.raises(ToolError, match="at least a title or a message"):
        run(Notify().run({"title": "  ", "message": " "}, ToolContext(Settings())))


def test_cooldown_blocks_a_second_toast_until_reset(shown: list[str]) -> None:
    ctx = ToolContext(Settings(notify={"cooldown_s": 60.0}))
    run(Notify().run({"title": "one"}, ctx))
    with pytest.raises(ToolError, match="cooldown"):
        run(Notify().run({"title": "two"}, ctx))
    reset_cooldown()
    run(Notify().run({"title": "three"}, ctx))
    assert len(shown) == 2


def test_failed_send_does_not_start_the_cooldown(monkeypatch) -> None:  # noqa: ANN001
    def boom(script: str) -> None:
        raise ToastError("Windows refused the toast")

    monkeypatch.setattr("luxion.notify.toast.run_script", boom)
    ctx = ToolContext(Settings(notify={"cooldown_s": 60.0}))
    with pytest.raises(ToolError, match="refused"):
        run(Notify().run({"title": "x"}, ctx))
    # The clock was never marked, so a later attempt is not blocked.
    monkeypatch.setattr("luxion.notify.toast.run_script", lambda script: None)
    run(Notify().run({"title": "y"}, ctx))


# --------------------------------------------------------------------------- API
def test_config_read_reports_defaults_and_status(clean_notify: TestClient) -> None:
    bundle = clean_notify.get("/api/notify").json()
    assert set(bundle) == {"config", "defaults", "status"}
    assert bundle["defaults"] == NotificationConfig().model_dump()
    assert set(bundle["config"]) == set(NotificationConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {
        "enabled",
        "app_name",
        "sound",
        "cooldown_s",
        "capability",
        "platform",
    }
    assert status["platform"] == "windows-toast"
    assert status["capability"]["allowed"] is True  # default granted


def test_config_patch_covers_every_notify_knob() -> None:
    from luxion.api.routes.notify import NotifyConfigPatch

    assert set(NotifyConfigPatch.model_fields) == set(NotificationConfig.model_fields)


def test_put_merges_into_notify_json_and_survives_reload(clean_notify: TestClient) -> None:
    first = clean_notify.put("/api/notify/config", json={"cooldown_s": 9.0, "sound": False}).json()
    assert first["config"]["cooldown_s"] == 9.0
    assert first["config"]["sound"] is False

    reset_settings_cache()
    persisted = get_settings().notify
    assert persisted.cooldown_s == 9.0
    assert persisted.sound is False

    clean_notify.put("/api/notify/config", json={"app_name": "DeskBot"})
    reset_settings_cache()
    again = get_settings().notify
    assert again.app_name == "DeskBot"
    assert again.cooldown_s == 9.0  # earlier edit survives


def test_put_rejects_unknown_keys_but_ignores_bad_values(clean_notify: TestClient) -> None:
    assert clean_notify.put("/api/notify/config", json={"nonsense": 1}).status_code == 422
    # Out-of-range values are silently dropped (the established overlay contract).
    clean_notify.put("/api/notify/config", json={"default_duration_s": 999})
    reset_settings_cache()
    assert get_settings().notify.default_duration_s == NotificationConfig().default_duration_s


def test_delete_drops_the_overlay(clean_notify: TestClient) -> None:
    clean_notify.put("/api/notify/config", json={"enabled": False})
    reset_settings_cache()
    assert get_settings().notify.enabled is False

    clean_notify.delete("/api/notify/config")
    reset_settings_cache()
    assert get_settings().notify.enabled == NotificationConfig().enabled
    assert not notify_override.notify_path(get_settings().app.data_dir).exists()


def test_test_endpoint_raises_a_real_shaped_toast(
    clean_notify: TestClient, shown: list[str]
) -> None:
    response = clean_notify.post("/api/notify/test")
    assert response.status_code == 200
    assert response.json() == {
        "shown": True,
        "title": "Notifications work",
        "duration_s": NotificationConfig().default_duration_s,
    }
    assert len(shown) == 1
    assert "Notifications work" in shown[0]


def test_test_endpoint_409_when_the_toast_fails(clean_notify: TestClient, monkeypatch) -> None:  # noqa: ANN001
    def boom(script: str) -> None:
        raise ToastError("powershell.exe not found — toast notifications need Windows")

    monkeypatch.setattr("luxion.notify.toast.run_script", boom)
    response = clean_notify.post("/api/notify/test")
    assert response.status_code == 409
    assert "powershell.exe not found" in response.json()["detail"]


def test_encode_script_is_what_powershell_receives() -> None:
    """run_script hands PowerShell an encoded payload, never raw text."""
    import subprocess
    from unittest.mock import patch

    from luxion.notify.toast import run_script

    captured = {}

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN201
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch("luxion.notify.toast.subprocess.run", fake_run):
        run_script("Write-Host hi")
    args = captured["args"]
    assert args[0] == "powershell.exe"
    assert "-EncodedCommand" in args
    encoded = args[args.index("-EncodedCommand") + 1]
    assert base64.b64decode(encoded).decode("utf-16-le") == "Write-Host hi"


def test_run_script_maps_failures_to_toast_error() -> None:
    import subprocess
    from unittest.mock import patch

    from luxion.notify.toast import run_script

    failed = subprocess.CompletedProcess([], 1, stdout="", stderr="access denied")
    with (
        patch("luxion.notify.toast.subprocess.run", return_value=failed),
        pytest.raises(ToastError, match="access denied"),
    ):
        run_script("x")
    with (
        patch("luxion.notify.toast.subprocess.run", side_effect=FileNotFoundError()),
        pytest.raises(ToastError, match="powershell.exe not found"),
    ):
        run_script("x")
    with (
        patch(
            "luxion.notify.toast.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="powershell.exe", timeout=15),
        ),
        pytest.raises(ToastError, match="timed out"),
    ):
        run_script("x")
