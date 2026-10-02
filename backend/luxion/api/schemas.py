"""Request/response schemas for the HTTP API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from luxion.config.settings import Settings
from luxion.context import ContextStats
from luxion.database.models import Conversation, Message
from luxion.llm.registry import PROVIDER_SPECS, get_provider
from luxion.security.capabilities import (  # noqa: F401 - re-exported response models
    CapabilityInfo,
    CapabilityReport,
)
from luxion.services.usage import (  # noqa: F401 - re-exported response models
    ContextBudgetOut,
    ConversationContextReport,
    RecentTurn,
    SummaryStateOut,
    TokenTotals,
    UsageReport,
    UsageTotals,
    context_stats_of,
)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.isoformat()
    return str(value)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    #: USD spend reported by the provider (stored in ``messages.meta``).
    cost_usd: float | None = None
    #: Prompt composition that produced this reply (stored in ``messages.meta``).
    context: ContextStats | None = None
    #: Tools that ran to produce this reply (stored in ``messages.meta``).
    tools: list[dict[str, Any]] | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at_iso(cls, value: Any) -> str | None:
        return _iso(value)

    @classmethod
    def from_model(cls, message: Message) -> MessageOut:
        meta = message.meta if isinstance(message.meta, dict) else {}
        cost = meta.get("cost_usd")
        tools = meta.get("tools")
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=_iso(message.created_at) or "",
            tokens_in=message.tokens_in,
            tokens_out=message.tokens_out,
            cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
            context=context_stats_of(meta),
            tools=tools if isinstance(tools, list) else None,
        )


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _timestamp_iso(cls, value: Any) -> str | None:
        return _iso(value)

    @classmethod
    def from_model(cls, conversation: Conversation) -> ConversationSummary:
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=_iso(conversation.created_at) or "",
            updated_at=_iso(conversation.updated_at) or "",
            message_count=len(conversation.messages),
        )


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = []

    @classmethod
    def from_model(cls, conversation: Conversation) -> ConversationDetail:
        summary = ConversationSummary.from_model(conversation)
        return cls(
            **summary.model_dump(),
            messages=[MessageOut.from_model(message) for message in conversation.messages],
        )


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)

    @field_validator("content")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class LLMStatus(BaseModel):
    """Safe view of the active LLM configuration (never exposes the key)."""

    provider: str
    label: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    request_timeout_s: float
    #: True when this provider can use a key *and* one actually resolves.
    #: A stray ``llm.api_key`` never marks a keyless provider as configured.
    api_key_configured: bool
    api_key_env: str
    uses_default_system_prompt: bool
    available_providers: list[dict[str, Any]] = []


def build_llm_status(settings: Settings) -> LLMStatus:
    specs = {str(spec["id"]): str(spec["label"]) for spec in PROVIDER_SPECS}
    provider = get_provider(settings.llm)
    consumes_key = (
        provider.requires_api_key
        or bool(provider.default_api_key_env)
        or bool(settings.llm.api_key_env)
    )
    return LLMStatus(
        provider=settings.llm.provider,
        label=specs.get(settings.llm.provider, settings.llm.provider),
        model=settings.llm.model,
        base_url=provider.base_url,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        request_timeout_s=settings.llm.request_timeout_s,
        api_key_configured=consumes_key and provider.api_key is not None,
        # Show the env var that will actually be consulted, provider default included.
        api_key_env=settings.llm.api_key_env or provider.default_api_key_env,
        uses_default_system_prompt=not bool(settings.llm.system_prompt.strip()),
        available_providers=list(PROVIDER_SPECS),
    )


# ---------------------------------------------------------------- tools (Phase 3)
class ToolInfo(BaseModel):
    """One registered tool plus its *current* permission (PRD §18, §21)."""

    name: str
    description: str
    risk: str
    category: str
    tags: list[str] = []
    read_only: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Effective decision right now.
    permission: str
    permission_reason: str = ""
    #: What the user stored (``None`` = fall back to the autonomy default).
    override: str | None = None
    #: Capability that must be granted before the tool may run (PRD §39).
    requires: str | None = None


class ToolCatalog(BaseModel):
    enabled: bool
    autonomy_level: int
    tools: list[ToolInfo] = []
    #: Default decision per risk level for the current autonomy level.
    defaults: list[dict[str, str]] = []


class PermissionReport(BaseModel):
    overrides: dict[str, str] = {}
    defaults: list[dict[str, str]] = []


class PermissionUpdate(BaseModel):
    level: str | None = Field(default=None, description="allow | confirm | deny | null to reset")


class ToolLogResponse(BaseModel):
    entries: list[Any] = []


class ConfirmationOut(BaseModel):
    id: str
    tool: str
    risk: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    description: str = ""
    conversation_id: str | None = None
    age_s: float = 0.0


class ConfirmationList(BaseModel):
    confirmations: list[ConfirmationOut] = []
    timeout_s: float = 0.0


class ConfirmationResolve(BaseModel):
    approved: bool


class ConfirmationOutcome(BaseModel):
    resolved: bool


class ToolRunRequest(BaseModel):
    """Manual execution from Settings (``approved`` stands in for the chat
    confirmation the UI cannot issue from this request)."""

    args: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


# ------------------------------------------- capabilities (Phase 3.5, PRD §39)
class CapabilityAction(BaseModel):
    """One action against a capability (validated against its kind)."""

    action: str = Field(
        description="probe | grant | deny | reset | open_settings | connect | disconnect"
    )
    #: connect: ``local_ics`` | ``ics_subscription``
    source: str | None = None
    #: connect: filesystem path (``local_ics``) or feed URL (``ics_subscription``)
    target: str | None = None
    label: str | None = None
    #: disconnect: one source id; omitted = disconnect every source
    id: str | None = None
