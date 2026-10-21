"""Vision tools (PRD §5.9, §33.15, Phase 11).

Two read-only tools:

======================  ==========================================  ===========
Tool                    Does                                       Capability
======================  ==========================================  ===========
``analyze_image``       look at an image file on disk               —
``analyze_screenshot``  capture the screen and look at it           ``screen_capture``
======================  ==========================================  ===========

Both hand the picture to the configured vision model through the **existing**
provider contract — no new Python dependency and no second LLM stack
(PRD §5.9). ``analyze_screenshot`` needs the ``screen_capture`` capability
because capturing the screen is hardware access (PRD §39);
``analyze_image`` only reads a file inside an approved workspace.

Both are gated by the ``vision.enabled`` master switch, like the web family.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.tools.builtin.screenshot import grab_screen
from luxion.vision.analyzer import analyze_images
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image

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


BUILTIN_TOOLS: list[Tool] = [AnalyzeImage(), AnalyzeScreenshot()]

__all__ = ["BUILTIN_TOOLS", "AnalyzeImage", "AnalyzeScreenshot", "CATEGORY"]
