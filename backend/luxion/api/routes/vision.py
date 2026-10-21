"""Vision status + settings + live actions (PRD §5.9, §11, §33.15, Phase 11).

``GET    /vision``          effective config + defaults + status (Settings card)
``PUT    /vision/config``   persist Settings → Vision edits (partial overlay)
``DELETE /vision/config``   back to ``.env`` defaults
``POST   /vision/probe``    check the vision endpoint + model (no vision call)
``POST   /vision/analyze``  look at an image file or at the screen
``POST   /vision/cameras``  probe which webcam indices open (Phase 11b)
``POST   /vision/camera``   capture a frame from the webcam (Phase 11b)
``POST   /vision/ocr``      read the text out of an image (Phase 11b)

The four POSTs run the same code paths as the tools, so the card can prove
each half of the family really works — a vision model that cannot see is a
silent failure otherwise. They are opt-in buttons on the card, never
automatic. ``/vision/cameras`` is the only endpoint that opens a device, so
nothing lights the camera indicator on page load.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from luxion.config.settings import (
    VisionConfig,
    get_settings,
    reset_settings_cache,
    save_vision_overrides,
)
from luxion.config.vision_override import clear_overrides
from luxion.security.capabilities import get_capabilities
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.tools.builtin.screenshot import grab_screen
from luxion.vision.analyzer import analyze_images, probe_vision
from luxion.vision.camera import (
    capture_frame,
    frame_to_image,
    list_cameras,
    opencv_available,
    save_frame,
)
from luxion.vision.imaging import SUPPORTED_SUFFIXES, VisionError, prepare_image
from luxion.vision.ocr import extract_text, rapidocr_available

router = APIRouter(prefix="/vision", tags=["vision"])


class VisionConfigBundle(BaseModel):
    """What Settings → Vision edits (effective values + defaults + status)."""

    config: VisionConfig
    defaults: VisionConfig
    status: dict[str, Any]
    catalog: dict[str, Any]


class VisionConfigPatch(BaseModel):
    """Partial vision settings — mirrors every field of ``VisionConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.VisionConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    prompt: str | None = None
    max_images: int | None = None
    max_dimension: int | None = None
    max_bytes: int | None = None
    timeout_s: float | None = None
    camera_index: int | None = None
    camera_width: int | None = None
    camera_height: int | None = None
    camera_warmup_frames: int | None = None
    ocr_engine: str | None = None
    ocr_prompt: str | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class ProbeOut(BaseModel):
    ok: bool
    provider: str
    model: str
    models: list[str] = []
    found: bool = False
    error: str | None = None


class AnalyzeRequest(BaseModel):
    """What to look at."""

    model_config = ConfigDict(extra="forbid")

    #: Image file to look at (inside an approved workspace).
    path: str | None = None
    #: Capture the screen instead of reading a file.
    screenshot: bool = False
    #: What to ask about the image.
    question: str | None = None


class AnalyzeOut(BaseModel):
    answer: str
    path: str | None = None
    image: dict[str, Any] = {}


class CamerasOut(BaseModel):
    """Which webcam indices actually open a device."""

    indices: list[int] = []
    #: The index the settings currently point at (may not be in ``indices``).
    camera_index: int = 0


class CameraCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Ask the vision model about the frame (needs vision enabled).
    question: str | None = None
    #: Save the PNG here (inside an approved workspace) instead of the data dir.
    path: str | None = None


class CameraCaptureOut(BaseModel):
    #: ``data:<mime>;base64,<payload>`` — render straight into an <img>.
    image: str
    mime: str
    width: int
    height: int
    path: str | None = None
    answer: str | None = None


class OcrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Image file to read (inside an approved workspace).
    path: str
    #: Force an engine; empty = the ``vision.ocr_engine`` setting.
    engine: str | None = None


class OcrOut(BaseModel):
    text: str
    engine: str
    source: str
    line_count: int
    elapsed_ms: int
    items: list[dict[str, Any]] = []
    #: Resolved workspace path the text was read from.
    path: str | None = None


def _status(settings) -> dict[str, Any]:
    """Static facts for the card — no network, never raises.

    ``opencv_available`` is an *import* check only: opening the webcam here
    would light the camera indicator every time Settings loads.
    """
    vision = settings.vision
    return {
        "enabled": vision.enabled,
        # True — the vision family reuses the chat provider contract, so it
        # needs no extra API key of its own.
        "keyless": not bool(vision.api_key_env.strip()),
        # True — no extra Python dependency for the model call itself.
        "browser_independent": True,
        "uses_chat_provider": not bool(vision.provider.strip()),
        "opencv_available": opencv_available(),
        "ocr_available": rapidocr_available(),
    }


