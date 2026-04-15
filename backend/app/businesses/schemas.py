"""HTTP request/response Pydantic schemas for the businesses endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.identity.schemas import normalize_phone


def _optional_normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return normalize_phone(stripped)


class BusinessCreateIn(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=500)
    contact_phone: str | None = None

    @field_validator("display_name")
    @classmethod
    def _trim_display_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("display_name must not be blank")
        return trimmed

    @field_validator("contact_phone")
    @classmethod
    def _normalize_contact(cls, v: str | None) -> str | None:
        return _optional_normalize_phone(v)


class BusinessUpdateIn(BaseModel):
    """Partial update. Only provided fields are applied.

    `contact_phone` accepts an explicit empty string or None to clear the
    override, since a business might want to fall back to the owner's phone
    later. We represent that as a sentinel in the service layer.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=500)
    contact_phone: str | None = None

    @field_validator("display_name")
    @classmethod
    def _trim_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("display_name must not be blank")
        return trimmed

    @field_validator("contact_phone")
    @classmethod
    def _normalize_contact(cls, v: str | None) -> str | None:
        return _optional_normalize_phone(v)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    display_name: str
    description: str | None
    address: str | None
    contact_phone: str | None
    created_at: datetime
    updated_at: datetime
