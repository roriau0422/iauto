"""FastAPI dependencies for the vehicles context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.dependencies import get_redis_dep, get_settings_dep, get_sms_provider
from app.identity.providers.sms import SmsProvider
from app.platform.config import Settings
from app.platform.db import get_session
from app.vehicles.service import VehiclesService


def get_vehicles_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
    sms: Annotated[SmsProvider, Depends(get_sms_provider)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> VehiclesService:
    return VehiclesService(
        session=session, redis=redis, sms=sms, settings=settings
    )
