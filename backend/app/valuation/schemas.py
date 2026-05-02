"""HTTP schemas for the valuation context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.marketplace.models import QuoteCondition
from app.valuation.models import ValuationModelStatus


class ValuationEstimateIn(BaseModel):
    vehicle_brand_id: uuid.UUID
    vehicle_model_id: uuid.UUID | None = None
    build_year: int = Field(..., ge=1900, le=2100)
    mileage_km: int | None = Field(default=None, ge=0, le=10_000_000)
    fuel_type: str | None = Field(default=None, max_length=64)
    condition: QuoteCondition | None = None


class ValuationEstimateOut(BaseModel):
    """Response shape for `POST /v1/valuation/estimate`."""

    predicted_mnt: int
    low_mnt: int
    high_mnt: int
    model_version: str
    is_heuristic_fallback: bool


class ValuationModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    status: ValuationModelStatus
    trained_at: datetime | None
    sample_count: int
    mae_mnt: int | None
    feature_columns: list[Any]
    created_at: datetime
    updated_at: datetime
