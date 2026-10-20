"""Email tools (PRD §33.4, Phase 10).

Four tools cover the §33.4 list — generate/rewrite/summarize are the model's
own language work, the machine's part is persisting, previewing and (always
after a HIGH-risk confirmation) delivering:

======================  =========  ======================================
Tool                    Risk       Job
======================  =========  ======================================
``email_draft``         medium     compose + persist a draft, return preview
``email_send``          high       deliver an email now (always confirms)
``email_send_draft``    high       deliver a stored draft (always confirms)
``email_read``          medium     recent inbox messages with previews
======================  =========  ======================================

Every tool is gated by the ``email.enabled`` master switch and refuses with a
message that says exactly where to configure the missing piece. SMTP/IMAP are
synchronous stdlib calls, so each runs through :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio

from luxion.email import drafts as draft_store
from luxion.email.errors import MailError
from luxion.email.imap_client import read_inbox
from luxion.email.message import build_message
from luxion.email.smtp_send import is_smtp_configured, send_message
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec

#: Common category so the tool router and the system prompt can recognise the
#: family.
CATEGORY = "email"

_RECIPIENT_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Email addresses, e.g. ['alex@example.com'].",
}


def _require_enabled(ctx: ToolContext) -> None:
    if not ctx.settings.email.enabled:
        raise ToolError(
            "email is disabled — enable it in Settings → Integrations → Email "
            "and configure your mail server"
        )


def _addresses(args: dict, key: str) -> list[str]:
    raw = args.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in raw if str(item).strip()]


def _build(args: dict, ctx: ToolContext):
    cfg = ctx.settings.email
    try:
        return build_message(
            to=_addresses(args, "to"),
            cc=_addresses(args, "cc"),
            bcc=_addresses(args, "bcc"),
            subject=str(args.get("subject") or ""),
            body=str(args.get("body") or ""),
            html=str(args.get("html") or ""),
            from_name=cfg.from_name,
            from_address=cfg.from_address,
            signature=cfg.signature,
            attachments=_addresses(args, "attachments"),
        )
    except MailError as exc:
        raise ToolError(str(exc)) from exc


class EmailDraft(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_draft",
            description=(
                "Compose an email and save it as a draft (nothing is sent). Returns a "
                "preview the user can review; follow with email_send_draft once they "
                "approve. Write the body yourself — polished, in the user's tone."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "email",
                "mail",
                "draft",
                "compose",
                "write",
                "message",
                "letter",
                "inbox",
                "reply",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "to": _RECIPIENT_SCHEMA,
                    "subject": {"type": "string", "description": "Subject line."},
                    "body": {"type": "string", "description": "Plain-text body."},
                    "html": {"type": "string", "description": "Optional HTML alternative."},
                    "cc": _RECIPIENT_SCHEMA,
                    "bcc": _RECIPIENT_SCHEMA,
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths to attach (max 20 MB each).",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        if not is_smtp_configured(ctx.settings.email):
            raise ToolError(
                "no sender configured — set LUXION_EMAIL__SMTP_HOST and "
                "LUXION_EMAIL__FROM_ADDRESS first"
            )
        message = _build(args, ctx)  # validates recipients/body before persisting
        draft = await asyncio.to_thread(
            draft_store.create_draft,
            ctx.settings.app.data_dir,
            {
                "to": [str(a) for a in (args.get("to") or [])],
                "cc": _addresses(args, "cc"),
                "bcc": _addresses(args, "bcc"),
                "subject": str(args.get("subject") or ""),
                "body": str(args.get("body") or ""),
                "html": str(args.get("html") or ""),
                "attachments": _addresses(args, "attachments"),
            },
        )
        del message  # built only to validate; the draft store holds the fields
        return ToolResult(
            output=f"draft saved (nothing sent yet).\n{draft.preview()}",
            data={"draft": draft.model_dump()},
        )


class EmailSend(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_send",
            description=(
                "Send an email right now via SMTP. High risk — the user always confirms. "
                "Prefer email_draft + email_send_draft when the user should review first; "
                "use this when they explicitly asked you to send it."
            ),
            risk="high",
            category=CATEGORY,
            tags=["send", "email", "mail", "deliver", "outgoing", "smtp", "message"],
            parameters={
                "type": "object",
                "properties": {
                    "to": _RECIPIENT_SCHEMA,
                    "subject": {"type": "string", "description": "Subject line."},
                    "body": {"type": "string", "description": "Plain-text body."},
                    "html": {"type": "string", "description": "Optional HTML alternative."},
                    "cc": _RECIPIENT_SCHEMA,
                    "bcc": _RECIPIENT_SCHEMA,
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths to attach (max 20 MB each).",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        message = _build(args, ctx)
        try:
            receipt = await asyncio.to_thread(send_message, ctx.settings.email, message)
        except MailError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(
            output=(
                f"email sent to {', '.join(receipt['to'])} "
                f"({receipt['size_bytes']} bytes, subject {receipt['subject']!r})"
            ),
            data={"receipt": receipt},
        )


class EmailSendDraft(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_send_draft",
            description=(
                "Deliver a draft created by email_draft (high risk — the user always "
                "confirms). The draft is deleted after a successful send."
            ),
            risk="high",
            category=CATEGORY,
            tags=["send", "email", "mail", "draft", "deliver", "approve"],
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": "The id returned by email_draft.",
                    }
                },
                "required": ["draft_id"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        draft_id = str(args.get("draft_id") or "").strip()
        if not draft_id:
            raise ToolError("draft_id is required")
        try:
            draft = await asyncio.to_thread(
                draft_store.load_draft, ctx.settings.app.data_dir, draft_id
            )
            message = build_message(
                to=draft.to,
                cc=draft.cc,
                bcc=draft.bcc,
                subject=draft.subject,
                body=draft.body,
                html=draft.html,
                from_name=ctx.settings.email.from_name,
                from_address=ctx.settings.email.from_address,
                signature=ctx.settings.email.signature,
                attachments=draft.attachments,
            )
            receipt = await asyncio.to_thread(send_message, ctx.settings.email, message)
        except MailError as exc:
            raise ToolError(str(exc)) from exc
        await asyncio.to_thread(draft_store.delete_draft, ctx.settings.app.data_dir, draft_id)
        return ToolResult(
            output=(
                f"draft {draft_id} sent to {', '.join(receipt['to'])} "
                f"({receipt['size_bytes']} bytes, subject {receipt['subject']!r})"
            ),
            data={"receipt": receipt, "draft_id": draft_id},
        )


class EmailRead(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_read",
            description=(
                "Read the most recent messages from the connected inbox (headers + a "
                "short preview each). Medium risk: it touches real mail — the user's "
                "permission rules apply. Use for 'check my email' / 'what came in'."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "read",
                "inbox",
                "email",
                "mail",
                "check",
                "messages",
                "received",
                "summarize",
            ],
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many recent messages (default from settings).",
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional filter over sender/subject/preview.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        limit = int(args.get("limit") or ctx.settings.email.read_limit)
        query = str(args.get("query") or "").strip()
        try:
            rows = await asyncio.to_thread(read_inbox, ctx.settings.email, limit=limit, query=query)
        except MailError as exc:
            raise ToolError(str(exc)) from exc
        if not rows:
            suffix = f" matching {query!r}" if query else ""
            return ToolResult(
                ok=False,
                output=f"no inbox messages{suffix}",
                error="no results",
                data={"messages": []},
            )
        lines = []
        for index, row in enumerate(rows, 1):
            lines.append(
                f"{index}. {row['from']} — {row['subject']} ({row['date']})\n   {row['preview']}"
            )
        header = f"{len(rows)} inbox message(s)" + (f" matching {query!r}" if query else "")
        return ToolResult(
            output=f"{header}:\n" + "\n".join(lines),
            data={"messages": rows},
        )


BUILTIN_TOOLS: list[Tool] = [EmailDraft(), EmailSend(), EmailSendDraft(), EmailRead()]
