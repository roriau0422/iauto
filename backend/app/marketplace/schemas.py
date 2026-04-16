"""HTTP request/response Pydantic schemas for marketplace endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.marketplace.models import PartSearchStatus, QuoteCondition

# Cap media at 4 URLs per spec §5.1 ("1-4 зураг хавсаргах").
MAX_MEDIA = 4
# Cap description at 2000 chars — plenty for a Mongolian RFQ and cheap
# protection against flood posts. The pg_trgm GIN index handles the search.
MAX_DESCRIPTION = 2000
# Price cap: ~1B MNT (≈ 290k USD). Anything higher is almost certainly a
# fat-finger. Real luxury rebuilds do land in the low hundreds-of-millions,
# so 1B leaves headroom without letting a typo create silly ledger rows.
MAX_PRICE_MNT = 999_999_999
MAX_QUOTE_NOTES = 2000


class PartSearchCreateIn(BaseModel):
    vehicle_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION)
    media_urls: list[str] = Field(default_factory=list, max_length=MAX_MEDIA)

    @field_validator("description")
    @classmethod
    def _trim_description(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("description must not be blank")
        return trimmed

    @field_validator("media_urls")
    @classmethod
    def _reject_blank_urls(cls, v: list[str]) -> list[str]:
        cleaned = [u.strip() for u in v]
        if any(not u for u in cleaned):
            raise ValueError("media_urls must not contain blank entries")
        return cleaned


class PartSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    description: str
    media_urls: list[str]
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
    media_urls: list[str] = Field(default_factory=list, max_length=MAX_MEDIA)

    @field_validator("notes")
    @classmethod
    def _trim_notes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None

    @field_validator("media_urls")
    @classmethod
    def _reject_blank_urls(cls, v: list[str]) -> list[str]:
        cleaned = [u.strip() for u in v]
        if any(not u for u in cleaned):
            raise ValueError("media_urls must not contain blank entries")
        return cleaned


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID  # = business_id
    part_search_id: uuid.UUID
    price_mnt: int
    condition: QuoteCondition
    notes: str | None
    media_urls: list[str]
    created_at: datetime
    updated_at: datetime


class QuoteListOut(BaseModel):
    items: list[QuoteOut]
    total: int
