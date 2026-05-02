"""Warehouse service — SKUs, stock movements, low-stock alerting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import BusinessMemberRole
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event
from app.warehouse.events import SkuCreated, StockMoved
from app.warehouse.models import (
    WarehouseMovementKind,
    WarehouseSku,
    WarehouseStockMovement,
)
from app.warehouse.repository import (
    WarehouseSkuRepository,
    WarehouseStockMovementRepository,
)
from app.warehouse.schemas import (
    SkuCreateIn,
    SkuUpdateIn,
    StockMovementCreateIn,
)

logger = get_logger("app.warehouse.service")

# Roles permitted to create/update/delete SKUs. Staff are read-only on
# the catalog but can record movements (they're the ones receiving
# inventory at the loading dock).
SKU_WRITE_ROLES: frozenset[BusinessMemberRole] = frozenset(
    {BusinessMemberRole.owner, BusinessMemberRole.manager}
)


@dataclass(slots=True)
class SkuListResult:
    items: list[WarehouseSku]
    total: int


@dataclass(slots=True)
class MovementListResult:
    items: list[WarehouseStockMovement]
    total: int


@dataclass(slots=True)
class MovementCreated:
    movement: WarehouseStockMovement
    on_hand_after: int


class WarehouseService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.skus = WarehouseSkuRepository(session)
        self.movements = WarehouseStockMovementRepository(session)

    # ---- SKU CRUD --------------------------------------------------------

    async def create_sku(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        payload: SkuCreateIn,
    ) -> WarehouseSku:
        if actor_role not in SKU_WRITE_ROLES:
            raise ForbiddenError("Only owner / manager can create SKUs")
        # Pre-check the unique invariant. The DB unique on
        # (tenant_id, sku_code) is the canonical guard, but a clean 409
        # for the common case avoids leaving the test fixture's outer
        # transaction in an unusable state when an INSERT fails (see
        # tasks/lessons.md — "session.begin_nested() around IntegrityError").
        existing = await self.skus.get_by_code(tenant_id=tenant_id, sku_code=payload.sku_code)
        if existing is not None:
            raise ConflictError(f"SKU code '{payload.sku_code}' already exists for this business")
        try:
            async with self.session.begin_nested():
                sku = await self.skus.create(
                    tenant_id=tenant_id,
                    sku_code=payload.sku_code,
                    display_name=payload.display_name,
                    description=payload.description,
                    condition=payload.condition,
                    vehicle_brand_id=payload.vehicle_brand_id,
                    vehicle_model_id=payload.vehicle_model_id,
                    unit_price_mnt=payload.unit_price_mnt,
                    low_stock_threshold=payload.low_stock_threshold,
                )
        except IntegrityError as exc:
            # Race window: another transaction inserted the same sku_code
            # between our pre-check and the savepoint commit.
            raise ConflictError(
                f"SKU code '{payload.sku_code}' already exists for this business"
            ) from exc
        write_outbox_event(
            self.session,
            SkuCreated(
                aggregate_id=sku.id,
                tenant_id=tenant_id,
                sku_code=sku.sku_code,
                display_name=sku.display_name,
            ),
        )
        logger.info(
            "warehouse_sku_created",
            sku_id=str(sku.id),
            tenant_id=str(tenant_id),
            sku_code=sku.sku_code,
        )
        return sku

    async def get_sku(self, *, tenant_id: uuid.UUID, sku_id: uuid.UUID) -> WarehouseSku:
        sku = await self.skus.get_by_id(tenant_id=tenant_id, sku_id=sku_id)
        if sku is None:
            raise NotFoundError("SKU not found")
        return sku

    async def list_skus(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str | None,
        limit: int,
        offset: int,
    ) -> SkuListResult:
        items, total = await self.skus.list_for_business(
            tenant_id=tenant_id, query=query, limit=limit, offset=offset
        )
        return SkuListResult(items=items, total=total)

    async def update_sku(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        sku_id: uuid.UUID,
        payload: SkuUpdateIn,
    ) -> WarehouseSku:
        if actor_role not in SKU_WRITE_ROLES:
            raise ForbiddenError("Only owner / manager can update SKUs")
        sku = await self.get_sku(tenant_id=tenant_id, sku_id=sku_id)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(sku, key, value)
        await self.session.flush()
        return sku

    async def delete_sku(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_role: BusinessMemberRole,
        sku_id: uuid.UUID,
    ) -> None:
        if actor_role != BusinessMemberRole.owner:
            raise ForbiddenError("Only the owner can delete SKUs")
        sku = await self.get_sku(tenant_id=tenant_id, sku_id=sku_id)
        on_hand = await self.movements.on_hand(tenant_id=tenant_id, sku_id=sku.id)
        if on_hand != 0:
            raise ConflictError(f"SKU has nonzero on_hand ({on_hand}); zero out the stock first")
        await self.skus.delete(sku)

    # ---- Stock movements -------------------------------------------------

    async def record_movement(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        sku_id: uuid.UUID,
        payload: StockMovementCreateIn,
        sale_id: uuid.UUID | None = None,
    ) -> MovementCreated:
        sku = await self.get_sku(tenant_id=tenant_id, sku_id=sku_id)
        signed_quantity = self._compute_signed_quantity(
            kind=payload.kind, quantity=payload.quantity, direction=payload.direction
        )
        # Issues never push on_hand below zero. Receive / positive adjust
        # can grow it without bound; negative adjust + issue must respect
        # the current balance.
        if signed_quantity < 0:
            current = await self.movements.on_hand(tenant_id=tenant_id, sku_id=sku.id)
            if current + signed_quantity < 0:
                raise ConflictError(
                    f"Movement would drop on_hand below zero "
                    f"(current={current}, attempted={signed_quantity})"
                )

        movement = await self.movements.create(
            tenant_id=tenant_id,
            sku_id=sku.id,
            kind=payload.kind,
            quantity=payload.quantity,
            signed_quantity=signed_quantity,
            note=payload.note,
            actor_user_id=actor_user_id,
            sale_id=sale_id,
        )
        on_hand_after = await self.movements.on_hand(tenant_id=tenant_id, sku_id=sku.id)
        write_outbox_event(
            self.session,
            StockMoved(
                aggregate_id=movement.id,
                tenant_id=tenant_id,
                sku_id=sku.id,
                kind=payload.kind.value,
                quantity=payload.quantity,
                signed_quantity=signed_quantity,
                on_hand_after=on_hand_after,
                sale_id=sale_id,
            ),
        )
        logger.info(
            "warehouse_stock_moved",
            movement_id=str(movement.id),
            sku_id=str(sku.id),
            kind=payload.kind.value,
            on_hand_after=on_hand_after,
        )
        return MovementCreated(movement=movement, on_hand_after=on_hand_after)

    async def list_movements(
        self,
        *,
        tenant_id: uuid.UUID,
        sku_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> MovementListResult:
        # Existence gate so a stranger SKU id 404s consistently.
        await self.get_sku(tenant_id=tenant_id, sku_id=sku_id)
        items, total = await self.movements.list_for_sku(
            tenant_id=tenant_id, sku_id=sku_id, limit=limit, offset=offset
        )
        return MovementListResult(items=items, total=total)

    async def get_on_hand(self, *, tenant_id: uuid.UUID, sku_id: uuid.UUID) -> int:
        return await self.movements.on_hand(tenant_id=tenant_id, sku_id=sku_id)

    @staticmethod
    def _compute_signed_quantity(
        *, kind: WarehouseMovementKind, quantity: int, direction: str
    ) -> int:
        """Resolve sign of the ledger entry from kind + direction.

        Receive is always positive. Issue is always negative. Adjust
        takes the explicit `direction` (`up` / `down`) — if a user
        records a stocktake correction, they tell us which way.
        """
        if kind == WarehouseMovementKind.receive:
            return quantity
        if kind == WarehouseMovementKind.issue:
            return -quantity
        # adjust
        return quantity if direction == "up" else -quantity
