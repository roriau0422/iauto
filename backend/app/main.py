"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ads.handlers import register as register_ads_handlers
from app.api.v1 import api_router as v1_router
from app.chat.handlers import register as register_chat_handlers
from app.notifications.handlers import register as register_notification_handlers
from app.platform.cache import dispose_redis, init_redis
from app.platform.config import Settings, get_settings
from app.platform.db import dispose_db, init_db
from app.platform.errors import (
    DomainError,
    domain_error_handler,
    unhandled_error_handler,
)
from app.platform.logging import configure_logging, get_logger
from app.platform.middleware import RequestIdMiddleware
from app.platform.observability import (
    MetricsMiddleware,
    init_sentry,
    init_tracing,
    metrics_endpoint,
)
from app.platform.rate_limit import AuthRateLimitMiddleware
from app.vehicles.handlers import register as register_vehicles_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger("app.lifespan")
    logger.info("startup_begin", env=settings.app_env.value, name=settings.app_name)

    # Sentry + OTel before DB so any boot failure gets reported.
    init_sentry(settings)
    init_tracing(settings)

    await init_db(settings)
    await init_redis(settings)

    # Outbox subscribers — register before the first request lands so the
    # worker (run in a separate process) and the API both see them.
    register_chat_handlers()
    register_notification_handlers()
    register_ads_handlers()
    register_vehicles_handlers()

    logger.info("startup_complete")
    try:
        yield
    finally:
        logger.info("shutdown_begin")
        await dispose_redis()
        await dispose_db()
        logger.info("shutdown_complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    # Configure logging eagerly so module imports that log something get the
    # right renderer even before the lifespan runs (e.g. migrations, tests).
    configure_logging(s)

    app = FastAPI(
        title="UCar API",
        version="0.1.0",
        debug=s.app_debug,
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Auth rate-limit runs BEFORE metrics so blocked requests don't
    # poison the latency histogram. Request-id is innermost so the
    # 429 body still carries a correlation id.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(AuthRateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)

    if s.http_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o).rstrip("/") for o in s.http_cors_origins],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(v1_router)
    # Prometheus scrape endpoint mounted at root so default scraper
    # configs don't need a path override. Excluded from OpenAPI to keep
    # the published schema focused on /v1/.
    app.add_api_route(
        "/metrics",
        metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
    )

    return app


app = create_app()
