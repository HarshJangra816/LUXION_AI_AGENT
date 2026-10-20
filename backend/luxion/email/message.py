"""MIME construction for outgoing mail (Phase 10, PRD §33.4).

Pure functions over the stdlib :mod:`email` package — no network, so the
whole render path (recipients, headers, text/html alternatives, attachments,
encoding) is unit-testable without a mail server. :mod:`luxion.email.smtp_send`
hands the built message to SMTP.

Header injection is the classic mail bug, so every header value is stripped
and any CR/LF is rejected outright rather than silently folded.
"""

from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from luxion.email.errors import MailError

#: One attachment may not exceed this; SMTP servers commonly cap at 20-25 MB.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
#: Total attachments budget for one message.
MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _clean_header(value: str, field: str) -> str:
    """Strip a header value and refuse CR/LF (header-injection guard)."""
    cleaned = (value or "").strip()
    if "\r" in cleaned or "\n" in cleaned:
        raise MailError(f"{field} must not contain line breaks")
    return cleaned


def _clean_address(value: str, field: str) -> str:
    address = _clean_header(value, field)
    if address and "@" not in address:
        raise MailError(f"{field} {address!r} does not look like an email address")
    return address


def _clean_address_list(values: Any, field: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = values.replace(";", ",").split(",")
    elif isinstance(values, list):
        raw = [str(part) for part in values]
    else:
        raise MailError(f"{field} must be a list of addresses")
    cleaned = [_clean_address(part, field) for part in raw if str(part).strip()]
    return cleaned


def build_message(
    *,
    to: Any,
    subject: str,
    body: str,
    from_name: str = "",
    from_address: str = "",
    cc: Any = None,
    bcc: Any = None,
    html: str = "",
    signature: str = "",
    attachments: Any = None,
) -> EmailMessage:
    """Build one ready-to-send :class:`EmailMessage`.

    ``to`` / ``cc`` accept a list or a comma-separated string. ``bcc`` is set
    as a header too: smtplib guarantees any Bcc field is *never transmitted*
    on the wire while still using it to address delivery — so blind copies
    work and stay invisible. Attachments are filesystem paths — each is read
    once, typed by content, size-capped.
    """
    from_addr = _clean_address(from_address, "from_address")
    if not from_addr:
        raise MailError(
            "no sender address — set LUXION_EMAIL__FROM_ADDRESS in .env or "
            "Settings → Integrations → Email"
        )
    recipients = _clean_address_list(to, "to")
    cc_list = _clean_address_list(cc, "cc")
    bcc_list = _clean_address_list(bcc, "bcc")
    if not recipients and not cc_list and not bcc_list:
        raise MailError("an email needs at least one recipient")

    subject_clean = _clean_header(subject, "subject")
    text_body = (body or "").strip()
    html_body = (html or "").strip()
    sign = (signature or "").strip()
    if sign and text_body:
        text_body = f"{text_body}\n\n--\n{sign}"
    elif sign:
        text_body = f"--\n{sign}"
    if not text_body and not html_body:
        raise MailError("the email has neither a text nor an HTML body")

    message = EmailMessage()
    display = _clean_header(from_name, "from_name")
    message["From"] = f"{display} <{from_addr}>" if display else from_addr
    if recipients:
        message["To"] = ", ".join(recipients)
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    if bcc_list:
        # smtplib never puts Bcc on the wire, but needs it for rcpt addresses.
        message["Bcc"] = ", ".join(bcc_list)
    message["Subject"] = subject_clean or "(no subject)"

    if html_body:
        # Plain text stays the fallback; many mail clients render the HTML.
        message.set_content(text_body or html_body)
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(text_body)

    _attach_files(message, attachments)
    return message


def _attach_files(message: EmailMessage, attachments: Any) -> None:
    paths = [str(p).strip() for p in (attachments or []) if str(p).strip()]
    if not paths:
        return
    total = 0
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise MailError(f"attachment not found: {raw}")
        size = path.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise MailError(
                f"attachment {path.name} is {size / 1_048_576:.1f} MB — "
                f"the per-file limit is {MAX_ATTACHMENT_BYTES // 1_048_576} MB"
            )
        total += size
        if total > MAX_TOTAL_ATTACHMENT_BYTES:
            raise MailError(
                f"attachments exceed the {MAX_TOTAL_ATTACHMENT_BYTES // 1_048_576} MB total limit"
            )
        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )


def render_preview(message: EmailMessage) -> str:
    """Plain-text preview of a built message (headers + body + attachments)."""
    lines = [
        f"From:    {message['From']}",
        f"To:      {message.get('To', '')}",
    ]
    if message.get("Cc"):
        lines.append(f"Cc:      {message['Cc']}")
    lines.append(f"Subject: {message['Subject']}")
    attachments = [
        part.get_filename() for part in message.iter_attachments() if part.get_filename()
    ]
    if attachments:
        lines.append(f"Attach:  {', '.join(attachments)}")
    lines.append("")
    body = message.get_body(preferencelist=("plain",))
    lines.append(body.get_content().strip() if body else "")
    return "\n".join(lines)


def summarize_message(message: EmailMessage, *, preview_chars: int = 500) -> str:
    """One screen of a message for the inbox reader (headers + text preview)."""
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content().strip() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = _strip_html(text)
    if len(text) > preview_chars:
        text = text[:preview_chars].rstrip() + "…"
    return text


def _strip_html(value: str) -> str:
    """Tiny HTML→text for previews (no dependency; the model gets the gist)."""
    out: list[str] = []
    in_tag = False
    for char in value:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            out.append(" ")
            continue
        if not in_tag:
            out.append(char)
    return " ".join("".join(out).split())
