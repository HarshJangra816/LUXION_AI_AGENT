"""Coding-agent config API: bundle, patch, reset (PRD §32 Tools → Terminal/Git, Phase 8).

Mirrors :mod:`tests.test_desktop_api` — the coding overlay lives in
``code.json`` the same way the desktop overlay lives in ``desktop.json``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from luxion.config import code_override
from luxion.config.settings import CodeConfig, get_settings, reset_settings_cache


@pytest.fixture()
def clean_code(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep code.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    code_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    code_override.clear_overrides(data_dir)
    reset_settings_cache()


# ------------------------------------------------------------------- bundle
def test_config_read_reports_defaults_and_status(clean_code: TestClient) -> None:
    bundle = clean_code.get("/api/code").json()

    assert set(bundle) == {"config", "defaults", "status"}
    assert bundle["defaults"] == CodeConfig().model_dump()
    assert set(bundle["config"]) == set(CodeConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {
        "platform",
        "git",
        "github_cli",
        "workspace",
        "terminal_capability",
        "terminal_capability_reason",
        "enabled",
    }
    # git is installed on this machine, so the card can show a live chip; on a
    # host without it the route must still render `git: False` instead of 500.
    assert isinstance(status["git"], bool)
    assert isinstance(status["github_cli"], bool)
    # The terminal capability ships OFF — running commands needs consent (§39).
    assert status["terminal_capability"] in ("granted", "denied")


def test_config_patch_covers_every_code_knob() -> None:
    from luxion.api.routes.code import CodeConfigPatch

    assert CodeConfigPatch.model_config.get("extra") == "forbid"
    assert set(CodeConfigPatch.model_fields) == set(CodeConfig.model_fields)


# --------------------------------------------------------------------- put
def test_config_patch_persists_and_merges(clean_code: TestClient) -> None:
    first = clean_code.put("/api/code/config", json={"enabled": False})
    assert first.status_code == 200
    assert first.json()["config"]["enabled"] is False

    # Untouched knobs keep the value they had before the patch.
    second = clean_code.put("/api/code/config", json={"command_timeout_s": 300})
    assert second.status_code == 200
    config = second.json()["config"]
    assert config["enabled"] is False
    assert config["command_timeout_s"] == 300
    assert config["max_output_chars"] == CodeConfig().max_output_chars

    # Only what the user touched lands in code.json, so .env keeps the rest.
    stored = code_override.load_overrides(get_settings().app.data_dir)
    assert set(stored) == {"enabled", "command_timeout_s"}


def test_config_patch_is_visible_to_settings(clean_code: TestClient) -> None:
    clean_code.put("/api/code/config", json={"max_output_chars": 5000})
    assert get_settings().code.max_output_chars == 5000


def test_config_patch_drops_invalid_values(clean_code: TestClient) -> None:
    # An out-of-range timeout is ignored (same contract as the browser/voice/
    # desktop overlays) rather than failing the whole card save.
    response = clean_code.put("/api/code/config", json={"command_timeout_s": -5})
    assert response.status_code == 200
    assert response.json()["config"]["command_timeout_s"] == CodeConfig().command_timeout_s


def test_config_patch_rejects_unknown_fields(clean_code: TestClient) -> None:
    response = clean_code.put("/api/code/config", json={"not_a_knob": 1})
    assert response.status_code == 422


# ------------------------------------------------------------------ delete
def test_config_reset_returns_to_defaults(clean_code: TestClient) -> None:
    clean_code.put("/api/code/config", json={"command_timeout_s": 30})

    reset = clean_code.delete("/api/code/config")
    assert reset.status_code == 200
    assert reset.json()["config"] == CodeConfig().model_dump()
    assert code_override.load_overrides(get_settings().app.data_dir) == {}


def test_config_reset_is_idempotent(clean_code: TestClient) -> None:
    for _ in range(2):
        response = clean_code.delete("/api/code/config")
        assert response.status_code == 200
        assert response.json()["config"] == CodeConfig().model_dump()
