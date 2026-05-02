"""Service-history endpoints + PDF export."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import Settings
from app.platform.errors import NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.models import VehicleServiceLogKind
from app.vehicles.pdf import render_service_history_pdf
from app.vehicles.schemas import VehicleServiceLogCreateIn, XypPayloadIn
from app.vehicles.service import VehiclesService

PLATE = "9987УБӨ"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU222200",
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


async def test_add_and_list_service_log(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688112101")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    log = await vehicles_service.add_service_log(
        user_id=driver.id,
        vehicle_id=reg.vehicle.id,
        payload=VehicleServiceLogCreateIn(
            kind=VehicleServiceLogKind.oil,
            noted_at=datetime.now(UTC),
            title="Engine oil swap",
            note="5W-30 fully synthetic",
            mileage_km=85_000,
            cost_mnt=120_000,
            location="UB Auto Service",
        ),
    )
    assert log.kind == VehicleServiceLogKind.oil
    assert log.title == "Engine oil swap"

    rows = await vehicles_service.list_service_history(user_id=driver.id, vehicle_id=reg.vehicle.id)
    assert len(rows) == 1
    assert rows[0].id == log.id

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    logged = [e for e in events if e.event_type == "vehicles.service_logged"]
    assert len(logged) == 1


async def test_add_service_log_rejects_stranger(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688112102")
    stranger = await _make_driver(db_session, "+97688112103")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    with pytest.raises(NotFoundError):
        await vehicles_service.add_service_log(
            user_id=stranger.id,
            vehicle_id=reg.vehicle.id,
            payload=VehicleServiceLogCreateIn(
                kind=VehicleServiceLogKind.tire,
                noted_at=datetime.now(UTC),
            ),
        )


async def test_delete_service_log_owner_only(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688112104")
    stranger = await _make_driver(db_session, "+97688112105")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    log = await vehicles_service.add_service_log(
        user_id=driver.id,
        vehicle_id=reg.vehicle.id,
        payload=VehicleServiceLogCreateIn(
            kind=VehicleServiceLogKind.battery,
            noted_at=datetime.now(UTC),
        ),
    )
    with pytest.raises(NotFoundError):
        await vehicles_service.delete_service_log(
            user_id=stranger.id, vehicle_id=reg.vehicle.id, log_id=log.id
        )
    await vehicles_service.delete_service_log(
        user_id=driver.id, vehicle_id=reg.vehicle.id, log_id=log.id
    )
    rows = await vehicles_service.list_service_history(user_id=driver.id, vehicle_id=reg.vehicle.id)
    assert rows == []


async def test_delete_service_log_404_for_unknown(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688112106")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    with pytest.raises(NotFoundError):
        await vehicles_service.delete_service_log(
            user_id=driver.id, vehicle_id=reg.vehicle.id, log_id=uuid.uuid4()
        )


def test_pdf_renderer_produces_valid_pdf() -> None:
    """The renderer is pure — exercise it directly with synthetic data.

    A valid PDF byte stream starts with `%PDF-` and ends with the
    `%%EOF` marker. We don't validate the rendered content — just
    confirm the file shape is well-formed.
    """
    pdf = render_service_history_pdf(
        plate=PLATE,
        make="Toyota",
        model="Camry",
        logs=[],
    )
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-100:]
