"""FastAPI dependencies for the payments context."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.providers.qpay import HttpQpayClient, QpayClient
from app.payments.service import PaymentsService
from app.platform.cache import get_redis
from app.platform.config import Settings, get_settings
from app.platform.db import get_session


@lru_cache(maxsize=1)
def _build_qpay_client_singleton() -> HttpQpayClient:
    """One process-wide QPay client.

    Tests substitute their own implementation by overriding `get_qpay_client`
    via FastAPI's `dependency_overrides`. The cache resolves only at request
    time, after `init_redis` has run in the lifespan.
    """
    return HttpQpayClient(settings=get_settings(), redis=get_redis())


def get_qpay_client(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> QpayClient:
    # Use the cached singleton in production. Re-creating per request would
    # rebuild the httpx client + connection pool every time.
    del settings, redis  # consumed by the singleton via direct lookups
    return _build_qpay_client_singleton()


def get_payments_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    qpay: Annotated[QpayClient, Depends(get_qpay_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentsService:
    return PaymentsService(session=session, qpay=qpay, settings=settings)
