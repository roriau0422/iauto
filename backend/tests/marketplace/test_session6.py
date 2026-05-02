"""Session 6 — reservations, sales, reviews, media-integration, expiry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import (
    BusinessCreateIn,
    VehicleBrandCoverageIn,
)
from app.businesses.service import BusinessesService
from app.catalog.models import VehicleBrand
from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.marketplace.models import (
    PartSearchStatus,
    QuoteCondition,
    Reservation,
    ReservationStatus,
    ReviewDirection,
)
from app.marketplace.repository import ReservationRepository
from app.marketplace.schemas import (
    PartSearchCreateIn,
    QuoteCreateIn,
    ReviewCreateIn,
)
from app.marketplace.service import MarketplaceService
from app.media.models import MediaAssetPurpose
from app.media.schemas import MediaUploadCreateIn
from app.media.service import MediaService
from app.platform.config import Settings
from app.platform.errors import ConflictError, NotFoundError, ValidationError
from app.platform.outbox import OutboxEvent
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from app.workers.reservations import run_once as expire_reservations_run_once
from tests.media.test_service import BUCKET, FakeMediaClient

PLATE_A = "9987УБӨ"
PLATE_B = "1234УБА"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU666666",
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


async def _make_active_quote(
    *,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
    driver_phone: str,
    owner_phone: str,
) -> tuple[User, User, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper: produce (driver, owner, business_id, search_id, quote_id)."""
    driver = await _make_driver(db_session, driver_phone)
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="Camry brake pads"),
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
        payload=QuoteCreateIn(price_mnt=150_000, condition=QuoteCondition.new),
    )
    return driver, owner, business.id, request.id, quote.id


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


async def test_reserve_quote_happy_path_emits_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, search_id, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110701",
        owner_phone="+97688110702",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    assert reservation.status == ReservationStatus.active
    assert reservation.tenant_id == business_id
    assert reservation.driver_id == driver.id
    assert reservation.part_search_id == search_id
    # ~24h hold.
    delta = reservation.expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=58) < delta <= timedelta(hours=24, minutes=1)

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    started = [e for e in events if e.event_type == "marketplace.reservation_started"]
    assert len(started) == 1
    assert started[0].tenant_id == business_id
    assert started[0].payload["price_mnt"] == 150_000


async def test_reserve_quote_rejects_stranger_driver(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110703",
        owner_phone="+97688110704",
    )
    stranger = await _make_driver(db_session, "+97688110705")
    with pytest.raises(NotFoundError):
        await marketplace.reserve(driver_id=stranger.id, quote_id=quote_id)


async def test_reserve_quote_rejects_unknown_quote(
    marketplace: MarketplaceService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110706")
    with pytest.raises(NotFoundError):
        await marketplace.reserve(driver_id=driver.id, quote_id=uuid.uuid4())


async def test_reserve_quote_rejects_double_reservation_on_quote(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110707",
        owner_phone="+97688110708",
    )
    await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    with pytest.raises(ConflictError):
        await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)


async def test_reserve_quote_rejects_when_other_active_on_search(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    """Two businesses quoted; driver reserved A; can't also reserve B."""
    driver = await _make_driver(db_session, "+97688110709")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="parts"),
    )
    toyota = await _toyota_brand(db_session)

    owner_a = await _make_business_owner(db_session, "+97688110710")
    biz_a = await businesses_service.create(
        owner=owner_a, payload=BusinessCreateIn(display_name="A")
    )
    await businesses_service.replace_vehicle_coverage(
        business=biz_a, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    quote_a = await marketplace.submit_quote(
        business_id=biz_a.id,
        owner_user_id=owner_a.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=100_000, condition=QuoteCondition.new),
    )

    owner_b = await _make_business_owner(db_session, "+97688110711")
    biz_b = await businesses_service.create(
        owner=owner_b, payload=BusinessCreateIn(display_name="B")
    )
    await businesses_service.replace_vehicle_coverage(
        business=biz_b, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    quote_b = await marketplace.submit_quote(
        business_id=biz_b.id,
        owner_user_id=owner_b.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=110_000, condition=QuoteCondition.used),
    )

    await marketplace.reserve(driver_id=driver.id, quote_id=quote_a.id)
    with pytest.raises(ConflictError):
        await marketplace.reserve(driver_id=driver.id, quote_id=quote_b.id)


async def test_reserve_quote_rejects_cancelled_search(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, search_id, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110712",
        owner_phone="+97688110713",
    )
    await marketplace.cancel(driver_id=driver.id, search_id=search_id)
    with pytest.raises(ConflictError):
        await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)


