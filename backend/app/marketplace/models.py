"""ORM models for the marketplace context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
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
    media_asset_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
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
    media_asset_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (
        UniqueConstraint(
            "part_search_id",
            "tenant_id",
            name="uq_quotes_part_search_id_tenant_id",
        ),
    )


# ---------------------------------------------------------------------------
# Session 6 — reservations, sales, reviews
# ---------------------------------------------------------------------------


class ReservationStatus(StrEnum):
    """Lifecycle of a 24h hold a driver places on a quote.

    - `active`    — the hold is in force; another business cannot win this
                    search until it resolves.
    - `cancelled` — the driver explicitly walked away.
    - `expired`   — the 24h TTL elapsed without conversion (Arq cron).
    - `completed` — the business marked the part delivered → spawned a sale.
    """

    active = "active"
    cancelled = "cancelled"
    expired = "expired"
    completed = "completed"


class Reservation(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """A driver's 24h hold on a specific business's quote.

    Unique on `quote_id` — a quote can be reserved at most once. The
    `part_search_id` is denormalized off the quote so coverage / status
    flips don't need a join. `tenant_id` (= business_id) is on the row
    for the business inbox feeds.
    """

    __tablename__ = "reservations"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    part_search_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("part_search_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReservationStatus] = mapped_column(
        SAEnum(ReservationStatus, name="reservation_status", native_enum=True),
        nullable=False,
        default=ReservationStatus.active,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("quote_id", name="uq_reservations_quote_id"),)


class Sale(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """A completed transaction. Created when a reservation flips to `completed`.

    Carries `price_mnt` frozen from the quote at reservation time. All FKs
    are RESTRICT — a sale row is the historical receipt and never gets
    silently swept by another row's deletion.
    """

    __tablename__ = "sales"

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reservations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    part_search_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("part_search_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    price_mnt: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("reservation_id", name="uq_sales_reservation_id"),)


class ReviewDirection(StrEnum):
    """Who is reviewing whom on a sale.

    - `buyer_to_seller` — driver writes about the business. Public, shows
                          on the business profile.
    - `seller_to_buyer` — business writes about the driver. Private,
                          aggregated for moderation flags only.
    """

    buyer_to_seller = "buyer_to_seller"
    seller_to_buyer = "seller_to_buyer"


class Review(UuidPrimaryKey, Timestamped, Base):
    """One review per direction per sale.

    Subject is exactly one of (`subject_business_id`, `subject_user_id`),
    enforced by a CHECK constraint declared in the migration. `is_public`
    is derived from `direction` at insert time — buyer→seller is public,
    seller→buyer is private — and cached on the row so the public-feed
    queries stay simple.
    """

    __tablename__ = "reviews"

    sale_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[ReviewDirection] = mapped_column(
        SAEnum(ReviewDirection, name="review_direction", native_enum=True),
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_business_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint("sale_id", "direction", name="uq_reviews_sale_id_direction"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        CheckConstraint(
            "(subject_business_id IS NOT NULL)::int + (subject_user_id IS NOT NULL)::int = 1",
            name="ck_reviews_subject_xor",
        ),
    )
