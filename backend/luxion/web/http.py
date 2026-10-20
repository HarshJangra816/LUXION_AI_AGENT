"""Shared HTTP helpers for every keyless web source (Phase 9).

All outbound calls funnel through :func:`get_text` / :func:`get_json` /
:func:`get_bytes` / :func:`post_bytes`, which:

- apply the configured user agent and timeout (:class:`luxion.config.settings.WebConfig`),
- follow redirects and normalise failures into a single :class:`~luxion.web.errors.WebError`,
- are trivially patchable in tests (``monkeypatch.setattr(web.http, "get_json", …)``).

No source module builds its own ``httpx.AsyncClient`` — that keeps the network
surface in one auditable place (PRD §57 rule 6: no stray secrets or clients).
"""

from __future__ import annotations

import json as _json
from typing import Any
from urllib.parse import urlsplit

import httpx

from luxion.config.settings import Settings, get_settings
from luxion.web.errors import WebError

#: Honest default identity; a source is far likelier to answer a named agent.
DEFAULT_USER_AGENT = "Luxion/0.1 (personal AI agent)"
DEFAULT_TIMEOUT_S = 15.0


def _host(url: str) -> str:
    return urlsplit(url).netloc or "web"


def _cfg(settings: Settings | None):
    return (settings or get_settings()).web


def user_agent(settings: Settings | None = None) -> str:
    """Effective User-Agent — the configured override, else the Luxion default."""
    return (_cfg(settings).user_agent or "").strip() or DEFAULT_USER_AGENT


def timeout_s(settings: Settings | None = None) -> float:
    return float(_cfg(settings).timeout_s)


def _client(
    settings: Settings | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    merged = {"User-Agent": user_agent(settings)}
    if headers:
        merged.update(headers)
    return httpx.AsyncClient(
        timeout=timeout,
        headers=merged,
        follow_redirects=True,
    )


async def get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> str:
    """GET ``url`` and return the body as text (HTML, CSV, RSS, …).

    ``headers`` adds request-specific headers on top of the shared
    User-Agent (some endpoints, e.g. Cloudflare's ``/meta``, 403 anything
    without an ``Origin``).
    """
    budget = timeout_s(settings) if timeout is None else float(timeout)
    try:
        async with _client(settings, budget, headers) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise WebError(f"{_host(url)} request failed: {exc}", source=_host(url)) from exc
    if response.status_code >= 400:
        raise WebError(f"{_host(url)} answered HTTP {response.status_code}", source=_host(url))
    return response.text


async def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> Any:
    """GET ``url`` and parse the JSON body (any shape — caller decides)."""
    text = await get_text(url, params=params, headers=headers, settings=settings, timeout=timeout)
    try:
        return _json.loads(text)
    except ValueError as exc:
        raise WebError(f"{_host(url)} returned invalid JSON", source=_host(url)) from exc


async def get_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> bytes:
    """GET ``url`` and return raw bytes (speed-test payloads, downloads)."""
    budget = timeout_s(settings) if timeout is None else float(timeout)
    try:
        async with _client(settings, budget, headers) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise WebError(f"{_host(url)} request failed: {exc}", source=_host(url)) from exc
    if response.status_code >= 400:
        raise WebError(f"{_host(url)} answered HTTP {response.status_code}", source=_host(url))
    return response.content


async def post_bytes(
    url: str,
    *,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> bytes:
    """POST raw bytes to ``url`` (used by the upload leg of the speed test)."""
    budget = timeout_s(settings) if timeout is None else float(timeout)
    try:
        async with _client(settings, budget, headers) as client:
            response = await client.post(url, content=content)
    except httpx.HTTPError as exc:
        raise WebError(f"{_host(url)} request failed: {exc}", source=_host(url)) from exc
    if response.status_code >= 400:
        raise WebError(f"{_host(url)} answered HTTP {response.status_code}", source=_host(url))
    return response.content
