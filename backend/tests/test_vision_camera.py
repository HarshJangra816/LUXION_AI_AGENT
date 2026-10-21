"""Camera capture + OCR (PRD §11, §33.15, §39, Phase 11b).

Hermetic by design: OpenCV's ``VideoCapture`` is replaced by a fake device and
RapidOCR by a fake engine, so the suite never opens the webcam, never loads an
ONNX session and never depends on the host's Windows camera privacy setting
(the ``camera`` capability is an OS probe — see
:func:`luxion.security.capabilities.probe_os_consent`).

One test does run the *real* RapidOCR package when it is installed; it is
skipped otherwise. It stays local: the recognition models ship inside the
wheel, so nothing is downloaded and no image leaves the box.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from luxion.config.settings import Settings
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.vision import CaptureCamera, OcrImage
from luxion.tools.registry import build_registry
from luxion.vision import camera as camera_mod
from luxion.vision import ocr as ocr_mod
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image
from luxion.vision.ocr import OcrItem, OcrResult, extract_text, rapidocr_available

CAMERA_TOOL_NAMES = {"capture_camera", "ocr_image"}


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def _png(width: int = 40, height: int = 30) -> bytes:
    """A tiny PNG built with Pillow (no binary fixture in the repo)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def _frame(height: int = 720, width: int = 1280, color=(10, 20, 30)):  # noqa: ANN001, ANN201
    """A BGR frame the way OpenCV hands one back."""
    import numpy as np

    return np.full((height, width, 3), color, dtype=np.uint8)


# ------------------------------------------------------------------- fake device
class _FakeCapture:
    """Stand-in for one ``cv2.VideoCapture`` handle."""

    def __init__(self, opened: bool, frames: list) -> None:  # noqa: ANN001
        self._opened = opened
        self._frames = list(frames)
        self.released = False
        self.requested: list[tuple[int, int]] = []

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the OpenCV API
        return self._opened

    def set(self, prop: int, value: float | int) -> bool:  # noqa: ANN001
        self.requested.append((prop, value))
        return True

    def read(self):  # noqa: ANN201, ANN001
        if not self._frames:
            return False, None
        frame = self._frames.pop(0)
        # A ``None`` slot models a frame the driver dropped.
        if frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        self.released = True


class _FakeCv2:
    """Stand-in for ``cv2``: devices are declared once, every open is recorded."""

    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self, devices: dict[int, list] | None = None) -> None:  # noqa: ANN001
        self.devices = devices or {}
        self.opens: list[int] = []
        self.captures: list[_FakeCapture] = []
        self.written: list[Path] = []

    def VideoCapture(self, index: int) -> _FakeCapture:  # noqa: N802 - mirrors OpenCV
        self.opens.append(index)
        frames = self.devices.get(index)
        capture = _FakeCapture(frames is not None, frames or [])
        self.captures.append(capture)
        return capture

    def imwrite(self, path: str, frame: object) -> bool:  # noqa: ANN001
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        self.written.append(target)
        return True


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeCv2) -> _FakeCv2:
    monkeypatch.setattr(camera_mod, "_cv2", lambda: fake)
    return fake


# ---------------------------------------------------------------- camera module
def test_capture_frame_requests_the_configured_size_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One warmup frame + the frame we keep.
    fake = _install(monkeypatch, _FakeCv2({0: [_frame(), _frame()]}))

    frame = camera_mod.capture_frame(index=0, width=1920, height=1080, warmup_frames=1)

    assert frame.shape == (720, 1280, 3)
    handle = fake.captures[0]
    # The driver is asked for the size we configured (it may negotiate away).
    assert (3, 1920) in handle.requested
    assert (4, 1080) in handle.requested
    # A leaked handle keeps the Windows webcam indicator lit.
    assert handle.released is True


def test_capture_frame_reports_a_missing_device(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeCv2({}))

    with pytest.raises(VisionError) as excinfo:
        camera_mod.capture_frame(index=2)
    assert excinfo.value.code == "camera_open_failed"
    assert "Privacy" in str(excinfo.value)
    assert fake.captures[0].released is True


def test_capture_frame_reports_a_device_that_returns_no_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Opens, but every read comes back empty (camera busy in another app).
    fake = _install(monkeypatch, _FakeCv2({0: []}))

    with pytest.raises(VisionError) as excinfo:
        camera_mod.capture_frame(index=0, warmup_frames=0)
    assert excinfo.value.code == "camera_no_frame"
    assert fake.captures[0].released is True


