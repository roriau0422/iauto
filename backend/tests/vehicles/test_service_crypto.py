"""Encryption-specific tests for the vehicles context.

The existing `test_service.py` already exercises VIN dedup and plate
handling end-to-end; this file adds assertions that are only meaningful
*after* the encryption swap (plaintext columns gone, ciphertext present,
raw_xyp still holds plaintext as a known gap).
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import Settings
from app.vehicles.models import Vehicle
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService

PLATE = "9987УБӨ"

XYP = XypPayloadIn(
    markName="Toyota",
    modelName="Prius",
    buildYear=2014,
    cabinNumber="JTDKN3DU5E1812345",
    motorNumber="2ZR-1234567",
    colorName="Silver",
    capacity=1800,
)


@pytest.fixture
def service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> VehiclesService:
    return VehiclesService(session=db_session, redis=redis, sms=sms, settings=settings)


async def _make_user(db_session: AsyncSession) -> User:
    user = User(phone="+97688111000", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_vehicle_plaintext_columns_are_gone(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'vehicles' AND column_name IN ('vin', 'plate')"
        )
    )
    assert result.first() is None


async def test_register_populates_cipher_and_search(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    result = await service.register_from_xyp(user_id=user.id, plate=PLATE, xyp=XYP)

    # Round-trip through the property.
    assert result.vehicle.vin == "JTDKN3DU5E1812345"
    assert result.vehicle.plate == PLATE

    # Direct column access must show encrypted bytes, not plaintext.
    row = (
        (await db_session.execute(select(Vehicle).where(Vehicle.id == result.vehicle.id)))
        .scalars()
        .one()
    )
    assert row.vin_cipher is not None
    assert len(row.vin_cipher) > 20
    assert row.vin_search is not None
    assert len(row.vin_search) == 64
    assert row.plate_cipher is not None
    assert len(row.plate_cipher) > 20


async def test_vin_dedup_still_works_via_blind_index(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user_a = await _make_user(db_session)
    user_b = User(phone="+97688111001", role=UserRole.driver)
    db_session.add(user_b)
    await db_session.flush()

    r1 = await service.register_from_xyp(user_id=user_a.id, plate=PLATE, xyp=XYP)
    r2 = await service.register_from_xyp(user_id=user_b.id, plate=PLATE, xyp=XYP)
    assert r1.vehicle.id == r2.vehicle.id  # same physical car

    # Exactly one row in vehicles.
    rows = (await db_session.execute(select(Vehicle))).scalars().all()
    assert len(rows) == 1


async def test_raw_xyp_still_contains_plaintext_vin_known_gap(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    """Documented gap: vehicles.raw_xyp (JSONB) is NOT encrypted.

    Encrypting JSONB is a follow-up project tracked in ARCHITECTURE.md. This
    test pins the current behavior so that if/when raw_xyp is encrypted,
    whoever makes the change also updates this assertion — avoids silent
    drift.
    """
    user = await _make_user(db_session)
    result = await service.register_from_xyp(user_id=user.id, plate=PLATE, xyp=XYP)
    row = (
        await db_session.execute(select(Vehicle).where(Vehicle.id == result.vehicle.id))
    ).scalar_one()
    assert row.raw_xyp is not None
    assert row.raw_xyp.get("cabinNumber") == "JTDKN3DU5E1812345"


async def test_plate_cipher_is_non_deterministic(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    u1 = await _make_user(db_session)
    u2 = User(phone="+97688111002", role=UserRole.driver)
    db_session.add(u2)
    await db_session.flush()

    xyp_a = XYP.model_copy(update={"cabinNumber": "AAAAAAAAAAAAAAAAA"})
    xyp_b = XYP.model_copy(update={"cabinNumber": "BBBBBBBBBBBBBBBBB"})

    await service.register_from_xyp(user_id=u1.id, plate=PLATE, xyp=xyp_a)
    await service.register_from_xyp(user_id=u2.id, plate=PLATE, xyp=xyp_b)

    rows = (await db_session.execute(select(Vehicle))).scalars().all()
    plate_ciphers = [bytes(r.plate_cipher) for r in rows]
    assert len(plate_ciphers) == 2
    # Both rows have the same plaintext plate but must store different
    # ciphertexts (Fernet embeds a random IV per encryption).
    assert plate_ciphers[0] != plate_ciphers[1]
    # And both round-trip to the same plaintext.
    assert {r.plate for r in rows} == {PLATE}
