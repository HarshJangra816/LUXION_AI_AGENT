"""Internet-speed test (PRD §37 "Internet speed", Phase 9).

Cloudflare's public speed endpoints are keyless and need no client library:

- ``/meta``          — ISP / ASN / colo / city, plus a round-trip latency probe;
- ``/__down?bytes=N`` — download payload measured against the wall clock;
- ``/__up`` (POST)    — optional upload leg.

The payload sizes come from ``WebConfig.speed_download_bytes`` /
``speed_upload_bytes`` so a data-conscious user can shrink the test, and the
whole tool is behind ``WebConfig.speed_enabled``. Speeds are simple
``bytes × 8 / seconds`` — descriptive, not an SLA.
"""

from __future__ import annotations

import time
from typing import Any

from luxion.web.errors import WebError
from luxion.web.http import get_bytes, get_json, post_bytes

META_URL = "https://speed.cloudflare.com/meta"
DOWN_URL = "https://speed.cloudflare.com/__down"
UP_URL = "https://speed.cloudflare.com/__up"

#: Cloudflare answers ``/meta`` with 403 unless the request carries an
#: ``Origin`` or ``Referer`` belonging to ``speed.cloudflare.com`` (verified
#: live 2026-10-19 — a browser-like User-Agent alone is not enough).
SPEED_HEADERS = {
    "Origin": "https://speed.cloudflare.com",
    "Referer": "https://speed.cloudflare.com/",
}


def _colo_name(colo: Any) -> str:
    """Normalise the ``colo`` field — a string in older payloads, a dict
    (``{"iata": "DEL", "lat": …, "city": …}``) in the current one."""
    if isinstance(colo, dict):
        return str(colo.get("iata") or colo.get("city") or "")
    return str(colo or "")


def mbps(byte_count: int, seconds: float) -> float:
    """Megabits per second for ``byte_count`` bytes over ``seconds``."""
    if seconds <= 0:
        return 0.0
    return round(byte_count * 8 / seconds / 1_000_000, 2)


async def connection_info(settings: Any = None) -> dict[str, Any]:
    """ISP / location facts plus a small round-trip latency estimate (ms)."""
    started = time.perf_counter()
    data = await get_json(META_URL, headers=SPEED_HEADERS, settings=settings, timeout=10.0)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(data, dict):
        raise WebError("cloudflare returned an unexpected payload", source="speed.cloudflare.com")
    return {
        "isp": data.get("asOrganization") or "",
        "asn": data.get("asn"),
        "ip": data.get("clientIp") or "",
        "colo": _colo_name(data.get("colo")),
        "city": data.get("city") or "",
        "region": data.get("region") or "",
        "country": data.get("country") or "",
        "protocol": data.get("httpProtocol") or "",
        "latency_ms": latency_ms,
    }


async def speed_test(
    *,
    download_bytes: int = 10_000_000,
    upload_bytes: int = 0,
    settings: Any = None,
) -> dict[str, Any]:
    """Run the download (and optional upload) measurement.

    ``upload_bytes=0`` skips the upload leg — it is the slower, more
    intrusive half and many users only care about download.
    """
    download_bytes = max(100_000, min(int(download_bytes), 100_000_000))
    info = await connection_info(settings)

    started = time.perf_counter()
    payload = await get_bytes(
        DOWN_URL,
        params={"bytes": download_bytes},
        headers=SPEED_HEADERS,
        settings=settings,
        timeout=60.0,
    )
    down_seconds = time.perf_counter() - started
    info["download_bytes"] = len(payload)
    info["download_seconds"] = round(down_seconds, 2)
    info["download_mbps"] = mbps(len(payload), down_seconds)

    if upload_bytes:
        upload_bytes = max(100_000, min(int(upload_bytes), 50_000_000))
        body = b"\0" * upload_bytes
        started = time.perf_counter()
        await post_bytes(
            UP_URL, content=body, headers=SPEED_HEADERS, settings=settings, timeout=60.0
        )
        up_seconds = time.perf_counter() - started
        info["upload_bytes"] = upload_bytes
        info["upload_seconds"] = round(up_seconds, 2)
        info["upload_mbps"] = mbps(upload_bytes, up_seconds)

    return info


def format_result(result: dict[str, Any]) -> str:
    where = ", ".join(
        p for p in (result.get("city"), result.get("region"), result.get("country")) if p
    )
    lines = [
        f"Internet speed via Cloudflare{' — ' + where if where else ''}",
        f"Download: {result.get('download_mbps')} Mbps over {result.get('download_bytes')} bytes "
        f"in {result.get('download_seconds')}s",
    ]
    if result.get("upload_mbps") is not None:
        lines.append(
            f"Upload: {result.get('upload_mbps')} Mbps over {result.get('upload_bytes')} bytes "
            f"in {result.get('upload_seconds')}s"
        )
    lines.append(f"Latency: {result.get('latency_ms')} ms · ISP: {result.get('isp') or 'unknown'}")
    lines.append(
        f"Exit node: {result.get('colo')} ({result.get('protocol')}) — measured against one "
        "Cloudflare node, so this reflects your link to Cloudflare, not every site."
    )
    return "\n".join(lines)