def test_capture_frame_discards_the_warmup_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    warm_a, warm_b, keep = _frame(), _frame(), _frame()
    fake = _install(monkeypatch, _FakeCv2({0: [warm_a, warm_b, keep]}))

    frame = camera_mod.capture_frame(index=0, warmup_frames=2)

    # The first two frames exist but are discarded for exposure settling.
    assert frame is keep
    assert fake.captures[0]._frames == []  # noqa: SLF001 - the fake's own list


def test_capture_frame_survives_dropped_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    keep = _frame()
    _install(monkeypatch, _FakeCv2({0: [None, None, keep]}))

    # Two dropped reads then a good one — one glitch must not fail the capture.
    assert camera_mod.capture_frame(index=0, warmup_frames=0) is keep


def test_list_cameras_reports_only_the_openable_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()], 2: [_frame()]}))

    assert camera_mod.list_cameras() == [0, 2]
    # Probes every slot in PROBE_INDICES, so a device at 1 and 3 is a miss.
    assert fake.opens == [0, 1, 2, 3]


def test_list_cameras_releases_every_probed_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()], 1: [_frame()]}))

    camera_mod.list_cameras()

    assert [handle.released for handle in fake.captures] == [True, True, True, True]


def test_opencv_available_never_opens_a_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings must not light the camera indicator on page load.

    ``opencv_available`` is only an import check; the device is opened by an
    explicit probe / capture instead (see the two tests below).
    """
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()]}))

    assert camera_mod.opencv_available() is True
    assert fake.opens == []


def test_camera_available_does_probe_a_device(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()]}))

    assert camera_mod.camera_available() is True
    assert fake.opens == [0]
    assert fake.captures[0].released is True


def test_opencv_available_is_false_without_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom():
        raise VisionError("no opencv", code="camera_dependency_missing")

    monkeypatch.setattr(camera_mod, "_cv2", _boom)
    assert camera_mod.opencv_available() is False
    assert camera_mod.list_cameras() == []


def test_frame_to_image_swaps_bgr_for_rgb() -> None:
    image = camera_mod.frame_to_image(_frame(height=4, width=4, color=(10, 20, 30)))

    assert image.mode == "RGB"
    # OpenCV is BGR, Pillow is RGB — without the swap every photo is tinted.
    assert image.getpixel((0, 0)) == (30, 20, 10)


def test_save_frame_writes_the_png(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()]}))
    destination = tmp_path / "nested" / "shot.png"

    written = camera_mod.save_frame(_frame(), destination)

    assert destination.exists()
    assert written == destination.stat().st_size == fake.written[0].stat().st_size


def test_save_frame_reports_a_write_it_could_not_make(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Refusing(_FakeCv2):
        def imwrite(self, path, frame):  # noqa: ANN001, ANN201
            return False

    _install(monkeypatch, _Refusing({0: [_frame()]}))

    with pytest.raises(VisionError) as excinfo:
        camera_mod.save_frame(_frame(), tmp_path / "shot.png")
    assert excinfo.value.code == "camera_write_failed"


def test_capture_image_returns_dimensions_and_a_saved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _install(monkeypatch, _FakeCv2({1: [_frame(height=480, width=640)]}))
    settings = Settings(
        vision={
            "camera_index": 1,
            "camera_width": 640,
            "camera_height": 480,
            "camera_warmup_frames": 0,
        }
    )
    destination = tmp_path / "captures" / "frame.png"

    prepared, dimensions, saved = run(
        camera_mod.capture_image(settings, save_to=destination, label="frame.png")
    )

    assert isinstance(prepared, PreparedImage)
    assert dimensions == (640, 480)
    assert saved == destination and destination.exists()
    assert fake.opens == [1]
    # The settings really drive the device: index 1, the requested size.
    assert fake.captures[0].requested == [(3, 640), (4, 480)]


def test_capture_image_skips_the_save_when_no_destination_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _FakeCv2({0: [_frame()]}))

    _prepared, dimensions, saved = run(
        camera_mod.capture_image(Settings(vision={"camera_warmup_frames": 0}))
    )

    assert dimensions == (1280, 720)
    assert saved is None


# ----------------------------------------------------------------- camera tool
def test_capture_camera_is_gated_on_the_camera_capability() -> None:
    registry = build_registry(Settings())
    spec = registry.spec("capture_camera")

    assert set(registry.names()) >= CAMERA_TOOL_NAMES
    # Opening a webcam is hardware access (PRD §39) — the capability layer
    # denies it before the risk engine ever runs.
    assert spec.requires == "camera"
    assert spec.risk == "low"
    assert spec.read_only is True


def test_capture_camera_saves_a_frame_without_asking_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No question → no model call, so this works with vision switched off."""
    import luxion.tools.builtin.vision as vision_tools

    seen: dict[str, object] = {}

    async def _capture(settings, *, save_to=None, label=None):  # noqa: ANN001, ANN001, ANN201
        seen["save_to"] = save_to
        destination = Path(save_to)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_png(64, 48))
        return prepare_image(destination, label="frame.png"), (640, 480), destination

    monkeypatch.setattr(vision_tools, "camera_capture", _capture)

    settings = Settings(
        security={"allowed_workspaces": [tmp_path]},
        vision={"enabled": False},
    )
    result = run(CaptureCamera().run({}, ToolContext(settings)))

    assert result.ok is True
    assert "Captured camera 0 (640x480)" in result.output
    assert result.data["width"] == 640 and result.data["height"] == 480
    assert Path(result.data["path"]).exists()
    # Saved into the data dir by default, not the workspace.
    assert Path(seen["save_to"]).is_relative_to(settings.app.data_dir)


