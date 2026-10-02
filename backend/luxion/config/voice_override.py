"""Runtime voice settings written by Settings → Voice (PRD §32).

Same contract as :mod:`luxion.config.provider_override`: ``.env`` /
``LUXION_VOICE__*`` stay the defaults, ``<data_dir>/voice.json`` records what
the user changed in the UI, and a missing / unreadable / hand-edited file is
ignored rather than taking the app down.

The file only ever holds **the fields the user actually touched** (partial
overlay), so adding a knob later never invalidates an old file, and unknown or
mistyped values are dropped instead of crashing :func:`get_settings`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILE_NAME = "voice.json"


def voice_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load_overrides(data_dir: Path) -> dict[str, Any]:
    """Read the persisted overlay as a plain dict (never raises)."""
    path = voice_path(data_dir)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("voice_overrides_unreadable path=%s error=%s", path, exc)
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("voice_overrides_ignored path=%s error=%s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("voice_overrides_ignored path=%s error=not an object", path)
        return {}
    return {str(key): value for key, value in data.items()}


def save_overrides(data_dir: Path, values: dict[str, Any]) -> Path | None:
    """Persist the overlay (write-then-rename). ``None`` when it is empty."""
    if not values:
        clear_overrides(data_dir)
        return None
    path = voice_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)
    return path


def clear_overrides(data_dir: Path) -> bool:
    """Drop the overlay so ``.env`` becomes authoritative again."""
    try:
        voice_path(data_dir).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("voice_overrides_not_removed path=%s error=%s", data_dir, exc)
        return False
    return True
