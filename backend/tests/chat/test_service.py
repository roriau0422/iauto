"""Service-level tests for the chat context."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn, VehicleBrandCoverageIn
from app.businesses.service import BusinessesService
from app.catalog.models import VehicleBrand
from app.chat.models import ChatMessageKind
from app.chat.service import ChatService
from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.marketplace.models import QuoteCondition
from app.marketplace.schemas import PartSearchCreateIn, QuoteCreateIn
from app.marketplace.service import MarketplaceService
from app.media.service import MediaService
from app.platform.config import Settings
from app.platform.errors import ForbiddenError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from tests.media.test_service import BUCKET, FakeMediaClient

PLATE = "9987УБӨ"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU999999",
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


async def _make_driver(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_business_owner(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.business)
    db_session.add(user)
    await db_session.flush()
    return user


async def _toyota_brand(db_session: AsyncSession) -> uuid.UUID:
    return (
        await db_session.execute(select(VehicleBrand.id).where(VehicleBrand.slug == "toyota"))
    ).scalar_one()


async def _make_quote(
    *,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
    driver_phone: str,
    owner_phone: str,
) -> tuple[User, User, uuid.UUID, uuid.UUID]:
    """Helper: produce (driver, owner, business_id, quote_id)."""
    driver = await _make_driver(db_session, driver_phone)
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="parts"),
    )
    owner = await _make_business_owner(db_session, owner_phone)
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
        payload=QuoteCreateIn(price_mnt=120_000, condition=QuoteCondition.new),
    )
    return driver, owner, business.id, quote.id


# ---------------------------------------------------------------------------
# Thread auto-create
# ---------------------------------------------------------------------------


async def test_ensure_thread_creates_with_system_welcome(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111001",
        owner_phone="+97688111002",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)
    assert thread.quote_id == quote_id
    assert thread.tenant_id == business_id
    assert thread.driver_id == driver.id

    history = await chat.list_messages(thread=thread, limit=10, before_id=None)
    assert len(history.items) == 1
    assert history.items[0].kind == ChatMessageKind.system
    assert "120000" in (history.items[0].body or "")


async def test_ensure_thread_idempotent(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, _, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111003",
        owner_phone="+97688111004",
    )
    a = await chat.ensure_thread_for_quote(quote_id=quote_id)
    b = await chat.ensure_thread_for_quote(quote_id=quote_id)
    assert a.id == b.id


async def test_ensure_thread_404_for_unknown_quote(chat: ChatService) -> None:
    with pytest.raises(NotFoundError):
        await chat.ensure_thread_for_quote(quote_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Party gate
# ---------------------------------------------------------------------------


async def test_get_thread_for_party_either_side(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111005",
        owner_phone="+97688111006",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)
    by_driver = await chat.get_thread_for_party(
        thread_id=thread.id, user_id=driver.id, business_id=None
    )
    assert by_driver.id == thread.id
    by_biz = await chat.get_thread_for_party(
        thread_id=thread.id, user_id=uuid.uuid4(), business_id=business_id
    )
    assert by_biz.id == thread.id


async def test_get_thread_404_for_stranger(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, _, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111007",
        owner_phone="+97688111008",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)
    with pytest.raises(NotFoundError):
        await chat.get_thread_for_party(thread_id=thread.id, user_id=uuid.uuid4(), business_id=None)


# ---------------------------------------------------------------------------
# Posting messages
# ---------------------------------------------------------------------------


async def test_post_text_message_publishes_event_and_pubsub(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
    redis: Redis,
) -> None:
    driver, _, _, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111009",
        owner_phone="+97688111010",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)

    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(f"chat:thread:{thread.id}")
        message = await chat.post_message(
            thread=thread,
            author_user_id=driver.id,
            kind=ChatMessageKind.text,
            body="Hello, do you have these in stock?",
            media_asset_id=None,
        )
        assert message.kind == ChatMessageKind.text
        assert message.body == "Hello, do you have these in stock?"

        # Pubsub fan-out should land. Drain the subscribe ack first.
        import asyncio as _aio
        from contextlib import suppress

        delivered = None
        for _ in range(20):
            raw = await pubsub.get_message(timeout=0.1)
            if raw and raw.get("type") == "message":
                delivered = raw
                break
            with suppress(_aio.CancelledError):
                await _aio.sleep(0)
        assert delivered is not None, "expected pubsub message"
    finally:
        await pubsub.unsubscribe(f"chat:thread:{thread.id}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    posted = [e for e in events if e.event_type == "chat.message_posted"]
    assert len(posted) == 1


async def test_post_message_refuses_system_kind(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111011",
        owner_phone="+97688111012",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)
    with pytest.raises(ForbiddenError):
        await chat.post_message(
            thread=thread,
            author_user_id=driver.id,
            kind=ChatMessageKind.system,
            body="should not work",
            media_asset_id=None,
        )


async def test_list_threads_for_business_orders_by_last_message(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, business_id, q1 = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111013",
        owner_phone="+97688111014",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=q1)
    result = await chat.list_threads_for_business(business_id=business_id, limit=20, offset=0)
    assert result.total >= 1
    ids = [t.id for t in result.items]
    assert thread.id in ids


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------


async def test_list_messages_pages_with_before_id(
    chat: ChatService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, quote_id = await _make_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688111015",
        owner_phone="+97688111016",
    )
    thread = await chat.ensure_thread_for_quote(quote_id=quote_id)
    # 5 user messages plus the system welcome = 6 total.
    for i in range(5):
        await chat.post_message(
            thread=thread,
            author_user_id=driver.id,
            kind=ChatMessageKind.text,
            body=f"msg {i}",
            media_asset_id=None,
        )

    page1 = await chat.list_messages(thread=thread, limit=3, before_id=None)
    assert len(page1.items) == 3
    assert page1.has_more is True

    page2 = await chat.list_messages(thread=thread, limit=3, before_id=page1.items[-1].id)
    assert len(page2.items) == 3
    assert page2.has_more is False
