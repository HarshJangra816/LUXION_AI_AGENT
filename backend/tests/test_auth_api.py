"""Authentication HTTP surface: bundle, patch/reset, profiles, live actions.

Phase 11c (PRD §27, §28, §33.2). Mirrors :mod:`tests.test_vision_api` — the
biometrics overlay lives in ``biometrics.json`` the same way the vision overlay
lives in ``vision.json``.

The two POST routes are never allowed to touch real hardware here: the capture
functions are stubbed, so the tests prove the *wiring* (modality routing, the
name requirement, the three rails, the 403/400 mapping) without a microphone,
a webcam or a 37 MB model download.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from luxion.config import biometrics_override
from luxion.config.settings import BiometricsConfig, get_settings, reset_settings_cache
from luxion.security.capabilities import get_capabilities


@pytest.fixture(autouse=True)
def _biometrics_capability_is_off():
    """The consent is per-machine state in a shared data dir — pin it OFF."""
    get_capabilities().set("biometrics", None)
    yield
    get_capabilities().set("biometrics", None)


@pytest.fixture()
def clean_auth(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep biometrics.json hermetic per test."""
    data_dir = get_settings().app.data_dir
    biometrics_override.clear_overrides(data_dir)
    reset_settings_cache()
    yield client
    biometrics_override.clear_overrides(data_dir)
    reset_settings_cache()


@pytest.fixture()
def workspace(client: TestClient, tmp_path: Path):  # noqa: ANN201
    """Let the API read files from ``tmp_path`` for the duration of a test."""
    settings = get_settings()
    original = list(settings.security.allowed_workspaces)
    settings.security.allowed_workspaces = [tmp_path]
    yield tmp_path
    settings.security.allowed_workspaces = original


# ------------------------------------------------------------------------ bundle
def test_config_read_reports_defaults_status_and_catalog(clean_auth: TestClient) -> None:
    bundle = clean_auth.get("/api/auth").json()

    assert set(bundle) == {"config", "defaults", "status", "catalog"}
    assert bundle["defaults"] == BiometricsConfig().model_dump()
    assert set(bundle["config"]) == set(BiometricsConfig.model_fields)

    status = bundle["status"]
    assert set(status) == {
        "mode",
        "max_profiles",
        "biometrics",
        "microphone",
        "camera",
        "opencv_available",
        "face_api",
        "models",
        "models_ready",
        "profiles",
    }
    # Loading Settings must never open a device or download a model.
    assert isinstance(status["opencv_available"], bool)
    assert isinstance(status["face_api"], bool)
    assert status["models_ready"] is False
    assert status["profiles"] == {"voice": 0, "face": 0}

    catalog = bundle["catalog"]
    assert [m["value"] for m in catalog["modes"]] == [
        "disabled",
        "voice_only",
        "face_only",
        "voice_face",
    ]
    assert catalog["modalities"] == ["voice", "face"]
    assert catalog["max_profiles"] == 5
    assert catalog["duration_range"] == [1.0, 15.0]
    assert {m["id"] for m in catalog["models"]} == {"yunet", "sface"}


def test_config_patch_covers_every_biometrics_knob() -> None:
    from luxion.api.routes.auth import AuthConfigPatch

    assert set(AuthConfigPatch.model_fields) == set(BiometricsConfig.model_fields), (
        "patch must mirror every BiometricsConfig knob"
    )


# -------------------------------------------------------------------------- patch
def test_put_merges_into_biometrics_json_and_survives_reload(clean_auth: TestClient) -> None:
    first = clean_auth.put(
        "/api/auth/config", json={"mode": "voice_only", "voice_threshold": 0.6}
    ).json()
    assert first["config"]["mode"] == "voice_only"
    assert first["config"]["voice_threshold"] == 0.6

    reset_settings_cache()
    persisted = get_settings().biometrics
    assert persisted.mode == "voice_only" and persisted.voice_threshold == 0.6

    # A second patch only touches what it carries — earlier edits survive.
    clean_auth.put("/api/auth/config", json={"voice_duration_s": 5})
    reset_settings_cache()
    again = get_settings().biometrics
    assert again.voice_duration_s == 5 and again.mode == "voice_only"


def test_put_rejects_unknown_keys_but_ignores_bad_values(clean_auth: TestClient) -> None:
    assert clean_auth.put("/api/auth/config", json={"nonsense": 1}).status_code == 422

    # Out-of-range values are silently dropped (the established overlay
    # contract), not a 422.
    assert clean_auth.put("/api/auth/config", json={"voice_threshold": 99}).status_code == 200
    reset_settings_cache()
    assert get_settings().biometrics.voice_threshold == BiometricsConfig().voice_threshold


def test_delete_drops_the_overlay(clean_auth: TestClient) -> None:
    clean_auth.put("/api/auth/config", json={"mode": "disabled"})
    reset_settings_cache()
    assert get_settings().biometrics.mode == "disabled"

    clean_auth.delete("/api/auth/config")
    reset_settings_cache()
    assert get_settings().biometrics.mode == BiometricsConfig().mode


