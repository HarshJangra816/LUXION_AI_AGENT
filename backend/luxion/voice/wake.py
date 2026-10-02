"""Wake-word phrase handling (PRD §26 "Hey Luxion")."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    """Lowercase and strip punctuation so fuzzy transcriptions still match."""
    folded = text.casefold().replace("_", " ")
    folded = re.sub(r"[^\w\s']+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def strip_wake(text: str, phrase: str) -> str | None:
    """If ``text`` starts with the wake phrase, return the command after it.

    ``None`` means the phrase was not spoken. An empty string means the user
    said *only* the wake word — the manager then arms and waits for the actual
    command. The remainder keeps the original casing and punctuation whenever
    word boundaries line up (the usual case); if one source word maps to
    several normalized tokens ("hey-luxion") the normalized tail is returned
    instead.
    """
    raw = text.strip()
    phrase_words = normalize(phrase).split()
    if not phrase_words or not raw:
        return None
    raw_words = raw.split()
    norm = normalize(raw).split()
    if norm[: len(phrase_words)] != phrase_words:
        return None
    consumed = 0
    tokens = 0
    for word in raw_words:
        consumed += 1
        tokens += len(normalize(word).split())
        if tokens >= len(phrase_words):
            break
    if tokens == len(phrase_words):
        return " ".join(raw_words[consumed:]).strip()
    return " ".join(norm[len(phrase_words) :]).strip()
