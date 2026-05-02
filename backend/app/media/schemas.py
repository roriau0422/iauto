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
# Audio types added in session 14 for the voice → text Whisper flow.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/ogg",
    }
)
# Extension lookup mirrors `ALLOWED_CONTENT_TYPES`. Only used for object-key
# suffix; not authoritative for storage.
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
}


class MediaUploadCreateIn(BaseModel):
    purpose: MediaAssetPurpose
    content_type: Literal[
        "image/jpeg",
        "image/png",
        "image/webp",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/ogg",
    ]
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
