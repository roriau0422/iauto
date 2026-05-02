"""HTTP routes for the ads context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.ads.dependencies import get_ads_service
from app.ads.models import AdPlacement
from app.ads.schemas import (
    CampaignActiveOut,
    CampaignCreatedOut,
    CampaignCreateIn,
    CampaignListOut,
    CampaignOut,
    TrackingOut,
)
from app.ads.service import AdsService
from app.businesses.dependencies import (
    BusinessContext,
    get_current_business_member,
)
from app.identity.dependencies import get_current_user
from app.identity.models import User

router = APIRouter(tags=["ads"])


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------


@router.get(
    "/ads/active",
    response_model=CampaignActiveOut,
    summary="Up to N active ads for a placement (public)",
)
async def list_active(
    service: Annotated[AdsService, Depends(get_ads_service)],
    placement: Annotated[AdPlacement, Query()],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> CampaignActiveOut:
    rows = await service.list_active_for_placement(placement=placement, limit=limit)
    return CampaignActiveOut(items=[CampaignOut.model_validate(c) for c in rows])


# ---------------------------------------------------------------------------
# Business management
# ---------------------------------------------------------------------------


@router.post(
    "/ads/campaigns",
    response_model=CampaignCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an ad campaign (owner / manager only)",
)
async def create_campaign(
    body: CampaignCreateIn,
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    user: Annotated[User, Depends(get_current_user)],
) -> CampaignCreatedOut:
    result = await service.create_campaign(
        tenant_id=ctx.business.id,
        owner_user_id=user.id,
        actor_role=ctx.role,
        payload=body,
    )
    return CampaignCreatedOut(
        campaign=CampaignOut.model_validate(result.campaign),
        payment_intent_id=result.payment_intent_id,
    )


@router.get(
    "/ads/campaigns/mine",
    response_model=CampaignListOut,
    summary="List the caller's ad campaigns",
)
async def list_mine(
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CampaignListOut:
    items, total = await service.list_for_business(
        tenant_id=ctx.business.id, limit=limit, offset=offset
    )
    return CampaignListOut(items=[CampaignOut.model_validate(c) for c in items], total=total)


@router.get(
    "/ads/campaigns/{campaign_id}",
    response_model=CampaignOut,
    summary="Read a campaign owned by the caller",
)
async def get_campaign(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> CampaignOut:
    campaign = await service.get_for_business(tenant_id=ctx.business.id, campaign_id=campaign_id)
    return CampaignOut.model_validate(campaign)


@router.post(
    "/ads/campaigns/{campaign_id}/pause",
    response_model=CampaignOut,
    summary="Pause an active campaign",
)
async def pause_campaign(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> CampaignOut:
    campaign = await service.pause(
        tenant_id=ctx.business.id, actor_role=ctx.role, campaign_id=campaign_id
    )
    return CampaignOut.model_validate(campaign)


@router.post(
    "/ads/campaigns/{campaign_id}/resume",
    response_model=CampaignOut,
    summary="Resume a paused campaign",
)
async def resume_campaign(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> CampaignOut:
    campaign = await service.resume(
        tenant_id=ctx.business.id, actor_role=ctx.role, campaign_id=campaign_id
    )
    return CampaignOut.model_validate(campaign)


@router.post(
    "/ads/campaigns/{campaign_id}/activate",
    response_model=CampaignOut,
    summary=(
        "Force-activate a pending_payment campaign (owner only). "
        "Phase 2 placeholder until the campaign-tied QPay invoice flow lands."
    ),
)
async def force_activate(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> CampaignOut:
    campaign = await service.force_activate(
        tenant_id=ctx.business.id, actor_role=ctx.role, campaign_id=campaign_id
    )
    return CampaignOut.model_validate(campaign)


# ---------------------------------------------------------------------------
# Tracking (any authenticated user)
# ---------------------------------------------------------------------------


@router.post(
    "/ads/campaigns/{campaign_id}/impressions",
    response_model=TrackingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record an impression",
)
async def record_impression(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> TrackingOut:
    result = await service.record_impression(campaign_id=campaign_id, viewer_user_id=user.id)
    return TrackingOut(
        campaign_id=result.campaign.id,
        impressions=result.campaign.impressions,
        clicks=result.campaign.clicks,
        spent_mnt=result.campaign.spent_mnt,
        status=result.campaign.status,
    )


@router.post(
    "/ads/campaigns/{campaign_id}/clicks",
    response_model=TrackingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a click",
)
async def record_click(
    campaign_id: uuid.UUID,
    service: Annotated[AdsService, Depends(get_ads_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> TrackingOut:
    result = await service.record_click(campaign_id=campaign_id, viewer_user_id=user.id)
    return TrackingOut(
        campaign_id=result.campaign.id,
        impressions=result.campaign.impressions,
        clicks=result.campaign.clicks,
        spent_mnt=result.campaign.spent_mnt,
        status=result.campaign.status,
    )
