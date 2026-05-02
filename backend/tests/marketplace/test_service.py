"""Service-level tests for the marketplace context (sessions 4 + 5)."""

from __future__ import annotations

import uuid

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
from app.marketplace.models import PartSearchRequest, PartSearchStatus, QuoteCondition
from app.marketplace.schemas import PartSearchCreateIn, QuoteCreateIn
from app.marketplace.service import MarketplaceService
from app.media.service import MediaService
from app.platform.config import Settings
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.models import SteeringSide
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from tests.media.test_service import BUCKET, FakeMediaClient

PLATE_A = "9987УБӨ"
PLATE_B = "1234УБА"
PLATE_C = "5555УБС"
PLATE_D = "6677УБД"

XYP_PRIUS = XypPayloadIn(
    markName="Toyota",
    modelName="Prius",
    buildYear=2014,
    cabinNumber="JTDKN3DU5E1812345",
    colorName="Silver",
    capacity=1800,
    wheelPosition="Зүүн",
)

# Toyota Camry, 2020, LHD — matches restrictive coverage (year >= 2015, LHD).
XYP_CAMRY_2020 = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU111111",
    colorName="White",
    capacity=2500,
    wheelPosition="Зүүн",
)

# Toyota Land Cruiser, 2010, RHD — too old for a 2015+ filter, wrong steering.
XYP_LC_2010_RHD = XypPayloadIn(
    markName="Toyota",
    modelName="Land Cruiser",
    buildYear=2010,
    cabinNumber="JTMHY05J804222222",
    colorName="Black",
    capacity=4700,
    wheelPosition="Баруун",
)

# Hyundai Sonata — a different brand than Toyota.
XYP_SONATA = XypPayloadIn(
    markName="Hyundai",
    modelName="Sonata",
    buildYear=2019,
    cabinNumber="KMHE34L35KA333333",
    colorName="Grey",
    capacity=2000,
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


async def _brand_id(db_session: AsyncSession, slug: str) -> uuid.UUID:
    result = await db_session.execute(select(VehicleBrand.id).where(VehicleBrand.slug == slug))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Session 4: driver-side RFQ
# ---------------------------------------------------------------------------


async def test_submit_search_happy_path_writes_outbox_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110301")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS)
    result = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id,
            description="Front-left brake pad for Prius 30",
            media_urls=[],
        ),
    )
    assert result.driver_id == driver.id
    assert result.vehicle_id == reg.vehicle.id
    assert result.status == PartSearchStatus.open

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    submitted = [e for e in events if e.event_type == "marketplace.part_search_submitted"]
    assert len(submitted) == 1
    assert submitted[0].payload["driver_id"] == str(driver.id)
    assert submitted[0].payload["vehicle_brand_id"] is not None  # catalog resolved


async def test_submit_search_rejects_vehicle_not_owned(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_driver(db_session, "+97688110302")
    stranger = await _make_driver(db_session, "+97688110303")
    reg = await vehicles_service.register_from_xyp(user_id=owner.id, plate=PLATE_A, xyp=XYP_PRIUS)
    with pytest.raises(NotFoundError):
        await marketplace.submit_search(
            driver_id=stranger.id,
            payload=PartSearchCreateIn(
                vehicle_id=reg.vehicle.id,
                description="whatever",
            ),
        )


async def test_submit_search_rejects_unknown_vehicle_id(
    marketplace: MarketplaceService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110304")
    with pytest.raises(NotFoundError):
        await marketplace.submit_search(
            driver_id=driver.id,
            payload=PartSearchCreateIn(
                vehicle_id=uuid.uuid4(),
                description="whatever",
            ),
        )


async def test_list_for_driver_filters_by_status(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110305")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS)
    first = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="first"),
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="second"),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=first.id)

    all_result = await marketplace.list_for_driver(
        driver_id=driver.id, status=None, limit=20, offset=0
    )
    assert all_result.total == 2

    open_result = await marketplace.list_for_driver(
        driver_id=driver.id,
        status=PartSearchStatus.open,
        limit=20,
        offset=0,
    )
    assert open_result.total == 1
    assert open_result.items[0].status == PartSearchStatus.open

    cancelled_result = await marketplace.list_for_driver(
        driver_id=driver.id,
        status=PartSearchStatus.cancelled,
        limit=20,
        offset=0,
    )
    assert cancelled_result.total == 1


async def test_cancel_transitions_status_and_emits_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110306")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="cancel me"),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)

    refreshed = await db_session.get(PartSearchRequest, request.id)
    assert refreshed is not None
    assert refreshed.status == PartSearchStatus.cancelled

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    cancelled = [e for e in events if e.event_type == "marketplace.part_search_cancelled"]
    assert len(cancelled) == 1


