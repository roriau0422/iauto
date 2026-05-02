"""HTTP routes for the notifications context."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.notifications.dependencies import get_notifications_service
from app.notifications.schemas import (
    NotificationDispatchListOut,
    NotificationDispatchOut,
)
from app.notifications.service import NotificationsService

router = APIRouter(tags=["notifications"])


@router.get(
    "/notifications/mine",
    response_model=NotificationDispatchListOut,
    summary="Caller's own push-dispatch history (newest first)",
)
async def list_my_notifications(
    service: Annotated[NotificationsService, Depends(get_notifications_service)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationDispatchListOut:
    items, total = await service.list_for_user(user_id=user.id, limit=limit, offset=offset)
    return NotificationDispatchListOut(
        items=[NotificationDispatchOut.model_validate(i) for i in items],
        total=total,
    )
