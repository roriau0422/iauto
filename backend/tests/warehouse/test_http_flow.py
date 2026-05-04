"""HTTP-level regression tests for the warehouse routes.

These guard the response-serialization path that pure service-level
tests miss — `PATCH /v1/warehouse/skus/{id}` blew up at runtime with
`MissingGreenlet` when SQLAlchemy lazy-loaded `updated_at` after the
service's flush. The fix is `await session.refresh(sku)`; this test
locks it in.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import BusinessMemberRole
from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.dependencies import get_redis_dep
from app.identity.models import User, UserRole
from app.main import create_app
from app.marketplace.models import QuoteCondition
from app.platform.db import get_session
from app.warehouse.schemas import SkuCreateIn
from app.warehouse.service import WarehouseService

PHONE = "+97688118801"


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


async def _bootstrap_business_and_login(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[str, str]:
    """Create a business owner via the service layer + log them in over
    HTTP. Returns `(access_token, business_id)`.
    """
    owner = User(phone=PHONE, role=UserRole.business)
    db_session.add(owner)
    await db_session.flush()
    biz_service = BusinessesService(session=db_session)
    business = await biz_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="HTTP Shop")
    )

    r = await client.post("/v1/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    r = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": PHONE,
            "code": code,
            "device": {"platform": "ios", "label": "pytest"},
            "role": "business",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"], str(business.id)


async def test_patch_sku_returns_serialized_response(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, business_id = await _bootstrap_business_and_login(client, db_session)
    auth = {"Authorization": f"Bearer {token}"}

    warehouse = WarehouseService(session=db_session)
    sku = await warehouse.create_sku(
        tenant_id=__import__("uuid").UUID(business_id),
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(
            sku_code="HTTP-PATCH-1",
            display_name="Initial",
            condition=QuoteCondition.new,
        ),
    )
    await db_session.commit()

    r = await client.patch(
        f"/v1/warehouse/skus/{sku.id}",
        headers=auth,
        json={"unit_price_mnt": 99_000, "display_name": "Renamed"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Renamed"
    assert body["unit_price_mnt"] == 99_000
    # `updated_at` carries `onupdate=func.now()`, so flush expires it.
    # If the service returns `sku` without refresh, Pydantic triggers a
    # lazy load on a closed greenlet and the response 500s. The
    # presence of an `updated_at` field in the body locks in the fix.
    assert body["updated_at"] is not None
