"""ORM models for the warehouse context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.marketplace.models import QuoteCondition
from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


class WarehouseMovementKind(StrEnum):
    """Why a stock movement was recorded.

    - `receive` — new inventory arrived. Always positive in `signed_quantity`.
    - `issue`   — inventory left (sale, internal use). Always negative.
    - `adjust`  — physical recount. Either sign; stocktake uses this.
    """

    receive = "receive"
    issue = "issue"
    adjust = "adjust"


class WarehouseSku(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """One SKU in a business's catalog.

    `(tenant_id, sku_code)` is unique — businesses pick their own
    code. `condition` reuses the marketplace `quote_condition` enum so
    a downstream auto-quote feature can match incoming RFQ conditions
    directly.
    """

    __tablename__ = "warehouse_skus"

    sku_code: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_brands.id", ondelete="SET NULL"),
        nullable=True,
    )
    vehicle_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    condition: Mapped[QuoteCondition] = mapped_column(
        SAEnum(
            QuoteCondition,
            name="quote_condition",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
    )
    unit_price_mnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku_code", name="uq_warehouse_skus_tenant_id_sku_code"),
    )


class WarehouseStockMovement(UuidPrimaryKey, TenantScoped, Base):
    """Append-only inventory ledger row.

    `signed_quantity` is denormalized off `(kind, quantity)` so that
    `SUM(signed_quantity)` computes on_hand without a CASE branch. The
    DB CHECK constraint in 0012 enforces the consistency invariant.
    """

    __tablename__ = "warehouse_stock_movements"

    sku_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("warehouse_skus.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[WarehouseMovementKind] = mapped_column(
        SAEnum(WarehouseMovementKind, name="warehouse_movement_kind", native_enum=True),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_warehouse_stock_movements_quantity_positive"),
    )
