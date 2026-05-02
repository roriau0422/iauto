"""Database access for the notifications context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import (
    NotificationDispatch,
    NotificationProvider,
    NotificationStatus,
)


class NotificationDispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        device_id: uuid.UUID | None,
        kind: str,
        provider: NotificationProvider,
        body_text: str,
        payload: dict[str, Any],
    ) -> NotificationDispatch:
        row = NotificationDispatch(
            user_id=user_id,
            device_id=device_id,
            kind=kind,
            provider=provider,
            body_text=body_text,
            payload=payload,
            status=NotificationStatus.queued,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationDispatch], int]:
        base = select(NotificationDispatch).where(NotificationDispatch.user_id == user_id)
        stmt = base.order_by(NotificationDispatch.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(NotificationDispatch.id)).where(
            NotificationDispatch.user_id == user_id
        )
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total
