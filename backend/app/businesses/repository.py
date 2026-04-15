"""Database access for the businesses context."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business


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
