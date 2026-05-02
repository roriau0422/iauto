"""Database access for the businesses context."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberRole,
    BusinessVehicleBrand,
)
from app.catalog.models import VehicleBrand
from app.vehicles.models import SteeringSide


class BusinessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, business_id: uuid.UUID) -> Business | None:
        return await self.session.get(Business, business_id)

    async def get_by_owner(self, owner_id: uuid.UUID) -> Business | None:
        stmt = select(Business).where(Business.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        display_name: str,
        description: str | None,
        address: str | None,
        contact_phone: str | None,
    ) -> Business:
        business = Business(
            owner_id=owner_id,
            display_name=display_name,
            description=description,
            address=address,
            contact_phone=contact_phone,
        )
        self.session.add(business)
        await self.session.flush()
        return business


class BusinessVehicleBrandRepository:
    """Read / replace-all for a business's vehicle coverage pivot.

    There's no single-row edit path — session 5 exposes a single PUT
    that replaces the whole coverage set, which matches how the mobile
    UI is going to build the form (a multi-select page, not per-brand
    toggles). Later sessions can add incremental add/remove methods if
    the flow needs them.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_business(self, business_id: uuid.UUID) -> list[BusinessVehicleBrand]:
        """Return coverage rows for a business, joined to the brand for stable ordering."""
        stmt = (
            select(BusinessVehicleBrand)
            .join(
                VehicleBrand,
                VehicleBrand.id == BusinessVehicleBrand.vehicle_brand_id,
            )
            .where(BusinessVehicleBrand.business_id == business_id)
            .order_by(VehicleBrand.sort_order, VehicleBrand.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def replace_all(
        self,
        *,
        business_id: uuid.UUID,
        entries: list[tuple[uuid.UUID, int | None, int | None, SteeringSide | None]],
    ) -> list[BusinessVehicleBrand]:
        """Delete every coverage row for this business, then insert `entries`.

        Runs inside the caller's transaction — if a downstream error
        rolls back, the old set is preserved. Each entry is a tuple of
        (brand_id, year_start, year_end, steering_side).
        """
        await self.session.execute(
            delete(BusinessVehicleBrand).where(BusinessVehicleBrand.business_id == business_id)
        )
        rows = [
            BusinessVehicleBrand(
                business_id=business_id,
                vehicle_brand_id=brand_id,
                year_start=year_start,
                year_end=year_end,
                steering_side=steering_side,
            )
            for brand_id, year_start, year_end, steering_side in entries
        ]
        self.session.add_all(rows)
        await self.session.flush()
        return await self.list_for_business(business_id)

    async def filter_known_brand_ids(self, brand_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Return the subset of the given IDs that actually exist in the catalog."""
        if not brand_ids:
            return set()
        stmt = select(VehicleBrand.id).where(VehicleBrand.id.in_(brand_ids))
        result = await self.session.execute(stmt)
        return set(result.scalars())


class BusinessMemberRepository:
    """Read/write the (business_id, user_id, role) pivot.

    Idempotent upsert lets the businesses service treat "ensure the owner
    is a member" the same as "add a manager" without branching.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, business_id: uuid.UUID, user_id: uuid.UUID) -> BusinessMember | None:
        return await self.session.get(BusinessMember, (business_id, user_id))

    async def list_for_business(self, business_id: uuid.UUID) -> list[BusinessMember]:
        stmt = (
            select(BusinessMember)
            .where(BusinessMember.business_id == business_id)
            .order_by(BusinessMember.created_at)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_for_user(self, user_id: uuid.UUID) -> list[BusinessMember]:
        stmt = select(BusinessMember).where(BusinessMember.user_id == user_id)
        return list((await self.session.execute(stmt)).scalars())

    async def upsert(
        self,
        *,
        business_id: uuid.UUID,
        user_id: uuid.UUID,
        role: BusinessMemberRole,
    ) -> BusinessMember:
        existing = await self.get(business_id, user_id)
        if existing is not None:
            existing.role = role
            await self.session.flush()
            return existing
        member = BusinessMember(business_id=business_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member

    async def delete(self, *, business_id: uuid.UUID, user_id: uuid.UUID) -> int:
        # `Result.rowcount` is on `CursorResult`, not `Result`. Cast keeps
        # the typed surface honest.
        from sqlalchemy.engine import CursorResult

        raw = await self.session.execute(
            delete(BusinessMember).where(
                BusinessMember.business_id == business_id,
                BusinessMember.user_id == user_id,
            )
        )
        await self.session.flush()
        rowcount = raw.rowcount if isinstance(raw, CursorResult) else 0
        return rowcount or 0
