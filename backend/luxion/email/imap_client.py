"""IMAP inbox reading (Phase 10, stdlib :mod:`imaplib` only).

Fetches the most recent inbox messages as parsed
:class:`email.message.EmailMessage` objects with short previews — enough for
"read my mail / summarise what came in". SSL is the only mode offered (port
993); plaintext IMAP is a relic nobody should run.

Synchronous by nature; the tool layer wraps calls in :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import contextlib
import email as email_lib
import imaplib
import logging
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

from luxion.config.settings import EmailConfig
from luxion.email.errors import MailError
from luxion.email.message import summarize_message
from luxion.email.smtp_send import is_imap_configured

logger = logging.getLogger(__name__)


def _decode(value: str | None) -> str:
    """RFC 2047 header decode ('=?utf-8?B?...?=' → readable text)."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - a malformed header must not kill the read
        return value


def _connect(config: EmailConfig) -> imaplib.IMAP4_SSL:
    if not is_imap_configured(config):
        raise MailError(
            "no IMAP server configured — set LUXION_EMAIL__IMAP_HOST in .env "
            "or Settings → Integrations → Email"
        )
    try:
        return imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=config.timeout_s)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(
            f"could not reach the IMAP server {config.imap_host}:{config.imap_port} ({exc})"
        ) from exc


def _login(client: imaplib.IMAP4_SSL, config: EmailConfig) -> None:
    from luxion.email.smtp_send import resolve_password

    username = (config.smtp_username or config.from_address).strip()
    password = resolve_password(config)
    if not username or not password:
        raise MailError(
            "no IMAP credentials — set LUXION_EMAIL__SMTP_USERNAME and the "
            "SMTP password (IMAP shares the account login)"
        )
    try:
        client.login(username, password)
    except imaplib.IMAP4.error as exc:
        raise MailError(
            f"the IMAP server rejected the login ({exc}) — with 2FA on, "
            "Gmail/Yahoo need an app password"
        ) from exc


def _parse(raw: bytes) -> EmailMessage:
    # policy=default is required: without it get_content() on the parsed body
    # hits Compat32, which has no content manager.
    return email_lib.message_from_bytes(  # type: ignore[return-value]
        raw, _class=EmailMessage, policy=policy.default
    )


def read_inbox(config: EmailConfig, *, limit: int | None = None, query: str = "") -> list[dict]:
    """The most recent inbox messages, newest first.

    ``query`` filters the fetched window client-side by sender/subject/body
    substring — deliberately not server-side IMAP SEARCH, which is charset-
    fragile across providers and pointless for the small windows Luxion reads.
    """
    want = min(limit or config.read_limit, config.read_limit)
    client = _connect(config)
    try:
        _login(client, config)
        try:
            client.select("INBOX", readonly=True)
        except imaplib.IMAP4.error as exc:
            raise MailError(f"could not open the inbox: {exc}") from exc
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise MailError(f"the IMAP server refused the inbox search: {status}")
        uids = (data[0] or b"").split()
        recent = uids[-max(want * 3, want) :]  # over-fetch so a query still has hits

        rows: list[dict[str, Any]] = []
        for uid in reversed(recent):
            if len(rows) >= want:
                break
            status, fetched = client.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not fetched or fetched[0] is None:
                continue
            raw = fetched[0][1]
            if not isinstance(raw, bytes):
                continue
            message = _parse(raw)
            row = {
                "uid": uid.decode(),
                "from": _decode(message.get("From")),
                "to": _decode(message.get("To")),
                "subject": _decode(message.get("Subject")) or "(no subject)",
                "date": _decode(message.get("Date")),
                "preview": summarize_message(message),
            }
            if query:
                haystack = f"{row['from']} {row['subject']} {row['preview']}".lower()
                if query.lower() not in haystack:
                    continue
            rows.append(row)
        return rows
    finally:
        with contextlib.suppress(OSError):
            client.logout()


def probe_imap(config: EmailConfig) -> str:
    """Connect + login + list the inbox — proves credentials without reading."""
    client = _connect(config)
    try:
        _login(client, config)
        status, data = client.select("INBOX", readonly=True)
        if status != "OK":
            raise MailError(f"the IMAP server refused to open the inbox: {status}")
        total = (data[0] or b"0").decode() if data and data[0] else "0"
        return f"ok ({total} messages)"
    finally:
        with contextlib.suppress(OSError):
            client.logout()
