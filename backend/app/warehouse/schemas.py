"""HTTP schemas for the warehouse context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.marketplace.models import QuoteCondition
from app.warehouse.models import WarehouseMovementKind

MAX_DISPLAY_NAME = 200
MAX_SKU_CODE = 100
MAX_DESCRIPTION = 2000
MAX_NOTE = 2000
MAX_PRICE_MNT = 999_999_999
MAX_QUANTITY = 1_000_000


class SkuCreateIn(BaseModel):
    sku_code: str = Field(..., min_length=1, max_length=MAX_SKU_CODE)
    display_name: str = Field(..., min_length=1, max_length=MAX_DISPLAY_NAME)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    condition: QuoteCondition
    vehicle_brand_id: uuid.UUID | None = None
    vehicle_model_id: uuid.UUID | None = None
    unit_price_mnt: int | None = Field(default=None, gt=0, le=MAX_PRICE_MNT)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)

    @field_validator("sku_code", "display_name")
    @classmethod
    def _trim_required(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("must not be blank")
        return trimmed

    @field_validator("description")
    @classmethod
    def _trim_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None


class SkuUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=MAX_DISPLAY_NAME)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    unit_price_mnt: int | None = Field(default=None, gt=0, le=MAX_PRICE_MNT)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)


class SkuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku_code: str
    display_name: str
    description: str | None
    condition: QuoteCondition
    vehicle_brand_id: uuid.UUID | None
    vehicle_model_id: uuid.UUID | None
    unit_price_mnt: int | None
    low_stock_threshold: int | None
    created_at: datetime
    updated_at: datetime


class SkuDetailOut(SkuOut):
    """Detail view also reports the running `on_hand`."""

    on_hand: int


class SkuListOut(BaseModel):
    items: list[SkuOut]
    total: int


class SkuDeleteOut(BaseModel):
    ok: Literal[True] = True


class StockMovementCreateIn(BaseModel):
    kind: WarehouseMovementKind
    quantity: int = Field(..., gt=0, le=MAX_QUANTITY)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    # Adjust kind allows a signed quantity. We default to positive for
    # adjust; clients explicitly send `direction='down'` to subtract.
    direction: Literal["up", "down"] = "up"

    @field_validator("note")
    @classmethod
    def _trim_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku_id: uuid.UUID
    tenant_id: uuid.UUID
    kind: WarehouseMovementKind
    quantity: int
    signed_quantity: int
    note: str | None
    actor_user_id: uuid.UUID
    sale_id: uuid.UUID | None
    created_at: datetime


class StockMovementCreatedOut(BaseModel):
    movement: StockMovementOut
    on_hand_after: int


class StockMovementListOut(BaseModel):
    items: list[StockMovementOut]
    total: int
