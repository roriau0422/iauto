"""Service-level tests for the catalog context."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import CatalogService, slugify

# ---------------------------------------------------------------------------
# slugify — pure function tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Toyota", "toyota"),
        ("TOYOTA", "toyota"),
        ("  toyota  ", "toyota"),
        ("Mercedes-Benz", "mercedesbenz"),
        ("Land Rover", "landrover"),
        ("Range Rover", "rangerover"),
        ("Model 3", "model3"),
        ("CR-V", "crv"),
        ("BMW", "bmw"),
        ("", ""),
        ("---", ""),
    ],
)
def test_slugify_is_deterministic(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_slugify_is_idempotent() -> None:
    assert slugify(slugify("Mercedes-Benz")) == slugify("Mercedes-Benz")


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


@pytest.fixture
def service(db_session: AsyncSession) -> CatalogService:
    return CatalogService(db_session)


async def test_list_countries_returns_seeded_rows(
    service: CatalogService,
) -> None:
    rows = await service.list_countries()
    codes = [r.code for r in rows]
    assert "JP" in codes
    assert "DE" in codes
    assert "KR" in codes
    # Japan must sort first — Mongolian market context.
    assert codes[0] == "JP"


async def test_list_brands_unfiltered(service: CatalogService) -> None:
    rows = await service.list_brands()
    slugs = {r.slug for r in rows}
    assert {"toyota", "hyundai", "mercedesbenz", "bmw"} <= slugs


async def test_list_brands_filtered_by_country(
    service: CatalogService,
) -> None:
    countries = await service.list_countries()
    japan = next(c for c in countries if c.code == "JP")
    japan_brands = await service.list_brands(country_id=japan.id)
    slugs = {b.slug for b in japan_brands}
    assert "toyota" in slugs
    assert "lexus" in slugs
    # German brand must NOT leak through.
    assert "bmw" not in slugs


async def test_list_models_filtered_by_brand(
    service: CatalogService,
) -> None:
    brands = await service.list_brands()
    toyota = next(b for b in brands if b.slug == "toyota")
    models = await service.list_models(brand_id=toyota.id)
    slugs = {m.slug for m in models}
    assert "prius" in slugs
    assert "landcruiser" in slugs
    assert "camry" in slugs


# ---------------------------------------------------------------------------
# Resolution — the hot path called during vehicle registration
# ---------------------------------------------------------------------------


async def test_resolve_exact_brand_and_model(
    service: CatalogService,
) -> None:
    resolved = await service.resolve_brand_model(make="Toyota", model="Prius")
    assert resolved.brand_id is not None
    assert resolved.model_id is not None


async def test_resolve_case_insensitive(service: CatalogService) -> None:
    resolved = await service.resolve_brand_model(make="TOYOTA", model="PRIUS")
    assert resolved.brand_id is not None
    assert resolved.model_id is not None


async def test_resolve_mercedes_benz_dash_variant(
    service: CatalogService,
) -> None:
    """`Mercedes-Benz` and `mercedes benz` both slugify to `mercedesbenz`."""
    r1 = await service.resolve_brand_model(make="Mercedes-Benz", model=None)
    r2 = await service.resolve_brand_model(make="mercedes benz", model=None)
    assert r1.brand_id is not None
    assert r1.brand_id == r2.brand_id


async def test_resolve_unknown_brand_returns_none(
    service: CatalogService,
) -> None:
    resolved = await service.resolve_brand_model(make="BrandThatDoesNotExist", model="Whatever")
    assert resolved.brand_id is None
    assert resolved.model_id is None


async def test_resolve_known_brand_unknown_model(
    service: CatalogService,
) -> None:
    """Brand matches but model does not — return brand_id, None model_id."""
    resolved = await service.resolve_brand_model(make="Toyota", model="ModelThatDoesNotExist")
    assert resolved.brand_id is not None
    assert resolved.model_id is None


async def test_resolve_with_none_inputs(service: CatalogService) -> None:
    resolved = await service.resolve_brand_model(make=None, model=None)
    assert resolved.brand_id is None
    assert resolved.model_id is None


async def test_resolve_model_scoped_to_brand(
    service: CatalogService,
) -> None:
    """`k5` belongs to Kia; must not resolve under Toyota."""
    resolved = await service.resolve_brand_model(make="Toyota", model="K5")
    assert resolved.brand_id is not None  # Toyota matches
    assert resolved.model_id is None  # K5 does not exist inside Toyota
