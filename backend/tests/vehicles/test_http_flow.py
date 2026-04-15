"""HTTP e2e tests for the vehicles endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.dependencies import get_redis_dep
from app.main import create_app
from app.platform.db import get_session

PHONE = "+97688110999"
PLATE = "9987УБӨ"

XYP_BODY = {
    "markName": "Toyota",
    "modelName": "Prius",
    "buildYear": 2014,
    "cabinNumber": "JTDKN3DU5E1812345",
    "motorNumber": "2ZR-1234567",
    "colorName": "Silver",
    "capacity": 1800,
}


@pytest_asyncio.fixture(loop_scope="session")
async def client(
    db_session: AsyncSession, redis: Redis
) -> AsyncIterator[AsyncClient]:
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


async def _login(client: AsyncClient) -> str:
    r = await client.post(
        "/v1/auth/otp/request", json={"phone": PHONE}
    )
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    r = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": PHONE,
            "code": code,
            "device": {"platform": "ios", "label": "pytest"},
        },
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def test_lookup_plan_is_public_and_cached(client: AsyncClient) -> None:
    r = await client.get("/v1/vehicles/lookup/plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_version"] == "2026-04-15.1"
    assert body["endpoint"]["url"].startswith("https://xyp-api.smartcar.mn")
    assert body["endpoint"]["headers"]["os"] == "web"
    assert r.headers.get("Cache-Control", "").startswith("public, max-age=")
    # The plan must ship the error-signature rules so the mobile client can
    # classify smartcar.mn text-body 400s as user input errors.
    signatures = body["expected"]["error_signatures"]
    assert any(s["category"] == "not_found" for s in signatures)


async def test_register_and_list_vehicle_round_trip(client: AsyncClient) -> None:
    access = await _login(client)
    auth = {"Authorization": f"Bearer {access}"}

    r = await client.post(
        "/v1/vehicles",
        headers=auth,
        json={"plate": PLATE, "xyp": XYP_BODY},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["was_new_vehicle"] is True
    assert body["already_owned"] is False
    vehicle_id = body["vehicle"]["id"]
    assert body["vehicle"]["make"] == "Toyota"
    assert body["vehicle"]["vin"] == "JTDKN3DU5E1812345"

    # List — should include the one we just registered.
    r = await client.get("/v1/vehicles", headers=auth)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(v["id"] == vehicle_id for v in items)

    # Delete.
    r = await client.delete(f"/v1/vehicles/{vehicle_id}", headers=auth)
    assert r.status_code == 200, r.text

    r = await client.get("/v1/vehicles", headers=auth)
    assert all(v["id"] != vehicle_id for v in r.json()["items"])


async def test_register_rejects_invalid_plate(client: AsyncClient) -> None:
    access = await _login(client)
    r = await client.post(
        "/v1/vehicles",
        headers={"Authorization": f"Bearer {access}"},
        json={"plate": "not-a-plate", "xyp": XYP_BODY},
    )
    assert r.status_code == 422


async def test_register_requires_auth(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/vehicles", json={"plate": PLATE, "xyp": XYP_BODY}
    )
    assert r.status_code == 401


async def test_report_endpoint_records_and_coalesces(
    client: AsyncClient,
) -> None:
    access = await _login(client)
    auth = {"Authorization": f"Bearer {access}"}

    # First failure → SMS fires.
    r = await client.post(
        "/v1/vehicles/lookup/report",
        headers=auth,
        json={
            "plate": PLATE,
            "status_code": 503,
            "error_snippet": "gateway timeout",
            "plan_version": "2026-04-15.1",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["alert_fired"] is True
    assert body["window_count"] == 1
    assert body["operator_notified"] is True

    # Second identical failure → coalesced, no new SMS.
    r2 = await client.post(
        "/v1/vehicles/lookup/report",
        headers=auth,
        json={
            "plate": PLATE,
            "status_code": 503,
            "error_snippet": "gateway timeout again",
            "plan_version": "2026-04-15.1",
        },
    )
    assert r2.status_code == 202, r2.text
    body2 = r2.json()
    assert body2["alert_fired"] is False
    assert body2["window_count"] == 2
    assert body2["operator_notified"] is False


async def test_report_validates_status_code(client: AsyncClient) -> None:
    access = await _login(client)
    r = await client.post(
        "/v1/vehicles/lookup/report",
        headers={"Authorization": f"Bearer {access}"},
        json={"plate": PLATE, "status_code": 99},
    )
    assert r.status_code == 422