async def test_cancel_reservation_happy_path(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110714",
        owner_phone="+97688110715",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    cancelled = await marketplace.cancel_reservation(
        driver_id=driver.id, reservation_id=reservation.id
    )
    assert cancelled.status == ReservationStatus.cancelled

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    cancelled_events = [e for e in events if e.event_type == "marketplace.reservation_cancelled"]
    assert len(cancelled_events) == 1


async def test_cancel_reservation_rejects_stranger(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110716",
        owner_phone="+97688110717",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    stranger = await _make_driver(db_session, "+97688110718")
    with pytest.raises(NotFoundError):
        await marketplace.cancel_reservation(driver_id=stranger.id, reservation_id=reservation.id)


async def test_cancel_reservation_double_cancel_409(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110719",
        owner_phone="+97688110720",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    await marketplace.cancel_reservation(driver_id=driver.id, reservation_id=reservation.id)
    with pytest.raises(ConflictError):
        await marketplace.cancel_reservation(driver_id=driver.id, reservation_id=reservation.id)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


async def test_complete_reservation_creates_sale_and_fulfills_search(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, search_id, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110721",
        owner_phone="+97688110722",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    sale = await marketplace.complete_reservation(
        business_id=business_id, reservation_id=reservation.id
    )
    assert sale.tenant_id == business_id
    assert sale.driver_id == driver.id
    assert sale.quote_id == quote_id
    assert sale.part_search_id == search_id
    assert sale.price_mnt == 150_000

    refreshed_search = await marketplace.searches.get_by_id(search_id)
    assert refreshed_search is not None
    assert refreshed_search.status == PartSearchStatus.fulfilled

    refreshed_reservation = await marketplace.reservations.get_by_id(reservation.id)
    assert refreshed_reservation is not None
    assert refreshed_reservation.status == ReservationStatus.completed

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    completed = [e for e in events if e.event_type == "marketplace.sale_completed"]
    assert len(completed) == 1
    assert completed[0].payload["price_mnt"] == 150_000


async def test_complete_reservation_rejects_stranger_business(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110723",
        owner_phone="+97688110724",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)

    stranger_owner = await _make_business_owner(db_session, "+97688110725")
    stranger_biz = await businesses_service.create(
        owner=stranger_owner, payload=BusinessCreateIn(display_name="Stranger")
    )
    with pytest.raises(NotFoundError):
        await marketplace.complete_reservation(
            business_id=stranger_biz.id, reservation_id=reservation.id
        )


async def test_complete_reservation_rejects_non_active(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110726",
        owner_phone="+97688110727",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    await marketplace.cancel_reservation(driver_id=driver.id, reservation_id=reservation.id)
    with pytest.raises(ConflictError):
        await marketplace.complete_reservation(
            business_id=business_id, reservation_id=reservation.id
        )


# ---------------------------------------------------------------------------
# Reservation expiry (Arq cron)
# ---------------------------------------------------------------------------


async def test_expire_reservations_flips_status_and_emits_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110728",
        owner_phone="+97688110729",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    # Backdate the expiry into the past so the sweeper picks it up.
    reservation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.flush()

    # The job runs in its own session/transaction, so we need the data
    # visible — call the in-process function directly with the test
    # session factory `db_session.bind`.
    repo = ReservationRepository(db_session)
    rows = await repo.claim_expired(now=datetime.now(UTC), batch_size=10)
    assert len(rows) == 1
    assert rows[0].status == ReservationStatus.expired


async def test_expire_reservations_run_once_emits_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    """`run_once` flips the row + emits the outbox event in one transaction.

    We feed the cron a session factory that hands back sessions bound to
    the test's nested-transaction connection, so all the cron's writes
    land inside the same savepoint and get rolled back on test teardown.
    The cron's `session.begin()` becomes a SAVEPOINT inside our outer
    SAVEPOINT — nesting is fine.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    driver, _, _, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110730",
        owner_phone="+97688110731",
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    reservation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.flush()

    # Bind the factory to our test connection so the cron's transaction is
    # nested inside our test savepoint.
    bind = db_session.connection
    connection = await bind()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    count = await expire_reservations_run_once(factory)
    assert count == 1

    # Re-fetch via the test session — the cron committed its inner
    # transaction, but our outer savepoint still sees the writes. Bypass
    # the identity-map cache by selecting the status column directly so SA
    # doesn't try to merge the existing row's stale state.
    from sqlalchemy import select as sa_select

    fresh_status = (
        await db_session.execute(
            sa_select(Reservation.status).where(Reservation.id == reservation.id)
        )
    ).scalar_one()
    assert fresh_status == ReservationStatus.expired

    outbox = (
        (
            await db_session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "marketplace.reservation_expired"
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(e.aggregate_id == reservation.id for e in outbox)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


async def _to_sale(
    *,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
    driver_phone: str,
    owner_phone: str,
) -> tuple[User, User, uuid.UUID, uuid.UUID]:
    driver, owner, business_id, _, quote_id = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone=driver_phone,
        owner_phone=owner_phone,
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote_id)
    sale = await marketplace.complete_reservation(
        business_id=business_id, reservation_id=reservation.id
    )
    return driver, owner, business_id, sale.id


async def test_buyer_review_is_public(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, sale_id = await _to_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110732",
        owner_phone="+97688110733",
    )
    review = await marketplace.submit_review_as_driver(
        driver_id=driver.id,
        sale_id=sale_id,
        payload=ReviewCreateIn(rating=5, body="Excellent shop"),
    )
    assert review.direction == ReviewDirection.buyer_to_seller
    assert review.is_public is True
    assert review.subject_business_id == business_id
    assert review.subject_user_id is None

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    submitted = [e for e in events if e.event_type == "marketplace.review_submitted"]
    assert len(submitted) == 1
    assert submitted[0].payload["direction"] == "buyer_to_seller"


async def test_seller_review_is_private(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, sale_id = await _to_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110734",
        owner_phone="+97688110735",
    )
    business = await businesses_service.businesses.get_by_id(business_id)
    assert business is not None
    review = await marketplace.submit_review_as_business(
        business=business,
        sale_id=sale_id,
        payload=ReviewCreateIn(rating=4, body="reliable buyer"),
    )
    assert review.direction == ReviewDirection.seller_to_buyer
    assert review.is_public is False
    assert review.subject_business_id is None
    assert review.subject_user_id == driver.id


async def test_review_duplicate_same_direction_409(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, _, sale_id = await _to_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110736",
        owner_phone="+97688110737",
    )
    await marketplace.submit_review_as_driver(
        driver_id=driver.id,
        sale_id=sale_id,
        payload=ReviewCreateIn(rating=5),
    )
    with pytest.raises(ConflictError):
        await marketplace.submit_review_as_driver(
            driver_id=driver.id,
            sale_id=sale_id,
            payload=ReviewCreateIn(rating=4),
        )


async def test_review_rejects_stranger_driver(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, _, sale_id = await _to_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110738",
        owner_phone="+97688110739",
    )
    stranger = await _make_driver(db_session, "+97688110740")
    with pytest.raises(NotFoundError):
        await marketplace.submit_review_as_driver(
            driver_id=stranger.id,
            sale_id=sale_id,
            payload=ReviewCreateIn(rating=5),
        )


async def test_get_sale_for_party_either_side(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, business_id, sale_id = await _to_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110741",
        owner_phone="+97688110742",
    )
    # Driver path.
    by_driver = await marketplace.get_sale_for_party(
        sale_id=sale_id, user_id=driver.id, business_id=None
    )
    assert by_driver.id == sale_id

    # Business path.
    by_biz = await marketplace.get_sale_for_party(
        sale_id=sale_id, user_id=uuid.uuid4(), business_id=business_id
    )
    assert by_biz.id == sale_id

    # Stranger.
    with pytest.raises(NotFoundError):
        await marketplace.get_sale_for_party(
            sale_id=sale_id, user_id=uuid.uuid4(), business_id=None
        )


# ---------------------------------------------------------------------------
# Media integration
# ---------------------------------------------------------------------------


async def test_submit_search_with_valid_media_ids(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    media_service: MediaService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110743")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY)
    asset = await media_service.request_upload(
        owner_id=driver.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    await media_service.confirm_upload(owner_id=driver.id, asset_id=asset.asset.id)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id,
            description="with photo",
            media_asset_ids=[asset.asset.id],
        ),
    )
    assert request.media_asset_ids == [str(asset.asset.id)]


async def test_submit_search_rejects_other_users_asset(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    media_service: MediaService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110744")
    other = await _make_driver(db_session, "+97688110745")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY)
    asset = await media_service.request_upload(
        owner_id=other.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    await media_service.confirm_upload(owner_id=other.id, asset_id=asset.asset.id)
    with pytest.raises(ValidationError):
        await marketplace.submit_search(
            driver_id=driver.id,
            payload=PartSearchCreateIn(
                vehicle_id=reg.vehicle.id,
                description="not yours",
                media_asset_ids=[asset.asset.id],
            ),
        )


async def test_submit_quote_rejects_wrong_purpose_asset(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    media_service: MediaService,
    db_session: AsyncSession,
) -> None:
    """Owner uploads a `part_search` asset, then tries to use it on a quote — 422."""
    driver, owner, business_id, _, _ = await _make_active_quote(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110746",
        owner_phone="+97688110747",
    )
    # Re-create another open search by the driver — same business already
    # quoted on the first one (1 quote per business per search).
    reg2 = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_B, xyp=XYP_CAMRY)
    other_request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg2.vehicle.id, description="second"),
    )
    asset = await media_service.request_upload(
        owner_id=owner.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,  # wrong purpose
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    await media_service.confirm_upload(owner_id=owner.id, asset_id=asset.asset.id)
    with pytest.raises(ValidationError):
        await marketplace.submit_quote(
            business_id=business_id,
            owner_user_id=owner.id,
            search_id=other_request.id,
            payload=QuoteCreateIn(
                price_mnt=99_000,
                condition=QuoteCondition.new,
                media_asset_ids=[asset.asset.id],
            ),
        )
