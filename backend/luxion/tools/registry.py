"""Tool registry (PRD §18).

Built once per process from the builtins plus any dynamically loaded plugin
directories (:mod:`luxion.tools.loader`); ``reset_registry()`` rebuilds it in
tests or after the user changes ``LUXION_TOOLS__PLUGIN_DIRS``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from luxion.config.settings import Settings, get_settings
from luxion.tools.base import Tool, ToolRisk, ToolSpec


class ToolRegistry:
    """Name → tool. Duplicate names are rejected so plugins cannot shadow one
    another silently."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid tool name: {name!r}")
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = tool

    def register_many(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools(self) -> list[Tool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self.tools()]

    def spec(self, name: str) -> ToolSpec | None:
        tool = self._tools.get(name)
        return tool.spec if tool else None

    def schemas(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Provider ``tools[]`` payload for ``names`` (default: everything)."""
        wanted = list(names) if names is not None else None
        specs = self.specs() if wanted is None else [s for n in wanted if (s := self.spec(n))]
        return [spec.as_openai() for spec in specs]

    def by_risk(self, risk: ToolRisk) -> list[ToolSpec]:
        return [spec for spec in self.specs() if spec.risk == risk]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


_registry: ToolRegistry | None = None
_registry_key: tuple[bool, tuple[str, ...]] | None = None


def _cache_key(settings: Settings) -> tuple[bool, tuple[str, ...]]:
    return (settings.tools.enabled, tuple(str(path) for path in settings.tools.plugin_dirs))


def build_registry(settings: Settings | None = None) -> ToolRegistry:
    """Fresh registry: builtins first, then plugin directories (loader)."""
    from luxion.tools.loader import load_all

    registry = ToolRegistry()
    load_all(registry, settings or get_settings())
    return registry


def get_registry(settings: Settings | None = None) -> ToolRegistry:
    """Process-wide registry, built on first use and rebuilt when
    ``tools.enabled`` / ``tools.plugin_dirs`` change."""
    global _registry, _registry_key
    resolved = settings or get_settings()
    key = _cache_key(resolved)
    if _registry is None or _registry_key != key:
        _registry = build_registry(resolved)
        _registry_key = key
    return _registry


def reset_registry() -> None:
    """Drop the cached registry (tests, plugin reload)."""
    global _registry, _registry_key
    _registry = None
    _registry_key = None
