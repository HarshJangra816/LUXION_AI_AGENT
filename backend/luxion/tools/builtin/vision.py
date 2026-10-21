"""Vision tools (PRD §5.9, §11, §33.15, Phase 11).

Four read-only tools:

======================  ==========================================  ===========
Tool                    Does                                       Capability
======================  ==========================================  ===========
``analyze_image``       look at an image file on disk               —
``analyze_screenshot``  capture the screen and look at it           ``screen_capture``
``capture_camera``      grab a frame from the webcam                ``camera``
``ocr_image``           read the text out of an image file          —
======================  ==========================================  ===========

The two "look" tools hand the picture to the configured vision model through
the **existing** provider contract — no second LLM stack (PRD §5.9).
``analyze_screenshot`` and ``capture_camera`` declare a capability because
capturing the screen and opening a webcam are hardware access (PRD §39), so
the capability layer blocks them *before* the risk engine runs; the other two
only read a file inside an approved workspace.

The camera and OCR tools keep working with ``vision.enabled`` switched off —
capturing a frame and reading its text are OpenCV operations that cost no
model call, so only the two "look" tools are gated by that switch.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.tools.builtin.screenshot import grab_screen
from luxion.vision.analyzer import analyze_images
from luxion.vision.camera import capture_image as camera_capture
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image
from luxion.vision.ocr import extract_text, rapidocr_available

#: Common category so the tool router and the system prompt recognise the
#: family at a glance.
CATEGORY = "vision"


def _prepare(source: object, ctx: ToolContext, *, label: str | None = None) -> PreparedImage:
    """Prepare an image for the model, mapping vision errors onto tool errors."""
    vision = ctx.settings.vision
    try:
        return prepare_image(
            source,
            max_dimension=vision.max_dimension,
            max_bytes=vision.max_bytes,
            label=label,
        )
    except VisionError as exc:
        raise ToolError(str(exc), code=exc.code) from exc


async def _ask(ctx: ToolContext, images: list[PreparedImage], question: object) -> str:
    """Ask the vision model, mapping vision errors onto tool errors."""
    try:
        return await analyze_images(
            ctx.settings,
            images,
            question=str(question) if question else None,
        )
    except VisionError as exc:
        raise ToolError(str(exc), code=exc.code) from exc


class AnalyzeImage(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="analyze_image",
            description=(
                "Look at an image file (PNG, JPEG, WEBP, BMP, TIFF) with the vision "
                "model and answer a question about it: what is on screen, what a "
                "diagram shows, which text can be read."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "image",
                "picture",
                "photo",
                "analyze",
                "analyse",
                "look",
                "see",
                "vision",
                "describe",
                "screenshot",
                "read",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Image file to look at, inside an approved workspace.",
                    },
                    "question": {
                        "type": "string",
                        "description": (
                            "What to ask about the image. Defaults to a full description "
                            "of what is visible."
                        ),
                    },
                },
                "required": ["path"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw = args.get("path")
        if not raw:
            raise ToolError(
                "analyze_image needs a 'path' to an image file",
                code="invalid_arguments",
            )
        target = resolve_in_workspace(str(raw), ctx)
        image = await asyncio.to_thread(_prepare, target, ctx, label=target.name)
        answer = await _ask(ctx, [image], args.get("question"))
        return ToolResult(
            output=answer,
            data={
                "path": str(target),
                "image": image.describe(),
                "answer": answer,
            },
        )


class AnalyzeScreenshot(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="analyze_screenshot",
            description=(
                "Capture the screen and look at it with the vision model. Use this "
                "to answer questions about what is currently on the display."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "screen",
                "screenshot",
                "capture",
                "display",
                "monitor",
                "look",
                "see",
                "vision",
                "describe",
            ],
            read_only=True,
            requires="screen_capture",
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "What to ask about the screen. Defaults to a description of "
                            "what is visible."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional destination for the captured PNG inside an approved "
                            "workspace. Defaults to the data directory."
                        ),
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw_path = args.get("path")
        if raw_path:
            destination = resolve_in_workspace(str(raw_path), ctx)
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            destination = ctx.settings.app.data_dir / "screenshots" / f"{stamp}.png"

        def _save() -> tuple[int, tuple[int, int]]:
            image, size = grab_screen()
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, format="PNG")  # type: ignore[attr-defined]
            return destination.stat().st_size, size

        size_bytes, dimensions = await asyncio.to_thread(_save)
        prepared = await asyncio.to_thread(_prepare, destination, ctx, label=destination.name)
        answer = await _ask(ctx, [prepared], args.get("question"))
        return ToolResult(
            output=answer,
            data={
                "path": str(destination),
                "bytes": size_bytes,
                "width": dimensions[0],
                "height": dimensions[1],
                "image": prepared.describe(),
                "answer": answer,
            },
        )


class CaptureCamera(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="capture_camera",
            description=(
                "Capture one frame from the webcam and save it as a PNG. Optionally "
                "ask the vision model what the frame shows. Use this for video calls "
                "on screen, a document on the desk, or anything the camera can see."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "camera",
                "webcam",
                "capture",
                "photo",
                "picture",
                "frame",
                "video",
                "look",
            ],
            read_only=True,
            requires="camera",
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "Ask the vision model about the frame. Omit it to just "
                            "capture and return the file path."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional destination for the PNG inside an approved "
                            "workspace. Defaults to the data directory."
                        ),
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw_path = args.get("path")
        if raw_path:
            destination = resolve_in_workspace(str(raw_path), ctx)
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            destination = ctx.settings.app.data_dir / "captures" / f"{stamp}.png"

        try:
            prepared, dimensions, saved = await camera_capture(ctx.settings, save_to=destination)
        except VisionError as exc:
            raise ToolError(str(exc), code=exc.code) from exc

        question = args.get("question")
        if question:
            answer = await _ask(ctx, [prepared], question)
        else:
            answer = (
                f"Captured camera {ctx.settings.vision.camera_index} "
                f"({dimensions[0]}x{dimensions[1]}) → {saved}"
            )
        return ToolResult(
            output=answer,
            data={
                "path": str(saved) if saved else None,
                "width": dimensions[0],
                "height": dimensions[1],
                "image": prepared.describe(),
                "answer": answer,
            },
        )


class OcrImage(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ocr_image",
            description=(
                "Read the text out of an image (a photo of a document, a screenshot "
                "of an error, a receipt). Returns the extracted text. Uses RapidOCR "
                "when it is installed, otherwise the vision model transcribes it."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "ocr",
                "text",
                "read",
                "extract",
                "document",
                "receipt",
                "photo",
                "scan",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Image file to read, inside an approved workspace.",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["auto", "rapidocr", "vision"],
                        "description": (
                            "Force an engine. Default 'auto': exact RapidOCR when "
                            "installed, falling back to the vision model."
                        ),
                    },
                },
                "required": ["path"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw = args.get("path")
        if not raw:
            raise ToolError("ocr_image needs a 'path' to an image file", code="invalid_arguments")
        target = resolve_in_workspace(str(raw), ctx)
        engine = args.get("engine") or None
        result = await _extract_async(ctx, target, engine)

        text = result.text.strip()
        output = text if text else "(no readable text found in the image)"
        return ToolResult(
            output=output,
            data={**result.as_dict(), "path": str(target)},
        )


async def _extract_async(ctx: ToolContext, target: object, engine: str | None) -> object:
    """OCR a file, mapping vision errors onto tool errors."""
    try:
        return await extract_text(ctx.settings, target, engine=engine)
    except VisionError as exc:
        raise ToolError(str(exc), code=exc.code) from exc


BUILTIN_TOOLS: list[Tool] = [AnalyzeImage(), AnalyzeScreenshot(), CaptureCamera(), OcrImage()]

__all__ = [
    "BUILTIN_TOOLS",
    "AnalyzeImage",
    "AnalyzeScreenshot",
    "CaptureCamera",
    "CATEGORY",
    "OcrImage",
    "rapidocr_available",
]
