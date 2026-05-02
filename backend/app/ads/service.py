"""Ads service — campaigns, tracking, exhaustion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.events import (
    AdCampaignActivated,
    AdCampaignCreated,
    AdCampaignExhausted,
    AdClickRecorded,
    AdImpressionRecorded,
)
from app.ads.models import AdCampaign, AdCampaignStatus, AdPlacement
from app.ads.repository import (
    AdCampaignRepository,
    AdClickRepository,
    AdImpressionRepository,
)
from app.ads.schemas import CampaignCreateIn
from app.businesses.models import BusinessMemberRole
from app.media.models import MediaAssetPurpose
from app.media.service import MediaService
from app.payments.repository import PaymentIntentRepository
from app.platform.config import Settings
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event

logger = get_logger("app.ads.service")

CAMPAIGN_WRITE_ROLES: frozenset[BusinessMemberRole] = frozenset(
    {BusinessMemberRole.owner, BusinessMemberRole.manager}
)


@dataclass(slots=True)
class CampaignCreated:
    campaign: AdCampaign
    payment_intent_id: uuid.UUID


@dataclass(slots=True)
class TrackingResult:
    campaign: AdCampaign
    exhausted: bool


class AdsService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        media_svc: MediaService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.campaigns = AdCampaignRepository(session)
        self.impressions = AdImpressionRepository(session)
        self.clicks = AdClickRepository(session)
        self.intents = PaymentIntentRepository(session)
        self.media_svc = media_svc
        self.settings = settings

    # ---- create + lifecycle --------------------------------------------

    async def create_campaign(
        self,
        *,
        tenant_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        payload: CampaignCreateIn,
    ) -> CampaignCreated:
        """Create a campaign in `pending_payment`.

        Phase 2 ships without the inline QPay invoice — the existing
        payment_intent FK requires a marketplace sale id, which doesn't
        apply to ad campaigns. Phase 5 ships a follow-up that nullifies
        `payment_intents.sale_id` and lets the business pay for an ad
        directly from this endpoint. For now: the campaign is parked in
        `pending_payment` and `payment_intent_id` is NULL until manually
        linked via the future endpoint.
        """
        if actor_role not in CAMPAIGN_WRITE_ROLES:
            raise ForbiddenError("Only owner / manager can create campaigns")

        if payload.media_asset_id is not None:
            await self.media_svc.validate_asset_ids(
                owner_id=owner_user_id,
                asset_ids=[payload.media_asset_id],
                purpose=MediaAssetPurpose.ad,
            )

        campaign = await self.campaigns.create(
            tenant_id=tenant_id,
            title=payload.title,
            body=payload.body,
            media_asset_id=payload.media_asset_id,
            placement=payload.placement,
            budget_mnt=payload.budget_mnt,
            cpm_mnt=payload.cpm_mnt,
        )
        write_outbox_event(
            self.session,
            AdCampaignCreated(
                aggregate_id=campaign.id,
                tenant_id=tenant_id,
                payment_intent_id=None,
                budget_mnt=campaign.budget_mnt,
            ),
        )
        logger.info(
            "ad_campaign_created",
            campaign_id=str(campaign.id),
            tenant_id=str(tenant_id),
        )
        return CampaignCreated(campaign=campaign, payment_intent_id=campaign.id)

    async def force_activate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        campaign_id: uuid.UUID,
    ) -> AdCampaign:
        """Operator/admin path to flip a campaign live without QPay.

        Phase 2 ships this so tests + manual onboarding can validate the
        full lifecycle. Phase 5 supersedes it once the campaign-tied
        QPay invoice flow lands.
        """
        if actor_role != BusinessMemberRole.owner:
            raise ForbiddenError("Only the owner can force-activate")
        campaign = await self.get_for_business(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status != AdCampaignStatus.pending_payment:
            raise ConflictError(f"Cannot activate a campaign in status '{campaign.status.value}'")
        campaign.status = AdCampaignStatus.active
        campaign.starts_at = datetime.now(UTC)
        await self.session.flush()
        write_outbox_event(
            self.session,
            AdCampaignActivated(aggregate_id=campaign.id, tenant_id=campaign.tenant_id),
        )
        return campaign

    async def activate_for_payment_intent(
        self, *, payment_intent_id: uuid.UUID
    ) -> AdCampaign | None:
        """Flip a `pending_payment` campaign to `active` on settlement.

        Called by the outbox handler when `payments.payment_settled`
        fires. Returns the campaign if a match was found; None otherwise
        (the settled intent isn't an ad).
        """
        campaign = await self.campaigns.get_by_payment_intent(payment_intent_id)
        if campaign is None:
            return None
        if campaign.status != AdCampaignStatus.pending_payment:
            return campaign
        campaign.status = AdCampaignStatus.active
        campaign.starts_at = datetime.now(UTC)
        await self.session.flush()
        write_outbox_event(
            self.session,
            AdCampaignActivated(aggregate_id=campaign.id, tenant_id=campaign.tenant_id),
        )
        logger.info("ad_campaign_activated", campaign_id=str(campaign.id))
        return campaign

    async def get_for_business(self, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> AdCampaign:
        campaign = await self.campaigns.get_by_id(campaign_id)
        if campaign is None or campaign.tenant_id != tenant_id:
            raise NotFoundError("Campaign not found")
        return campaign

    async def list_for_business(
        self, *, tenant_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AdCampaign], int]:
        return await self.campaigns.list_for_business(
            tenant_id=tenant_id, limit=limit, offset=offset
        )

    async def list_active_for_placement(
        self, *, placement: AdPlacement, limit: int
    ) -> list[AdCampaign]:
        return await self.campaigns.list_active_for_placement(placement=placement, limit=limit)

    async def pause(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        campaign_id: uuid.UUID,
    ) -> AdCampaign:
        if actor_role not in CAMPAIGN_WRITE_ROLES:
            raise ForbiddenError("Only owner / manager can pause campaigns")
        campaign = await self.get_for_business(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status != AdCampaignStatus.active:
            raise ConflictError(f"Cannot pause a campaign in status '{campaign.status.value}'")
        campaign.status = AdCampaignStatus.paused
        await self.session.flush()
        return campaign

    async def resume(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        campaign_id: uuid.UUID,
    ) -> AdCampaign:
        if actor_role not in CAMPAIGN_WRITE_ROLES:
            raise ForbiddenError("Only owner / manager can resume campaigns")
        campaign = await self.get_for_business(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status != AdCampaignStatus.paused:
            raise ConflictError(f"Cannot resume a campaign in status '{campaign.status.value}'")
        if campaign.spent_mnt >= campaign.budget_mnt:
            raise ConflictError("Campaign budget is already exhausted")
        campaign.status = AdCampaignStatus.active
        await self.session.flush()
        return campaign

    # ---- tracking ------------------------------------------------------

    async def record_impression(
        self,
        *,
        campaign_id: uuid.UUID,
        viewer_user_id: uuid.UUID | None,
    ) -> TrackingResult:
        campaign = await self.campaigns.get_by_id(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found")
        if campaign.status != AdCampaignStatus.active:
            # Don't 4xx — tracking is best-effort; just no-op.
            return TrackingResult(campaign=campaign, exhausted=False)

        await self.impressions.create(campaign_id=campaign.id, viewer_user_id=viewer_user_id)
        # CPM-based debit. Use integer math throughout: 1 impression =
        # cpm_mnt / 1000 MNT, but with integer rounding we'd lose every
        # impression below 1000 CPM. Track impressions in the campaign
        # counter and recompute spent on each impression batch of 1000
        # via integer division — rounded down means the platform never
        # over-bills.
        campaign.impressions += 1
        campaign.spent_mnt = (campaign.impressions * campaign.cpm_mnt) // 1000
        exhausted = False
        if campaign.spent_mnt >= campaign.budget_mnt:
            campaign.status = AdCampaignStatus.exhausted
            campaign.ends_at = datetime.now(UTC)
            exhausted = True
        await self.session.flush()

        write_outbox_event(
            self.session,
            AdImpressionRecorded(
                aggregate_id=campaign.id,
                tenant_id=campaign.tenant_id,
                viewer_user_id=viewer_user_id,
                spent_mnt=campaign.spent_mnt,
            ),
        )
        if exhausted:
            write_outbox_event(
                self.session,
                AdCampaignExhausted(
                    aggregate_id=campaign.id,
                    tenant_id=campaign.tenant_id,
                    spent_mnt=campaign.spent_mnt,
                    budget_mnt=campaign.budget_mnt,
                ),
            )
            logger.info("ad_campaign_exhausted", campaign_id=str(campaign.id))
        return TrackingResult(campaign=campaign, exhausted=exhausted)

    async def record_click(
        self,
        *,
        campaign_id: uuid.UUID,
        viewer_user_id: uuid.UUID | None,
    ) -> TrackingResult:
        campaign = await self.campaigns.get_by_id(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found")
        if campaign.status != AdCampaignStatus.active:
            return TrackingResult(campaign=campaign, exhausted=False)
        await self.clicks.create(campaign_id=campaign.id, viewer_user_id=viewer_user_id)
        campaign.clicks += 1
        await self.session.flush()
        write_outbox_event(
            self.session,
            AdClickRecorded(
                aggregate_id=campaign.id,
                tenant_id=campaign.tenant_id,
                viewer_user_id=viewer_user_id,
            ),
        )
        return TrackingResult(campaign=campaign, exhausted=False)
