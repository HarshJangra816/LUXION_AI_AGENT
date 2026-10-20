"""WhatsApp automation (Phase 10, PRD §33.3).

Two routes to a message, per the user's confirmed choice:

- :mod:`luxion.whatsapp.web` — Playwright Web on ``web.whatsapp.com`` with a
  persistent login profile (send + read chats)
- :mod:`luxion.whatsapp.protocol` — the native ``whatsapp://`` deep link that
  hands a composed message to the installed WhatsApp desktop app
"""

from __future__ import annotations

from luxion.whatsapp.errors import WhatsAppError
from luxion.whatsapp.manager import (
    WhatsAppManager,
    WhatsAppSession,
    close_whatsapp_manager,
    get_whatsapp_manager,
    reset_whatsapp_manager,
    set_whatsapp_launcher,
)
from luxion.whatsapp.protocol import build_deep_link, open_deep_link
from luxion.whatsapp.web import grab_qr, probe_login, read_messages, send_message, wait_for_login

__all__ = [
    "WhatsAppError",
    "WhatsAppManager",
    "WhatsAppSession",
    "build_deep_link",
    "close_whatsapp_manager",
    "get_whatsapp_manager",
    "grab_qr",
    "open_deep_link",
    "probe_login",
    "read_messages",
    "reset_whatsapp_manager",
    "send_message",
    "set_whatsapp_launcher",
    "wait_for_login",
]
