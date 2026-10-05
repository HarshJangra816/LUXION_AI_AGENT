"""Turn finished chat turns into durable memories (PRD §15, §58 rule 5).

Two extractors are combined and de-duplicated:

``llm``
    one small JSON call over the last :data:`EXTRACT_WINDOW` turns — catches
    anything worth keeping that the patterns below do not know about.
``heuristics``
    free, offline and deterministic — the commands in PRD §33.14
    (``Remember that…``, ``My name is…``, ``Don't forget to…``) plus the
    mock-provider path used by the test suite.

The pass is idempotent: ``conversation.meta['memory_extracted_through']``
records the last message id it looked at, so replaying a turn never stores the
same statement twice (``remember`` also de-dupes on the text hash).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from luxion.config.settings import Settings, get_settings
from luxion.database.models import Conversation, Message
from luxion.database.session import get_session_factory
from luxion.llm.errors import LLMError
from luxion.llm.registry import get_provider
from luxion.llm.types import ChatMessage
from luxion.memory.models import MEMORY_KINDS
from luxion.memory.store import remember

logger = logging.getLogger(__name__)

#: Turns handed to the extractor (both roles, newest last).
EXTRACT_WINDOW = 12
#: Statements one pass may add — a chat turn is not a brainstorm.
MAX_PER_PASS = 4
#: Enough to be a statement; shorter is chat noise.
MIN_TEXT = 4

#: A candidate before it becomes a row.
Candidate = dict[str, Any]

_SYSTEM_PROMPT = (
    "You extract long-term memory from a chat transcript. "
    "Reply with ONLY a JSON array, no prose and no code fence. "
    "Each item is "
    '{"kind": "fact|preference|task|project|episode", '
    '"text": "<one standalone statement>", "importance": <0..1 number>}. '
    "Keep durable information the user told you: names, preferences, "
    "constraints, project facts, unfinished tasks. "
    "Never store the whole conversation, greetings, or things you made up. "
    "Return [] when nothing is worth keeping."
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bremember\s+(?:that\s+)?(.+)", re.I), "fact"),
    (re.compile(r"\bplease\s+note\s+(?:that\s+)?(.+)", re.I), "fact"),
    (re.compile(r"\bmy\s+name\s+is\s+(.+)", re.I), "fact"),
    (re.compile(r"\bcall\s+me\s+(.+)", re.I), "fact"),
    (
        re.compile(r"\bi\s+(?:always\s+|usually\s+)?(?:prefer|like|want|need)\s+(.+)", re.I),
        "preference",
    ),
    (re.compile(r"\bmy\s+preferred\s+(.+)", re.I), "preference"),
    (re.compile(r"\bdon'?t\s+forget\s+(?:to\s+)?(.+)", re.I), "task"),
    (re.compile(r"\b(?:i(?:'| a)?m\s+)?(?:working|building)\s+(?:on\s+)?(.+)", re.I), "project"),
)


# --------------------------------------------------------------------------- turn access
def _load_turns(conversation_id: str, limit: int) -> tuple[list[tuple[str, str]], int, Any] | None:
    """``(turns, latest_message_id, meta)`` for the newest ``limit`` messages."""
    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            return None
        rows = list(
            session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(limit)
            ).scalars()
        )
        rows.reverse()
        turns = [(row.role, row.content) for row in rows if row.content.strip()]
        latest_id = max((row.id for row in rows), default=0)
        meta = dict(conversation.meta) if isinstance(conversation.meta, dict) else {}
        return turns, latest_id, meta


def _mark_extracted(conversation_id: str, latest_id: int) -> None:
    with get_session_factory()() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            return
        meta = dict(conversation.meta) if isinstance(conversation.meta, dict) else {}
        meta["memory_extracted_through"] = latest_id
        conversation.meta = meta
        session.commit()


# --------------------------------------------------------------------------- extractors
def heuristic_candidates(turns: Sequence[tuple[str, str]]) -> list[Candidate]:
    """Pattern pass over the transcript — offline, free, deterministic."""
    found: list[Candidate] = []
    for role, content in turns:
        if role != "user":
            continue
        for pattern, kind in _PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            text = match.group(1).strip()
            if len(text) < MIN_TEXT:
                continue
            found.append({"kind": kind, "text": text, "importance": 0.6, "source": "user"})
            break
    return found[:MAX_PER_PASS]


def parse_candidates(raw: str) -> list[Candidate]:
    """Parse the extractor's JSON array, tolerating fences and stray prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return _validate(payload)


