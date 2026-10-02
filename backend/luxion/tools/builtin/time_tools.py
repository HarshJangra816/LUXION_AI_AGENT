"""Clock tools — pure, side-effect free (PRD §20: LOW)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec


def _now(tz: str | None) -> datetime:
    if tz:
        try:
            return datetime.now(ZoneInfo(tz))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ToolError(f"unknown timezone '{tz}'") from exc
    return datetime.now().astimezone()


class GetTime(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_time",
            description=(
                "Get the current local time (and UTC) in ISO format. "
                "Use instead of guessing the time."
            ),
            risk="low",
            category="time",
            tags=["time", "clock", "hour", "now", "current", "utc", "timezone"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "tz": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'Europe/London'. Defaults to local.",
                    }
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        local = _now(args.get("tz"))
        utc = local.astimezone(UTC)
        return ToolResult(
            output=(
                f"Local: {local.isoformat(timespec='seconds')} | "
                f"UTC: {utc.isoformat(timespec='seconds')}"
            ),
            data={
                "local": local.isoformat(timespec="seconds"),
                "utc": utc.isoformat(timespec="seconds"),
                "tz": str(local.tzinfo),
            },
        )


class GetDate(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_date",
            description="Get today's date, the weekday and days remaining in the year.",
            risk="low",
            category="time",
            tags=["date", "day", "weekday", "today", "calendar", "year"],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "tz": {
                        "type": "string",
                        "description": "IANA timezone. Defaults to local.",
                    }
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        today = _now(args.get("tz"))
        remaining = (today.replace(month=12, day=31) - today).days
        iso = today.isocalendar()
        output = (
            f"{today.date().isoformat()} ({today.strftime('%A')}) | "
            f"ISO week {iso.week} | {remaining} days until Dec 31"
        )
        return ToolResult(
            output=output,
            data={
                "date": today.date().isoformat(),
                "weekday": today.strftime("%A"),
                "iso_week": int(iso.week),
                "days_left_in_year": remaining,
            },
        )


BUILTIN_TOOLS: list[Tool] = [GetTime(), GetDate()]
