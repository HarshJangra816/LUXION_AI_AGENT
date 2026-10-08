"""Repository search — ``search_code`` (PRD §17 Repository Intelligence).

The read side of the workspace index exposed to the model: "where is the
retry logic?", "what calls ``flush_stream``?" — answered with file paths and
line ranges instead of pasting a whole repository into the context (PRD §17:
*never send an entire repository to the LLM*).

Risk is ``low`` and ``read_only``: it touches the index, never the disk.
"""

from __future__ import annotations

from typing import Any

from luxion.database.session import get_session_factory
from luxion.repository.retrieval import files_relevant_to, relative_path, search_repository
from luxion.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult, ToolSpec

_REPOSITORY_TAGS = [
    "code",
    "search",
    "repository",
    "project",
    "workspace",
    "file",
    "find",
    "grep",
    "where",
    "index",
    "source",
]


class SearchCode(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_code",
            description=(
                "Semantic search over the indexed project files (source and docs): "
                "returns the matching files with their line ranges and a short "
                "excerpt. Use before reading a file you have not opened yet, to "
                "locate a function, class, config key or error message, and to "
                "answer 'where/what calls X' questions. Read only the returned "
                "line ranges — do not read whole files when a hit answers it. "
                "Never use it for long-term memory (use recall) or the web."
            ),
            risk="low",
            category="repository",
            tags=_REPOSITORY_TAGS,
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to locate, e.g. 'retry backoff' or 'flush_stream'.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "How many hits to return (1..20, default 6).",
                    },
                    "files": {
                        "type": "integer",
                        "description": "Group hits into this many files (1..10, default 5).",
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentError("search_code: 'query' must be a non-empty string")
        raw_k = args.get("k")
        k = 6 if raw_k is None else int(raw_k)
        k = max(1, min(k, 20))
        raw_files = args.get("files")
        max_files = 5 if raw_files is None else int(raw_files)
        max_files = max(1, min(max_files, 10))

        settings = ctx.settings
        if not settings.rag.enabled:
            return ToolResult(
                output=(
                    "Repository search is disabled (LUXION_RAG__ENABLED=false), so no "
                    "project files are indexed."
                ),
                data={"query": query, "hits": [], "enabled": False},
            )
        roots = settings.security.allowed_workspaces

        with get_session_factory()() as session:
            hits = search_repository(session, query, k=k)
            grouped = files_relevant_to(session, query, k=k, max_files=max_files)

        if not hits:
            return ToolResult(
                output=(
                    f"No indexed project files match '{query}'. The workspace may not be "
                    "indexed yet — ask the user to run Knowledge → Index files."
                ),
                data={"query": query, "hits": [], "files": []},
            )

        lines = [
            f"{relative_path(hit.path, roots)}:{hit.range} (score {hit.score:.2f}) "
            f"{_first_line(hit.text)}"
            for hit in hits
        ]
        return ToolResult(
            output="\n".join(lines),
            data={
                "query": query,
                "hits": [hit.as_dict() for hit in hits],
                "files": [
                    {
                        "path": match.path,
                        "source_type": match.source_type,
                        "language": match.language,
                        "score": round(float(match.score), 4),
                        "range": match.range,
                        "preview": match.preview,
                    }
                    for match in grouped
                ],
            },
        )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


BUILTIN_TOOLS: list[Tool] = [SearchCode()]
