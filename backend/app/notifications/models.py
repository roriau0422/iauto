"""ORM model for the notifications context."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class NotificationProvider(StrEnum):
    fcm = "fcm"
    apns = "apns"
    console = "console"


class NotificationStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"


class NotificationDispatch(UuidPrimaryKey, Timestamped, Base):
    """One push attempt at one recipient device.

    Append-only; we never edit a row once persisted (status flips happen
    via UPDATE but the row identity stays stable for the audit log).
    """

    __tablename__ = "notification_dispatches"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[NotificationProvider] = mapped_column(
        SAEnum(NotificationProvider, name="notification_provider", native_enum=True),
        nullable=False,
    )
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", native_enum=True),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
