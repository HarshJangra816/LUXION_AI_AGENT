"""WhatsApp tools (PRD §33.3, Phase 10).

=====================  =========  =============================================
Tool                   Risk       Job
=====================  =========  =============================================
``whatsapp_send``      high       message a contact via WhatsApp Web (confirms)
``whatsapp_read``      medium     read the last messages of one chat
``whatsapp_open``      medium     hand a composed message to the desktop app
                                 through the ``whatsapp://`` protocol
=====================  =========  =============================================

``whatsapp_send`` / ``whatsapp_read`` drive WhatsApp Web through the shared
:mod:`luxion.whatsapp.manager` session (persistent login profile). They refuse
with a scan-the-QR message while logged out. ``whatsapp_open`` needs no
session at all — the OS opens the installed app with the text pre-filled and
the user presses Send themselves.
"""

from __future__ import annotations

import asyncio

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.whatsapp.errors import WhatsAppError
from luxion.whatsapp.manager import get_whatsapp_manager
from luxion.whatsapp.protocol import build_deep_link, open_deep_link
from luxion.whatsapp.web import read_messages, send_message

#: Common category so the tool router and the system prompt can recognise the
#: family.
CATEGORY = "whatsapp"

_CONTACT_SCHEMA = {
    "type": "string",
    "description": (
        "Contact name as it appears in WhatsApp (searched in your chats) or a "
        "phone number with country code, e.g. '+44 7700 900123'."
    ),
}


def _require_enabled(ctx: ToolContext) -> None:
    if not ctx.settings.whatsapp.enabled:
        raise ToolError(
            "WhatsApp automation is disabled — enable it in Settings → Integrations → WhatsApp"
        )


def _manager(ctx: ToolContext):
    try:
        return get_whatsapp_manager(ctx.settings)
    except WhatsAppError as exc:
        raise ToolError(str(exc)) from exc


class WhatsappSend(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="whatsapp_send",
            description=(
                "Send a WhatsApp message to a contact through WhatsApp Web. High risk — "
                "the user always confirms before a message goes to a person. Needs the "
                "QR login once (Settings → Integrations → WhatsApp)."
            ),
            risk="high",
            category=CATEGORY,
            tags=[
                "whatsapp",
                "message",
                "send",
                "text",
                "sms",
                "chat",
                "contact",
                "reply",
                "mobile",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "contact": _CONTACT_SCHEMA,
                    "text": {"type": "string", "description": "The message to send."},
                },
                "required": ["contact", "text"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        contact = str(args.get("contact") or "").strip()
        text = str(args.get("text") or "").strip()
        if not contact:
            raise ToolError("contact is required")
        if not text:
            raise ToolError("text is required")
        manager = _manager(ctx)
        session = await manager.session()
        try:
            outcome = await send_message(
                session,
                contact,
                text,
                timeout_ms=ctx.settings.whatsapp.timeout_s * 1000,
            )
        except WhatsAppError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            output=f"WhatsApp message sent to {contact} ({outcome['chars']} chars)",
            data={"whatsapp": outcome},
        )


class WhatsappRead(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="whatsapp_read",
            description=(
                "Read the last messages of one WhatsApp chat (who said what). Medium "
                "risk: it opens a real conversation — the user's permission rules apply."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "whatsapp",
                "read",
                "messages",
                "chat",
                "conversation",
                "inbox",
                "check",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "contact": _CONTACT_SCHEMA,
                    "limit": {
                        "type": "integer",
                        "description": "How many recent messages (default 10).",
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
                "required": ["contact"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        contact = str(args.get("contact") or "").strip()
        if not contact:
            raise ToolError("contact is required")
        limit = int(args.get("limit") or 10)
        manager = _manager(ctx)
        session = await manager.session()
        try:
            rows = await read_messages(
                session,
                contact,
                limit=limit,
                timeout_ms=ctx.settings.whatsapp.timeout_s * 1000,
            )
        except WhatsAppError as exc:
            raise ToolError(str(exc)) from exc
        if not rows:
            return ToolResult(
                ok=False,
                output=f"no rendered messages in the chat with {contact!r}",
                error="no results",
                data={"messages": []},
            )
        lines = [
            f"{'you:' if row['direction'] == 'out' else 'them:'} {row['text']}" for row in rows
        ]
        return ToolResult(
            output=f"last {len(rows)} message(s) with {contact}:\n" + "\n".join(lines),
            data={"messages": rows, "contact": contact},
        )


class WhatsappOpen(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="whatsapp_open",
            description=(
                "Open WhatsApp on this machine with a chat ready and the message "
                "pre-filled, via the native whatsapp:// protocol (falls back to wa.me "
                "in the browser). The user presses Send themselves — use this when they "
                "want to review the message before it leaves."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "whatsapp",
                "open",
                "launch",
                "app",
                "compose",
                "draft",
                "hand",
                "desktop",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": "Phone number with country code (optional).",
                    },
                    "text": {
                        "type": "string",
                        "description": "Message text to pre-fill (optional).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        contact = str(args.get("contact") or "").strip()
        text = str(args.get("text") or "").strip()
        try:
            uri = build_deep_link(phone=contact, text=text)
            outcome = await asyncio.to_thread(open_deep_link, uri)
        except WhatsAppError as exc:
            raise ToolError(str(exc)) from exc
        via = "WhatsApp desktop" if outcome["opened"] == "protocol" else "wa.me in the browser"
        return ToolResult(
            output=(
                f"opened {via} with the chat ready — the message is pre-filled and the "
                "user presses Send themselves"
            ),
            data={"whatsapp": outcome},
        )


BUILTIN_TOOLS: list[Tool] = [WhatsappSend(), WhatsappRead(), WhatsappOpen()]
