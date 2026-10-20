"""WhatsApp Web DOM operations (PRD §33.3, Phase 10).

Everything that touches the page lives here, with the selectors in one place.
This is **DOM automation** — WhatsApp has no official send API that does not
require Meta business onboarding — so WhatsApp Web redesigns can move these
selectors. Each operation therefore tries a short list of candidates and, on
failure, says plainly that the selectors may have drifted and where to update
them (:data:`SELECTOR_HINT`).

The page surface used is deliberately tiny (``goto`` / ``url`` /
``wait_for_selector`` / ``query_selector`` / ``fill`` / ``press`` / ``click`` /
``eval_on_selector_all`` / ``evaluate``) — the same methods the Phase 6
browser tools use, so the test fakes stay trivial.
"""

from __future__ import annotations

from typing import Any

from luxion.whatsapp.errors import WhatsAppError
from luxion.whatsapp.manager import WhatsAppSession

#: Shown when a selector no longer matches anything on WhatsApp Web.
SELECTOR_HINT = (
    "WhatsApp Web may have shipped a redesign that moved its selectors — "
    "update luxion/whatsapp/web.py"
)

#: Search box candidates (the title string is localized; data-tab drifts).
SEARCH_BOX_SELECTORS = (
    'div[contenteditable="true"][data-tab="3"]',
    'div[contenteditable="true"][title*="Search" i]',
    'div[contenteditable="true"][aria-label*="Search" i]',
    '[role="textbox"][title*="Search" i]',
)
#: The message composer at the bottom of the open chat.
COMPOSER_SELECTORS = (
    'footer div[contenteditable="true"][data-tab="10"]',
    'footer div[contenteditable="true"]',
    'div[contenteditable="true"][data-tab="10"]',
)
#: Rendered message bubbles inside the open chat.
MESSAGES_SELECTOR = '[data-testid="msg-container"], .message-in, .message-out'
#: The QR canvas on the logged-out page.
QR_CANVAS_SELECTORS = (
    'canvas[aria-label*="QR" i]',
    'canvas[aria-label*="code" i]',
    "div[data-ref] canvas",
    "canvas",
)


async def _act(coro: Any, what: str, *, hint: str = SELECTOR_HINT) -> Any:
    """Run one Playwright call, mapping its errors to ``WhatsAppError``."""
    try:
        return await coro
    except WhatsAppError:
        raise
    except Exception as exc:  # noqa: BLE001 - playwright errors vary by version
        raise WhatsAppError(f"{what} failed ({exc}) — {hint}") from exc


async def _first_match(
    session: WhatsAppSession, selectors: tuple[str, ...], *, timeout_ms: float
) -> str:
    """The first candidate selector that resolves within the budget."""
    per_try = max(timeout_ms / len(selectors), 1000)
    last: Exception | None = None
    for selector in selectors:
        try:
            await session.page.wait_for_selector(selector, timeout=per_try, state="visible")
            return selector
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            last = exc
    raise WhatsAppError(
        f"none of the expected WhatsApp elements appeared within {timeout_ms / 1000:.0f}s "
        f"({'; '.join(selectors)}) — {SELECTOR_HINT}"
    ) from last


async def probe_login(session: WhatsAppSession) -> bool:
    """True when the page shows the app (not the QR login screen).

    Cheap check: the logged-out page carries the QR canvas, the logged-in one
    carries the search box. Result is cached on the session for ``status()``.
    """
    qr = None
    for selector in QR_CANVAS_SELECTORS:
        try:
            qr = await session.page.query_selector(selector)
        except Exception:  # noqa: BLE001 - fakes/versions vary
            qr = None
        if qr is not None:
            break
    if qr is not None:
        session.logged_in = False
        return False

    search = None
    for selector in SEARCH_BOX_SELECTORS:
        try:
            search = await session.page.query_selector(selector)
        except Exception:  # noqa: BLE001 - fakes/versions vary
            search = None
        if search is not None:
            break
    session.logged_in = search is not None
    return session.logged_in


