"""Draft store for the email flow (Phase 10, PRD §33.4 "Draft"/"Preview").

One JSON file per draft under ``<data_dir>/email_drafts/`` — nothing leaves
the machine until ``email_send_draft`` (HIGH risk, always confirmed) delivers
it. Generation/rewrite/summarize are the model's own language work over this
text; the store only persists what should be reviewable and sendable later.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from luxion.email.errors import MailError

logger = logging.getLogger(__name__)

DIR_NAME = "email_drafts"


class Draft(BaseModel):
    """One composed-but-unsent email."""

    id: str
    created_at: str
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    html: str = ""
    attachments: list[str] = Field(default_factory=list)

    def preview(self, *, chars: int = 800) -> str:
        """Headers + body the tool returns so the user can review it."""
        lines = [
            f"draft {self.id} — created {self.created_at}",
            f"To:      {', '.join(self.to) or '(none)'}",
        ]
        if self.cc:
            lines.append(f"Cc:      {', '.join(self.cc)}")
        lines.append(f"Subject: {self.subject or '(no subject)'}")
        if self.attachments:
            lines.append(f"Attach:  {', '.join(self.attachments)}")
        lines.append("")
        body = self.body.strip() or "(HTML-only draft — see the Integrations card)"
        lines.append(body[:chars] + ("…" if len(body) > chars else ""))
        return "\n".join(lines)


def drafts_dir(data_dir: Path) -> Path:
    return Path(data_dir) / DIR_NAME


def _path(data_dir: Path, draft_id: str) -> Path:
    # Ids are generated here (uuid4 hex) — reject anything path-like anyway.
    safe = "".join(ch for ch in draft_id if ch.isalnum() or ch in "-_")
    if not safe or safe != draft_id:
        raise MailError(f"invalid draft id: {draft_id!r}")
    return drafts_dir(data_dir) / f"{safe}.json"


def create_draft(data_dir: Path, payload: dict[str, Any]) -> Draft:
    """Persist one draft (write-then-rename) and return it."""
    draft = Draft(
        id=uuid.uuid4().hex[:12],
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        to=[str(v) for v in payload.get("to", [])],
        cc=[str(v) for v in payload.get("cc", [])],
        bcc=[str(v) for v in payload.get("bcc", [])],
        subject=str(payload.get("subject", "")),
        body=str(payload.get("body", "")),
        html=str(payload.get("html", "")),
        attachments=[str(v) for v in payload.get("attachments", [])],
    )
    path = _path(data_dir, draft.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, path)
    logger.info("email_draft_created id=%s", draft.id)
    return draft


def list_drafts(data_dir: Path, *, limit: int = 20) -> list[Draft]:
    """Newest drafts first. Unreadable files are skipped, never fatal."""
    directory = drafts_dir(data_dir)
    if not directory.is_dir():
        return []
    drafts: list[Draft] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            drafts.append(Draft.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("draft_unreadable path=%s error=%s", path, exc)
        if len(drafts) >= limit:
            break
    return drafts


def load_draft(data_dir: Path, draft_id: str) -> Draft:
    path = _path(data_dir, draft_id)
    try:
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MailError(f"no draft with id {draft_id!r}") from exc
    except (OSError, ValueError) as exc:
        raise MailError(f"draft {draft_id!r} is unreadable: {exc}") from exc


def delete_draft(data_dir: Path, draft_id: str) -> bool:
    try:
        _path(data_dir, draft_id).unlink()
    except (FileNotFoundError, MailError):
        return False
    except OSError as exc:
        logger.warning("draft_not_removed id=%s error=%s", draft_id, exc)
        return False
    return True
