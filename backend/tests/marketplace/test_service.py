"""Service-level tests for the marketplace context (session 4 slice)."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.marketplace.models import PartSearchRequest, PartSearchStatus
from app.marketplace.schemas import PartSearchCreateIn
from app.marketplace.service import MarketplaceService
from app.platform.config import Settings
from app.platform.errors import ConflictError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService

PLATE_A = "9987УБӨ"
PLATE_B = "1234УБА"

XYP_PRIUS = XypPayloadIn(
    markName="Toyota",
    modelName="Prius",
    buildYear=2014,
    cabinNumber="JTDKN3DU5E1812345",
    colorName="Silver",
    capacity=1800,
    wheelPosition="Зүүн",
)


@pytest.fixture
def marketplace(db_session: AsyncSession) -> MarketplaceService:
    return MarketplaceService(session=db_session)


@pytest.fixture
def vehicles_service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> VehiclesService:
    return VehiclesService(session=db_session, redis=redis, sms=sms, settings=settings)


async def _make_driver(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_submit_search_happy_path_writes_outbox_event(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110301")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
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
    submitted = [
        e for e in events if e.event_type == "marketplace.part_search_submitted"
    ]
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
    reg = await vehicles_service.register_from_xyp(
        user_id=owner.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
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
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    first = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id, description="first"
        ),
    )
    await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id, description="second"
        ),
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
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id, description="cancel me"
        ),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)

    refreshed = await db_session.get(PartSearchRequest, request.id)
    assert refreshed is not None
    assert refreshed.status == PartSearchStatus.cancelled

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    cancelled = [
        e for e in events if e.event_type == "marketplace.part_search_cancelled"
    ]
    assert len(cancelled) == 1


async def test_cancel_rejects_stranger(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_driver(db_session, "+97688110307")
    stranger = await _make_driver(db_session, "+97688110308")
    reg = await vehicles_service.register_from_xyp(
        user_id=owner.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    request = await marketplace.submit_search(
        driver_id=owner.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id, description="not yours"
        ),
    )
    with pytest.raises(NotFoundError):
        await marketplace.cancel(driver_id=stranger.id, search_id=request.id)


async def test_cancel_twice_is_a_conflict(
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110309")
    reg = await vehicles_service.register_from_xyp(
        user_id=driver.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(
            vehicle_id=reg.vehicle.id, description="double-cancel"
        ),
    )
    await marketplace.cancel(driver_id=driver.id, search_id=request.id)
    with pytest.raises(ConflictError):
        await marketplace.cancel(driver_id=driver.id, search_id=request.id)
