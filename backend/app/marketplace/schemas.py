"""HTTP request/response Pydantic schemas for marketplace endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.marketplace.models import PartSearchStatus

# Cap media at 4 URLs per spec §5.1 ("1-4 зураг хавсаргах").
MAX_MEDIA = 4
# Cap description at 2000 chars — plenty for a Mongolian RFQ and cheap
# protection against flood posts. The pg_trgm GIN index handles the search.
MAX_DESCRIPTION = 2000


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
