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
    assert set(status) == {
        "enabled",
        "keyless",
        "browser_independent",
        "uses_chat_provider",
        "opencv_available",
        "ocr_available",
    }
    assert status["enabled"] is True
    assert status["browser_independent"] is True
    assert status["uses_chat_provider"] is True
    # Import checks only — loading Settings must never open the webcam,
    # or the camera indicator would light every time the card renders.
    assert isinstance(status["opencv_available"], bool)
    assert isinstance(status["ocr_available"], bool)

    catalog = bundle["catalog"]
    assert "qwen2.5vl:3b" in catalog["suggested_models"]
    assert ".png" in catalog["supported_types"]
    assert catalog["ocr_engines"] == ["auto", "rapidocr", "vision"]
    assert catalog["camera_max_index"] == 9


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


# ------------------------------------------------- camera (Phase 11b)
def _bgr_frame(height: int = 240, width: int = 320):
    import numpy as np

    return np.zeros((height, width, 3), dtype=np.uint8)


def test_cameras_probe_is_opt_in_and_reports_indices(
    clean_vision: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading Settings must never open the webcam — only the POST does."""
    import luxion.api.routes.vision as vision_routes

    opened: list[str] = []

    def _list() -> list[int]:
        opened.append("probe")
        return [0, 2]

    monkeypatch.setattr(vision_routes, "list_cameras", _list)

    bundle = clean_vision.get("/api/vision").json()
    assert isinstance(bundle["status"]["opencv_available"], bool)
    assert opened == [], "GET /vision opened a device"

    payload = clean_vision.post("/api/vision/cameras").json()
    assert payload == {"indices": [0, 2], "camera_index": 0}
    assert opened == ["probe"]


def test_camera_capture_denied_when_windows_blocks_the_webcam(
    clean_vision: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capability denial is a hard block no autonomy level can override."""
    import luxion.api.routes.vision as vision_routes

    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "deny")
    monkeypatch.setattr(
        vision_routes,
        "capture_frame",
        lambda **_kw: pytest.fail("the camera was opened despite the denial"),
    )

    response = clean_vision.post("/api/vision/camera", json={})
    assert response.status_code == 403
    assert "windows" in response.json()["detail"].lower()


def test_camera_capture_returns_a_data_url(
    clean_vision: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.vision as vision_routes

    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "allow")
    monkeypatch.setattr(vision_routes, "capture_frame", lambda **_kw: _bgr_frame(240, 320))

    payload = clean_vision.post("/api/vision/camera", json={}).json()

    assert payload["width"] == 320 and payload["height"] == 240
    assert payload["image"].startswith("data:image/png;base64,")
    assert payload["answer"] is None
    assert payload["path"] and payload["path"].endswith(".png")
    assert Path(payload["path"]).exists()


def test_camera_capture_rejects_unknown_keys(clean_vision: TestClient) -> None:
    assert clean_vision.post("/api/vision/camera", json={"nope": 1}).status_code == 422


def test_camera_capture_surfaces_a_missing_webcam(
    clean_vision: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.vision as vision_routes
    from luxion.vision.imaging import VisionError

    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "allow")

    def _boom(**_kw):
        raise VisionError("Camera 0 could not be opened.", code="camera_open_failed")

    monkeypatch.setattr(vision_routes, "capture_frame", _boom)

    response = clean_vision.post("/api/vision/camera", json={})
    assert response.status_code == 400
    assert "Camera 0" in response.json()["detail"]


# ------------------------------------------------------- OCR (Phase 11b)
def test_ocr_reads_a_file(
    clean_vision: TestClient, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.vision as vision_routes
    from luxion.vision.ocr import OcrResult

    target = workspace / "doc.png"
    target.write_bytes(_png())
    seen: dict[str, object] = {}

    async def _extract(settings, source, *, engine=None, label=None):  # noqa: ANN001, ANN001, ANN001, ANN201
        seen["engine"] = engine
        return OcrResult(text="hello world", engine="rapidocr", source=Path(source).name)

    monkeypatch.setattr(vision_routes, "extract_text", _extract)

    payload = clean_vision.post("/api/vision/ocr", json={"path": str(target)}).json()

    assert payload["text"] == "hello world"
    assert payload["engine"] == "rapidocr"
    assert payload["line_count"] == 1
    assert payload["path"] == str(target)
    assert seen["engine"] is None  # no override → the configured engine


def test_ocr_forwards_the_requested_engine(
    clean_vision: TestClient, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.api.routes.vision as vision_routes
    from luxion.vision.ocr import OcrResult

    target = workspace / "doc.png"
    target.write_bytes(_png())
    seen: dict[str, object] = {}

    async def _extract(settings, source, *, engine=None, label=None):  # noqa: ANN001, ANN001, ANN001, ANN201
        seen["engine"] = engine
        return OcrResult(text="t", engine=engine or "auto", source=Path(source).name)

    monkeypatch.setattr(vision_routes, "extract_text", _extract)

    clean_vision.post("/api/vision/ocr", json={"path": str(target), "engine": "vision"})
    assert seen["engine"] == "vision"


def test_ocr_rejects_unknown_keys(clean_vision: TestClient) -> None:
    assert (
        clean_vision.post("/api/vision/ocr", json={"path": "x.png", "nope": 1}).status_code == 422
    )


def test_ocr_reports_an_unknown_engine(clean_vision: TestClient, workspace: Path) -> None:
    target = workspace / "doc.png"
    target.write_bytes(_png())

    response = clean_vision.post(
        "/api/vision/ocr", json={"path": str(target), "engine": "tesseract"}
    )
    assert response.status_code == 400
    assert "engine" in response.json()["detail"].lower()


def test_ocr_refuses_a_file_outside_the_workspace(clean_vision: TestClient, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-ocr"
    outside.mkdir(exist_ok=True)
    target = outside / "doc.png"
    target.write_bytes(_png())

    response = clean_vision.post("/api/vision/ocr", json={"path": str(target)})
    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()
