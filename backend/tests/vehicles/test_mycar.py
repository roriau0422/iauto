"""My Car endpoints — service-history + tax/insurance/fines stubs."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import Settings
from app.platform.errors import NotFoundError
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService

PLATE = "9987УБӨ"


XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU888888",
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


async def _make_driver(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_service_history_returns_empty_for_owner(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110901")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    rows = await vehicles_service.list_service_history(user_id=driver.id, vehicle_id=reg.vehicle.id)
    assert rows == []


async def test_service_history_404_for_stranger(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110902")
    stranger = await _make_driver(db_session, "+97688110903")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    with pytest.raises(NotFoundError):
        await vehicles_service.list_service_history(user_id=stranger.id, vehicle_id=reg.vehicle.id)


async def test_service_history_404_for_unknown_vehicle(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110904")
    with pytest.raises(NotFoundError):
        await vehicles_service.list_service_history(user_id=driver.id, vehicle_id=uuid.uuid4())
