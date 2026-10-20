"""Minimal HTML/atomised-text helpers.

Shared by the web sources that scrape markup (search snippets, RSS
descriptions, TVMaze summaries). Deliberately dependency-free — the project
rule is stdlib + the already-present ``httpx`` (FOSS-first, Phase 8).
"""

from __future__ import annotations

import html as _html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
#: Zero-width and variation-selector code points that search engines embed in
#: titles (DuckDuckGo renders a leading U+FE0F, some feeds use U+200B). They
#: are invisible but are *not* whitespace, so they survive ``\s+`` stripping,
#: then break Windows consoles and can confuse the model. Written as escapes
#: so this file stays readable.
_INVISIBLE = re.compile("[\\u200b-\\u200f\\u2060-\\u2064\\ufeff\\ufe0e\\ufe0f]")


def strip_tags(fragment: str) -> str:
    """Drop every ``<tag>`` (to nothing, so inline emphasis doesn't add a
    stray space), remove invisible code points, unescape entities and
    collapse whitespace."""
    text = _TAG.sub("", fragment or "")
    text = _INVISIBLE.sub("", _html.unescape(text))
    return _WS.sub(" ", text).strip()


def plain(text: str) -> str:
    """Unescape entities and normalise whitespace (no tags to strip)."""
    cleaned = _INVISIBLE.sub("", _html.unescape(text or ""))
    return _WS.sub(" ", cleaned).strip()
