"""HTTP routes for the businesses context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.businesses.dependencies import (
    BusinessContext,
    get_businesses_service,
    get_current_business,
    get_current_business_member,
)
from app.businesses.models import Business, BusinessMemberRole
from app.businesses.schemas import (
    BusinessCreateIn,
    BusinessMemberAddIn,
    BusinessMemberDeleteOut,
    BusinessMemberListOut,
    BusinessMemberOut,
    BusinessOut,
    BusinessUpdateIn,
    VehicleBrandCoverageListOut,
    VehicleBrandCoverageOut,
    VehicleBrandCoverageReplaceIn,
)
from app.businesses.service import BusinessesService
from app.identity.dependencies import get_current_user
from app.identity.models import User

router = APIRouter(tags=["businesses"])


@router.post(
    "/businesses",
    response_model=BusinessOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a business profile for the authenticated user",
)
async def create_business(
    body: BusinessCreateIn,
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> BusinessOut:
    business = await service.create(owner=user, payload=body)
    return BusinessOut.model_validate(business)


@router.get(
    "/businesses/me",
    response_model=BusinessOut,
    summary="Return the authenticated owner's business profile",
)
async def get_my_business(
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> BusinessOut:
    business = await service.get_for_owner(user)
    return BusinessOut.model_validate(business)


@router.patch(
    "/businesses/me",
    response_model=BusinessOut,
    summary="Partially update the authenticated owner's business profile",
)
async def update_my_business(
    body: BusinessUpdateIn,
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> BusinessOut:
    business = await service.update(owner=user, payload=body)
    return BusinessOut.model_validate(business)


@router.get(
    "/businesses/me/vehicle-brands",
    response_model=VehicleBrandCoverageListOut,
    summary="List the business's current vehicle brand coverage",
)
async def list_vehicle_brands(
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    business: Annotated[Business, Depends(get_current_business)],
) -> VehicleBrandCoverageListOut:
    items = await service.get_vehicle_coverage(business)
    return VehicleBrandCoverageListOut(
        items=[VehicleBrandCoverageOut.model_validate(i) for i in items]
    )


@router.put(
    "/businesses/me/vehicle-brands",
    response_model=VehicleBrandCoverageListOut,
    summary="Replace the business's vehicle brand coverage set",
)
async def replace_vehicle_brands(
    body: VehicleBrandCoverageReplaceIn,
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    business: Annotated[Business, Depends(get_current_business)],
) -> VehicleBrandCoverageListOut:
    items = await service.replace_vehicle_coverage(business=business, entries=body.items)
    return VehicleBrandCoverageListOut(
        items=[VehicleBrandCoverageOut.model_validate(i) for i in items]
    )


# ---------------------------------------------------------------------------
# Members (session 10)
# ---------------------------------------------------------------------------


@router.get(
    "/businesses/me/members",
    response_model=BusinessMemberListOut,
    summary="List members of the caller's business",
)
async def list_members(
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> BusinessMemberListOut:
    rows = await service.list_members(ctx.business)
    return BusinessMemberListOut(items=[BusinessMemberOut.model_validate(r) for r in rows])


@router.post(
    "/businesses/me/members",
    response_model=BusinessMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a manager / staff member to the caller's business (owner only)",
)
async def add_member(
    body: BusinessMemberAddIn,
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> BusinessMemberOut:
    member = await service.add_member(
        business=ctx.business,
        actor_role=ctx.role,
        user_phone=body.user_phone,
        role=BusinessMemberRole(body.role),
    )
    return BusinessMemberOut.model_validate(member)


@router.delete(
    "/businesses/me/members/{user_id}",
    response_model=BusinessMemberDeleteOut,
    summary="Remove a member from the caller's business (owner only)",
)
async def remove_member(
    user_id: uuid.UUID,
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
) -> BusinessMemberDeleteOut:
    await service.remove_member(business=ctx.business, actor_role=ctx.role, user_id=user_id)
    return BusinessMemberDeleteOut()
