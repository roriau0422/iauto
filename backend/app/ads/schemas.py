"""HTTP schemas for the ads context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ads.models import AdCampaignStatus, AdPlacement

MAX_TITLE = 200
MAX_BODY = 4000
MAX_PRICE_MNT = 999_999_999
MAX_BUDGET_MNT = 999_999_999
MIN_CPM_MNT = 100
MAX_CPM_MNT = 10_000_000


class CampaignCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE)
    body: str = Field(..., min_length=1, max_length=MAX_BODY)
    media_asset_id: uuid.UUID | None = None
    placement: AdPlacement
    budget_mnt: int = Field(..., gt=0, le=MAX_BUDGET_MNT)
    cpm_mnt: int = Field(..., ge=MIN_CPM_MNT, le=MAX_CPM_MNT)

    @field_validator("title", "body")
    @classmethod
    def _trim(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("must not be blank")
        return trimmed


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    body: str
    media_asset_id: uuid.UUID | None
    placement: AdPlacement
    budget_mnt: int
    cpm_mnt: int
    status: AdCampaignStatus
    payment_intent_id: uuid.UUID | None
    starts_at: datetime | None
    ends_at: datetime | None
    impressions: int
    clicks: int
    spent_mnt: int
    created_at: datetime
    updated_at: datetime


class CampaignCreatedOut(BaseModel):
    """Response on POST /ads/campaigns. Carries the QPay invoice payload
    so the caller can complete payment without a separate /payments call.
    """

    campaign: CampaignOut
    payment_intent_id: uuid.UUID
    qr_text: str | None = None
    qr_image_base64: str | None = None
    deeplink: str | None = None


class CampaignListOut(BaseModel):
    items: list[CampaignOut]
    total: int


class CampaignActiveOut(BaseModel):
    items: list[CampaignOut]


class TrackingOut(BaseModel):
    ok: Literal[True] = True
    campaign_id: uuid.UUID
    impressions: int
    clicks: int
    spent_mnt: int
    status: AdCampaignStatus
