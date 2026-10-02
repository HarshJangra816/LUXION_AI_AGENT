"""Dynamic tool loading (PRD §19, §18 tool directory layout).

Two sources beyond the builtins:

* ``LUXION_TOOLS__PLUGIN_DIRS`` — directories scanned for ``*.py`` modules.
  A module is loaded when it defines ``TOOLS: list[Tool]`` or a
  ``register(registry)`` function.
* a module-level ``select()`` hook a plugin can use to hide tools by default.

Failures are logged and skipped: one broken plugin must never take the whole
tool system down.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

from luxion.config.settings import Settings
from luxion.tools.base import Tool
from luxion.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def load_builtins(registry: ToolRegistry) -> int:
    from luxion.tools.builtin import BUILTIN_TOOLS

    registry.register_many(BUILTIN_TOOLS)
    return len(BUILTIN_TOOLS)


def load_plugin_file(path: Path, registry: ToolRegistry) -> int:
    """Import one plugin module and register whatever it exposes."""
    module_name = f"luxion_plugin_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        logger.warning("tool_plugin_unloadable", extra={"path": str(path)})
        return 0
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a broken plugin must not break Luxion
        logger.warning(
            "tool_plugin_failed",
            extra={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        )
        sys.modules.pop(module_name, None)
        return 0

    registered = 0
    register = getattr(module, "register", None)
    if callable(register):
        try:
            register(registry)
            registered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tool_plugin_register_failed",
                extra={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            )
    tools = getattr(module, "TOOLS", None)
    if isinstance(tools, Iterable):
        for item in tools:
            if isinstance(item, Tool):
                try:
                    registry.register(item)
                    registered += 1
                except ValueError as exc:
                    logger.warning(
                        "tool_plugin_duplicate", extra={"path": str(path), "error": str(exc)}
                    )
    if registered == 0:
        logger.info("tool_plugin_empty", extra={"path": str(path)})
    return registered


def load_directories(registry: ToolRegistry, directories: Iterable[Path]) -> int:
    total = 0
    for directory in directories:
        root = Path(directory).expanduser()
        if not root.is_dir():
            logger.info("tool_plugin_dir_missing", extra={"path": str(root)})
            continue
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue
            total += load_plugin_file(path, registry)
    return total


def load_all(registry: ToolRegistry, settings: Settings) -> None:
    """Builtins first (they own the canonical names), then plugins."""
    if not settings.tools.enabled:
        logger.info("tools_disabled")
        return
    load_builtins(registry)
    loaded = load_directories(registry, settings.tools.plugin_dirs)
    logger.info(
        "tools_loaded",
        extra={"tools": len(registry), "plugin_tools": loaded},
    )
