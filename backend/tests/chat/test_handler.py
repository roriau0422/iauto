"""Verify the quote_sent outbox handler auto-creates a chat thread."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn, VehicleBrandCoverageIn
from app.businesses.service import BusinessesService
from app.catalog.models import VehicleBrand
from app.chat.models import ChatThread
from app.chat.service import ChatService
from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.marketplace.events import QuoteSent
from app.marketplace.models import QuoteCondition
from app.marketplace.schemas import PartSearchCreateIn, QuoteCreateIn
from app.marketplace.service import MarketplaceService
from app.media.service import MediaService
from app.platform.config import Settings
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from tests.media.test_service import BUCKET, FakeMediaClient

PLATE = "9987УБӨ"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU111100",
    colorName="White",
    capacity=2500,
    wheelPosition="Зүүн",
)


@pytest.fixture
def vehicles_service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> VehiclesService:
    return VehiclesService(session=db_session, redis=redis, sms=sms, settings=settings)


@pytest.fixture
def businesses_service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


@pytest.fixture
def media_service(db_session: AsyncSession) -> MediaService:
    return MediaService(session=db_session, client=FakeMediaClient(), bucket=BUCKET)


@pytest.fixture
def marketplace(
    db_session: AsyncSession,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    media_service: MediaService,
) -> MarketplaceService:
    return MarketplaceService(
        session=db_session,
        vehicles_svc=vehicles_service,
        businesses_svc=businesses_service,
        media_svc=media_service,
    )


@pytest.fixture
def chat(db_session: AsyncSession, redis: Redis, media_service: MediaService) -> ChatService:
    return ChatService(session=db_session, redis=redis, media_svc=media_service)


async def _toyota_brand(db_session: AsyncSession) -> uuid.UUID:
    return (
        await db_session.execute(select(VehicleBrand.id).where(VehicleBrand.slug == "toyota"))
    ).scalar_one()


async def test_handler_creates_thread_from_quote_sent(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    """The outbox handler is just `ChatService.ensure_thread_for_quote` —
    we drive it via the service directly so we don't have to wire the
    outbox consumer into a test process. The fan-out path is the same."""
    driver = User(phone="+97688111101", role=UserRole.driver)
    db_session.add(driver)
    await db_session.flush()
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="..."),
    )
    owner = User(phone="+97688111102", role=UserRole.business)
    db_session.add(owner)
    await db_session.flush()
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _toyota_brand(db_session)
    await businesses_service.replace_vehicle_coverage(
        business=business, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    quote = await marketplace.submit_quote(
        business_id=business.id,
        owner_user_id=owner.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=88_000, condition=QuoteCondition.used),
    )

    # Simulate the outbox-consumer dispatch: build the QuoteSent event and
    # ask the chat service to react.
    event = QuoteSent(
        aggregate_id=quote.id,
        tenant_id=business.id,
        part_search_id=request.id,
        driver_id=driver.id,
        price_mnt=quote.price_mnt,
        condition=quote.condition.value,
    )
    thread = await chat.ensure_thread_for_quote(quote_id=event.aggregate_id)
    assert thread.tenant_id == business.id
    assert thread.driver_id == driver.id

    rows = (await db_session.execute(select(ChatThread))).scalars().all()
    assert any(t.quote_id == quote.id for t in rows)
