"""Health and readiness probes.

`/v1/health` is a cheap liveness check — returns 200 as long as the process
can respond. `/v1/ready` actually touches Postgres and Redis, so a failure
means the instance should stop receiving traffic.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.platform.cache import get_redis
from app.platform.db import get_session_factory
from app.platform.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "iauto-backend"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    redis: bool


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse}},
)
async def ready() -> ReadinessResponse:
    db_ok = False
    redis_ok = False

    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("readiness_db_failed", error=str(exc))

    try:
        redis = get_redis()
        await redis.ping()
        redis_ok = True
    except Exception as exc:
        logger.warning("readiness_redis_failed", error=str(exc))

    overall: Literal["ready", "degraded"] = "ready" if (db_ok and redis_ok) else "degraded"
    response = ReadinessResponse(status=overall, database=db_ok, redis=redis_ok)

    if overall == "degraded":
        from fastapi.responses import JSONResponse

        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response