# ----------------------------------------------------------------------- profiles
def test_profiles_start_empty_and_a_bad_modality_is_404(clean_auth: TestClient) -> None:
    payload = clean_auth.get("/api/auth/profiles").json()
    assert payload == {"voice": [], "face": []}

    assert clean_auth.delete("/api/auth/profiles/retina/anything").status_code == 404
    assert clean_auth.delete("/api/auth/profiles/voice/ghost").status_code == 404


# -------------------------------------------------------------------- live actions
def test_enroll_requires_a_name(clean_auth: TestClient) -> None:
    response = clean_auth.post("/api/auth/enroll", json={"modality": "voice"})
    assert response.status_code == 400
    assert "name" in response.json()["detail"].lower()


def test_enroll_is_blocked_by_the_off_capability(clean_auth: TestClient) -> None:
    """The capability ships OFF — a live action is a hard 403 before any capture."""
    response = clean_auth.post("/api/auth/enroll", json={"modality": "voice", "name": "harsh"})
    assert response.status_code == 403
    assert "capability" in response.json()["detail"].lower() or "turn" in (
        response.json()["detail"].lower()
    )


def test_enroll_refuses_a_disabled_mode(clean_auth: TestClient, workspace: Path) -> None:
    """Even with the capability on, the security mode gates which factor runs."""
    get_capabilities().set("biometrics", "granted")
    clean_auth.put("/api/auth/config", json={"mode": "face_only"})
    reset_settings_cache()
    try:
        response = clean_auth.post("/api/auth/enroll", json={"modality": "voice", "name": "harsh"})
        assert response.status_code == 403
        assert "voice" in response.json()["detail"].lower()
    finally:
        get_capabilities().set("biometrics", None)


def test_enroll_forwards_a_voice_wav_through_the_workspace(
    clean_auth: TestClient, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.auth as auth_routes

    get_capabilities().set("biometrics", "granted")
    seen: dict[str, object] = {}

    async def _enroll(settings, name, *, path=None, duration_s=None):  # noqa: ANN001, ANN201
        seen.update(name=name, path=path, duration_s=duration_s)
        return {
            "modality": "voice",
            "name": name,
            "message": f"Voice profile '{name}' enrolled.",
        }

    monkeypatch.setattr(auth_routes.biometrics, "enroll_voice", _enroll)
    try:
        target = workspace / "clip.wav"
        target.write_bytes(b"RIFFfake")
        payload = clean_auth.post(
            "/api/auth/enroll",
            json={"modality": "voice", "name": "harsh", "path": str(target)},
        ).json()
    finally:
        get_capabilities().set("biometrics", None)

    assert payload["name"] == "harsh"
    assert seen["name"] == "harsh"
    assert seen["path"] == str(target)  # resolved inside the workspace
    assert seen["duration_s"] is None  # omitted → the configured default


def test_verify_routes_to_the_right_modality(
    clean_auth: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.auth as auth_routes

    get_capabilities().set("biometrics", "granted")
    called: list[str] = []

    async def _voice(settings, name=None, **_kw):  # noqa: ANN001, ANN201
        called.append("voice")
        return {"modality": "voice", "message": "ok", "matched": True}

    async def _face(settings, name=None, **_kw):  # noqa: ANN001, ANN201
        called.append("face")
        return {"modality": "face", "message": "ok", "matched": False}

    monkeypatch.setattr(auth_routes.biometrics, "verify_voice", _voice)
    monkeypatch.setattr(auth_routes.biometrics, "verify_face", _face)
    try:
        clean_auth.post("/api/auth/verify", json={"modality": "voice"})
        clean_auth.post("/api/auth/verify", json={"modality": "face"})
    finally:
        get_capabilities().set("biometrics", None)

    assert called == ["voice", "face"]


def test_verify_rejects_unknown_keys(clean_auth: TestClient) -> None:
    assert (
        clean_auth.post("/api/auth/verify", json={"modality": "voice", "nope": 1}).status_code
        == 422
    )


def test_a_denied_capture_is_403_and_a_fixable_error_is_400(
    clean_auth: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.auth as auth_routes
    from luxion.vision.imaging import VisionError

    get_capabilities().set("biometrics", "granted")

    async def _denied(settings, name=None, **_kw):  # noqa: ANN001, ANN201
        raise VisionError("Camera is blocked by Windows.", code="auth_camera_denied")

    async def _fixable(settings, name=None, **_kw):  # noqa: ANN001, ANN201
        raise VisionError("No face was detected.", code="auth_no_face")

    monkeypatch.setattr(auth_routes.biometrics, "verify_face", _denied)
    denied = clean_auth.post("/api/auth/verify", json={"modality": "face"})
    assert denied.status_code == 403

    monkeypatch.setattr(auth_routes.biometrics, "verify_face", _fixable)
    fixable = clean_auth.post("/api/auth/verify", json={"modality": "face"})
    assert fixable.status_code == 400
    get_capabilities().set("biometrics", None)
