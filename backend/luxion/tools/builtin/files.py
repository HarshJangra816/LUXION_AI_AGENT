"""Filesystem tools restricted to approved workspaces (PRD §42)."""

from __future__ import annotations

from pathlib import Path

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

DEFAULT_READ_BYTES = 64 * 1024
MAX_READ_BYTES = 512 * 1024
MAX_WRITE_BYTES = 1024 * 1024


class WorkspaceViolation(ToolError):
    def __init__(self, path: Path | str) -> None:
        super().__init__(
            f"'{path}' is outside every approved workspace "
            "(see Security → allowed workspaces, PRD §42)",
            code="workspace_violation",
        )


def resolve_in_workspace(raw: str, ctx: ToolContext) -> Path:
    """Resolve ``raw`` and reject anything outside the approved workspaces."""
    workspaces = ctx.workspaces
    if not workspaces:
        raise ToolError("no approved workspace is configured (LUXION_SECURITY__ALLOWED_WORKSPACES)")

    candidate = Path(str(raw)).expanduser()
    if not candidate.is_absolute():
        # Relative paths anchor on the first workspace, never on the CWD.
        candidate = workspaces[0] / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ToolError(f"cannot resolve '{raw}': {exc}") from exc

    for workspace in workspaces:
        try:
            root = workspace.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_relative_to(root):
            return resolved
    raise WorkspaceViolation(raw)


def _read_file() -> Tool:
    return ReadFile()


def _write_file() -> Tool:
    return WriteFile()


class ReadFile(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description=(
                "Read a text file from an approved workspace. Returns the file's "
                "content, clipped to the byte limit you ask for."
            ),
            risk="low",
            category="filesystem",
            tags=[
                "read",
                "file",
                "open",
                "content",
                "text",
                "path",
                "source",
                "code",
                "view",
                "directory",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Bytes to read (default 65536, max 524288).",
                    },
                },
                "required": ["path"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = resolve_in_workspace(str(args["path"]), ctx)
        if not path.exists():
            raise ToolError(f"file not found: {path}")
        if path.is_dir():
            entries = sorted(child.name for child in path.iterdir())[:200]
            return ToolResult(
                output=f"Directory {path} ({len(entries)} entries)\n" + "\n".join(entries),
                data={"path": str(path), "is_dir": True, "entries": entries},
            )

        limit = int(args.get("max_bytes") or DEFAULT_READ_BYTES)
        limit = max(1, min(limit, MAX_READ_BYTES))
        raw = path.read_bytes()[: limit + 1]
        clipped = len(raw) > limit
        text = raw[:limit].decode("utf-8", errors="replace")
        if clipped:
            text += "\n…[clipped]"
        size = path.stat().st_size
        return ToolResult(
            output=text,
            data={"path": str(path), "size": size, "clipped": clipped, "bytes_read": limit},
        )


class WriteFile(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description=(
                "Create or overwrite a text file inside an approved workspace. "
                "Parent directories are created automatically."
            ),
            risk="medium",
            category="filesystem",
            tags=["write", "save", "create", "file", "edit", "persist", "store"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path.",
                    },
                    "content": {"type": "string", "description": "Full text to write."},
                    "append": {"type": "boolean", "description": "Append instead of overwrite."},
                },
                "required": ["path", "content"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = resolve_in_workspace(str(args["path"]), ctx)
        content = str(args.get("content", ""))
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ToolError(f"content too large ({len(encoded)} bytes, max {MAX_WRITE_BYTES})")
        if path.exists() and path.is_dir():
            raise ToolError(f"'{path}' is a directory")

        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if args.get("append") else "wb"
        with path.open(mode) as handle:
            handle.write(encoded)
        action = "appended to" if args.get("append") else "wrote"
        return ToolResult(
            output=f"{action} {path} ({len(encoded)} bytes)",
            data={"path": str(path), "bytes": len(encoded), "appended": bool(args.get("append"))},
        )


BUILTIN_TOOLS: list[Tool] = [_read_file(), _write_file()]