def test_capture_camera_answers_a_question_through_the_vision_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.tools.builtin.vision as vision_tools

    async def _capture(settings, *, save_to=None, label=None):  # noqa: ANN001, ANN001, ANN201
        destination = Path(save_to)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_png(32, 32))
        return prepare_image(destination, label="frame.png"), (32, 32), destination

    monkeypatch.setattr(vision_tools, "camera_capture", _capture)
    _patch_provider(monkeypatch, _FakeProvider("A person at a desk."))

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    result = run(CaptureCamera().run({"question": "who is there?"}, ToolContext(settings)))

    assert result.output == "A person at a desk."
    assert result.data["answer"] == result.output


def test_capture_camera_surfaces_a_missing_webcam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.tools.builtin.vision as vision_tools

    async def _capture(settings, *, save_to=None, label=None):  # noqa: ANN001, ANN001, ANN201
        raise VisionError("Camera 0 could not be opened.", code="camera_open_failed")

    monkeypatch.setattr(vision_tools, "camera_capture", _capture)

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    with pytest.raises(ToolError) as excinfo:
        run(CaptureCamera().run({}, ToolContext(settings)))
    assert excinfo.value.code == "camera_open_failed"


def test_capture_camera_never_opens_the_device_for_an_outside_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workspace check runs *before* the webcam is touched."""
    fake = _install(monkeypatch, _FakeCv2({0: [_frame()]}))

    target = tmp_path / "shot.png"
    elsewhere = tmp_path.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    settings = Settings(security={"allowed_workspaces": [elsewhere]})

    with pytest.raises(ToolError) as excinfo:
        run(CaptureCamera().run({"path": str(target)}, ToolContext(settings)))

    assert excinfo.value.code == "workspace_violation"
    assert fake.opens == []


# ------------------------------------------------------------------- OCR module
def test_rapidocr_available_tracks_the_installed_package() -> None:
    try:
        import rapidocr_onnxruntime  # noqa: F401, PLC0415
    except ImportError:
        installed = False
    else:
        installed = True
    assert rapidocr_available() is installed


def test_extract_text_uses_rapidocr_when_it_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: True)

    def _fake(image, *, source="image"):  # noqa: ANN001, ANN201
        return OcrResult(text="hello world", engine="rapidocr", source=source)

    monkeypatch.setattr(ocr_mod, "run_rapidocr", _fake)

    result = run(extract_text(Settings(), target))

    assert result.engine == "rapidocr"
    assert result.text == "hello world"
    assert result.source == "doc.png"


def test_extract_text_falls_back_to_the_vision_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No OCR package installed → the vision model transcribes instead."""
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: False)
    _patch_provider(monkeypatch, _FakeProvider("Invoice total 42."))

    result = run(extract_text(Settings(), target))

    assert result.engine == "vision"
    assert result.text == "Invoice total 42."
    assert result.items == []


