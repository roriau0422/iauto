"""Health and readiness probes.

`/v1/health` is a cheap liveness check — returns 200 as long as the process
can respond, regardless of dependency state. Use it for k8s liveness probes.

`/v1/ready` actually touches Postgres, Redis, and MinIO. A 503 here means
the instance should stop receiving traffic — k8s readiness, AWS ALB target
health, etc. The outbox-lag gauge mirrors into Prometheus on the same
sweep so dashboards can spot a wedged worker without a separate scraper.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.platform.cache import get_redis
from app.platform.config import get_settings
from app.platform.db import get_session_factory
from app.platform.logging import get_logger
from app.platform.observability import OUTBOX_BACKLOG
from app.platform.outbox import OutboxEvent

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

# Cap each individual probe's wallclock so a single dependency hang
# doesn't block /ready and trip a load-balancer alarm. 2s is enough for
# every healthy backend; longer means the dep is misbehaving.
_PROBE_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "iauto-backend"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    redis: bool
    object_storage: bool
    outbox_backlog: int


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    return HealthResponse()


async def _probe_db() -> tuple[bool, int]:
    """Returns (ok, outbox_backlog). Backlog defaults to -1 on error so
    the gauge doesn't accidentally publish a stale 0."""
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            backlog_row = await session.execute(
                select(func.count()).where(OutboxEvent.dispatched_at.is_(None))
            )
            backlog = int(backlog_row.scalar_one())
        return True, backlog
    except Exception as exc:
        logger.warning("readiness_db_failed", error=str(exc))
        return False, -1


async def _probe_redis() -> bool:
    try:
        redis = get_redis()
        await redis.ping()
        return True
    except Exception as exc:
        logger.warning("readiness_redis_failed", error=str(exc))
        return False


async def _probe_object_storage() -> bool:
    """Touch the configured MinIO/S3 bucket via head_bucket.

    Run via `asyncio.to_thread` because boto3 is sync. We only call this
    from the readiness probe and the cron, so the thread overhead is
    immaterial. A misconfigured bucket or expired creds → 503 here.
    """
    settings = get_settings()
    if not settings.s3_endpoint_url:
        # Object storage not configured (some dev environments). Skip
        # the probe rather than failing the whole readiness check.
        return True
    try:
        from app.media.client import S3MediaClient

        client = S3MediaClient(settings)

        def _check() -> None:
            client._client.head_bucket(Bucket=settings.s3_bucket_media)

        await asyncio.wait_for(asyncio.to_thread(_check), timeout=_PROBE_TIMEOUT_SECONDS)
        return True
    except Exception as exc:
        logger.warning("readiness_object_storage_failed", error=str(exc))
        return False


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse}},
)
async def ready() -> ReadinessResponse:
    # Run all three probes concurrently — readiness latency adds up
    # otherwise. Each individual probe self-times-out on hang.
    db_task = asyncio.create_task(asyncio.wait_for(_probe_db(), _PROBE_TIMEOUT_SECONDS))
    redis_task = asyncio.create_task(asyncio.wait_for(_probe_redis(), _PROBE_TIMEOUT_SECONDS))
    s3_task = asyncio.create_task(_probe_object_storage())

    try:
        db_ok, backlog = await db_task
    except TimeoutError:
        db_ok, backlog = False, -1
    try:
        redis_ok = await redis_task
    except TimeoutError:
        redis_ok = False
    s3_ok = await s3_task

    # Mirror to Prometheus so the outbox-lag dashboard works without a
    # separate scrape job.
    if backlog >= 0:
        OUTBOX_BACKLOG.set(backlog)

    overall: Literal["ready", "degraded"] = (
        "ready" if (db_ok and redis_ok and s3_ok) else "degraded"
    )
    response = ReadinessResponse(
        status=overall,
        database=db_ok,
        redis=redis_ok,
        object_storage=s3_ok,
        outbox_backlog=max(backlog, 0),
    )

    if overall == "degraded":
        from fastapi.responses import JSONResponse

        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response
