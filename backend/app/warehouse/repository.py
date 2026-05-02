"""Database access for the warehouse context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.models import QuoteCondition
from app.warehouse.models import (
    WarehouseMovementKind,
    WarehouseSku,
    WarehouseStockMovement,
)


class WarehouseSkuRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, *, tenant_id: uuid.UUID, sku_id: uuid.UUID) -> WarehouseSku | None:
        sku = await self.session.get(WarehouseSku, sku_id)
        if sku is None or sku.tenant_id != tenant_id:
            return None
        return sku

    async def get_by_code(self, *, tenant_id: uuid.UUID, sku_code: str) -> WarehouseSku | None:
        stmt = select(WarehouseSku).where(
            WarehouseSku.tenant_id == tenant_id,
            WarehouseSku.sku_code == sku_code,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        sku_code: str,
        display_name: str,
        description: str | None,
        condition: QuoteCondition,
        vehicle_brand_id: uuid.UUID | None,
        vehicle_model_id: uuid.UUID | None,
        unit_price_mnt: int | None,
        low_stock_threshold: int | None,
    ) -> WarehouseSku:
        sku = WarehouseSku(
            tenant_id=tenant_id,
            sku_code=sku_code,
            display_name=display_name,
            description=description,
            condition=condition,
            vehicle_brand_id=vehicle_brand_id,
            vehicle_model_id=vehicle_model_id,
            unit_price_mnt=unit_price_mnt,
            low_stock_threshold=low_stock_threshold,
        )
        self.session.add(sku)
        await self.session.flush()
        return sku

    async def list_for_business(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[WarehouseSku], int]:
        base = select(WarehouseSku).where(WarehouseSku.tenant_id == tenant_id)
        count_base = select(func.count(WarehouseSku.id)).where(WarehouseSku.tenant_id == tenant_id)
        if query:
            # Trgm similarity / ILIKE — use ILIKE for now; the trgm GIN
            # index makes it cheap, and we can swap to `pg_trgm.similarity`
            # if ranking matters later.
            pattern = f"%{query}%"
            base = base.where(WarehouseSku.display_name.ilike(pattern))
            count_base = count_base.where(WarehouseSku.display_name.ilike(pattern))
        stmt = base.order_by(WarehouseSku.created_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_base)).scalar_one())
        return rows, total

    async def delete(self, sku: WarehouseSku) -> None:
        await self.session.delete(sku)
        await self.session.flush()


class WarehouseStockMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        sku_id: uuid.UUID,
        kind: WarehouseMovementKind,
        quantity: int,
        signed_quantity: int,
        note: str | None,
        actor_user_id: uuid.UUID,
        sale_id: uuid.UUID | None = None,
    ) -> WarehouseStockMovement:
        row = WarehouseStockMovement(
            tenant_id=tenant_id,
            sku_id=sku_id,
            kind=kind,
            quantity=quantity,
            signed_quantity=signed_quantity,
            note=note,
            actor_user_id=actor_user_id,
            sale_id=sale_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def on_hand(self, *, tenant_id: uuid.UUID, sku_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.sum(WarehouseStockMovement.signed_quantity), 0)).where(
            WarehouseStockMovement.tenant_id == tenant_id,
            WarehouseStockMovement.sku_id == sku_id,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_sku(
        self,
        *,
        tenant_id: uuid.UUID,
        sku_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[WarehouseStockMovement], int]:
        stmt = (
            select(WarehouseStockMovement)
            .where(
                WarehouseStockMovement.tenant_id == tenant_id,
                WarehouseStockMovement.sku_id == sku_id,
            )
            .order_by(WarehouseStockMovement.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count(WarehouseStockMovement.id)).where(
            WarehouseStockMovement.tenant_id == tenant_id,
            WarehouseStockMovement.sku_id == sku_id,
        )
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total
