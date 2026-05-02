"""HTTP request/response Pydantic schemas for marketplace endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.marketplace.models import (
    PartSearchStatus,
    QuoteCondition,
    ReservationStatus,
    ReviewDirection,
)

# Cap media at 4 assets per spec §5.1 ("1-4 зураг хавсаргах").
MAX_MEDIA = 4
# Cap description at 2000 chars — plenty for a Mongolian RFQ and cheap
# protection against flood posts. The pg_trgm GIN index handles the search.
MAX_DESCRIPTION = 2000
# Price cap: ~1B MNT (≈ 290k USD). Anything higher is almost certainly a
# fat-finger. Real luxury rebuilds do land in the low hundreds-of-millions,
# so 1B leaves headroom without letting a typo create silly ledger rows.
MAX_PRICE_MNT = 999_999_999
MAX_QUOTE_NOTES = 2000
# Free-text body on a public review.
MAX_REVIEW_BODY = 4000


def _dedupe_uuid_list(v: list[uuid.UUID]) -> list[uuid.UUID]:
    """Reject duplicate UUIDs; preserve order of first occurrence."""
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for item in v:
        if item in seen:
            raise ValueError("media_asset_ids must not contain duplicates")
        seen.add(item)
        out.append(item)
    return out


class PartSearchCreateIn(BaseModel):
    vehicle_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION)
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEDIA)

    @field_validator("description")
    @classmethod
    def _trim_description(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("description must not be blank")
        return trimmed

    @field_validator("media_asset_ids")
    @classmethod
    def _no_duplicates(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe_uuid_list(v)


class PartSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    description: str
    media_asset_ids: list[uuid.UUID]
    status: PartSearchStatus
    created_at: datetime
    updated_at: datetime


class PartSearchListOut(BaseModel):
    items: list[PartSearchOut]
    total: int


class PartSearchCancelOut(BaseModel):
    ok: Literal[True] = True
    status: PartSearchStatus


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


class QuoteCreateIn(BaseModel):
    price_mnt: int = Field(..., gt=0, le=MAX_PRICE_MNT)
    condition: QuoteCondition
    notes: str | None = Field(default=None, max_length=MAX_QUOTE_NOTES)
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEDIA)

    @field_validator("notes")
    @classmethod
    def _trim_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None

    @field_validator("media_asset_ids")
    @classmethod
    def _no_duplicates(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe_uuid_list(v)


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID  # = business_id
    part_search_id: uuid.UUID
    price_mnt: int
    condition: QuoteCondition
    notes: str | None
    media_asset_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class QuoteListOut(BaseModel):
    items: list[QuoteOut]
    total: int


# ---------------------------------------------------------------------------
# Reservations (session 6)
# ---------------------------------------------------------------------------


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    status: ReservationStatus
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class ReservationListOut(BaseModel):
    items: list[ReservationOut]
    total: int


# ---------------------------------------------------------------------------
# Sales (session 6)
# ---------------------------------------------------------------------------


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    reservation_id: uuid.UUID
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    price_mnt: int
    created_at: datetime
    updated_at: datetime


class SaleListOut(BaseModel):
    items: list[SaleOut]
    total: int


# ---------------------------------------------------------------------------
# Reviews (session 6)
# ---------------------------------------------------------------------------


class ReviewCreateIn(BaseModel):
    """Caller's role implies `direction` — driver→business is buyer→seller,
    business→driver is seller→buyer. The router resolves direction from the
    authenticated principal so we can't be tricked by the wire payload.
    """

    rating: int = Field(..., ge=1, le=5)
    body: str | None = Field(default=None, max_length=MAX_REVIEW_BODY)

    @field_validator("body")
    @classmethod
    def _trim_body(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sale_id: uuid.UUID
    direction: ReviewDirection
    author_user_id: uuid.UUID
    subject_business_id: uuid.UUID | None
    subject_user_id: uuid.UUID | None
    rating: int
    body: str | None
    is_public: bool
    created_at: datetime
    updated_at: datetime


class ReviewListOut(BaseModel):
    items: list[ReviewOut]
    total: int
