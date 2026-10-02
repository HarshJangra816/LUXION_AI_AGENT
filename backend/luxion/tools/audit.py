"""Tool execution audit log (PRD §43).

Append-only JSONL at ``<data_dir>/tool_log.jsonl``, trimmed to
``tools.log_limit``. A file rather than a table on purpose: the log is an
operator artefact, not application state, and keeping it off the live
SQLite schema avoids a migration (same decision as ``cost_usd``).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from luxion.config.settings import Settings

#: Argument keys whose values never reach the log (PRD §40, §57 rule 6).
SECRET_HINTS = ("key", "token", "password", "secret", "credential", "auth")
MAX_OUTPUT_CHARS = 2_000
MAX_ARGS_CHARS = 1_000


class ToolLogEntry(BaseModel):
    timestamp: str
    tool: str
    target: str | None = None
    risk: str
    permission: str
    result: str
    duration_ms: float | None = None
    conversation_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    error: str | None = None


_lock = threading.Lock()


def redact(args: dict[str, Any]) -> dict[str, Any]:
    """Blank out anything that looks like a credential before logging."""
    cleaned: dict[str, Any] = {}
    for key, value in args.items():
        if any(hint in key.lower() for hint in SECRET_HINTS):
            cleaned[key] = "***"
        else:
            cleaned[key] = value
    return cleaned


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…[{len(text) - limit} more chars]"


def log_path(settings: Settings) -> Path:
    return settings.app.data_dir / "tool_log.jsonl"


def append_log(settings: Settings, entry: ToolLogEntry) -> None:
    """Append one entry and keep the file at ``tools.log_limit`` lines."""
    path = log_path(settings)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        _trim(path, settings.tools.log_limit)


def _trim(path: Path, limit: int) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    # Rewrite only once the file has noticeably outgrown the cap.
    if len(lines) <= int(limit * 1.25):
        return
    kept = lines[-limit:]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def read_log(settings: Settings, *, limit: int = 50) -> list[ToolLogEntry]:
    """Newest-first slice of the audit log (never raises)."""
    path = log_path(settings)
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[ToolLogEntry] = []
    for line in reversed(raw_lines[-limit:]):
        try:
            entries.append(ToolLogEntry.model_validate_json(line))
        except Exception:  # noqa: BLE001 - a corrupt line must not break the view
            continue
    return entries


def build_entry(
    *,
    tool: str,
    risk: str,
    permission: str,
    result: str,
    args: dict[str, Any] | None = None,
    target: str | None = None,
    output: str | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
    conversation_id: str | None = None,
) -> ToolLogEntry:
    safe_args = redact(args or {})
    return ToolLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        tool=tool,
        target=target or _auto_target(tool, safe_args),
        risk=risk,
        permission=permission,
        result=result,
        duration_ms=None if duration_ms is None else round(duration_ms, 2),
        conversation_id=conversation_id,
        args=json.loads(_clip(json.dumps(safe_args, ensure_ascii=False), MAX_ARGS_CHARS))
        if safe_args
        else {},
        output=_clip(output, MAX_OUTPUT_CHARS) if output else None,
        error=_clip(error, 400) if error else None,
    )


#: Which argument identifies "what the tool touched" for the log's target column.
_TARGET_ARGS = {
    "read_file": "path",
    "write_file": "path",
    "open_url": "url",
    "open_application": "name",
    "close_application": "name",
    "take_screenshot": "path",
}


def _auto_target(tool: str, args: dict[str, Any]) -> str | None:
    key = _TARGET_ARGS.get(tool)
    if key and isinstance(args.get(key), str):
        return str(args[key])[:200]
    return None
