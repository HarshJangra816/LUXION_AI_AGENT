"""Screen capture (PRD §20: take_screenshot is LOW; §33.15 screenshots)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from luxion.tools.base import Tool, ToolContext, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace


def _grab() -> tuple[object, tuple[int, int]]:
    from PIL import ImageGrab

    image = ImageGrab.grab(all_screens=True)
    return image, image.size


class TakeScreenshot(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="take_screenshot",
            description=(
                "Capture all connected displays and save the PNG. Returns the saved "
                "file path so it can be read or attached."
            ),
            risk="low",
            category="vision",
            tags=[
                "screenshot",
                "capture",
                "screen",
                "grab",
                "picture",
                "image",
                "display",
                "snapshot",
            ],
            read_only=True,
            requires="screen_capture",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional destination inside an approved workspace.",
                    }
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raw = args.get("path")
        if raw:
            destination = resolve_in_workspace(str(raw), ctx)
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            destination = ctx.settings.app.data_dir / "screenshots" / f"{stamp}.png"

        destination.parent.mkdir(parents=True, exist_ok=True)

        def _save() -> tuple[int, tuple[int, int]]:
            image, size = _grab()
            image.save(destination, format="PNG")  # type: ignore[attr-defined]
            return destination.stat().st_size, size

        size_bytes, dimensions = await asyncio.to_thread(_save)
        return ToolResult(
            output=f"saved screenshot to {destination} ({dimensions[0]}x{dimensions[1]})",
            data={
                "path": str(destination),
                "bytes": size_bytes,
                "width": dimensions[0],
                "height": dimensions[1],
            },
        )


BUILTIN_TOOLS: list[Tool] = [TakeScreenshot()]
