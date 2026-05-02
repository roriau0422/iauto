"""Outbox subscribers for the ads context.

Listens for `payments.payment_settled` and flips any campaign that
references the settled intent to `active`. The intent_id → campaign
mapping uses the partial index on `ad_campaigns.payment_intent_id`,
so the lookup is cheap.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.service import AdsService
from app.media.client import S3MediaClient
from app.media.service import MediaService
from app.platform.config import get_settings
from app.platform.events import DomainEvent
from app.platform.logging import get_logger
from app.platform.outbox import register_handler

logger = get_logger("app.ads.handlers")


def _build_service(session: AsyncSession) -> AdsService:
    settings = get_settings()
    media = MediaService(
        session=session,
        client=S3MediaClient(settings),
        bucket=settings.s3_bucket_media,
    )
    return AdsService(session=session, media_svc=media, settings=settings)


async def on_payment_settled(event: DomainEvent, session: AsyncSession) -> None:
    """If the settled intent is for an ad campaign, activate it."""
    intent_id_raw = event.aggregate_id
    intent_id = (
        intent_id_raw if isinstance(intent_id_raw, uuid.UUID) else uuid.UUID(str(intent_id_raw))
    )
    service = _build_service(session)
    campaign = await service.activate_for_payment_intent(payment_intent_id=intent_id)
    if campaign is not None:
        logger.info(
            "ad_campaign_activated_from_payment",
            campaign_id=str(campaign.id),
            intent_id=str(intent_id),
        )


def register() -> None:
    register_handler("payments.payment_settled", on_payment_settled)
