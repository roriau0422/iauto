"""Service-level tests for the vehicles context."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import Settings
from app.platform.errors import ForbiddenError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.alerts import SMS_BODY_MAX
from app.vehicles.models import (
    Vehicle,
    VehicleOwnership,
    VerificationSource,
)
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService

PLATE_A = "9987УБӨ"
PLATE_B = "1234УБА"

XYP_PRIUS = XypPayloadIn(
    markName="Toyota",
    modelName="Prius",
    buildYear=2014,
    cabinNumber="JTDKN3DU5E1812345",
    motorNumber="2ZR-1234567",
    colorName="Silver",
    capacity=1800,
)

XYP_LANDCRUISER = XypPayloadIn(
    markName="Toyota",
    modelName="Land Cruiser 200",
    buildYear="2018",         # upstream sometimes stringy
    cabinNumber="JTMHV05J604123456",
    motorNumber="1VD-FTV-999",
    colorName="Black",
    capacity="4500",
)

XYP_NO_VIN = XypPayloadIn(
    markName="UAZ",
    modelName="Hunter",
    buildYear=2005,
    cabinNumber=None,
    motorNumber=None,
    colorName="Green",
    capacity=2700,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> VehiclesService:
    return VehiclesService(
        session=db_session, redis=redis, sms=sms, settings=settings
    )


async def _make_user(
    db_session: AsyncSession, phone: str = "+97688110001"
) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_register_new_vin_creates_vehicle_and_ownership(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    result = await service.register_from_xyp(
        user_id=user.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    assert result.was_new_vehicle is True
    assert result.already_owned is False
    assert result.vehicle.vin == "JTDKN3DU5E1812345"
    assert result.vehicle.make == "Toyota"
    assert result.vehicle.model == "Prius"
    assert result.vehicle.build_year == 2014
    assert result.vehicle.verification_source == VerificationSource.xyp_public

    ownerships = (await db_session.execute(select(VehicleOwnership))).scalars().all()
    assert len(ownerships) == 1
    assert ownerships[0].user_id == user.id

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    event_types = {e.event_type for e in events}
    assert "vehicles.vehicle_registered" in event_types
    assert "vehicles.ownership_added" in event_types


async def test_register_existing_vin_reuses_vehicle_and_adds_ownership(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user_a = await _make_user(db_session, phone="+97688110001")
    user_b = await _make_user(db_session, phone="+97688110002")

    await service.register_from_xyp(
        user_id=user_a.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    result_b = await service.register_from_xyp(
        user_id=user_b.id, plate=PLATE_A, xyp=XYP_PRIUS
    )

    assert result_b.was_new_vehicle is False
    assert result_b.already_owned is False
    # Still only one row in vehicles — dedup worked.
    vehicles = (await db_session.execute(select(Vehicle))).scalars().all()
    assert len(vehicles) == 1
    ownerships = (await db_session.execute(select(VehicleOwnership))).scalars().all()
    assert {o.user_id for o in ownerships} == {user_a.id, user_b.id}

    # vehicle_registered fires exactly once, ownership_added fires twice.
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    registered = [e for e in events if e.event_type == "vehicles.vehicle_registered"]
    owned = [e for e in events if e.event_type == "vehicles.ownership_added"]
    assert len(registered) == 1
    assert len(owned) == 2


async def test_register_twice_same_user_is_idempotent(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    await service.register_from_xyp(
        user_id=user.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    result2 = await service.register_from_xyp(
        user_id=user.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    assert result2.already_owned is True

    ownerships = (await db_session.execute(select(VehicleOwnership))).scalars().all()
    assert len(ownerships) == 1


async def test_null_vin_always_creates_new_vehicle(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    r1 = await service.register_from_xyp(
        user_id=user.id, plate=PLATE_A, xyp=XYP_NO_VIN
    )
    r2 = await service.register_from_xyp(
        user_id=user.id, plate=PLATE_B, xyp=XYP_NO_VIN
    )
    assert r1.was_new_vehicle is True
    assert r2.was_new_vehicle is True
    vehicles = (await db_session.execute(select(Vehicle))).scalars().all()
    assert len(vehicles) == 2
    assert all(v.vin is None for v in vehicles)


# ---------------------------------------------------------------------------
# List / unregister
# ---------------------------------------------------------------------------


async def test_list_for_user_returns_only_owned_vehicles(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user_a = await _make_user(db_session, phone="+97688110011")
    user_b = await _make_user(db_session, phone="+97688110012")

    await service.register_from_xyp(
        user_id=user_a.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    await service.register_from_xyp(
        user_id=user_b.id, plate=PLATE_B, xyp=XYP_LANDCRUISER
    )

    a_list = await service.list_for_user(user_a.id)
    b_list = await service.list_for_user(user_b.id)
    assert {v.vin for v in a_list} == {XYP_PRIUS.cabinNumber}
    assert {v.vin for v in b_list} == {XYP_LANDCRUISER.cabinNumber}


async def test_unregister_drops_ownership_but_keeps_vehicle(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user_a = await _make_user(db_session, phone="+97688110021")
    user_b = await _make_user(db_session, phone="+97688110022")

    r = await service.register_from_xyp(
        user_id=user_a.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    await service.register_from_xyp(
        user_id=user_b.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    await service.unregister(user_id=user_a.id, vehicle_id=r.vehicle.id)

    remaining = (
        await db_session.execute(select(VehicleOwnership))
    ).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].user_id == user_b.id

    # The vehicle itself still exists for user_b.
    assert await service.vehicles.get_by_id(r.vehicle.id) is not None


async def test_unregister_rejects_non_owner(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user_a = await _make_user(db_session, phone="+97688110031")
    user_stranger = await _make_user(db_session, phone="+97688110032")
    r = await service.register_from_xyp(
        user_id=user_a.id, plate=PLATE_A, xyp=XYP_PRIUS
    )
    with pytest.raises(ForbiddenError):
        await service.unregister(
            user_id=user_stranger.id, vehicle_id=r.vehicle.id
        )


async def test_unregister_unknown_vehicle_raises(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    with pytest.raises(NotFoundError):
        await service.unregister(user_id=user.id, vehicle_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Lookup plan + failure reporting + SMS alerting
# ---------------------------------------------------------------------------


async def test_get_active_plan_returns_seeded_row(
    service: VehiclesService,
) -> None:
    plan = await service.get_active_plan()
    assert plan.is_active is True
    assert "smartcar.mn" in plan.endpoint_url
    assert plan.service_code == "WS100401_getVehicleInfo"
    assert "User-Agent" in plan.headers
    # Error signatures ship in the plan so the mobile client can classify
    # smartcar's text-body 400s as user input errors instead of outages.
    signatures = plan.expected.get("error_signatures") or []
    not_found = next(
        (s for s in signatures if s.get("category") == "not_found"), None
    )
    assert not_found is not None, "not_found signature missing from plan"
    assert not_found["match"]["status"] == 400
    assert "олдсонгүй" in not_found["match"]["body_contains_any"]
    assert not_found["alert_operator"] is False
    assert not_found["client_message_mn"]


async def test_record_lookup_failure_fires_sms_first_time(
    service: VehiclesService,
    sms: InMemorySmsProvider,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    # Point the operator phone at a known test value via settings, which is
    # already +97688110921 from .env. The InMemorySmsProvider records the
    # send target and body.
    user = await _make_user(db_session)
    result = await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=503,
        error_snippet="gateway timeout",
        plan_version="2026-04-15.1",
    )
    assert result.alert.fired is True
    assert result.alert.window_count == 1
    assert result.alert.operator_notified is True
    assert len(sms.sent) == 1
    to, body = sms.sent[0]
    assert to == settings.operator_phone
    assert "XYP failing" in body
    assert "5xx" in body
    assert "****УБӨ" in body
    assert len(body) <= SMS_BODY_MAX


async def test_alert_coalesces_within_window(
    service: VehiclesService,
    sms: InMemorySmsProvider,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    for _ in range(5):
        await service.record_lookup_failure(
            user_id=user.id,
            plate=PLATE_A,
            status_code=503,
            error_snippet=None,
            plan_version="2026-04-15.1",
        )
    # Only one SMS despite five failures.
    assert len(sms.sent) == 1
    # ... but the last report should report window_count=5.
    final = await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=503,
        error_snippet=None,
        plan_version="2026-04-15.1",
    )
    assert final.alert.fired is False
    assert final.alert.window_count == 6


async def test_not_found_report_is_recorded_but_does_not_alert(
    service: VehiclesService,
    sms: InMemorySmsProvider,
    db_session: AsyncSession,
) -> None:
    """smartcar returns HTTP 400 + raw text like
    `0000ЖХУ дугаартай тээврийн хэрэгслийн мэдээлэл олдсонгүй` when a plate
    doesn't exist. That's a user typo, not a gateway outage, and must never
    page the operator — but we still record the report row and the event.
    """
    user = await _make_user(db_session)
    result = await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_B,
        status_code=400,
        error_snippet=(
            "1234УБА дугаартай тээврийн хэрэгслийн мэдээлэл олдсонгүй"
        ),
        plan_version="2026-04-15.1",
    )
    assert result.alert.fired is False
    assert result.alert.operator_notified is False
    assert len(sms.sent) == 0

    # The report + event are still persisted for audit.
    events = (
        await db_session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "vehicles.lookup_failed"
            )
        )
    ).scalars().all()
    assert len(events) == 1


async def test_generic_400_without_not_found_text_still_alerts(
    service: VehiclesService,
    sms: InMemorySmsProvider,
    db_session: AsyncSession,
) -> None:
    """A 400 that does NOT match the not-found signature is treated as a
    real outage candidate and pages the operator."""
    user = await _make_user(db_session)
    result = await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=400,
        error_snippet="Bad Request: schema mismatch",
        plan_version="2026-04-15.1",
    )
    assert result.alert.fired is True
    assert result.alert.operator_notified is True
    assert len(sms.sent) == 1


async def test_different_status_buckets_alert_independently(
    service: VehiclesService,
    sms: InMemorySmsProvider,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=503,
        error_snippet=None,
        plan_version=None,
    )
    await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=429,
        error_snippet=None,
        plan_version=None,
    )
    assert len(sms.sent) == 2
    bodies = [b for _, b in sms.sent]
    assert any("5xx" in b for b in bodies)
    assert any("429" in b for b in bodies)


async def test_report_emits_lookup_failed_event(
    service: VehiclesService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    await service.record_lookup_failure(
        user_id=user.id,
        plate=PLATE_A,
        status_code=502,
        error_snippet=None,
        plan_version="2026-04-15.1",
    )
    events = (
        await db_session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "vehicles.lookup_failed"
            )
        )
    ).scalars().all()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["status_code"] == 502
    assert payload["plate_masked"] == "****УБӨ"
    assert payload["plan_version"] == "2026-04-15.1"