def _catalog() -> dict[str, Any]:
    return {
        "suggested_models": [
            "qwen2.5vl:3b",
            "llama3.2-vision",
            "minicpm-v",
            "llava:7b",
        ],
        "supported_types": sorted(SUPPORTED_SUFFIXES),
        "max_images": 8,
        "ocr_engines": ["auto", "rapidocr", "vision"],
        "camera_max_index": 9,
    }


def _bundle() -> VisionConfigBundle:
    settings = get_settings()
    return VisionConfigBundle(
        config=settings.vision,
        defaults=VisionConfig(),
        status=_status(settings),
        catalog=_catalog(),
    )


@router.get("", response_model=VisionConfigBundle)
async def read_vision() -> VisionConfigBundle:
    return _bundle()


@router.put("/config", response_model=VisionConfigBundle)
async def write_vision(patch: VisionConfigPatch) -> VisionConfigBundle:
    settings = get_settings()
    try:
        save_vision_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=VisionConfigBundle)
async def reset_vision() -> VisionConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.post("/probe", response_model=ProbeOut)
async def probe_vision_endpoint() -> ProbeOut:
    """Reachability check for the vision endpoint (no vision call spent)."""
    settings = get_settings()
    result = await probe_vision(settings)
    return ProbeOut(**result)


@router.post("/analyze", response_model=AnalyzeOut)
async def analyze(request: AnalyzeRequest) -> AnalyzeOut:
    """Look at an image file or at the screen and return the model's answer."""
    settings = get_settings()
    if not settings.vision.enabled:
        raise HTTPException(status_code=400, detail="Vision is turned off.")

    vision = settings.vision
    target = None
    source: object
    label: str
    if request.path:
        ctx = ToolContext(settings)
        try:
            target = resolve_in_workspace(request.path, ctx)
        except ToolError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source = target
        label = target.name
    elif request.screenshot:
        decision = get_capabilities(settings).check("screen_capture")
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        target = settings.app.data_dir / "screenshots" / f"{stamp}.png"

        def _save() -> None:
            image, _size = grab_screen()
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")  # type: ignore[attr-defined]

        await asyncio.to_thread(_save)
        source = target
        label = target.name
    else:
        raise HTTPException(status_code=400, detail="Pass a 'path' or set 'screenshot'.")

    try:
        image = await asyncio.to_thread(
            prepare_image,
            source,
            max_dimension=vision.max_dimension,
            max_bytes=vision.max_bytes,
            label=label,
        )
        answer = await analyze_images(settings, [image], question=request.question)
    except VisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AnalyzeOut(answer=answer, path=str(target), image=image.describe())


@router.post("/cameras", response_model=CamerasOut)
async def probe_cameras() -> CamerasOut:
    """Probe which webcam indices open (opens each device briefly).

    Deliberately a POST: opening a camera lights the hardware indicator, so
    this must never run as a side effect of loading Settings.
    """
    settings = get_settings()
    indices = await asyncio.to_thread(list_cameras)
    return CamerasOut(indices=indices, camera_index=settings.vision.camera_index)


@router.post("/camera", response_model=CameraCaptureOut)
async def capture(request: CameraCaptureRequest) -> CameraCaptureOut:
    """Capture one frame from the webcam, optionally asking what it shows."""
    settings = get_settings()
    decision = get_capabilities(settings).check("camera")
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    vision = settings.vision
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    target: Any = None
    if request.path:
        ctx = ToolContext(settings)
        try:
            target = resolve_in_workspace(request.path, ctx)
        except ToolError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        target = settings.app.data_dir / "captures" / f"{stamp}.png"

    try:
        frame = await asyncio.to_thread(
            capture_frame,
            index=vision.camera_index,
            width=vision.camera_width,
            height=vision.camera_height,
            warmup_frames=vision.camera_warmup_frames,
        )
        image = await asyncio.to_thread(
            prepare_image,
            await asyncio.to_thread(frame_to_image, frame),
            max_dimension=vision.max_dimension,
            max_bytes=vision.max_bytes,
            label=target.name,
        )
        await asyncio.to_thread(save_frame, frame, target)
    except VisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    answer: str | None = None
    if request.question:
        try:
            answer = await analyze_images(settings, [image], question=request.question)
        except VisionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    height, width = frame.shape[:2]
    return CameraCaptureOut(
        image=f"data:{image.mime};base64,{image.data}",
        mime=image.mime,
        width=width,
        height=height,
        path=str(target),
        answer=answer,
    )


@router.post("/ocr", response_model=OcrOut)
async def ocr(request: OcrRequest) -> OcrOut:
    """Read the text out of an image file (RapidOCR, else the vision model)."""
    settings = get_settings()
    ctx = ToolContext(settings)
    try:
        target = resolve_in_workspace(request.path, ctx)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = await extract_text(settings, target, engine=request.engine)
    except VisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OcrOut(**result.as_dict(), path=str(target))
