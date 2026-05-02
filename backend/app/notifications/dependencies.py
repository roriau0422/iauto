"""FastAPI dependencies for the notifications context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.providers import ConsolePushProvider, PushProvider
from app.notifications.service import NotificationsService
from app.platform.db import get_session


def get_push_provider() -> PushProvider:
    return ConsolePushProvider()


def get_notifications_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[PushProvider, Depends(get_push_provider)],
) -> NotificationsService:
    return NotificationsService(session=session, provider=provider)
