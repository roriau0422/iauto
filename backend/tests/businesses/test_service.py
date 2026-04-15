"""Service-level tests for the businesses context."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn, BusinessUpdateIn
from app.businesses.service import BusinessesService
from app.identity.models import User, UserRole
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError


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


async def test_create_happy_path(
    service: BusinessesService, db_session: AsyncSession
) -> None:
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
        await service.create(
            owner=owner, payload=BusinessCreateIn(display_name="Second")
        )


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
