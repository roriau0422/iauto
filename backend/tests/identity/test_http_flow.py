"""End-to-end HTTP flow through FastAPI for the identity vertical slice.

We run the real app with the real routes and only override the two platform
dependencies that would otherwise talk to the developer's main database and
Redis DB: `get_session` → transactional test session, `get_redis_dep` → the
dedicated test Redis DB (#15 via the `redis` fixture).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.dependencies import get_redis_dep
from app.main import create_app
from app.platform.db import get_session

PHONE = "+97688110921"


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


async def test_otp_flow_end_to_end(client: AsyncClient) -> None:
    # 1. request OTP
    resp = await client.post("/v1/auth/otp/request", json={"phone": PHONE})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["sent"] is True
    assert body["debug_code"] is not None
    code = body["debug_code"]

    # 2. verify
    resp = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": PHONE,
            "code": code,
            "device": {"platform": "ios", "label": "pytest"},
        },
    )
    assert resp.status_code == 200, resp.text
    pair = resp.json()
    access = pair["access_token"]
    refresh = pair["refresh_token"]
    assert pair["token_type"] == "Bearer"
    assert pair["user"]["phone"] == PHONE

    # 3. /v1/me with bearer
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["phone"] == PHONE

    # 4. /v1/me without bearer → 401
    resp = await client.get("/v1/me")
    assert resp.status_code == 401

    # 5. refresh rotation — same rotation rules as the service tests
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text
    new_pair = resp.json()
    assert new_pair["refresh_token"] != refresh

    # 6. logout
    resp = await client.post(
        "/v1/auth/logout",
        json={"refresh_token": new_pair["refresh_token"]},
    )
    assert resp.status_code == 200

    # Logged-out refresh token can no longer rotate.
    resp = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": new_pair["refresh_token"]},
    )
    assert resp.status_code == 401


async def test_request_otp_rejects_bad_phone(client: AsyncClient) -> None:
    resp = await client.post("/v1/auth/otp/request", json={"phone": "not a phone"})
    assert resp.status_code == 422


async def test_verify_otp_without_code_fails(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/auth/otp/verify",
        json={"phone": PHONE, "code": "123456"},
    )
    assert resp.status_code == 401  # no code was requested — AuthError
