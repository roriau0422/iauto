"""ORM models for the marketplace context."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class PartSearchStatus(StrEnum):
    """Lifecycle state of a driver-submitted part search request.

    - `open`      — created, visible to matching businesses, can receive quotes
    - `cancelled` — the driver cancelled before a quote was accepted
    - `expired`   — auto-closed after an inactivity window (session 5+)
    - `fulfilled` — a quote was accepted and the reservation turned into a sale
    """

    open = "open"
    cancelled = "cancelled"
    expired = "expired"
    fulfilled = "fulfilled"


class PartSearchRequest(UuidPrimaryKey, Timestamped, Base):
    """A driver's request-for-quote for parts that fit a specific vehicle.

    Spec §5.1: the driver picks a vehicle they own, writes a free-text
    description in Mongolian, and optionally attaches 1–4 images. Session 4
    lands without image upload — `media_urls` accepts whatever opaque
    strings the client sends and the media-platform slice will tighten the
    contract later.

    The `vehicle_id` FK uses ON DELETE RESTRICT so a driver can't
    accidentally orphan an active search by unregistering their car. They
    must cancel the search first.
    """

    __tablename__ = "part_search_requests"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    media_urls: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    status: Mapped[PartSearchStatus] = mapped_column(
        SAEnum(PartSearchStatus, name="part_search_status", native_enum=True),
        nullable=False,
        default=PartSearchStatus.open,
    )
