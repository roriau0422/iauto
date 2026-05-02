"""FastAPI dependencies for the chat context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import ChatService
from app.media.dependencies import get_media_service
from app.media.service import MediaService
from app.platform.cache import get_redis
from app.platform.db import get_session


def get_redis_dep() -> Redis:
    return get_redis()


def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
    media_svc: Annotated[MediaService, Depends(get_media_service)],
) -> ChatService:
    return ChatService(session=session, redis=redis, media_svc=media_svc)
