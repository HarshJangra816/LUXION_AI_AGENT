"""Vision status + settings + live analysis (PRD §5.9, §33.15, Phase 11).

``GET    /vision``          effective config + defaults + status (Settings card)
``PUT    /vision/config``   persist Settings → Vision edits (partial overlay)
``DELETE /vision/config``   back to ``.env`` defaults
``POST   /vision/probe``    check the vision endpoint + model (no vision call)
``POST   /vision/analyze``  look at an image file or at the screen

``/vision/analyze`` is the one **action** endpoint: it runs the same code path
as the ``analyze_image`` / ``analyze_screenshot`` tools so the card can prove
the setup really works (a vision model that cannot see is a silent failure
otherwise). It is opt-in — a button on the card, never automatic.
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
from luxion.vision.imaging import SUPPORTED_SUFFIXES, VisionError, prepare_image

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


def _status(settings) -> dict[str, Any]:
    """Static facts for the card — no network, never raises."""
    vision = settings.vision
    return {
        "enabled": vision.enabled,
        # True — the vision family reuses the chat provider contract, so it
        # needs no extra API key of its own.
        "keyless": not bool(vision.api_key_env.strip()),
        # True — no extra Python dependency for the model call itself.
        "browser_independent": True,
        "uses_chat_provider": not bool(vision.provider.strip()),
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
