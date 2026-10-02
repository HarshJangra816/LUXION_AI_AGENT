"""Desktop application launch/terminate (PRD §33.20, §20: HIGH risk)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

#: Never terminated, whatever the model asks for (PRD §40).
PROTECTED_PROCESS_NAMES = {
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "explorer.exe",
    "idle",
    "pid 0",
    "pid 4",
}

START_MENU_ROOTS = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
)


def _start_menu_candidates(name: str) -> list[Path]:
    wanted = name.lower().removesuffix(".lnk").removesuffix(".exe")
    found: list[Path] = []
    for root in START_MENU_ROOTS:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if path.suffix.lower() not in {".lnk", ".exe"}:
                    continue
                stem = path.stem.lower()
                if stem == wanted or stem.startswith(wanted):
                    found.append(path)
        except OSError:
            continue
    return found


def _launch(target: str, ctx: ToolContext) -> tuple[str, str]:
    """Blocking launch. Returns (resolved description, target actually used)."""
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        for workspace in ctx.workspaces:
            probe = workspace / candidate
            if probe.exists():
                candidate = probe
                break

    if candidate.exists():
        if sys.platform == "win32":
            os.startfile(str(candidate))  # noqa: S606 - user-approved app launch
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(candidate)])  # noqa: S603
        return f"launched {candidate}", str(candidate)

    matches = _start_menu_candidates(target)
    if matches:
        chosen = matches[0]
        if sys.platform == "win32":
            os.startfile(str(chosen))  # noqa: S606
        return f"launched {chosen}", str(chosen)

    raise ToolError(f"nothing found for '{target}' (not a path and not in the Start Menu)")


class OpenApplication(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_application",
            description=(
                "Launch a desktop application by name (matched against the Start Menu) "
                "or by file path."
            ),
            risk="high",
            category="application",
            tags=["open", "launch", "start", "run", "app", "application", "program", "execute"],
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Application name (e.g. 'notepad') or absolute path.",
                    }
                },
                "required": ["name"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args["name"]).strip()
        if not name:
            raise ToolError("name must not be empty")
        output, resolved = await asyncio.to_thread(_launch, name, ctx)
        return ToolResult(output=output, data={"requested": name, "resolved": resolved})


class CloseApplication(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="close_application",
            description=(
                "Terminate running processes by name (e.g. 'notepad.exe'). "
                "Refuses protected system processes."
            ),
            risk="high",
            category="application",
            tags=["close", "kill", "terminate", "stop", "quit", "end", "process", "app"],
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Process name, with or without '.exe'.",
                    }
                },
                "required": ["name"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args["name"]).strip()
        if not name:
            raise ToolError("name must not be empty")
        return await asyncio.to_thread(_terminate, name)


def _terminate(name: str) -> ToolResult:
    import psutil

    wanted = name.lower()
    if wanted in PROTECTED_PROCESS_NAMES:
        raise ToolError(f"'{name}' is a protected system process")

    terminated: list[str] = []
    skipped: list[str] = []
    for process in psutil.process_iter(["pid", "name"]):
        current = (process.info.get("name") or "").lower()
        if (
            current not in wanted
            and current != f"{wanted}.exe".lower()
            and not current.startswith(wanted)
        ):
            continue
        if current in PROTECTED_PROCESS_NAMES:
            skipped.append(current)
            continue
        try:
            process.terminate()
            terminated.append(f"{current} (pid {process.info['pid']})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            skipped.append(f"{current}: {type(exc).__name__}")

    if not terminated and not skipped:
        raise ToolError(f"no running process named '{name}'")

    return ToolResult(
        output=("terminated: " + ", ".join(terminated) if terminated else "nothing terminated")
        + (f" | skipped: {', '.join(skipped)}" if skipped else ""),
        data={"terminated": terminated, "skipped": skipped},
    )


BUILTIN_TOOLS: list[Tool] = [OpenApplication(), CloseApplication()]