async def test_cancel_rejects_stranger(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_driver(db_session, "+97688110307")
    stranger = await _make_driver(db_session, "+97688110308")
    reg = await vehicles_service.register_from_xyp(user_id=owner.id, plate=PLATE_A, xyp=XYP_PRIUS)
    request = await marketplace.submit_search(
        driver_id=owner.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="not yours"),
    )
    with pytest.raises(NotFoundError):
        await marketplace.cancel(driver_id=stranger.id, search_id=request.id)


async def test_cancel_twice_is_a_conflict(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110309")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="double-cancel"),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)
    with pytest.raises(ConflictError):
        await marketplace.cancel(driver_id=driver.id, search_id=request.id)


# ---------------------------------------------------------------------------
# Session 5: incoming feed + quotes
# ---------------------------------------------------------------------------


async def test_list_incoming_returns_matching_searches(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    # Driver owns one Toyota and one Hyundai, submits one search per vehicle.
    driver = await _make_driver(db_session, "+97688110501")
    toyota_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    hyundai_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_B, xyp=XYP_SONATA
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=toyota_reg.vehicle.id, description="toyota part"),
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=hyundai_reg.vehicle.id, description="hyundai part"),
    )

    # Business covers only Toyota.
    owner = await _make_business_owner(db_session, "+97688110502")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Toyota Shop")
    )
    toyota_brand_id = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota_brand_id)],
    )

    result = await marketplace.list_incoming(business_id=business.id, limit=20, offset=0)
    assert result.total == 1
    assert result.items[0].description == "toyota part"


async def test_list_incoming_respects_year_range(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110503")
    # 2010 Toyota — should be filtered out by year_start=2015.
    old_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_C, xyp=XYP_LC_2010_RHD
    )
    # 2020 Toyota — should pass.
    new_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=old_reg.vehicle.id, description="old LC"),
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=new_reg.vehicle.id, description="new Camry"),
    )

    owner = await _make_business_owner(db_session, "+97688110504")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Modern Toyota Only")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(vehicle_brand_id=toyota, year_start=2015),
        ],
    )

    result = await marketplace.list_incoming(business_id=business.id, limit=20, offset=0)
    assert result.total == 1
    assert result.items[0].description == "new Camry"


async def test_list_incoming_respects_steering_side(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110505")
    rhd_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_C, xyp=XYP_LC_2010_RHD
    )
    lhd_reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=rhd_reg.vehicle.id, description="RHD LC"),
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=lhd_reg.vehicle.id, description="LHD Camry"),
    )

    owner = await _make_business_owner(db_session, "+97688110506")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="LHD Only")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(vehicle_brand_id=toyota, steering_side=SteeringSide.LHD),
        ],
    )

    result = await marketplace.list_incoming(business_id=business.id, limit=20, offset=0)
    assert result.total == 1
    assert result.items[0].description == "LHD Camry"


async def test_list_incoming_empty_coverage_returns_empty(
    marketplace: MarketplaceService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_business_owner(db_session, "+97688110507")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="No Coverage")
    )
    result = await marketplace.list_incoming(business_id=business.id, limit=20, offset=0)
    assert result.total == 0
    assert result.items == []


async def test_list_incoming_excludes_cancelled_searches(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110508")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="will cancel"),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)

    owner = await _make_business_owner(db_session, "+97688110509")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Active Only")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )

    result = await marketplace.list_incoming(business_id=business.id, limit=20, offset=0)
    assert result.total == 0


async def test_submit_quote_happy_path_emits_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110510")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="brake pads"),
    )

    owner = await _make_business_owner(db_session, "+97688110511")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )

    quote = await marketplace.submit_quote(
        business_id=business.id,
        owner_user_id=owner.id,
        search_id=request.id,
        payload=QuoteCreateIn(
            price_mnt=150_000,
            condition=QuoteCondition.new,
            notes="Original Toyota part in stock",
        ),
    )
    assert quote.tenant_id == business.id
    assert quote.part_search_id == request.id
    assert quote.price_mnt == 150_000
    assert quote.condition == QuoteCondition.new

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    sent = [e for e in events if e.event_type == "marketplace.quote_sent"]
    assert len(sent) == 1
    payload = sent[0].payload
    assert payload["part_search_id"] == str(request.id)
    assert payload["driver_id"] == str(driver.id)
    assert payload["price_mnt"] == 150_000
    assert payload["condition"] == "new"
    assert sent[0].tenant_id == business.id


async def test_submit_quote_rejects_non_open_search(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110512")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="cancel then quote"),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)

    owner = await _make_business_owner(db_session, "+97688110513")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )

    with pytest.raises(ConflictError):
        await marketplace.submit_quote(
            business_id=business.id,
            owner_user_id=owner.id,
            search_id=request.id,
            payload=QuoteCreateIn(price_mnt=1, condition=QuoteCondition.used),
        )