def test_extract_text_sends_the_ocr_prompt_not_the_description_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: False)
    provider = _FakeProvider("some text")
    _patch_provider(monkeypatch, provider)

    settings = Settings(vision={"ocr_prompt": "Transcribe only."})
    run(extract_text(settings, target))

    assert "Transcribe only." in provider.messages[0].content
    assert "Describe this image" not in provider.messages[0].content


def test_auto_engine_falls_through_when_rapidocr_finds_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blank image produces no text — 'auto' must keep going, not return ''."""
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: True)
    monkeypatch.setattr(
        ocr_mod,
        "run_rapidocr",
        lambda image, *, source="image": OcrResult(text="  ", engine="rapidocr", source=source),
    )
    _patch_provider(monkeypatch, _FakeProvider("read from the model"))

    result = run(extract_text(Settings(), target))

    assert result.engine == "vision"
    assert result.text == "read from the model"


def test_rapidocr_engine_fails_loudly_when_the_package_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: False)

    with pytest.raises(VisionError) as excinfo:
        run(extract_text(Settings(), target, engine="rapidocr"))
    assert excinfo.value.code == "ocr_engine_missing"


def test_vision_engine_refuses_when_vision_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: False)

    with pytest.raises(VisionError) as excinfo:
        run(extract_text(Settings(vision={"enabled": False}), target))
    # OCR with vision off is only an error when there is no OCR engine left.
    assert excinfo.value.code == "vision_disabled"


def test_unknown_engine_is_rejected(tmp_path: Path) -> None:
    target = _write_image(tmp_path)

    with pytest.raises(VisionError) as excinfo:
        run(extract_text(Settings(), target, engine="tesseract"))
    assert excinfo.value.code == "ocr_unknown_engine"


def test_engine_override_wins_over_the_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _write_image(tmp_path)
    monkeypatch.setattr(ocr_mod, "rapidocr_available", lambda: True)
    monkeypatch.setattr(
        ocr_mod,
        "run_rapidocr",
        lambda image, *, source="image": OcrResult(text="forced", engine="rapidocr", source=source),
    )

    settings = Settings(vision={"ocr_engine": "vision"})
    _patch_provider(monkeypatch, _FakeProvider("from the model"))

    # engine="rapidocr" overrides the stored "vision" setting...
    assert run(extract_text(settings, target, engine="rapidocr")).text == "forced"
    # ...and the setting is honoured when no override is passed.
    assert run(extract_text(settings, target)).text == "from the model"


def test_run_rapidocr_sorts_items_into_reading_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection returns boxes unordered; joined text must read top-to-bottom."""
    from PIL import Image

    bottom = [[10, 100], [90, 100], [90, 120], [10, 120]]
    top = [[10, 20], [90, 20], [90, 40], [10, 40]]

    class _Engine:
        def __call__(self, array):  # noqa: ANN001, ANN201
            return [[bottom, "second line", 0.9], [top, "first line", 0.8]], [1, 2, 3]

    monkeypatch.setattr(ocr_mod, "_ENGINE", _Engine())
    result = ocr_mod.run_rapidocr(Image.new("RGB", (200, 200), (255, 255, 255)), source="x")

    assert [item.text for item in result.items] == ["first line", "second line"]
    assert result.text == "first line\nsecond line"
    assert result.engine == "rapidocr"
    assert result.items[0].box[0] == [10.0, 20.0]


def test_ocr_result_counts_lines_and_serialises() -> None:
    result = OcrResult(
        text="one\ntwo\n\nthree",
        engine="rapidocr",
        source="doc.png",
        items=[OcrItem("one", 0.912345, [[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0]])],
    )

    assert result.line_count == 3  # the blank line does not count
    data = result.as_dict()
    assert data["engine"] == "rapidocr"
    assert data["line_count"] == 3
    assert data["items"][0]["text"] == "one"
    assert data["items"][0]["score"] == 0.912  # rounded for the API


# -------------------------------------------------------------------- OCR tool
def test_ocr_image_is_read_only_and_needs_no_capability() -> None:
    spec = build_registry(Settings()).spec("ocr_image")

    # Reading a file's text is neither hardware access nor a mutation.
    assert spec.requires is None
    assert spec.read_only is True
    assert spec.risk == "low"


