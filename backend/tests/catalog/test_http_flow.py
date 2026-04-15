"""HTTP e2e tests for the catalog endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.platform.db import get_session


@pytest_asyncio.fixture(loop_scope="session")
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_countries(client: AsyncClient) -> None:
    r = await client.get("/v1/catalog/countries")
    assert r.status_code == 200
    items = r.json()["items"]
    codes = [c["code"] for c in items]
    assert "JP" in codes
    assert codes[0] == "JP"  # seeded sort_order puts Japan first
    # Cyrillic name round-trip should not get mangled.
    japan = next(c for c in items if c["code"] == "JP")
    assert japan["name_mn"] == "Япон"


async def test_list_brands_unfiltered(client: AsyncClient) -> None:
    r = await client.get("/v1/catalog/brands")
    assert r.status_code == 200
    slugs = {b["slug"] for b in r.json()["items"]}
    assert {"toyota", "hyundai", "bmw", "mercedesbenz"} <= slugs


async def test_list_brands_filter_by_country(client: AsyncClient) -> None:
    # Resolve Japan's id via the countries endpoint first.
    r = await client.get("/v1/catalog/countries")
    japan = next(c for c in r.json()["items"] if c["code"] == "JP")

    r = await client.get("/v1/catalog/brands", params={"country_id": japan["id"]})
    assert r.status_code == 200
    slugs = {b["slug"] for b in r.json()["items"]}
    assert "toyota" in slugs
    assert "bmw" not in slugs  # German, must not leak


async def test_list_models_filter_by_brand(client: AsyncClient) -> None:
    r = await client.get("/v1/catalog/brands")
    toyota = next(b for b in r.json()["items"] if b["slug"] == "toyota")

    r = await client.get("/v1/catalog/models", params={"brand_id": toyota["id"]})
    assert r.status_code == 200
    slugs = {m["slug"] for m in r.json()["items"]}
    assert "prius" in slugs
    assert "landcruiser" in slugs


async def test_brand_filter_with_bogus_country(client: AsyncClient) -> None:
    r = await client.get(
        "/v1/catalog/brands",
        params={"country_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_brand_filter_with_malformed_uuid(client: AsyncClient) -> None:
    r = await client.get("/v1/catalog/brands", params={"country_id": "not-a-uuid"})
    # Pydantic rejects malformed UUIDs with 422 before hitting the service.
    assert r.status_code == 422
