"""FastAPI application factory for the Luxion backend."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from luxion import __version__
from luxion.api.routes import (
    capabilities,
    conversations,
    health,
    llm,
    memory,
    tools,
    usage,
    voice,
)
from luxion.config.settings import get_settings
from luxion.database.session import dispose_engine, init_db
from luxion.llm.registry import aclose_provider
from luxion.logging_setup import configure_logging
from luxion.voice.manager import close_voice_manager

logger = logging.getLogger(__name__)

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.logging, logs_dir=settings.app.logs_dir, force=True)
    init_db()
    logger.info(
        "backend_started",
        extra={
            "environment": settings.app.environment,
            "version": __version__,
            "provider": settings.llm.provider,
        },
    )
    try:
        yield
    finally:
        close_voice_manager()
        await aclose_provider()
        dispose_engine()
        logger.info("backend_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Luxion Backend",
        version=__version__,
        description="Backend API for the Luxion personal AI agent.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(conversations.router, prefix=API_PREFIX)
    app.include_router(llm.router, prefix=API_PREFIX)
    app.include_router(usage.router, prefix=API_PREFIX)
    app.include_router(tools.router, prefix=API_PREFIX)
    app.include_router(capabilities.router, prefix=API_PREFIX)
    app.include_router(memory.router, prefix=API_PREFIX)
    app.include_router(voice.router, prefix=API_PREFIX)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.middleware("http")
    async def request_timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Process-Time-ms"] = str(duration_ms)
        return response

    return app


app = create_app()
