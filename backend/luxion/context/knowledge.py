"""Knowledge injection (Phase 5d, PRD §58 + §16 context integration).

Every chat turn gets a compact block of *retrieved context* appended to the
system prompt: the memories that match the user's text, and the project files
the question is probably about. Neither is chat history — they are side-channel
facts the model would otherwise have to ask a tool for.

Design rules:

- **Never fatal.** A broken index, a missing model or an empty store degrades
  to ``""``; a turn must not fail because retrieval did.
- **Budgeted.** ``context.knowledge_max_chars`` is split evenly between the
  memory and repository halves when both are on, so one noisy side cannot eat
  the whole allowance.
- **Gated twice.** ``rag.enabled`` is the master switch; ``inject_memory`` /
  ``inject_repository`` are the per-source toggles Settings → Memory exposes.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from luxion.config.settings import Settings
from luxion.memory.recall import format_memories, recall, recent_memories
from luxion.repository.retrieval import files_relevant_to, format_repo_context

logger = logging.getLogger(__name__)

#: Shortest user text worth handing to the repository retriever — one or two
#: characters match everything ("a", "hi") and would only inject noise.
MIN_REPO_QUERY_CHARS = 3


def memory_context(
    session: Session,
    settings: Settings,
    *,
    query: str = "",
    max_chars: int = 1200,
) -> str:
    """The ``Relevant memories`` block — recalled by query, else the freshest.

    With no query (or nothing found) the newest memories are injected anyway:
    "what did I tell you about X" should never be needed for the assistant to
    know the user's name.
    """
    if not settings.rag.enabled or not settings.rag.inject_memory or max_chars <= 0:
        return ""
    try:
        text = (query or "").strip()
        memories = []
        if text:
            hits = recall(
                session,
                text,
                k=settings.rag.top_k,
                min_score=settings.rag.min_score,
            )
            memories = [hit.memory for hit in hits]
        if not memories:
            memories = recent_memories(session, k=3)
        return format_memories(memories, max_chars=max_chars)
    except Exception:  # noqa: BLE001 - retrieval must never break a chat turn
        logger.warning("memory_context_failed", exc_info=True)
        return ""


def repository_context(
    session: Session,
    settings: Settings,
    *,
    query: str,
    max_chars: int = 1200,
) -> str:
    """The ``Relevant files`` block — skipped for a query too short to rank."""
    if not settings.rag.enabled or not settings.rag.inject_repository or max_chars <= 0:
        return ""
    text = (query or "").strip()
    if len(text) < MIN_REPO_QUERY_CHARS:
        return ""
    try:
        files = files_relevant_to(session, text)
        return format_repo_context(files, max_chars=max_chars)
    except Exception:  # noqa: BLE001 - retrieval must never break a chat turn
        logger.warning("repository_context_failed", exc_info=True)
        return ""


def knowledge_context(
    session: Session,
    settings: Settings,
    *,
    query: str = "",
) -> str:
    """Everything retrieved for this turn, prompt-ready (``""`` = nothing).

    Memory comes first, repository second — the model reads who the user is
    before it reads where their code lives.
    """
    limit = settings.context.knowledge_max_chars
    if limit <= 0:
        return ""
    want_memory = settings.rag.enabled and settings.rag.inject_memory
    want_repo = settings.rag.enabled and settings.rag.inject_repository
    if not want_memory and not want_repo:
        return ""
    share = limit // 2 if (want_memory and want_repo) else limit

    parts: list[str] = []
    memory = memory_context(session, settings, query=query, max_chars=share) if want_memory else ""
    repository = (
        repository_context(session, settings, query=query, max_chars=share) if want_repo else ""
    )
    if memory:
        parts.append(f"Relevant memories:\n{memory}")
    if repository:
        parts.append(f"Relevant files:\n{repository}")
    return "\n\n".join(parts)


__all__ = [
    "MIN_REPO_QUERY_CHARS",
    "knowledge_context",
    "memory_context",
    "repository_context",
]
