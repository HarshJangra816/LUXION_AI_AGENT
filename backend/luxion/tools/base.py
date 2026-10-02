"""Tool contract: what a tool is, what it returns, how it is validated.

Every capability Luxion exposes to the model is a :class:`Tool` — a static
:class:`ToolSpec` (JSON schema + risk) plus one async ``run``. The executor
never imports a concrete tool, so plugins and builtins are interchangeable
(PRD §57 rule 14: keep tools modular).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from luxion.config.settings import Settings

ToolRisk = Literal["low", "medium", "high", "critical"]
PermissionLevel = Literal["allow", "confirm", "deny"]

RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class ToolError(Exception):
    """Base class for tool failures the model should see as an error result."""

    def __init__(self, message: str, *, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


class ToolArgumentError(ToolError):
    """The model passed arguments that do not match the schema."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_arguments")


class ToolSpec(BaseModel):
    """Static description handed to the LLM (PRD §18 ``Tool(...)``)."""

    name: str
    description: str
    risk: ToolRisk = "low"
    category: str = "general"
    #: Keywords used by the dynamic tool router (PRD §19).
    tags: list[str] = Field(default_factory=list)
    #: JSON Schema for the arguments (``type: object``).
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    #: Free of side effects — the only kind autonomy level 2 runs unattended.
    read_only: bool = False
    #: Capability that must be granted before this tool may run *at all*.
    #: Checked before the permission engine — a denied capability is a hard
    #: block regardless of autonomy level (PRD §39).
    requires: str | None = None

    def as_openai(self) -> dict[str, Any]:
        """OpenAI ``/chat/completions`` ``tools[]`` entry (also used by Ollama)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolResult(BaseModel):
    """Outcome of one execution, normalised for both the UI and the model."""

    ok: bool = True
    output: str = ""
    #: Structured payload for the UI (screenshot path, stats, …).
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ToolContext:
    """Runtime facts a tool may need (never the API keys — PRD §57 rule 6)."""

    __slots__ = ("settings", "conversation_id", "turn_id")

    def __init__(self, settings: Settings, *, conversation_id: str | None = None) -> None:
        self.settings = settings
        self.conversation_id = conversation_id
        self.turn_id: str | None = None

    @property
    def workspaces(self) -> list:
        return list(self.settings.security.allowed_workspaces)


class Tool(ABC):
    """A registered capability. Subclasses only implement ``spec`` + ``run``."""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Static metadata; must be cheap and side-effect free."""

    @abstractmethod
    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute. Raise :class:`ToolError` for expected failures."""


# --------------------------------------------------------------------- schema
def validate_args(spec: ToolSpec, args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate model-supplied arguments against the tool's JSON Schema.

    Deliberately a small subset (type / required / enum / properties) — enough
    to reject malformed calls early without pulling in a schema library.
    """
    given = dict(args or {})
    schema = spec.parameters or {}
    if schema.get("type", "object") != "object":
        return given

    properties: dict[str, Any] = schema.get("properties") or {}
    required: list[str] = list(schema.get("required") or [])

    missing = [key for key in required if key not in given]
    if missing:
        raise ToolArgumentError(f"{spec.name}: missing required argument(s): {', '.join(missing)}")

    allowed = set(properties)
    unknown = [key for key in given if allowed and key not in allowed]
    if unknown:
        raise ToolArgumentError(f"{spec.name}: unknown argument(s): {', '.join(sorted(unknown))}")

    for key, value in list(given.items()):
        schema_of = properties.get(key)
        if not isinstance(schema_of, dict):
            continue
        expected = schema_of.get("type")
        if expected and not _matches_type(value, expected):
            raise ToolArgumentError(
                f"{spec.name}: '{key}' must be {expected}, got {type(value).__name__}"
            )
        enum = schema_of.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolArgumentError(f"{spec.name}: '{key}' must be one of {enum}")
    return given


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True
