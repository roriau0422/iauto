"""ORM models for the vehicles context."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.base import Base, Timestamped, UuidPrimaryKey
from app.platform.crypto import get_cipher, get_search_index


class VerificationSource(StrEnum):
    xyp_public = "xyp_public"  # Client-posted XYP payload (smartcar.mn)
    manual = "manual"  # User-entered fallback when XYP unreachable


class SteeringSide(StrEnum):
    """Steering-wheel / drive-side layout of a physical car.

    Mongolia has a mixed fleet: Japanese imports are overwhelmingly RHD
    (steering on the right), while Korean / German / US / Chinese imports
    are LHD. Business coverage tables (session 5) use this as a filter so
    a shop stocking LHD Tiguan parts doesn't get searches for RHD Prii.

    Mapping from the XYP `wheelPosition` field:
        "Зүүн"  (Mongolian for "left")  → LHD
        "Баруун" (Mongolian for "right") → RHD
    """

    LHD = "LHD"
    RHD = "RHD"


def normalize_vin(raw: str) -> str:
    return raw.strip().upper()


def parse_wheel_position(raw: str | None) -> SteeringSide | None:
    """Map XYP `wheelPosition` Mongolian text to the SteeringSide enum.

    Returns None for unknown / missing input so the column stays nullable
    when smartcar.mn omits the field or introduces a new variant.
    """
    if raw is None:
        return None
    normalized = raw.strip()
    if not normalized:
        return None
    if normalized in ("Зүүн", "зүүн"):
        return SteeringSide.LHD
    if normalized in ("Баруун", "баруун"):
        return SteeringSide.RHD
    return None


def parse_import_month(raw: str | None) -> date | None:
    """Truncate an XYP `importDate` ISO timestamp to the 1st of its month.

    The spec asks for year+month only — the day is noise for the flywheel
    (import registration is a policy/tax bucket, not a delivery milestone).
    Storing as `date` with day=01 keeps it sortable and range-queryable.
    Returns None for missing / unparseable input.
    """
    if raw is None or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.date().replace(day=1)


class Vehicle(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "vehicles"

    # Encrypted PII columns — reads/writes go through Python properties.
    #
    # VIN uses blind-index dedup: one physical car → one row, even though
    # every caller only ever hands us the raw VIN string. Partial unique
    # index on `vin_search WHERE vin_search IS NOT NULL` lives in the
    # migration so rows without a VIN (legacy / XYP-unavailable) coexist.
    #
    # Plate is not searched by value (only by vehicle id), so it stores a
    # ciphertext alone — no blind index column. Masking for logs happens
    # against the decrypted value via `mask_plate()`.
    vin_cipher: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    vin_search: Mapped[str | None] = mapped_column(Text, nullable=True)
    plate_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
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
    # XYP `className` — Mongolian vehicle license class ("B", "C", ...).
    class_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # XYP `fuelType` — Mongolian fuel name ("Бензин", "Дизель", ...).
    fuel_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # XYP `importDate` truncated to year+month (day always 01).
    import_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    # XYP `wheelPosition` → LHD/RHD. Part of the session-5 matching key.
    steering_side: Mapped[SteeringSide | None] = mapped_column(
        SAEnum(SteeringSide, name="vehicle_steering_side", native_enum=True),
        nullable=True,
        index=True,
    )
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

    @property
    def vin(self) -> str | None:
        """Decrypted VIN, uppercase, or None if the vehicle has no VIN."""
        if self.vin_cipher is None:
            return None
        return get_cipher().decrypt(self.vin_cipher)

    @vin.setter
    def vin(self, value: str | None) -> None:
        if value is None or not value.strip():
            self.vin_cipher = None
            self.vin_search = None
            return
        normalized = normalize_vin(value)
        self.vin_cipher = get_cipher().encrypt(normalized)
        self.vin_search = get_search_index().compute(normalized)

    @property
    def plate(self) -> str:
        """Decrypted plate (always present)."""
        return get_cipher().decrypt(self.plate_cipher)

    @plate.setter
    def plate(self, value: str) -> None:
        # Plate is already normalized to canonical `NNNNLLL` form by the
        # schema validator upstream — we do not re-normalize here to avoid
        # dragging the vehicles schema module into this ORM file.
        self.plate_cipher = get_cipher().encrypt(value)


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


class VehicleServiceLogKind(StrEnum):
    """Categories of maintenance log entries per spec §9.3.

    Stub set for session 7 — `oil/filter/tire/battery/misc` covers the
    common cases. Session 9 may extend with more categories if product
    needs them; that's an additive enum migration.
    """

    oil = "oil"
    filter = "filter"
    tire = "tire"
    battery = "battery"
    misc = "misc"


class VehicleServiceLog(UuidPrimaryKey, Timestamped, Base):
    """One service-history entry against a vehicle.

    Session 7 ships this as a stub: the table + enum exist so the My Car
    service-history endpoint can return an empty array; session 9 wires
    the create flow per spec §9.3.
    """

    __tablename__ = "vehicle_service_logs"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[VehicleServiceLogKind] = mapped_column(
        SAEnum(
            VehicleServiceLogKind,
            name="vehicle_service_log_kind",
            native_enum=True,
        ),
        nullable=False,
    )
    noted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    mileage_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_mnt: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
