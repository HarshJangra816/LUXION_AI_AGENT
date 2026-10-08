"""The builtins the agent ships (PRD "Initial tools").

Each module exposes ``BUILTIN_TOOLS``; add a module here and it is registered
automatically on the next registry build.
"""

from __future__ import annotations

from luxion.tools.base import Tool
from luxion.tools.builtin.apps import BUILTIN_TOOLS as _APPS
from luxion.tools.builtin.files import BUILTIN_TOOLS as _FILES
from luxion.tools.builtin.memories import BUILTIN_TOOLS as _MEMORIES
from luxion.tools.builtin.repository import BUILTIN_TOOLS as _REPOSITORY
from luxion.tools.builtin.screenshot import BUILTIN_TOOLS as _SCREENSHOT
from luxion.tools.builtin.system import BUILTIN_TOOLS as _SYSTEM
from luxion.tools.builtin.time_tools import BUILTIN_TOOLS as _TIME
from luxion.tools.builtin.web import BUILTIN_TOOLS as _WEB

BUILTIN_TOOLS: list[Tool] = [
    *_TIME,
    *_SYSTEM,
    *_SCREENSHOT,
    *_FILES,
    *_APPS,
    *_WEB,
    *_MEMORIES,
    *_REPOSITORY,
]

__all__ = ["BUILTIN_TOOLS"]
