"""Database access for the marketplace context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.models import PartSearchRequest, PartSearchStatus


class PartSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, search_id: uuid.UUID) -> PartSearchRequest | None:
        return await self.session.get(PartSearchRequest, search_id)

    async def create(
        self,
        *,
        driver_id: uuid.UUID,
        vehicle_id: uuid.UUID,
        description: str,
        media_urls: list[str],
    ) -> PartSearchRequest:
        row = PartSearchRequest(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            description=description,
            media_urls=list(media_urls),
            status=PartSearchStatus.open,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        status: PartSearchStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PartSearchRequest], int]:
        base = select(PartSearchRequest).where(PartSearchRequest.driver_id == driver_id)
        count_base = select(func.count(PartSearchRequest.id)).where(
            PartSearchRequest.driver_id == driver_id
        )
        if status is not None:
            base = base.where(PartSearchRequest.status == status)
            count_base = count_base.where(PartSearchRequest.status == status)
        stmt = base.order_by(PartSearchRequest.created_at.desc()).limit(limit).offset(offset)
        rows_result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_base)
        rows = list(rows_result.scalars())
        total = int(total_result.scalar_one())
        return rows, total
