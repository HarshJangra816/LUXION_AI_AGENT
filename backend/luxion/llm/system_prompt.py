"""System prompt (Phase 1 base + Phase 3 tool guide).

``llm.system_prompt`` overrides everything, so users can experiment without
code changes. Otherwise the prompt is assembled from a stable body plus either
a "no tools available" notice or the tool guide describing exactly the tools
exposed for the current request (PRD §19).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from luxion.config.settings import Settings
from luxion.tools.base import ToolSpec

_BASE = """\
You are Luxion, a personal AI assistant running locally on the user's desktop.

Behaviour:
- Answer directly and concisely; prefer short paragraphs and lists over essays.
- Use Markdown for structure (headings, lists, fenced code blocks).
- Never use emojis unless the user explicitly asks for them.
- If you are unsure, say so instead of inventing facts.
- You are running offline-first: do not assume internet access unless the user
  mentions it.
- The user's machine is Windows; prefer Windows-native commands and paths.

Autonomy: level {autonomy} of 5."""

_NO_TOOLS = """
You cannot call tools in this request, so when a task would need one,
describe what you would do instead of claiming you did it."""

#: Kept for backwards compatibility — the exact Phase 1 prompt.
DEFAULT_SYSTEM_PROMPT = _BASE + _NO_TOOLS


def _tool_guide(tools: Sequence[ToolSpec]) -> str:
    lines = ["", "", "Tools available for this request:"]
    for spec in tools:
        lines.append(f"- {spec.name}: {spec.description} (risk: {spec.risk})")
    lines += [
        "",
        "Tool rules:",
        "- Call a tool when it is the reliable way to answer; never guess a value a tool "
        "can return.",
        "- One tool call per step, then wait for its result before continuing.",
        "- Use a tool's result verbatim as your source of truth. If a result is an error or was "
        "denied, say so honestly instead of inventing an outcome.",
        "- Only call tools that are listed above; anything else will be rejected.",
    ]
    return "\n".join(lines)


def build_system_prompt(settings: Settings, tools: Sequence[ToolSpec] | None = None) -> str:
    """Resolve the system message for this build.

    ``tools`` is the tool set exposed for the *current* request — passing it
    switches the prompt from "you have no tools" to the tool guide.
    """
    if custom := settings.llm.system_prompt.strip():
        return custom
    now = datetime.now(UTC)
    body = DEFAULT_SYSTEM_PROMPT if tools is None else _BASE
    prompt = body.format(autonomy=settings.security.autonomy_level)
    if tools is not None:
        prompt += _tool_guide(tools)
    return prompt + f"\nCurrent UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
