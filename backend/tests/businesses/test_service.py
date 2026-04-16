"""Service-level tests for the businesses context."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import (
    BusinessCreateIn,
    BusinessUpdateIn,
    VehicleBrandCoverageIn,
)
from app.businesses.service import BusinessesService
from app.catalog.models import VehicleBrand
from app.identity.models import User, UserRole
from app.platform.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.vehicles.models import SteeringSide


@pytest.fixture
def service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


async def _make_user(
    db_session: AsyncSession,
    *,
    phone: str,
    role: UserRole = UserRole.business,
) -> User:
    user = User(phone=phone, role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_happy_path(service: BusinessesService, db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, phone="+97688110100")
    business = await service.create(
        owner=owner,
        payload=BusinessCreateIn(
            display_name="Navi Market",
            description="Car parts for Toyota and Lexus",
            address="UB, Sukhbaatar district, 1st khoroo",
            contact_phone="+97688110200",
        ),
    )
    assert business.owner_id == owner.id
    assert business.display_name == "Navi Market"
    assert business.description is not None
    assert business.contact_phone == "+97688110200"


async def test_create_rejects_driver_role(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    driver = await _make_user(db_session, phone="+97688110101", role=UserRole.driver)
    with pytest.raises(ForbiddenError):
        await service.create(
            owner=driver,
            payload=BusinessCreateIn(display_name="Nope"),
        )


async def test_create_rejects_duplicate_profile(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110102")
    await service.create(owner=owner, payload=BusinessCreateIn(display_name="First"))
    with pytest.raises(ConflictError):
        await service.create(owner=owner, payload=BusinessCreateIn(display_name="Second"))


async def test_get_for_owner_404_when_missing(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110103")
    with pytest.raises(NotFoundError):
        await service.get_for_owner(owner)


async def test_update_applies_partial_change_and_preserves_others(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110104")
    await service.create(
        owner=owner,
        payload=BusinessCreateIn(
            display_name="Before",
            description="original",
            address="original address",
        ),
    )
    updated = await service.update(
        owner=owner,
        payload=BusinessUpdateIn(display_name="After"),
    )
    assert updated.display_name == "After"
    assert updated.description == "original"
    assert updated.address == "original address"


async def test_update_can_clear_contact_phone(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110105")
    await service.create(
        owner=owner,
        payload=BusinessCreateIn(
            display_name="ClearMe",
            contact_phone="+97688110106",
        ),
    )
    cleared = await service.update(
        owner=owner,
        payload=BusinessUpdateIn(contact_phone=None),
    )
    assert cleared.contact_phone is None
    assert cleared.contact_phone_cipher is None
    assert cleared.contact_phone_search is None


# ---------------------------------------------------------------------------
# Vehicle brand coverage
# ---------------------------------------------------------------------------


async def _pick_brand_ids(db_session: AsyncSession, slugs: list[str]) -> list[uuid.UUID]:
    result = await db_session.execute(
        select(VehicleBrand.id, VehicleBrand.slug).where(VehicleBrand.slug.in_(slugs))
    )
    mapping = {slug: bid for bid, slug in result.all()}
    # Preserve the caller's requested order so assertions stay stable.
    return [mapping[s] for s in slugs]


async def test_replace_vehicle_coverage_happy_path(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110110")
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop A"))
    [toyota, lexus] = await _pick_brand_ids(db_session, ["toyota", "lexus"])

    result = await service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(vehicle_brand_id=toyota),
            VehicleBrandCoverageIn(
                vehicle_brand_id=lexus,
                year_start=2015,
                year_end=2024,
                steering_side=SteeringSide.LHD,
            ),
        ],
    )
    assert len(result) == 2
    stored = {r.vehicle_brand_id: r for r in result}
    assert stored[toyota].year_start is None
    assert stored[toyota].year_end is None
    assert stored[toyota].steering_side is None
    assert stored[lexus].year_start == 2015
    assert stored[lexus].year_end == 2024
    assert stored[lexus].steering_side == SteeringSide.LHD


async def test_replace_vehicle_coverage_is_idempotent_replace(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110111")
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop B"))
    [toyota, lexus, hyundai] = await _pick_brand_ids(db_session, ["toyota", "lexus", "hyundai"])

    await service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(vehicle_brand_id=toyota),
            VehicleBrandCoverageIn(vehicle_brand_id=lexus),
        ],
    )
    # Second PUT drops lexus, swaps in hyundai.
    result = await service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(vehicle_brand_id=toyota),
            VehicleBrandCoverageIn(vehicle_brand_id=hyundai),
        ],
    )
    brand_ids = {r.vehicle_brand_id for r in result}
    assert brand_ids == {toyota, hyundai}


async def test_replace_vehicle_coverage_empty_clears_all(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110112")
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop C"))
    [toyota] = await _pick_brand_ids(db_session, ["toyota"])

    await service.replace_vehicle_coverage(
        business=business,
        entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)],
    )
    cleared = await service.replace_vehicle_coverage(business=business, entries=[])
    assert cleared == []


async def test_replace_vehicle_coverage_rejects_unknown_brand(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110113")
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop D"))
    [toyota] = await _pick_brand_ids(db_session, ["toyota"])

    with pytest.raises(ValidationError):
        await service.replace_vehicle_coverage(
            business=business,
            entries=[
                VehicleBrandCoverageIn(vehicle_brand_id=toyota),
                VehicleBrandCoverageIn(vehicle_brand_id=uuid.uuid4()),
            ],
        )
    # Rejection is atomic: toyota was not persisted either.
    current = await service.get_vehicle_coverage(business)
    assert current == []


async def test_vehicle_brand_coverage_schema_rejects_inverted_year_range() -> None:
    [toyota] = [uuid.uuid4()]  # schema validation runs before brand lookup
    with pytest.raises(ValueError, match="year_start must not exceed year_end"):
        VehicleBrandCoverageIn(
            vehicle_brand_id=toyota,
            year_start=2020,
            year_end=2015,
        )


async def test_get_coverage_filters_round_trip(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, phone="+97688110114")
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop E"))
    [toyota] = await _pick_brand_ids(db_session, ["toyota"])

    await service.replace_vehicle_coverage(
        business=business,
        entries=[
            VehicleBrandCoverageIn(
                vehicle_brand_id=toyota,
                year_start=2010,
                year_end=2020,
                steering_side=SteeringSide.RHD,
            ),
        ],
    )
    filters = await service.get_coverage_filters(business.id)
    assert len(filters) == 1
    [only] = filters
    assert only.brand_id == toyota
    assert only.year_start == 2010
    assert only.year_end == 2020
    assert only.steering_side == SteeringSide.RHD