def _validate(items: Iterable[Any]) -> list[Candidate]:
    valid: list[Candidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or len(text.strip()) < MIN_TEXT:
            continue
        kind = item.get("kind") if isinstance(item.get("kind"), str) else "fact"
        if kind not in MEMORY_KINDS:
            kind = "fact"
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        valid.append(
            {
                "kind": kind,
                "text": text.strip(),
                "importance": min(1.0, max(0.0, importance)),
                "source": "extracted",
            }
        )
        if len(valid) >= MAX_PER_PASS:
            break
    return valid


async def _llm_candidates(turns: Sequence[tuple[str, str]], settings: Settings) -> list[Candidate]:
    """One small completion over the window. Failures degrade to heuristics."""
    transcript = "\n".join(f"{role}: {content}" for role, content in turns)
    provider = get_provider(settings.llm)
    try:
        model = await provider.resolve_model()
        result = await provider.complete(
            [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"Transcript:\n{transcript}"),
            ],
            model=model,
            temperature=0.0,
            max_tokens=600,
        )
    except LLMError as exc:
        logger.info("memory_extraction_llm_failed error=%s code=%s", exc, exc.code)
        return []
    except Exception as exc:  # noqa: BLE001 - extraction must never break a chat
        logger.info("memory_extraction_llm_error error=%s", exc)
        return []
    return parse_candidates(result.text)


# --------------------------------------------------------------------------- orchestration
def _persist(
    conversation_id: str,
    latest_id: int,
    candidates: Sequence[Candidate],
) -> int:
    """Store the candidates and record how far the extractor has read.

    ``remember`` enforces the ``memory_max`` ceiling and de-dupes on the text
    hash, so a rejected candidate is simply skipped here.
    """
    saved = 0
    with get_session_factory()() as session:
        for candidate in candidates:
            try:
                _memory, created = remember(
                    session,
                    str(candidate["text"]),
                    kind=str(candidate.get("kind", "fact")),
                    source=str(candidate.get("source", "extracted")),
                    conversation_id=conversation_id,
                    importance=float(candidate.get("importance", 0.5)),
                )
            except ValueError as exc:
                logger.debug("memory_candidate_rejected reason=%s", exc)
                continue
            saved += int(created)
    _mark_extracted(conversation_id, latest_id)
    if saved:
        logger.info("memory_extracted conversation=%s saved=%s", conversation_id, saved)
    return saved


async def extract_from_conversation(
    conversation_id: str, *, settings: Settings | None = None
) -> int:
    """Extract and store memories from the newest turns. Returns rows saved."""
    cfg = settings or get_settings()
    if not cfg.rag.memory_extraction:
        return 0
    loaded = await run_in_threadpool(_load_turns, conversation_id, EXTRACT_WINDOW)
    if loaded is None:
        return 0
    turns, latest_id, meta = loaded
    if not turns or not latest_id or meta.get("memory_extracted_through") == latest_id:
        return 0

    candidates: list[Candidate] = []
    if cfg.llm.provider != "mock":
        candidates = await _llm_candidates(turns, cfg)
    # heuristics always run: they are what catches an explicit "Remember that…"
    known = {(item["kind"], item["text"].casefold()) for item in candidates}
    for item in heuristic_candidates(turns):
        if (item["kind"], item["text"].casefold()) not in known:
            candidates.append(item)
    if not candidates:
        _mark_extracted(conversation_id, latest_id)
        return 0
    return await run_in_threadpool(_persist, conversation_id, latest_id, candidates)


# --------------------------------------------------------------------------- scheduling
_tasks: set[asyncio.Task] = set()


def schedule_extraction(
    conversation_id: str, *, settings: Settings | None = None
) -> asyncio.Task | None:
    """Fire-and-forget pass after a turn; never blocks or fails the chat."""
    cfg = settings or get_settings()
    if not cfg.rag.memory_extraction:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    async def _run() -> None:
        try:
            await extract_from_conversation(conversation_id, settings=cfg)
        except Exception as exc:  # noqa: BLE001 - background work, chat already replied
            logger.warning("memory_extraction_failed error=%s", exc)

    task = loop.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


__all__ = [
    "EXTRACT_WINDOW",
    "MAX_PER_PASS",
    "extract_from_conversation",
    "heuristic_candidates",
    "parse_candidates",
    "schedule_extraction",
]
