"""HTTP schemas for the notifications context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.notifications.models import NotificationProvider, NotificationStatus


class NotificationDispatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    device_id: uuid.UUID | None
    kind: str
    provider: NotificationProvider
    body_text: str
    payload: dict[str, Any]
    status: NotificationStatus
    error: str | None
    created_at: datetime
    updated_at: datetime


class NotificationDispatchListOut(BaseModel):
    items: list[NotificationDispatchOut]
    total: int
