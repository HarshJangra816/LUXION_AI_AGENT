"""Memory subsystem (PRD §15 Conversation Memory, Phase 5b).

* :mod:`luxion.memory.models`     — the ``memories`` table (kind, text, importance)
* :mod:`luxion.memory.store`      — ``remember`` / ``forget`` / ``list`` + indexing
* :mod:`luxion.memory.recall`     — hybrid search over stored memories
* :mod:`luxion.memory.extraction` — LLM + heuristic extraction from finished turns

The searchable copy of every memory lives in the Phase 5a index under
``source_type = "memory"``, so recall, forgetting and a future re-embed all go
through the same code path as documents.
"""

from __future__ import annotations

from luxion.memory.extraction import extract_from_conversation, schedule_extraction
from luxion.memory.models import DEFAULT_KIND, MEMORY_KINDS, Memory
from luxion.memory.recall import MemoryHit, format_memories, recall, recent_memories
from luxion.memory.store import (
    clear_memories,
    count_memories,
    forget,
    get_memory,
    list_memories,
    memory_hash,
    normalize_text,
    remember,
)

__all__ = [
    "DEFAULT_KIND",
    "MEMORY_KINDS",
    "Memory",
    "MemoryHit",
    "clear_memories",
    "count_memories",
    "extract_from_conversation",
    "forget",
    "format_memories",
    "get_memory",
    "list_memories",
    "memory_hash",
    "normalize_text",
    "recall",
    "recent_memories",
    "remember",
    "schedule_extraction",
]
