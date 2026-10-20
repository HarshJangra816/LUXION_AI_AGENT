"""Email (Phase 10, PRD §33.4) — SMTP send + IMAP read, stdlib only.

Modules:

- :mod:`luxion.email.message`     — MIME building (pure, unit-tested)
- :mod:`luxion.email.smtp_send`   — delivery + SMTP probe
- :mod:`luxion.email.imap_client` — inbox reading + IMAP probe
- :mod:`luxion.email.drafts`      — the draft store behind draft → preview → send

PRD §33.4 lists generate / rewrite / summarize / draft / preview / send.
Generation, rewriting and summarizing are the model's own language work in
chat; these modules persist a draft, render its preview and (after the HIGH-
risk confirmation) deliver it — the parts that need the machine.
"""

from __future__ import annotations

from luxion.email.drafts import (
    Draft,
    create_draft,
    delete_draft,
    drafts_dir,
    list_drafts,
    load_draft,
)
from luxion.email.errors import MailError
from luxion.email.imap_client import probe_imap, read_inbox
from luxion.email.message import build_message, render_preview
from luxion.email.smtp_send import (
    is_imap_configured,
    is_smtp_configured,
    probe_smtp,
    resolve_password,
    send_message,
)

__all__ = [
    "Draft",
    "MailError",
    "build_message",
    "create_draft",
    "delete_draft",
    "drafts_dir",
    "is_imap_configured",
    "is_smtp_configured",
    "list_drafts",
    "load_draft",
    "probe_imap",
    "probe_smtp",
    "read_inbox",
    "render_preview",
    "resolve_password",
    "send_message",
]
