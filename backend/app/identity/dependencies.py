"""FastAPI dependencies for the identity context.

`get_identity_service` assembles an `IdentityService` from the DB session,
Redis, the SMS provider, and settings. `get_current_user` reads the bearer
token and returns the authenticated user (or raises 401).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User
from app.identity.providers.sms import SmsProvider, make_sms_provider
from app.identity.repository import UserRepository
from app.identity.security import decode_access_token
from app.identity.service import IdentityService
from app.platform.cache import get_redis
from app.platform.config import Settings, get_settings
from app.platform.db import get_session
from app.platform.errors import AuthError


def get_settings_dep() -> Settings:
    return get_settings()


def get_redis_dep() -> Redis:
    return get_redis()


def get_sms_provider(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SmsProvider:
    return make_sms_provider(settings)


def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
    sms: Annotated[SmsProvider, Depends(get_sms_provider)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> IdentityService:
    return IdentityService(session=session, redis=redis, sms=sms, settings=settings)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
    settings: Annotated[Settings, Depends(get_settings_dep)] = None,  # type: ignore[assignment]
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = decode_access_token(token, settings)

    user = await UserRepository(session).get_by_id(claims.sub)
    if user is None or not user.is_active:
        raise AuthError("Account not found or disabled")
    return user
