"""The native ``whatsapp://`` protocol route (PRD §33.3, Phase 10).

Hands a composed message to the **installed** WhatsApp desktop app instead of
driving WhatsApp Web: ``whatsapp://send?phone=…&text=…`` opens the app with
the chat ready and the text pre-filled — the user still presses Send, which
is exactly the "after authorization" behaviour the PRD asks for. When no
handler is registered (WhatsApp never installed), the equivalent ``https://wa.me/``
link is opened in the default browser instead.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from luxion.whatsapp.errors import WhatsAppError

logger = logging.getLogger(__name__)

PROTOCOL_SCHEME = "whatsapp://"
WEB_FALLBACK = "https://wa.me/"


def normalize_phone(phone: str) -> str:
    """Digits only, optional leading ``+`` — WhatsApp expects ``<country><number>``."""
    raw = (phone or "").strip()
    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or len(cleaned) < 7:
        raise WhatsAppError(
            f"{phone!r} is not a usable phone number — give it with the country "
            "code, e.g. '+44 7700 900123'"
        )
    return cleaned


def build_deep_link(phone: str = "", text: str = "") -> str:
    """``whatsapp://send?…`` (or the wa.me web equivalent when no phone)."""
    body = quote((text or "").strip(), safe="")
    if phone:
        digits = normalize_phone(phone)
        link = f"{PROTOCOL_SCHEME}send?phone={digits}"
        if body:
            link += f"&text={body}"
        return link
    if body:
        return f"{PROTOCOL_SCHEME}send?text={body}"
    return f"{PROTOCOL_SCHEME}send"


def open_deep_link(uri: str) -> dict[str, Any]:
    """Hand the URI to the OS. Returns which route actually opened."""
    if not uri.startswith(PROTOCOL_SCHEME):
        raise WhatsAppError(f"refusing to open a non-whatsapp URI: {uri}")
    if sys.platform == "win32":
        try:
            os.startfile(uri)  # type: ignore[attr-defined]  # Windows-only API
        except OSError as exc:
            logger.info("whatsapp_protocol_missing error=%s", exc)
            return _open_web_fallback(uri)
        return {"opened": "protocol", "uri": uri}
    # Non-Windows dev boxes: the browser understands the wa.me form only.
    return _open_web_fallback(uri)


def _open_web_fallback(uri: str) -> dict[str, Any]:
    """Translate the deep link to the equivalent https://wa.me/ URL.

    ``whatsapp://send?phone=44…&text=hi`` → ``https://wa.me/44…?text=hi``;
    without a phone it degrades to ``https://wa.me/?text=hi`` (WhatsApp's
    documented share URL). Text is re-encoded from the parsed query so the
    browser receives exactly one well-formed parameter.
    """
    import webbrowser

    query = urlsplit(uri).query  # "phone=…&text=…" (scheme://send is opaque here)
    params = parse_qs(query)
    phone = (params.get("phone") or [""])[0]
    text = (params.get("text") or [""])[0]
    web = f"{WEB_FALLBACK}{phone}" if phone else WEB_FALLBACK
    if text:
        web += ("&" if "?" in web else "?") + f"text={quote(text, safe='')}"
    opened = webbrowser.open(web, new=2)
    if not opened:
        raise WhatsAppError(
            "no handler for whatsapp:// and no browser to fall back to — "
            "install WhatsApp Desktop or a browser"
        )
    return {"opened": "web", "uri": web}
