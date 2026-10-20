"""Provenance for live answers (PRD §37).

PRD §37 requires the system to keep four kinds of information apart:

    Current information | Historical information | Model knowledge | User-provided

Luxion satisfies that by *stamping* every live tool result with the endpoint it
came from and the UTC time it was fetched (:func:`stamp`), and by teaching the
model — through :data:`GUIDANCE` appended to the system prompt whenever a web
tool is exposed — to say when an answer rests on live retrieval versus its own
training data.

Nothing here does I/O; it is pure formatting, so it is cheap to call from every
tool and trivial to test.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: What a stamped result is: information fetched live, i.e. it can be newer
#: than the model's training cutoff and it can go stale.
KIND_CURRENT = "current"
KIND_HISTORICAL = "historical"

#: Appended to the system prompt when any web-intelligence tool is exposed.
GUIDANCE = """\
Information sourcing rules:
- Answers you build from a `web_*`, `get_weather`, `get_news`, `movie_lookup`,
  `stock_quote`, `internet_speed` or `world_clock` result are LIVE retrieval.
  Each result is stamped `[source: …, retrieved: …]` — quote that stamp when
  the freshness matters (prices, weather, headlines, "today").
- Distinguish live facts from your own training knowledge. If the two disagree,
  trust the live result and say you looked it up.
- Facts about the user come from memories / the conversation, not from the web.
- Live results can go stale; never present a stamped number as timeless truth."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now(moment: datetime | None = None) -> str:
    """ISO-8601 UTC, second precision, always suffixed ``Z``."""
    moment = moment or utc_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def stamp(source: str, *, retrieved_at: datetime | None = None) -> str:
    """The one-line provenance footer every web tool appends to its output."""
    return f"[source: {source}, retrieved: {iso_now(retrieved_at)}]"


def provenance_dict(source: str, *, retrieved_at: datetime | None = None) -> dict[str, str]:
    """Machine-readable form of :func:`stamp`, merged into a tool's ``data``."""
    moment = retrieved_at or utc_now()
    return {
        "kind": KIND_CURRENT,
        "source": source,
        "retrieved_at": iso_now(moment),
    }
