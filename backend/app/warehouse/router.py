"""HTTP routes for the warehouse context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.businesses.dependencies import (
    BusinessContext,
    get_current_business_member,
)
from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.warehouse.dependencies import get_warehouse_service
from app.warehouse.schemas import (
    SkuCreateIn,
    SkuDeleteOut,
    SkuDetailOut,
    SkuListOut,
    SkuOut,
    SkuUpdateIn,
    StockMovementCreatedOut,
    StockMovementCreateIn,
    StockMovementListOut,
    StockMovementOut,
)
from app.warehouse.service import WarehouseService

router = APIRouter(tags=["warehouse"])


@router.post(
    "/warehouse/skus",
    response_model=SkuOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a SKU (owner / manager only)",
)
async def create_sku(
    body: SkuCreateIn,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> SkuOut:
    sku = await service.create_sku(
        tenant_id=ctx.business.id,
        actor_role=ctx.role,
        payload=body,
    )
    return SkuOut.model_validate(sku)


@router.get(
    "/warehouse/skus",
    response_model=SkuListOut,
    summary="List SKUs in the caller's business catalog",
)
async def list_skus(
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SkuListOut:
    result = await service.list_skus(tenant_id=ctx.business.id, query=q, limit=limit, offset=offset)
    return SkuListOut(
        items=[SkuOut.model_validate(s) for s in result.items],
        total=result.total,
    )


@router.get(
    "/warehouse/skus/{sku_id}",
    response_model=SkuDetailOut,
    summary="Read a SKU with current on_hand",
)
async def get_sku(
    sku_id: uuid.UUID,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> SkuDetailOut:
    sku = await service.get_sku(tenant_id=ctx.business.id, sku_id=sku_id)
    on_hand = await service.get_on_hand(tenant_id=ctx.business.id, sku_id=sku.id)
    return SkuDetailOut(
        id=sku.id,
        tenant_id=sku.tenant_id,
        sku_code=sku.sku_code,
        display_name=sku.display_name,
        description=sku.description,
        condition=sku.condition,
        vehicle_brand_id=sku.vehicle_brand_id,
        vehicle_model_id=sku.vehicle_model_id,
        unit_price_mnt=sku.unit_price_mnt,
        low_stock_threshold=sku.low_stock_threshold,
        created_at=sku.created_at,
        updated_at=sku.updated_at,
        on_hand=on_hand,
    )


@router.patch(
    "/warehouse/skus/{sku_id}",
    response_model=SkuOut,
    summary="Patch a SKU (owner / manager only)",
)
async def update_sku(
    sku_id: uuid.UUID,
    body: SkuUpdateIn,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> SkuOut:
    sku = await service.update_sku(
        tenant_id=ctx.business.id,
        actor_role=ctx.role,
        sku_id=sku_id,
        payload=body,
    )
    return SkuOut.model_validate(sku)


@router.delete(
    "/warehouse/skus/{sku_id}",
    response_model=SkuDeleteOut,
    summary="Delete a SKU (owner only; on_hand must be zero)",
)
async def delete_sku(
    sku_id: uuid.UUID,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> SkuDeleteOut:
    await service.delete_sku(tenant_id=ctx.business.id, actor_role=ctx.role, sku_id=sku_id)
    return SkuDeleteOut()


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------


@router.post(
    "/warehouse/skus/{sku_id}/movements",
    response_model=StockMovementCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a stock movement against a SKU (any member)",
)
async def record_movement(
    sku_id: uuid.UUID,
    body: StockMovementCreateIn,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    user: Annotated[User, Depends(get_current_user)],
) -> StockMovementCreatedOut:
    result = await service.record_movement(
        tenant_id=ctx.business.id,
        actor_user_id=user.id,
        sku_id=sku_id,
        payload=body,
    )
    return StockMovementCreatedOut(
        movement=StockMovementOut.model_validate(result.movement),
        on_hand_after=result.on_hand_after,
    )


@router.get(
    "/warehouse/skus/{sku_id}/movements",
    response_model=StockMovementListOut,
    summary="List stock movements for a SKU, newest first",
)
async def list_movements(
    sku_id: uuid.UUID,
    service: Annotated[WarehouseService, Depends(get_warehouse_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StockMovementListOut:
    result = await service.list_movements(
        tenant_id=ctx.business.id, sku_id=sku_id, limit=limit, offset=offset
    )
    return StockMovementListOut(
        items=[StockMovementOut.model_validate(m) for m in result.items],
        total=result.total,
    )
