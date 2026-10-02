"""Dynamic tool routing (PRD §19).

The model should never see every tool at once. ``select_tools`` scores the
registry against the user's request (tag/name/description keyword overlap)
and returns a capped slice. When nothing matches — a vague first message — it
falls back to exposing everything within the cap rather than leaving the model
blind, and always keeps the cheapest read-only tools in the candidate pool.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from luxion.config.settings import Settings
from luxion.tools.base import ToolSpec
from luxion.tools.registry import ToolRegistry

_WORD = re.compile(r"[a-z0-9_]{3,}")
_STOPWORDS = {"the", "and", "for", "with", "please", "you", "can", "this", "that"}


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def score(spec: ToolSpec, query: set[str]) -> int:
    if not query:
        return 0
    hits = len(query & set(spec.tags))
    hits += 2 * len(query & set(_WORD.findall(spec.name.lower())))
    hits += len(query & set(_WORD.findall(spec.description.lower())))
    return hits


def _rank(specs: list[ToolSpec], words: set[str]) -> list[ToolSpec]:
    return sorted(specs, key=lambda spec: (-score(spec, words), spec.name))


def select_tools(
    query: str,
    registry: ToolRegistry,
    settings: Settings,
    *,
    always: Iterable[str] = (),
) -> list[ToolSpec]:
    """Tools to expose for one request, best match first, capped."""
    specs = registry.specs()
    limit = settings.tools.max_exposed
    words = _tokens(query)
    if len(specs) <= limit and not any(always):
        # Nothing has to be dropped, but the order still ranks relevance so
        # callers (and the Settings preview) see what matters first.
        return _rank(specs, words)

    ranked = _rank(specs, words)

    keep: list[ToolSpec] = []
    for spec in ranked:
        if len(keep) >= limit:
            break
        if spec.name in always or spec.tags or score(spec, words) > 0:
            keep.append(spec)

    # Nothing matched the request: expose the head of the registry instead of
    # an empty tool list (the model would otherwise claim it cannot act).
    if not keep:
        keep = ranked[:limit]
    return keep
