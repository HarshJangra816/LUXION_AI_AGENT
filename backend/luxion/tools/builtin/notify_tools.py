"""Notification tool (Phase 10, PRD §33 "Notifications").

One tool, one job: raise a desktop toast through :mod:`luxion.notify`. It is
gated by the ``notifications`` capability (hard gate, default granted — Tools
→ Permissions & capabilities) *and* the ``notify.enabled`` master switch, and
the module-level cooldown keeps a chatty turn from stacking toasts.
"""

from __future__ import annotations

from luxion.notify.toast import ToastError, send_toast
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

#: Common category so the tool router and the system prompt can recognise the
#: family.
CATEGORY = "notifications"


class Notify(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify",
            description=(
                "Show a desktop notification (Windows toast) on this machine. Use when the "
                "user should notice something without watching the chat — a finished task, a "
                "reminder, a result they asked to be alerted about. Keep it short: one line "
                "the user can read at a glance."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "notify",
                "notification",
                "toast",
                "alert",
                "remind",
                "reminder",
                "desktop",
                "popup",
                "ping",
            ],
            requires="notifications",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short headline, e.g. 'Backup finished'.",
                    },
                    "message": {
                        "type": "string",
                        "description": "One line of detail shown under the title.",
                    },
                    "duration_s": {
                        "type": "integer",
                        "description": "Seconds on screen (3-25; default from settings).",
                        "minimum": 3,
                        "maximum": 25,
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        title = str(args.get("title") or "").strip()
        message = str(args.get("message") or "").strip()
        raw_duration = args.get("duration_s")
        duration = int(raw_duration) if raw_duration is not None else None
        if duration is not None and not 3 <= duration <= 25:
            raise ToolError("duration_s must be between 3 and 25 seconds")

        try:
            outcome = await send_toast(title, message, settings=ctx.settings, duration_s=duration)
        except ToastError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            output=f"notification shown: {outcome['title']!r}",
            data={"notification": outcome},
        )


BUILTIN_TOOLS: list[Tool] = [Notify()]
