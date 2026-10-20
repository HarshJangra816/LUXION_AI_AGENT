"""Runtime email settings written by Settings → Email (Phase 10).

Same contract as :mod:`luxion.config.web_override` and friends: ``.env`` /
``LUXION_EMAIL__*`` stay the defaults, ``<data_dir>/email.json`` records what
the user changed in the UI, and a missing / unreadable / hand-edited file is
ignored rather than taking the app down.

The SMTP **password is never stored here** — the overlay is a world-readable
JSON the API returns verbatim. Credentials live in ``.env`` (or the env var
``smtp_password_env`` points at) only.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILE_NAME = "email.json"

#: Credential fields this overlay refuses to persist, belt-and-braces beside
#: :func:`luxion.config.settings._valid_email_values` (which strips them on
#: load). Kept as a local literal to avoid importing settings — settings
#: imports this module. A test keeps the two sets identical.
SECRET_FIELDS = frozenset({"smtp_password"})


def email_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load_overrides(data_dir: Path) -> dict[str, Any]:
    """Read the persisted overlay as a plain dict (never raises)."""
    path = email_path(data_dir)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("email_overrides_unreadable path=%s error=%s", path, exc)
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("email_overrides_ignored path=%s error=%s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("email_overrides_ignored path=%s error=not an object", path)
        return {}
    return {str(key): value for key, value in data.items()}


def save_overrides(data_dir: Path, values: dict[str, Any]) -> Path | None:
    """Persist the overlay (write-then-rename). ``None`` when it is empty.

    Secret fields are dropped here as well, so no code path — direct or via
    :func:`luxion.config.settings.save_email_overrides` — can land a password
    on disk.
    """
    safe = {key: value for key, value in values.items() if key not in SECRET_FIELDS}
    if not safe:
        clear_overrides(data_dir)
        return None
    path = email_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)
    return path


def clear_overrides(data_dir: Path) -> bool:
    """Drop the overlay so ``.env`` becomes authoritative again."""
    try:
        email_path(data_dir).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("email_overrides_not_removed path=%s error=%s", data_dir, exc)
        return False
    return True
