"""Runtime RAG settings written by Settings → Memory (PRD §32).

Same contract as :mod:`luxion.config.voice_override`: ``.env`` /
``LUXION_RAG__*`` stay the defaults, ``<data_dir>/rag.json`` records what the
user changed in the UI (the embedding model in particular, because it decides
the vector dimension of everything already indexed), and a missing / unreadable
/ hand-edited file is ignored rather than taking the app down.

Only **the fields the user actually touched** are stored, so ``.env`` keeps
every default it was not told to change.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILE_NAME = "rag.json"


def rag_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load_overrides(data_dir: Path) -> dict[str, Any]:
    """Read the persisted overlay as a plain dict (never raises)."""
    path = rag_path(data_dir)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("rag_overrides_unreadable path=%s error=%s", path, exc)
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("rag_overrides_ignored path=%s error=%s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("rag_overrides_ignored path=%s error=not an object", path)
        return {}
    return {str(key): value for key, value in data.items()}


def save_overrides(data_dir: Path, values: dict[str, Any]) -> Path | None:
    """Persist the overlay (write-then-rename). ``None`` when it is empty."""
    if not values:
        clear_overrides(data_dir)
        return None
    path = rag_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)
    return path


def clear_overrides(data_dir: Path) -> bool:
    """Drop the overlay so ``.env`` becomes authoritative again."""
    try:
        rag_path(data_dir).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("rag_overrides_not_removed path=%s error=%s", data_dir, exc)
        return False
    return True
