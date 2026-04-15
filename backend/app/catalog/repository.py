"""Database access for the catalog context."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import VehicleBrand, VehicleCountry, VehicleModel


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- countries ---------------------------------------------------------

    async def list_countries(self) -> list[VehicleCountry]:
        stmt = select(VehicleCountry).order_by(VehicleCountry.sort_order, VehicleCountry.name_en)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    # ---- brands ------------------------------------------------------------

    async def list_brands(self, *, country_id: uuid.UUID | None = None) -> list[VehicleBrand]:
        stmt = select(VehicleBrand)
        if country_id is not None:
            stmt = stmt.where(VehicleBrand.country_id == country_id)
        stmt = stmt.order_by(VehicleBrand.sort_order, VehicleBrand.name)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_brand_by_slug(self, slug: str) -> VehicleBrand | None:
        stmt = select(VehicleBrand).where(VehicleBrand.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ---- models ------------------------------------------------------------

    async def list_models(self, *, brand_id: uuid.UUID | None = None) -> list[VehicleModel]:
        stmt = select(VehicleModel)
        if brand_id is not None:
            stmt = stmt.where(VehicleModel.brand_id == brand_id)
        stmt = stmt.order_by(VehicleModel.sort_order, VehicleModel.name)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_model_by_brand_slug(
        self, *, brand_id: uuid.UUID, slug: str
    ) -> VehicleModel | None:
        stmt = select(VehicleModel).where(
            and_(
                VehicleModel.brand_id == brand_id,
                VehicleModel.slug == slug,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
