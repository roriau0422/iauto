"""Database access for the ads context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.models import (
    AdCampaign,
    AdCampaignStatus,
    AdClick,
    AdImpression,
    AdPlacement,
)


class AdCampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, campaign_id: uuid.UUID) -> AdCampaign | None:
        return await self.session.get(AdCampaign, campaign_id)

    async def get_by_payment_intent(self, payment_intent_id: uuid.UUID) -> AdCampaign | None:
        stmt = select(AdCampaign).where(AdCampaign.payment_intent_id == payment_intent_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        title: str,
        body: str,
        media_asset_id: uuid.UUID | None,
        placement: AdPlacement,
        budget_mnt: int,
        cpm_mnt: int,
    ) -> AdCampaign:
        campaign = AdCampaign(
            tenant_id=tenant_id,
            title=title,
            body=body,
            media_asset_id=media_asset_id,
            placement=placement,
            budget_mnt=budget_mnt,
            cpm_mnt=cpm_mnt,
            status=AdCampaignStatus.pending_payment,
        )
        self.session.add(campaign)
        await self.session.flush()
        return campaign

    async def list_for_business(
        self,
        *,
        tenant_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[AdCampaign], int]:
        base = select(AdCampaign).where(AdCampaign.tenant_id == tenant_id)
        stmt = base.order_by(AdCampaign.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(AdCampaign.id)).where(AdCampaign.tenant_id == tenant_id)
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def list_active_for_placement(
        self,
        *,
        placement: AdPlacement,
        limit: int,
    ) -> list[AdCampaign]:
        stmt = (
            select(AdCampaign)
            .where(
                AdCampaign.status == AdCampaignStatus.active,
                AdCampaign.placement == placement,
            )
            .order_by(AdCampaign.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())


class AdImpressionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        viewer_user_id: uuid.UUID | None,
    ) -> AdImpression:
        row = AdImpression(campaign_id=campaign_id, viewer_user_id=viewer_user_id)
        self.session.add(row)
        await self.session.flush()
        return row


class AdClickRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        viewer_user_id: uuid.UUID | None,
    ) -> AdClick:
        row = AdClick(campaign_id=campaign_id, viewer_user_id=viewer_user_id)
        self.session.add(row)
        await self.session.flush()
        return row
