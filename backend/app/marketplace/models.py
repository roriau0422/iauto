"""ORM models for the marketplace context."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


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
    media_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[PartSearchStatus] = mapped_column(
        SAEnum(PartSearchStatus, name="part_search_status", native_enum=True),
        nullable=False,
        default=PartSearchStatus.open,
    )


class QuoteCondition(StrEnum):
    """Physical condition of the part a business is offering.

    Maps directly to spec §5.3: "шинэ / хуучин / орж ирсэн".
    `imported` captures the MN market's "орж ирсэн" category — used
    parts sourced from overseas auto markets, a meaningful distinction
    from locally-sourced "хуучин" second-hand stock.
    """

    new = "new"
    used = "used"
    imported = "imported"


class Quote(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """A business's price quote for a driver's part search.

    `tenant_id` is the `businesses.id` that submitted the quote — the
    FK is added in the migration (the TenantScoped mixin gives a bare
    column so this table is wired to whatever tenant model fits the
    context). Unique on (part_search_id, tenant_id) enforces at most
    one quote per business per search; the driver sees one quote per
    seller and the seller can't overwrite their own without an explicit
    edit flow (not in session 5).
    """

    __tablename__ = "quotes"

    part_search_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("part_search_requests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    price_mnt: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[QuoteCondition] = mapped_column(
        SAEnum(QuoteCondition, name="quote_condition", native_enum=True),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (
        UniqueConstraint(
            "part_search_id",
            "tenant_id",
            name="uq_quotes_part_search_id_tenant_id",
        ),
    )
