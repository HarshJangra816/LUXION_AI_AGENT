"""Settings → Desktop config API: bundle, patch, reset (PRD §32, Phase 7).

Mirrors :mod:`tests.test_browser_api` — the desktop overlay lives in
``desktop.json`` the same way the browser overlay lives in ``browser.json``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from luxion.config import desktop_override
from luxion.config.settings import DesktopConfig, get_settings, reset_settings_cache


@pytest.fixture()
def clean_desktop(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep desktop.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    desktop_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    desktop_override.clear_overrides(data_dir)
    reset_settings_cache()


# ------------------------------------------------------------------- bundle
def test_config_read_reports_defaults_and_status(clean_desktop: TestClient) -> None:
    bundle = clean_desktop.get("/api/desktop").json()

    assert set(bundle) == {"config", "defaults", "status"}
    assert bundle["defaults"] == DesktopConfig().model_dump()
    assert set(bundle["config"]) == set(DesktopConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {
        "supported",
        "platform",
        "ui_automation",
        "windows",
        "input_capability",
        "input_capability_reason",
        "enabled",
    }
    # This suite runs on Windows, so the platform is live; on any other host the
    # card must still render, reporting `supported: False` instead of failing.
    assert isinstance(status["supported"], bool)
    assert isinstance(status["windows"], int)
    assert status["enabled"] is True


def test_config_patch_covers_every_desktop_knob() -> None:
    from luxion.api.routes.desktop import DesktopConfigPatch

    assert DesktopConfigPatch.model_config.get("extra") == "forbid"
    patch_fields = set(DesktopConfigPatch.model_fields)
    config_fields = set(DesktopConfig.model_fields)
    assert patch_fields == config_fields


# --------------------------------------------------------------------- put
def test_config_patch_persists_and_merges(clean_desktop: TestClient) -> None:
    first = clean_desktop.put("/api/desktop/config", json={"ui_automation": False})
    assert first.status_code == 200
    assert first.json()["config"]["ui_automation"] is False

    # Untouched knobs keep the value they had before the patch.
    second = clean_desktop.put("/api/desktop/config", json={"max_elements": 120})
    assert second.status_code == 200
    config = second.json()["config"]
    assert config["ui_automation"] is False
    assert config["max_elements"] == 120
    assert config["enabled"] is DesktopConfig().enabled

    # Only what the user touched lands in desktop.json, so .env keeps the rest.
    stored = desktop_override.load_overrides(get_settings().app.data_dir)
    assert set(stored) == {"ui_automation", "max_elements"}


def test_config_patch_drops_invalid_values(clean_desktop: TestClient) -> None:
    # An out-of-range count is ignored (same contract as the browser/voice
    # overlays) rather than failing the whole card save.
    response = clean_desktop.put("/api/desktop/config", json={"max_elements": 50_000})
    assert response.status_code == 200
    assert response.json()["config"]["max_elements"] == DesktopConfig().max_elements


def test_config_patch_rejects_unknown_fields(clean_desktop: TestClient) -> None:
    response = clean_desktop.put("/api/desktop/config", json={"not_a_knob": 1})
    assert response.status_code == 422


# ------------------------------------------------------------------ delete
def test_config_reset_returns_to_defaults(clean_desktop: TestClient) -> None:
    clean_desktop.put("/api/desktop/config", json={"focus_delay_s": 1.5})

    reset = clean_desktop.delete("/api/desktop/config")
    assert reset.status_code == 200
    assert reset.json()["config"] == DesktopConfig().model_dump()
    assert desktop_override.load_overrides(get_settings().app.data_dir) == {}


def test_config_reset_is_idempotent(clean_desktop: TestClient) -> None:
    for _ in range(2):
        response = clean_desktop.delete("/api/desktop/config")
        assert response.status_code == 200
        assert response.json()["config"] == DesktopConfig().model_dump()
