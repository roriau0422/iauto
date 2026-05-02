"""HTTP request/response schemas for the media platform."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.media.client import PUT_MAX_BYTES
from app.media.models import MediaAssetPurpose, MediaAssetStatus

# What the platform accepts on upload. Anything else gets a 422 — keeping
# the type set narrow makes the antivirus/content-policy story easier later.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
# Extension lookup mirrors `ALLOWED_CONTENT_TYPES`. Only used for object-key
# suffix; not authoritative for storage.
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MediaUploadCreateIn(BaseModel):
    purpose: MediaAssetPurpose
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_size: int = Field(..., gt=0, le=PUT_MAX_BYTES)


class MediaUploadCreateOut(BaseModel):
    asset_id: uuid.UUID
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime
    max_bytes: int


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    purpose: MediaAssetPurpose
    status: MediaAssetStatus
    content_type: str
    byte_size: int | None
    created_at: datetime
    updated_at: datetime


class MediaAssetDownloadOut(BaseModel):
    asset_id: uuid.UUID
    download_url: str
    expires_at: datetime
