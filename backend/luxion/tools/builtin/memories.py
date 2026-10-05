"""Memory tools — ``remember`` / ``recall`` / ``forget`` (PRD §33.14).

The three commands a user types as prose (``"Remember that…"``,
``"What did I tell you about…"``, ``"Forget this…"``) exposed as capabilities.
Risk follows the blast radius: reading memories is ``low``, writing one is
``medium`` (it is persistent), deleting one is ``medium`` too — the autonomy
matrix already turns that into a confirmation at level 2 (PRD §22).
"""

from __future__ import annotations

from typing import Any

from luxion.database.session import get_session_factory
from luxion.memory.models import MEMORY_KINDS
from luxion.memory.recall import format_memories, recall
from luxion.memory.store import forget, get_memory, remember
from luxion.tools.base import Tool, ToolArgumentError, ToolContext, ToolError, ToolResult, ToolSpec

_MEMORY_TAGS = [
    "memory",
    "remember",
    "recall",
    "forget",
    "note",
    "notes",
    "facts",
    "preferences",
    "preference",
    "tell you",
    "long term",
    "long-term",
]


class Remember(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="remember",
            description=(
                "Store a durable fact, preference, project note or unfinished task "
                "about the user so it survives the conversation. Use when the user "
                "says 'remember that…', 'make a note…', or states a preference you "
                "should apply next time. Do not use for the current task's scratch "
                "work or for anything that is already in the conversation."
            ),
            risk="medium",
            category="memory",
            tags=_MEMORY_TAGS,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "One standalone statement, e.g. 'Prefers SQLite'.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [*MEMORY_KINDS],
                        "description": "What kind of memory this is. Defaults to 'fact'.",
                    },
                    "importance": {
                        "type": "number",
                        "description": "0..1. Higher memories are surfaced first. Defaults to 0.5.",
                    },
                },
                "required": ["text"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentError("remember: 'text' must be a non-empty string")
        kind = args.get("kind") if isinstance(args.get("kind"), str) else "fact"
        importance = args.get("importance")
        try:
            weight = 0.5 if importance is None else float(importance)
        except (TypeError, ValueError) as exc:
            raise ToolArgumentError("remember: 'importance' must be a number") from exc

        with get_session_factory()() as session:
            try:
                memory, created = remember(
                    session,
                    text,
                    kind=kind,
                    source="user",
                    conversation_id=ctx.conversation_id,
                    importance=weight,
                )
            except ValueError as exc:
                raise ToolError(str(exc), code="memory_rejected") from exc
            payload = memory.as_dict()
        return ToolResult(
            output=(
                f"Saved memory #{payload['id']}: {memory.text}"
                if created
                else f"Already stored as #{payload['id']}: {memory.text}"
            ),
            data={**payload, "created": created},
        )


class Recall(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="recall",
            description=(
                "Search long-term memory by meaning or by a phrase: facts, "
                "preferences, project notes and unfinished tasks you stored with "
                "'remember'. Use when the user asks 'what did I tell you about…', "
                "before answering anything that depends on what they already said, "
                "and when a task's constraints might be in memory."
            ),
            risk="low",
            category="memory",
            tags=_MEMORY_TAGS,
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for, e.g. 'database preference'.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "How many memories to return (1..20, default 5).",
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentError("recall: 'query' must be a non-empty string")
        raw_k = args.get("k")
        k = 5 if raw_k is None else int(raw_k)
        k = max(1, min(k, 20))

        with get_session_factory()() as session:
            hits = recall(session, query, k=k)
            if not hits:
                return ToolResult(
                    output=f"No memories match '{query}'.",
                    data={"query": query, "hits": []},
                )
            lines = [
                f"#{hit.memory.id} [{hit.memory.kind}] {hit.memory.text} "
                f"(score {hit.score:.2f}, importance {hit.memory.importance:.2f})"
                for hit in hits
            ]
            return ToolResult(
                output="\n".join(lines),
                data={
                    "query": query,
                    "hits": [hit.as_dict() for hit in hits],
                    "preview": format_memories([hit.memory for hit in hits]),
                },
            )


class Forget(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="forget",
            description=(
                "Delete a stored memory. Pass memory_id when you know it (from "
                "'recall'), or a query to drop the closest match. Use when the "
                "user says 'forget this…', 'delete that memory', or corrects "
                "something you stored earlier."
            ),
            risk="medium",
            category="memory",
            tags=_MEMORY_TAGS,
            parameters={
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "integer",
                        "description": "Id of the memory to delete.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Find the closest memory to this and delete it.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        memory_id = args.get("memory_id")
        query = args.get("query")
        if memory_id is None and not (isinstance(query, str) and query.strip()):
            raise ToolArgumentError("forget: pass 'memory_id' or 'query'")

        with get_session_factory()() as session:
            target_id: int | None = None
            if memory_id is not None:
                try:
                    target_id = int(memory_id)
                except (TypeError, ValueError) as exc:
                    raise ToolArgumentError("forget: 'memory_id' must be an integer") from exc
            else:
                hits = recall(session, str(query), k=1)
                if not hits:
                    raise ToolError(f"no stored memory matches '{query}'", code="memory_not_found")
                target_id = hits[0].memory.id

            existing = get_memory(session, target_id)
            if existing is None:
                raise ToolError(f"memory #{target_id} does not exist", code="memory_not_found")
            label = existing.text
            if not forget(session, target_id):
                raise ToolError(f"memory #{target_id} does not exist", code="memory_not_found")

        return ToolResult(
            output=f"Forgot #{target_id}: {label}",
            data={"id": target_id, "text": label, "deleted": True},
        )


BUILTIN_TOOLS: list[Tool] = [Remember(), Recall(), Forget()]
