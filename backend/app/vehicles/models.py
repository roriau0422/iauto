"""ORM models for the vehicles context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class VerificationSource(StrEnum):
    xyp_public = "xyp_public"  # Client-posted XYP payload (smartcar.mn)
    manual = "manual"  # User-entered fallback when XYP unreachable


class Vehicle(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "vehicles"

    vin: Mapped[str | None] = mapped_column(Text, nullable=True)
    plate: Mapped[str] = mapped_column(Text, nullable=False)
    make: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable FK into the catalog — resolved at registration time from the
    # raw XYP `markName` / `modelName` strings. Null means the catalog does
    # not yet contain this brand/model (curator task), the raw string stays
    # in `make` / `model` so UIs still have something to show.
    vehicle_brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_brands.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vehicle_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    build_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity_cc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_xyp: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verification_source: Mapped[VerificationSource] = mapped_column(
        SAEnum(VerificationSource, name="vehicle_verification_source", native_enum=True),
        nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    ownerships: Mapped[list[VehicleOwnership]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
    )


class VehicleOwnership(Base):
    """Pivot row linking one user to one vehicle.

    No surrogate id — the natural PK is `(user_id, vehicle_id)`. Delete-cascade
    from both sides so removing a user or a vehicle sweeps the pivot.
    """

    __tablename__ = "vehicle_ownerships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    vehicle: Mapped[Vehicle] = relationship(back_populates="ownerships")


class VehicleLookupPlan(UuidPrimaryKey, Timestamped, Base):
    """Versioned instruction set the mobile client executes against XYP.

    Exactly one row is active at a time, enforced by a partial unique index
    in the migration. To roll out new headers or a new gateway URL, insert a
    new row with `is_active=true` and the old row gets flipped off in the
    same transaction.
    """

    __tablename__ = "vehicle_lookup_plans"

    plan_version: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    service_code: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_method: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    body_template: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    slots: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3600")


class VehicleLookupReport(UuidPrimaryKey, Timestamped, Base):
    """Record of a client-side XYP failure.

    We keep plate masked here — this table is debugging / audit, not a
    user-visible resource. `reported_by_user_id` can be null if the report
    came in before the client had a session (shouldn't happen under the
    current router but the nullability leaves room).
    """

    __tablename__ = "vehicle_lookup_reports"

    plate_masked: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan_version: Mapped[str | None] = mapped_column(Text, nullable=True)
