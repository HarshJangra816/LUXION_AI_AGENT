"""Health and version endpoints."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from luxion import __version__
from luxion.database.session import check_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()
API_VERSION = "1"


@router.get("/health")
def health() -> JSONResponse:
    db_ok = check_connection()
    payload = {
        "status": "ok" if db_ok else "degraded",
        "service": "luxion-backend",
        "version": __version__,
        "api_version": API_VERSION,
        "time_utc": datetime.now(UTC).isoformat(),
        "uptime_s": round(time.time() - _STARTED_AT, 3),
        "database": "ok" if db_ok else "error",
    }
    return JSONResponse(content=payload, status_code=200 if db_ok else 503)


@router.get("/version")
def version() -> dict[str, str]:
    return {"name": "luxion-backend", "version": __version__, "api_version": API_VERSION}
