"""SMTP delivery (Phase 10, stdlib :mod:`smtplib` only).

Everything here is synchronous by nature — the tool layer wraps calls in
:func:`asyncio.to_thread`. The session shape follows the security setting:
``ssl`` connects with :class:`smtplib.SMTP_SSL`, ``starttls`` upgrades a
plain connection, ``none`` stays in the clear (only sensible on a trusted
LAN relay).
"""

from __future__ import annotations

import contextlib
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

from luxion.config.settings import EmailConfig
from luxion.email.errors import MailError

logger = logging.getLogger(__name__)


def resolve_password(config: EmailConfig) -> str:
    """The SMTP password, preferring the env var ``smtp_password_env`` names.

    Lets the secret live outside ``.env`` (CI secret, user environment
    variable) while still supporting the inline ``LUXION_EMAIL__SMTP_PASSWORD``.
    """
    named = (config.smtp_password_env or "").strip()
    if named:
        return os.environ.get(named, "")
    return config.smtp_password or ""


def is_smtp_configured(config: EmailConfig) -> bool:
    return bool(config.enabled and config.smtp_host and config.from_address)


def is_imap_configured(config: EmailConfig) -> bool:
    return bool(config.enabled and config.imap_host)


def _connect(config: EmailConfig) -> smtplib.SMTP:
    if not config.smtp_host:
        raise MailError(
            "no SMTP server configured — set LUXION_EMAIL__SMTP_HOST (and "
            "FROM_ADDRESS) in .env or Settings → Integrations → Email"
        )
    try:
        if config.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, timeout=config.timeout_s
            )
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.timeout_s)
            if config.smtp_security == "starttls":
                server.ehlo()
                server.starttls()
                server.ehlo()
        return server
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(
            f"could not reach the SMTP server {config.smtp_host}:{config.smtp_port} ({exc})"
        ) from exc


def _login(server: smtplib.SMTP, config: EmailConfig) -> None:
    username = (config.smtp_username or config.from_address).strip()
    if not username:
        return
    password = resolve_password(config)
    if not password:
        raise MailError(
            "no SMTP password — set LUXION_EMAIL__SMTP_PASSWORD (or point "
            "LUXION_EMAIL__SMTP_PASSWORD_ENV at the env var that holds it)"
        )
    try:
        server.login(username, password)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "the SMTP server rejected the login — with 2FA on, Gmail/Yahoo "
            "need an app password, not the account password"
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP login failed: {exc}") from exc


def send_message(config: EmailConfig, message: EmailMessage) -> dict[str, Any]:
    """Deliver one built message. Returns a receipt dict for the tool result."""
    recipients = [
        address
        for header in ("To", "Cc", "Bcc")
        for address in (message.get(header) or "").split(",")
        if address.strip()
    ]
    if not recipients:
        raise MailError("no recipients to deliver to")

    server = _connect(config)
    try:
        _login(server, config)
        try:
            refused = server.send_message(
                message,
                from_addr=config.from_address,
                to_addrs=[address.strip() for address in recipients],
            )
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(f"the server refused every recipient: {exc.recipients}") from exc
        except smtplib.SMTPException as exc:
            raise MailError(f"the server refused the message: {exc}") from exc
    finally:
        # Teardown must never mask the send result.
        with contextlib.suppress(OSError):
            server.quit()

    if refused:
        logger.warning("smtp_partial_refusal %s", refused)
    size = len(message.as_bytes())
    logger.info(
        "email_sent",
        extra={"to": recipients, "subject": message["Subject"], "bytes": size},
    )
    return {
        "sent": True,
        "message_id": message.get("Message-ID", ""),
        "to": [address.strip() for address in recipients],
        "subject": message["Subject"],
        "size_bytes": size,
        "refused": {str(key): str(value) for key, value in refused.items()} if refused else {},
    }


def probe_smtp(config: EmailConfig) -> str:
    """Connect + EHLO only — proves reachability without sending anything."""
    server = _connect(config)
    try:
        server.ehlo()
        if server.has_extn("starttls") and config.smtp_security == "starttls":
            return "ok (STARTTLS offered)"
        return "ok"
    finally:
        with contextlib.suppress(OSError):
            server.quit()
