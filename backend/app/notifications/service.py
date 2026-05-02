"""Notifications service — dispatch a push, persist the audit row."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import NotificationDispatch, NotificationStatus
from app.notifications.providers import PushProvider
from app.notifications.repository import NotificationDispatchRepository
from app.platform.logging import get_logger

logger = get_logger("app.notifications.service")


class NotificationsService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        provider: PushProvider,
    ) -> None:
        self.session = session
        self.dispatches = NotificationDispatchRepository(session)
        self.provider = provider

    async def dispatch(
        self,
        *,
        user_id: uuid.UUID,
        kind: str,
        body_text: str,
        payload: dict[str, Any],
    ) -> NotificationDispatch:
        """Create the audit row, attempt delivery, persist final status.

        Today the call to the provider runs inline — no external queue.
        When session 9.5 (or phase 5) lands real FCM/APNs, swap this to
        enqueue + a worker so an outage on the push provider doesn't
        stall the API. The audit row contract stays the same.
        """
        row = await self.dispatches.create(
            user_id=user_id,
            device_id=None,
            kind=kind,
            provider=self.provider.name,
            body_text=body_text,
            payload=payload,
        )
        result = await self.provider.send(
            user_id=user_id,
            device_id=None,
            body_text=body_text,
            payload=payload,
        )
        row.status = result.status
        row.error = result.error
        await self.session.flush()
        if result.status == NotificationStatus.failed:
            logger.warning(
                "notification_send_failed",
                dispatch_id=str(row.id),
                error=result.error,
            )
        return row

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationDispatch], int]:
        return await self.dispatches.list_for_user(user_id=user_id, limit=limit, offset=offset)
