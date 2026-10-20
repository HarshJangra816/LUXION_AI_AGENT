"""Email settings, probes and drafts (PRD §33.4, Phase 10).

``GET    /email``             effective config + defaults + status (Settings card)
``PUT    /email/config``      persist Settings → Email edits (partial overlay)
``DELETE /email/config``      back to ``.env`` defaults
``POST   /email/probe``       reach SMTP and IMAP once, no mail is sent
``GET    /email/drafts``      stored drafts (newest first)
``DELETE /email/drafts/{id}`` drop one draft

The SMTP password never appears in any payload: the bundle is built from a
config copy with the secret fields stripped, and the patch model does not
even carry a password field (``extra="forbid"``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, model_serializer

from luxion.config.email_override import clear_overrides
from luxion.config.settings import (
    EMAIL_SECRET_FIELDS,
    EmailConfig,
    get_settings,
    reset_settings_cache,
    save_email_overrides,
)
from luxion.email.drafts import Draft, delete_draft, list_drafts
from luxion.email.errors import MailError
from luxion.email.imap_client import probe_imap
from luxion.email.smtp_send import (
    is_imap_configured,
    is_smtp_configured,
    probe_smtp,
    resolve_password,
)

router = APIRouter(prefix="/email", tags=["email"])


class EmailConfigBundle(BaseModel):
    """What Settings → Email edits (effective values + defaults + status).

    The config/defaults payloads are stripped of every secret field at
    serialization time — the password key does not exist in any response,
    not even as an empty string.
    """

    config: EmailConfig
    defaults: EmailConfig
    status: dict[str, Any]
    drafts: list[Draft]

    @model_serializer(mode="wrap")
    def _strip_secrets(self, handler):  # noqa: ANN001, ANN201
        data = handler(self)
        for key in ("config", "defaults"):
            payload = data.get(key)
            if isinstance(payload, dict):
                for secret in EMAIL_SECRET_FIELDS:
                    payload.pop(secret, None)
        return data


class EmailConfigPatch(BaseModel):
    """Partial email settings — mirrors every writable ``EmailConfig`` field.

    All fields optional so the Settings card can PATCH just what changed. The
    secret fields (``smtp_password``) are deliberately absent: credentials
    live in the environment only. A test keeps the writable set in sync with
    :class:`luxion.config.settings.EmailConfig`.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    smtp_username: str | None = None
    smtp_password_env: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    from_name: str | None = None
    from_address: str | None = None
    signature: str | None = None
    timeout_s: float | None = None
    read_limit: int | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class ProbeOut(BaseModel):
    results: dict[str, str]


def _redacted(config: EmailConfig) -> EmailConfig:
    return EmailConfig(**config.model_dump(exclude=EMAIL_SECRET_FIELDS))


def _status(settings) -> dict[str, Any]:
    """Static facts for the card — no network, never raises."""
    cfg = settings.email
    return {
        "enabled": cfg.enabled,
        "smtp_configured": is_smtp_configured(cfg),
        "imap_configured": is_imap_configured(cfg),
        "password_configured": bool(resolve_password(cfg)),
        "password_env": bool(cfg.smtp_password_env),
        "from_address": cfg.from_address,
    }


def _bundle() -> EmailConfigBundle:
    settings = get_settings()
    return EmailConfigBundle(
        config=_redacted(settings.email),
        defaults=_redacted(EmailConfig()),
        status=_status(settings),
        drafts=list_drafts(settings.app.data_dir),
    )


@router.get("", response_model=EmailConfigBundle)
async def read_email() -> EmailConfigBundle:
    return _bundle()


@router.put("/config", response_model=EmailConfigBundle)
async def write_email(patch: EmailConfigPatch) -> EmailConfigBundle:
    settings = get_settings()
    try:
        save_email_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=EmailConfigBundle)
async def reset_email() -> EmailConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.post("/probe", response_model=ProbeOut)
async def probe_email() -> ProbeOut:
    """Reach SMTP and IMAP once. No mail is sent; the inbox is only selected."""
    settings = get_settings()
    cfg = settings.email
    results: dict[str, str] = {}

    if not cfg.enabled:
        return ProbeOut(
            results={"smtp": "skipped: email is disabled", "imap": "skipped: email is disabled"}
        )
    if not cfg.smtp_host:
        results["smtp"] = "skipped: no SMTP host configured"
    else:
        try:
            results["smtp"] = await asyncio.to_thread(probe_smtp, cfg)
        except MailError as exc:
            results["smtp"] = f"error: {exc}"
    if not cfg.imap_host:
        results["imap"] = "skipped: no IMAP host configured"
    else:
        try:
            results["imap"] = await asyncio.to_thread(probe_imap, cfg)
        except MailError as exc:
            results["imap"] = f"error: {exc}"
    return ProbeOut(results=results)


@router.get("/drafts", response_model=list[Draft])
async def read_drafts() -> list[Draft]:
    return list_drafts(get_settings().app.data_dir)


@router.delete("/drafts/{draft_id}", response_model=dict[str, Any])
async def drop_draft(draft_id: str) -> dict[str, Any]:
    if not delete_draft(get_settings().app.data_dir, draft_id):
        raise HTTPException(status_code=404, detail=f"no draft with id {draft_id!r}")
    return {"deleted": draft_id}
