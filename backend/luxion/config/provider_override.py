"""Runtime provider selection written by the Settings page.

Tapping an adapter in Settings must switch the active LLM provider without
editing ``.env`` and restarting the backend (PRD §32 *Settings → AI*), so the
choice is persisted next to the database and re-applied whenever settings are
built:

* ``.env`` / ``LUXION_LLM__*`` stay the **defaults** and seed the adapter they
  already describe;
* ``<data_dir>/llm_provider.json`` records the **active** adapter plus the
  model id the user typed for each adapter (model names are provider-specific,
  so they are remembered per adapter);
* a missing, unreadable or hand-edited file is ignored rather than taking the
  app down — ``get_settings()`` then simply falls back to ``.env``.

This module owns only the data shape and the file IO. Mapping the selection
onto :class:`~luxion.config.settings.LLMConfig` lives in ``settings.py``, which
is what keeps this file free to import from its own parent (no import cycle).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

FILE_NAME = "llm_provider.json"


class ProviderSelection(BaseModel):
    """What the user last chose in Settings → Installed provider adapters."""

    #: Active adapter id. Empty (or unknown) means "use ``.env``".
    active: str = ""
    #: Model id per adapter; an adapter without an entry auto-detects the
    #: first model the endpoint reports.
    models: dict[str, str] = Field(default_factory=dict)


def selection_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load_selection(data_dir: Path) -> ProviderSelection | None:
    """Read the persisted selection, or ``None`` when there is nothing usable."""
    path = selection_path(data_dir)
    try:
        # utf-8-sig: tolerate the BOM Windows editors (PowerShell 5.1,
        # Notepad) put in front of the JSON — otherwise it fails to parse.
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:  # unreadable directory, locked file, ...
        logger.warning("provider_selection_unreadable path=%s error=%s", path, exc)
        return None
    try:
        return ProviderSelection.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        logger.warning("provider_selection_ignored path=%s error=%s", path, exc)
        return None


def save_selection(data_dir: Path, selection: ProviderSelection) -> Path:
    """Persist ``selection`` (write-then-rename, so a crash never truncates it)."""
    path = selection_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(selection.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def clear_selection(data_dir: Path) -> bool:
    """Delete the persisted selection (Settings → *reset to .env*)."""
    try:
        selection_path(data_dir).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("provider_selection_not_removed path=%s error=%s", data_dir, exc)
        return False
    return True
