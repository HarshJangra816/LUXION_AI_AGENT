"""Web-intelligence config API: bundle, patch, reset (PRD §37, Phase 9).

Mirrors :mod:`tests.test_code_api` — the web overlay lives in ``web.json`` the
same way the coding overlay lives in ``code.json``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from luxion.config import web_override
from luxion.config.settings import WebConfig, get_settings, reset_settings_cache


@pytest.fixture()
def clean_web(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep web.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    web_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    web_override.clear_overrides(data_dir)
    reset_settings_cache()


def test_config_read_reports_defaults_status_and_catalog(clean_web: TestClient) -> None:
    bundle = clean_web.get("/api/web").json()

    assert set(bundle) == {"config", "defaults", "status", "catalog"}
    assert bundle["defaults"] == WebConfig().model_dump()
    assert set(bundle["config"]) == set(WebConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {"enabled", "speed_enabled", "keyless", "browser_independent"}
    assert status["keyless"] is True  # no API keys anywhere in this family

    catalog = bundle["catalog"]
    assert "top" in catalog["news_topics"]
    assert "1y" in catalog["finance_ranges"]


def test_config_patch_covers_every_web_knob() -> None:
    from luxion.api.routes.web import WebConfigPatch

    patch_fields = set(WebConfigPatch.model_fields)
    assert patch_fields == set(WebConfig.model_fields), "patch must mirror every WebConfig knob"


def test_put_merges_into_web_json_and_survives_reload(clean_web: TestClient) -> None:
    first = clean_web.put("/api/web/config", json={"speed_enabled": False, "max_results": 9}).json()
    assert first["config"]["speed_enabled"] is False
    assert first["config"]["max_results"] == 9

    reset_settings_cache()
    persisted = get_settings().web
    assert persisted.speed_enabled is False
    assert persisted.max_results == 9

    # A second patch only touches what it carries — earlier edits survive.
    clean_web.put("/api/web/config", json={"temperature_unit": "fahrenheit"})
    reset_settings_cache()
    again = get_settings().web
    assert again.temperature_unit == "fahrenheit"
    assert again.speed_enabled is False
    assert again.max_results == 9


def test_put_rejects_unknown_keys_but_ignores_bad_values(clean_web: TestClient) -> None:
    assert clean_web.put("/api/web/config", json={"nonsense": 1}).status_code == 422

    # Out-of-range values are silently dropped (the established overlay
    # contract, same as voice/rag/browser/desktop/code), not a 422.
    clean_web.put("/api/web/config", json={"max_results": 9999})
    reset_settings_cache()
    assert get_settings().web.max_results == WebConfig().max_results


def test_delete_drops_the_overlay(clean_web: TestClient) -> None:
    clean_web.put("/api/web/config", json={"enabled": False})
    reset_settings_cache()
    assert get_settings().web.enabled is False

    clean_web.delete("/api/web/config")
    reset_settings_cache()
    assert get_settings().web.enabled == WebConfig().enabled
    assert not web_override.web_path(get_settings().app.data_dir).exists()


def test_web_json_file_is_written_atomically(clean_web: TestClient) -> None:
    clean_web.put("/api/web/config", json={"news_items": 3})
    path = web_override.web_path(get_settings().app.data_dir)
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()
