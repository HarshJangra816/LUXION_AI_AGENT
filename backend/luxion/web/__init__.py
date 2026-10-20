"""Web-intelligence sources (PRD §37, §38, Phase 9).

Keyless, free/public endpoints only — in keeping with the project's FOSS-first
rule (no new Python dependencies: stdlib parsing + the existing ``httpx``).
Each module fetches through :mod:`luxion.web.http`, so tests patch exactly one
seam and every request shares a user agent, a timeout and error wording.

Modules map 1:1 to the PRD §37 capability list:

- :mod:`luxion.web.search`    — DuckDuckGo HTML search
- :mod:`luxion.web.weather`   — Open-Meteo geocoding + forecast
- :mod:`luxion.web.news`      — RSS/Atom feeds + Hacker News
- :mod:`luxion.web.movies`    — TVMaze (TV + movies)
- :mod:`luxion.web.finance`   — Yahoo chart quotes + computed indicators
- :mod:`luxion.web.speed`     — Cloudflare internet-speed test
- :mod:`luxion.web.clock`     — world clock (zoneinfo)

:mod:`luxion.web.provenance` carries the PRD §37 rule that live answers must
be distinguishable from model knowledge: every tool output is stamped with its
source and retrieval time.
"""

from __future__ import annotations

from luxion.web.errors import WebError

__all__ = ["WebError"]
