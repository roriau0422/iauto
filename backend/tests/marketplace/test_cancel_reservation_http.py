"""HTTP-level regression: POST /v1/marketplace/reservations/{id}/cancel
must serialize ReservationOut without a MissingGreenlet on `updated_at`.

Same bug class as warehouse.update_sku, businesses.update,
ads.pause/resume/activate, and media.confirm_upload."""

from __future__ import annotations

import base64
import json as _json
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.dependencies import get_redis_dep
from app.identity.models import User, UserRole
from app.main import create_app
from app.marketplace.models import (
    PartSearchRequest,
    PartSearchStatus,
    Quote,
    QuoteCondition,
    Reservation,
    ReservationStatus,
)
from app.platform.db import get_session
from app.vehicles.models import Vehicle, VehicleOwnership, VerificationSource


@pytest_asyncio.fixture(loop_scope="session")
async def client(db_session: AsyncSession, redis: Redis) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_redis() -> Redis:
        return redis

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_redis_dep] = _override_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


PHONE = "+97688118803"


async def _login_driver(client: AsyncClient) -> tuple[str, uuid.UUID]:
    r = await client.post("/v1/auth/otp/request", json={"phone": PHONE})
    code = r.json()["debug_code"]
    r = await client.post(
        "/v1/auth/otp/verify",
        json={"phone": PHONE, "code": code, "device": {"platform": "ios", "label": "pytest"}},
    )
    token = r.json()["access_token"]
    sub = _json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["sub"]
    return token, uuid.UUID(sub)


async def test_cancel_reservation_serializes_response(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Lock in the `await session.refresh(reservation)` after flush."""
    token, driver_id = await _login_driver(client)
    auth = {"Authorization": f"Bearer {token}"}

    # Bootstrap minimal world: business owner + business + vehicle + search +
    # quote + reservation tied to the driver.
    biz_owner = User(phone="+97688118899", role=UserRole.business)
    db_session.add(biz_owner)
    await db_session.flush()
    biz_service = BusinessesService(session=db_session)
    business = await biz_service.create(
        owner=biz_owner, payload=BusinessCreateIn(display_name="Cancel-Smoke Shop")
    )

    vehicle = Vehicle(
        vin=f"VIN-{uuid.uuid4().hex[:12]}",
        plate=f"TEST{uuid.uuid4().hex[:6]}",
        make="Toyota",
        model="Test",
        verification_source=VerificationSource.xyp_public,
    )
    db_session.add(vehicle)
    await db_session.flush()
    db_session.add(VehicleOwnership(user_id=driver_id, vehicle_id=vehicle.id))
    await db_session.flush()

    search = PartSearchRequest(
        driver_id=driver_id,
        vehicle_id=vehicle.id,
        description="Front-left brake pads",
        status=PartSearchStatus.open,
    )
    db_session.add(search)
    await db_session.flush()

    quote = Quote(
        tenant_id=business.id,
        part_search_id=search.id,
        price_mnt=200_000,
        condition=QuoteCondition.new,
    )
    db_session.add(quote)
    await db_session.flush()

    from datetime import UTC, datetime, timedelta

    reservation = Reservation(
        tenant_id=business.id,
        quote_id=quote.id,
        part_search_id=search.id,
        driver_id=driver_id,
        status=ReservationStatus.active,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(reservation)
    await db_session.flush()
    res_id = reservation.id
    await db_session.commit()

    r = await client.post(f"/v1/marketplace/reservations/{res_id}/cancel", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled"
    # `updated_at` carries `onupdate=func.now()` — its presence in the body
    # confirms the post-flush refresh worked.
    assert body["updated_at"] is not None
