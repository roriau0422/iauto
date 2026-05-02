"""ORM models for the valuation context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class ValuationModelStatus(StrEnum):
    training = "training"
    active = "active"
    retired = "retired"


class ValuationModel(UuidPrimaryKey, Timestamped, Base):
    """Registry row per trained model. Exactly one `active` at a time."""

    __tablename__ = "valuation_models"

    version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ValuationModelStatus] = mapped_column(
        SAEnum(ValuationModelStatus, name="valuation_model_status", native_enum=True),
        nullable=False,
        default=ValuationModelStatus.training,
    )
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mae_mnt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    artifact_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (UniqueConstraint("version", name="uq_valuation_models_version"),)


class ValuationEstimate(UuidPrimaryKey, Base):
    """Per-call audit row. `features` carries the request shape verbatim."""

    __tablename__ = "valuation_estimates"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("valuation_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    predicted_mnt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    low_mnt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    high_mnt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
