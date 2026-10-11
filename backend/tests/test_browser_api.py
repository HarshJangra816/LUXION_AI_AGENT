"""Settings → Browser config API: bundle, patch, reset (PRD §32, Phase 6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from luxion.browser.manager import reset_browser_manager
from luxion.config import browser_override
from luxion.config.settings import (
    BrowserConfig,
    Settings,
    get_settings,
    reset_settings_cache,
)


@pytest.fixture()
def clean_browser(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep browser.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    browser_override.clear_overrides(data_dir)
    reset_settings_cache()
    reset_browser_manager()
    yield client
    browser_override.clear_overrides(data_dir)
    reset_settings_cache()
    reset_browser_manager()


# ------------------------------------------------------------------- bundle
def test_config_read_reports_defaults_and_status(clean_browser: TestClient) -> None:
    bundle = clean_browser.get("/api/browser").json()

    assert set(bundle) == {"config", "defaults", "status"}
    assert bundle["defaults"] == BrowserConfig().model_dump()
    assert set(bundle["config"]) == set(BrowserConfig.model_fields)
    assert bundle["status"]["enabled"] is True
    assert bundle["status"]["running"] is False
    assert bundle["status"]["search_engine"] == "duckduckgo"
    assert bundle["status"]["download_dir"]


def test_config_patch_covers_every_browser_knob() -> None:
    from luxion.api.routes.browser import BrowserConfigPatch

    assert BrowserConfigPatch.model_config.get("extra") == "forbid"
    patch_fields = set(BrowserConfigPatch.model_fields)
    config_fields = set(BrowserConfig.model_fields)
    assert patch_fields == config_fields


# --------------------------------------------------------------------- put
def test_config_patch_persists_and_merges(clean_browser: TestClient) -> None:
    first = clean_browser.put("/api/browser/config", json={"headless": False})
    assert first.status_code == 200
    assert first.json()["config"]["headless"] is False

    # A second patch only carries what changed; the first edit must survive.
    second = clean_browser.put("/api/browser/config", json={"search_engine": "bing"})
    assert second.json()["config"]["headless"] is False
    assert second.json()["config"]["search_engine"] == "bing"

    overlay = browser_override.load_overrides(get_settings().app.data_dir)
    assert overlay == {"headless": False, "search_engine": "bing"}


def test_config_patch_rejects_unknown_keys(clean_browser: TestClient) -> None:
    response = clean_browser.put("/api/browser/config", json={"turbo": True})
    assert response.status_code == 422


def test_config_patch_drops_invalid_values(clean_browser: TestClient) -> None:
    # An out-of-range timeout is ignored (same contract as the voice/rag
    # overlays) rather than 422-ing the whole card save.
    response = clean_browser.put("/api/browser/config", json={"navigation_timeout_s": -5})
    assert response.status_code == 200
    assert response.json()["config"]["navigation_timeout_s"] == BrowserConfig().navigation_timeout_s


def test_config_patch_is_visible_to_settings(clean_browser: TestClient) -> None:
    clean_browser.put("/api/browser/config", json={"enabled": False, "extract_max_chars": 1234})
    settings = get_settings()
    assert settings.browser.enabled is False
    assert settings.browser.extract_max_chars == 1234


# ------------------------------------------------------------------ delete
def test_config_delete_restores_defaults(clean_browser: TestClient) -> None:
    clean_browser.put("/api/browser/config", json={"headless": False, "search_engine": "google"})
    response = clean_browser.delete("/api/browser/config")
    assert response.status_code == 200
    assert response.json()["config"] == BrowserConfig().model_dump()
    assert get_settings().browser == BrowserConfig()
    assert browser_override.load_overrides(get_settings().app.data_dir) == {}


def test_config_delete_is_idempotent(clean_browser: TestClient) -> None:
    assert clean_browser.delete("/api/browser/config").status_code == 200
    assert clean_browser.delete("/api/browser/config").status_code == 200


# --------------------------------------------------------------- env parsing
def test_browser_env_knobs_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUXION_BROWSER__HEADLESS", "false")
    monkeypatch.setenv("LUXION_BROWSER__SEARCH_ENGINE", "google")
    monkeypatch.setenv("LUXION_BROWSER__NAVIGATION_TIMEOUT_S", "45")
    monkeypatch.setenv("LUXION_BROWSER__EXTRACT_MAX_CHARS", "2000")
    reset_settings_cache()
    try:
        settings = Settings()
        assert settings.browser.headless is False
        assert settings.browser.search_engine == "google"
        assert settings.browser.navigation_timeout_s == 45.0
        assert settings.browser.extract_max_chars == 2000
    finally:
        monkeypatch.delenv("LUXION_BROWSER__HEADLESS", raising=False)
        monkeypatch.delenv("LUXION_BROWSER__SEARCH_ENGINE", raising=False)
        monkeypatch.delenv("LUXION_BROWSER__NAVIGATION_TIMEOUT_S", raising=False)
        monkeypatch.delenv("LUXION_BROWSER__EXTRACT_MAX_CHARS", raising=False)
        reset_settings_cache()


def test_invalid_browser_json_is_ignored(tmp_path) -> None:
    (tmp_path / "browser.json").write_text("{ not json", encoding="utf-8")
    assert browser_override.load_overrides(tmp_path) == {}
    (tmp_path / "browser.json").write_text("[1,2,3]", encoding="utf-8")
    assert browser_override.load_overrides(tmp_path) == {}
    # Unknown / invalid keys are filtered by the settings overlay.
    (tmp_path / "browser.json").write_text(
        '{"headless": "banana", "nonsense": 1, "action_timeout_s": 5}', encoding="utf-8"
    )
    settings = Settings()
    settings.app.data_dir = tmp_path
    from luxion.config.settings import apply_browser_overrides

    apply_browser_overrides(settings)
    assert settings.browser.headless is True  # invalid value dropped
    assert settings.browser.action_timeout_s == 5.0