def test_ocr_image_returns_the_extracted_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.tools.builtin.vision as vision_tools

    target = _write_image(tmp_path)
    seen: dict[str, object] = {}

    async def _extract(ctx, path, engine=None):  # noqa: ANN001, ANN001, ANN201
        seen["path"] = Path(path)
        seen["engine"] = engine
        return OcrResult(text="hello world", engine="rapidocr", source=Path(path).name)

    monkeypatch.setattr(vision_tools, "extract_text", _extract)

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    result = run(OcrImage().run({"path": str(target)}, ToolContext(settings)))

    assert result.output == "hello world"
    assert seen["path"] == target
    assert seen["engine"] is None  # no override → the configured engine
    assert result.data["path"] == str(target)
    assert result.data["line_count"] == 1


def test_ocr_image_forwards_the_requested_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luxion.tools.builtin.vision as vision_tools

    target = _write_image(tmp_path)
    seen: dict[str, object] = {}

    async def _extract(ctx, path, engine=None):  # noqa: ANN001, ANN001, ANN201
        seen["engine"] = engine
        return OcrResult(text="", engine=engine or "auto", source=Path(path).name)

    monkeypatch.setattr(vision_tools, "extract_text", _extract)

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    result = run(OcrImage().run({"path": str(target), "engine": "vision"}, ToolContext(settings)))

    assert seen["engine"] == "vision"
    # An empty read must say so rather than returning a blank line.
    assert result.output == "(no readable text found in the image)"


def test_ocr_image_surfaces_a_vision_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import luxion.tools.builtin.vision as vision_tools

    target = _write_image(tmp_path)

    async def _extract(ctx, path, engine=None):  # noqa: ANN001, ANN001, ANN201
        raise VisionError("RapidOCR is not installed", code="ocr_engine_missing")

    monkeypatch.setattr(vision_tools, "extract_text", _extract)

    settings = Settings(security={"allowed_workspaces": [tmp_path]})
    with pytest.raises(ToolError) as excinfo:
        run(OcrImage().run({"path": str(target)}, ToolContext(settings)))
    assert excinfo.value.code == "ocr_engine_missing"


def test_ocr_image_needs_a_path() -> None:
    with pytest.raises(ToolError) as excinfo:
        run(OcrImage().run({}, ToolContext(Settings())))
    assert excinfo.value.code == "invalid_arguments"


def test_ocr_image_refuses_a_file_outside_the_workspace(tmp_path: Path) -> None:
    target = _write_image(tmp_path)
    elsewhere = tmp_path.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)

    settings = Settings(security={"allowed_workspaces": [elsewhere]})
    with pytest.raises(ToolError) as excinfo:
        run(OcrImage().run({"path": str(target)}, ToolContext(settings)))
    assert excinfo.value.code == "workspace_violation"


# ------------------------------------------------------------------ real package
@pytest.mark.skipif(not rapidocr_available(), reason="rapidocr-onnxruntime not installed")
def test_real_rapidocr_reads_a_rendered_line() -> None:
    """End-to-end against the real ONNX models (local, nothing downloaded)."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (720, 180), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        font = ImageFont.load_default()
    draw.text((30, 45), "LUXION 12345", fill=(0, 0, 0), font=font)

    result = ocr_mod.run_rapidocr(image, source="rendered")

    assert result.engine == "rapidocr"
    assert result.items, "at least one text run must be detected"
    assert any("LUXION" in item.text.upper() for item in result.items)


# ---------------------------------------------------------------------- helpers
def _write_image(tmp_path: Path, name: str = "doc.png") -> Path:
    target = tmp_path / name
    target.write_bytes(_png(40, 30))
    return target


class _FakeProvider:
    """Records the messages it was handed and answers with fixed text."""

    def __init__(self, text: str = "A blue rectangle.") -> None:
        self.text = text
        self.messages: list = []
        self.model: str | None = None

    async def resolve_model(self) -> str:
        return "fake-vision"

    async def complete(self, messages, *, model=None, **_kwargs):  # noqa: ANN001, ANN003
        self.messages = list(messages)
        self.model = model
        return SimpleNamespace(text=self.text)


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider) -> None:
    import luxion.vision.analyzer as analyzer

    monkeypatch.setattr(analyzer, "get_provider", lambda _config: provider)