async def test_submit_quote_rejects_duplicate(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110514")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="no duplicates"),
    )

    owner = await _make_business_owner(db_session, "+97688110515")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )

    await marketplace.submit_quote(
        business_id=business.id,
        owner_user_id=owner.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=100, condition=QuoteCondition.new),
    )
    with pytest.raises(ConflictError):
        await marketplace.submit_quote(
            business_id=business.id,
            owner_user_id=owner.id,
            search_id=request.id,
            payload=QuoteCreateIn(price_mnt=200, condition=QuoteCondition.used),
        )


async def test_submit_quote_rejects_brand_outside_coverage(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110516")
    # Driver's vehicle is a Hyundai.
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_B, xyp=XYP_SONATA)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="hyundai part"),
    )

    # Business covers only Toyota.
    owner = await _make_business_owner(db_session, "+97688110517")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Toyota Only")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )

    with pytest.raises(ForbiddenError):
        await marketplace.submit_quote(
            business_id=business.id,
            owner_user_id=owner.id,
            search_id=request.id,
            payload=QuoteCreateIn(price_mnt=100, condition=QuoteCondition.new),
        )


async def test_submit_quote_rejects_year_out_of_range(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110518")
    # 2010 Land Cruiser.
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_C, xyp=XYP_LC_2010_RHD
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="old LC"),
    )

    owner = await _make_business_owner(db_session, "+97688110519")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="2015+")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota, year_start=2015)],
    )

    with pytest.raises(ForbiddenError):
        await marketplace.submit_quote(
            business_id=business.id,
            owner_user_id=owner.id,
            search_id=request.id,
            payload=QuoteCreateIn(price_mnt=100, condition=QuoteCondition.new),
        )


async def test_submit_quote_404_when_search_missing(
    marketplace: MarketplaceService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_business_owner(db_session, "+97688110520")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    with pytest.raises(NotFoundError):
        await marketplace.submit_quote(
            business_id=business.id,
            owner_user_id=owner.id,
            search_id=uuid.uuid4(),
            payload=QuoteCreateIn(price_mnt=100, condition=QuoteCondition.new),
        )


async def test_list_my_quotes_scopes_to_business(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110521")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    req1 = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="one"),
    )
    req2 = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="two"),
    )

    owner_a = await _make_business_owner(db_session, "+97688110522")
    biz_a = await businesses_service.create(
        owner=owner_a, payload=BusinessCreateIn(display_name="A")
    )
    owner_b = await _make_business_owner(db_session, "+97688110523")
    biz_b = await businesses_service.create(
        owner=owner_b, payload=BusinessCreateIn(display_name="B")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=biz_a, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    await businesses_service.replace_vehicle_coverage(
        business=biz_b, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )

    await marketplace.submit_quote(
        business_id=biz_a.id,
        owner_user_id=owner_a.id,
        search_id=req1.id,
        payload=QuoteCreateIn(price_mnt=111, condition=QuoteCondition.new),
    )
    await marketplace.submit_quote(
        business_id=biz_b.id,
        owner_user_id=owner_b.id,
        search_id=req1.id,
        payload=QuoteCreateIn(price_mnt=222, condition=QuoteCondition.used),
    )
    await marketplace.submit_quote(
        business_id=biz_a.id,
        owner_user_id=owner_a.id,
        search_id=req2.id,
        payload=QuoteCreateIn(price_mnt=333, condition=QuoteCondition.imported),
    )

    a_quotes = await marketplace.list_my_quotes(business_id=biz_a.id, limit=20, offset=0)
    b_quotes = await marketplace.list_my_quotes(business_id=biz_b.id, limit=20, offset=0)
    assert a_quotes.total == 2
    assert b_quotes.total == 1
    assert {q.price_mnt for q in a_quotes.items} == {111, 333}
    assert b_quotes.items[0].price_mnt == 222


async def test_list_quotes_for_search_driver_view(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110524")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="driver view"),
    )
    owner = await _make_business_owner(db_session, "+97688110525")
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _brand_id(db_session, "toyota")
    await businesses_service.replace_vehicle_coverage(
        business=business, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    await marketplace.submit_quote(
        business_id=business.id,
        owner_user_id=owner.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=99, condition=QuoteCondition.used),
    )

    result = await marketplace.list_quotes_for_search(
        driver_id=driver.id, search_id=request.id, limit=20, offset=0
    )
    assert result.total == 1
    assert result.items[0].price_mnt == 99


async def test_list_quotes_for_search_rejects_stranger(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner_driver = await _make_driver(db_session, "+97688110526")
    stranger = await _make_driver(db_session, "+97688110527")
    reg = await vehicles_service.register_from_xyp(
        user_id=owner_driver.id, plate=PLATE_A, xyp=XYP_CAMRY_2020
    )
    request = await marketplace.submit_search(
        driver_id=owner_driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="private"),
    )

    with pytest.raises(NotFoundError):
        await marketplace.list_quotes_for_search(
            driver_id=stranger.id, search_id=request.id, limit=20, offset=0
        )
