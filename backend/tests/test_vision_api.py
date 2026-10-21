"""Vision config API: bundle, patch, reset, probe and a live analysis.

Phase 11a (PRD §5.9, §33.15). Mirrors :mod:`tests.test_web_api` — the vision
overlay lives in ``vision.json`` the same way the web overlay lives in
``web.json``.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from luxion.config import vision_override
from luxion.config.settings import VisionConfig, get_settings, reset_settings_cache


@pytest.fixture()
def clean_vision(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep vision.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    vision_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    vision_override.clear_overrides(data_dir)
    reset_settings_cache()


@pytest.fixture()
def workspace(client: TestClient, tmp_path: Path):  # noqa: ANN201
    """Let the API read files from ``tmp_path`` for the duration of a test."""
    settings = get_settings()
    original = list(settings.security.allowed_workspaces)
    settings.security.allowed_workspaces = [tmp_path]
    yield tmp_path
    settings.security.allowed_workspaces = original


def _png(width: int = 24, height: int = 18) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------------ bundle
def test_config_read_reports_defaults_status_and_catalog(clean_vision: TestClient) -> None:
    bundle = clean_vision.get("/api/vision").json()

    assert set(bundle) == {"config", "defaults", "status", "catalog"}
    assert bundle["defaults"] == VisionConfig().model_dump()
    assert set(bundle["config"]) == set(VisionConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {"enabled", "keyless", "browser_independent", "uses_chat_provider"}
    assert status["enabled"] is True
    assert status["browser_independent"] is True
    assert status["uses_chat_provider"] is True

    catalog = bundle["catalog"]
    assert "qwen2.5vl:3b" in catalog["suggested_models"]
    assert ".png" in catalog["supported_types"]


def test_config_patch_covers_every_vision_knob() -> None:
    from luxion.api.routes.vision import VisionConfigPatch

    patch_fields = set(VisionConfigPatch.model_fields)
    assert patch_fields == set(VisionConfig.model_fields), (
        "patch must mirror every VisionConfig knob"
    )


# -------------------------------------------------------------------------- patch
def test_put_merges_into_vision_json_and_survives_reload(clean_vision: TestClient) -> None:
    first = clean_vision.put(
        "/api/vision/config", json={"model": "qwen2.5vl:3b", "max_dimension": 1024}
    ).json()
    assert first["config"]["model"] == "qwen2.5vl:3b"
    assert first["config"]["max_dimension"] == 1024

    reset_settings_cache()
    persisted = get_settings().vision
    assert persisted.model == "qwen2.5vl:3b"
    assert persisted.max_dimension == 1024

    # A second patch only touches what it carries — earlier edits survive.
    clean_vision.put("/api/vision/config", json={"timeout_s": 45})
    reset_settings_cache()
    again = get_settings().vision
    assert again.timeout_s == 45
    assert again.model == "qwen2.5vl:3b"
    assert again.max_dimension == 1024


def test_put_rejects_unknown_keys_but_ignores_bad_values(clean_vision: TestClient) -> None:
    assert clean_vision.put("/api/vision/config", json={"nonsense": 1}).status_code == 422

    # Out-of-range values are silently dropped (the established overlay
    # contract, same as voice/rag/browser/desktop/code/web), not a 422.
    assert clean_vision.put("/api/vision/config", json={"max_images": 9999}).status_code == 200
    reset_settings_cache()
    assert get_settings().vision.max_images == VisionConfig().max_images


def test_delete_drops_the_overlay(clean_vision: TestClient) -> None:
    clean_vision.put("/api/vision/config", json={"enabled": False})
    reset_settings_cache()
    assert get_settings().vision.enabled is False

    clean_vision.delete("/api/vision/config")
    reset_settings_cache()
    assert get_settings().vision.enabled is True


# -------------------------------------------------------------------------- probe
def test_probe_reports_the_endpoint_without_spending_a_vision_call(
    clean_vision: TestClient,
) -> None:
    result = clean_vision.post("/api/vision/probe").json()
    assert result["ok"] is True
    assert result["provider"] == "mock"
    assert "mock-1" in result["models"]
    assert result["error"] is None


# ------------------------------------------------------------------------ analyze
def test_analyze_looks_at_a_file(clean_vision: TestClient, workspace: Path) -> None:
    target = workspace / "shot.png"
    target.write_bytes(_png())

    response = clean_vision.post("/api/vision/analyze", json={"path": str(target)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert payload["image"]["mime"] == "image/png"
    assert payload["path"] == str(target)


def test_analyze_needs_a_source(clean_vision: TestClient) -> None:
    assert clean_vision.post("/api/vision/analyze", json={}).status_code == 400


def test_analyze_refuses_a_disabled_family(clean_vision: TestClient, workspace: Path) -> None:
    clean_vision.put("/api/vision/config", json={"enabled": False})
    reset_settings_cache()

    target = workspace / "shot.png"
    target.write_bytes(_png())
    assert clean_vision.post("/api/vision/analyze", json={"path": str(target)}).status_code == 400


def test_analyze_rejects_unknown_keys(clean_vision: TestClient) -> None:
    assert clean_vision.post("/api/vision/analyze", json={"nope": 1}).status_code == 422


def test_analyze_refuses_a_file_outside_the_workspace(
    clean_vision: TestClient, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "outside-vision"
    outside.mkdir(exist_ok=True)
    target = outside / "shot.png"
    target.write_bytes(_png())

    response = clean_vision.post("/api/vision/analyze", json={"path": str(target)})
    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()
