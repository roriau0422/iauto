"""Ads: campaign lifecycle, tracking math, exhaustion."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.models import AdCampaignStatus, AdPlacement
from app.ads.schemas import CampaignCreateIn
from app.ads.service import AdsService
from app.businesses.models import BusinessMemberRole
from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.models import User, UserRole
from app.media.service import MediaService
from app.platform.config import Settings
from app.platform.errors import ConflictError, ForbiddenError
from app.platform.outbox import OutboxEvent
from tests.media.test_service import BUCKET, FakeMediaClient


@pytest.fixture
def businesses_service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


@pytest.fixture
def media_service(db_session: AsyncSession) -> MediaService:
    return MediaService(session=db_session, client=FakeMediaClient(), bucket=BUCKET)


@pytest.fixture
def ads(
    db_session: AsyncSession,
    media_service: MediaService,
    settings: Settings,
) -> AdsService:
    return AdsService(session=db_session, media_svc=media_service, settings=settings)


async def _make_business(
    *,
    db_session: AsyncSession,
    businesses_service: BusinessesService,
    owner_phone: str,
) -> tuple[User, uuid.UUID]:
    owner = User(phone=owner_phone, role=UserRole.business)
    db_session.add(owner)
    await db_session.flush()
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    return owner, business.id


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_create_campaign_emits_event(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113501",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="Brake pad sale",
            body="50% off this weekend",
            placement=AdPlacement.story_feed,
            budget_mnt=100_000,
            cpm_mnt=5_000,
        ),
    )
    assert result.campaign.status == AdCampaignStatus.pending_payment
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    created = [e for e in events if e.event_type == "ads.campaign_created"]
    assert len(created) == 1


async def test_create_campaign_staff_forbidden(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113502",
    )
    with pytest.raises(ForbiddenError):
        await ads.create_campaign(
            tenant_id=business_id,
            owner_user_id=uuid.uuid4(),
            actor_role=BusinessMemberRole.staff,
            payload=CampaignCreateIn(
                title="x",
                body="y",
                placement=AdPlacement.story_feed,
                budget_mnt=10_000,
                cpm_mnt=1_000,
            ),
        )


async def test_force_activate_owner_only(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113503",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    with pytest.raises(ForbiddenError):
        await ads.force_activate(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.manager,
            campaign_id=result.campaign.id,
        )
    activated = await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    assert activated.status == AdCampaignStatus.active
    assert activated.starts_at is not None


async def test_pause_resume(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113504",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    paused = await ads.pause(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    assert paused.status == AdCampaignStatus.paused
    resumed = await ads.resume(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    assert resumed.status == AdCampaignStatus.active


# ---------------------------------------------------------------------------
# Tracking math
# ---------------------------------------------------------------------------


async def test_impressions_charge_cpm(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113505",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        # CPM 10000 → each impression debits 10 MNT.
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=100,
            cpm_mnt=10_000,
        ),
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )

    # 5 impressions = 50 MNT spent (5 × 10000 / 1000).
    for _ in range(5):
        await ads.record_impression(campaign_id=result.campaign.id, viewer_user_id=None)
    fresh = await ads.get_for_business(tenant_id=business_id, campaign_id=result.campaign.id)
    assert fresh.impressions == 5
    assert fresh.spent_mnt == 50
    assert fresh.status == AdCampaignStatus.active


async def test_campaign_exhausts_when_spent_meets_budget(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113506",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        # CPM 10000, budget 100 → 10 impressions exhausts (10 × 10 = 100).
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=100,
            cpm_mnt=10_000,
        ),
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    for i in range(10):
        outcome = await ads.record_impression(campaign_id=result.campaign.id, viewer_user_id=None)
        if i < 9:
            assert outcome.exhausted is False
        else:
            assert outcome.exhausted is True
            assert outcome.campaign.status == AdCampaignStatus.exhausted

    # An 11th impression on an exhausted campaign is a no-op (not 4xx,
    # tracking is best-effort).
    later = await ads.record_impression(campaign_id=result.campaign.id, viewer_user_id=None)
    assert later.campaign.impressions == 10  # unchanged
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    exhausted_events = [e for e in events if e.event_type == "ads.campaign_exhausted"]
    assert len(exhausted_events) == 1


async def test_clicks_increment_counter(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113507",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=result.campaign.id,
    )
    await ads.record_click(campaign_id=result.campaign.id, viewer_user_id=None)
    await ads.record_click(campaign_id=result.campaign.id, viewer_user_id=None)
    fresh = await ads.get_for_business(tenant_id=business_id, campaign_id=result.campaign.id)
    assert fresh.clicks == 2


async def test_pause_blocks_pause_when_not_active(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113508",
    )
    result = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="x",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    with pytest.raises(ConflictError):
        # Can't pause a `pending_payment` campaign.
        await ads.pause(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.owner,
            campaign_id=result.campaign.id,
        )


async def test_active_listing_filters_by_placement(
    ads: AdsService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688113509",
    )
    a = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="story-only",
            body="y",
            placement=AdPlacement.story_feed,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    b = await ads.create_campaign(
        tenant_id=business_id,
        owner_user_id=owner.id,
        actor_role=BusinessMemberRole.owner,
        payload=CampaignCreateIn(
            title="search-only",
            body="y",
            placement=AdPlacement.search_results,
            budget_mnt=10_000,
            cpm_mnt=1_000,
        ),
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=a.campaign.id,
    )
    await ads.force_activate(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        campaign_id=b.campaign.id,
    )
    feed = await ads.list_active_for_placement(placement=AdPlacement.story_feed, limit=10)
    assert {c.title for c in feed} == {"story-only"}
    search = await ads.list_active_for_placement(placement=AdPlacement.search_results, limit=10)
    assert {c.title for c in search} == {"search-only"}