async def grab_qr(session: WhatsAppSession, *, timeout_ms: float = 15000) -> str | None:
    """The login QR as a ``data:image/png;base64,…`` URL, or ``None``.

    Lets the Integrations card show the QR in the UI — no need to hunt for a
    headless window. WhatsApp regenerates the code every ~20 s, so callers
    poll.
    """
    selector = await _first_match(session, QR_CANVAS_SELECTORS, timeout_ms=timeout_ms)
    data_url = await _act(
        session.page.eval_on_selector(selector, "canvas => canvas.toDataURL('image/png')"),
        "reading the QR code",
    )
    session.logged_in = False
    return data_url if isinstance(data_url, str) and data_url.startswith("data:image") else None


async def wait_for_login(session: WhatsAppSession, *, timeout_s: float) -> bool:
    """Poll until the QR is scanned (search box appears) or time runs out."""
    deadline = timeout_s
    step = 2000.0
    waited = 0.0
    while waited <= deadline:
        if await probe_login(session):
            return True
        import asyncio

        await asyncio.sleep(step / 1000)
        waited += step
    session.logged_in = False
    return False


async def _open_chat(session: WhatsAppSession, contact: str, *, timeout_ms: float) -> None:
    """Search for a contact/chat and open the first match."""
    search = await _first_match(session, SEARCH_BOX_SELECTORS, timeout_ms=timeout_ms)
    await _act(
        session.page.fill(search, contact, timeout=timeout_ms),
        f"typing the contact {contact!r} into the search box",
    )
    await _act(
        session.page.press(search, "Enter", timeout=timeout_ms),
        f"opening the chat for {contact!r}",
    )
    # The composer's presence proves a chat actually opened.
    await _first_match(session, COMPOSER_SELECTORS, timeout_ms=timeout_ms)


async def send_message(
    session: WhatsAppSession,
    contact: str,
    text: str,
    *,
    timeout_ms: float,
) -> dict[str, Any]:
    """Open the chat for ``contact`` and send one message."""
    if not await probe_login(session):
        raise WhatsAppError(
            "not logged in to WhatsApp Web — scan the QR in "
            "Settings → Integrations → WhatsApp first"
        )
    await _open_chat(session, contact, timeout_ms=timeout_ms)
    composer = await _first_match(session, COMPOSER_SELECTORS, timeout_ms=timeout_ms)
    await _act(
        session.page.fill(composer, text, timeout=timeout_ms),
        "typing the message",
    )
    await _act(
        session.page.press(composer, "Enter", timeout=timeout_ms),
        "sending the message (Enter)",
    )
    session.logged_in = True
    return {"sent": True, "contact": contact, "chars": len(text)}


async def read_messages(
    session: WhatsAppSession,
    contact: str,
    *,
    limit: int = 10,
    timeout_ms: float,
) -> list[dict[str, Any]]:
    """The last rendered messages of one chat (newest last)."""
    if not await probe_login(session):
        raise WhatsAppError(
            "not logged in to WhatsApp Web — scan the QR in "
            "Settings → Integrations → WhatsApp first"
        )
    await _open_chat(session, contact, timeout_ms=timeout_ms)
    rows = await _act(
        session.page.eval_on_selector_all(
            MESSAGES_SELECTOR,
            """els => els
                .slice(-40)
                .map(el => ({
                    text: (el.innerText || '').trim(),
                    outgoing: !!el.closest('.message-out, [data-testid="msg-out"]'),
                }))
                .filter(row => row.text)""",
        ),
        "reading the chat messages",
    )
    session.logged_in = True
    messages = [
        {"text": str(row.get("text", "")), "direction": "out" if row.get("outgoing") else "in"}
        for row in (rows or [])[-limit:]
        if isinstance(row, dict)
    ]
    return messages
