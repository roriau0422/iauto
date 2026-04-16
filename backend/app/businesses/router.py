"""HTTP routes for the businesses context."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.businesses.dependencies import get_businesses_service, get_current_business
from app.businesses.models import Business
from app.businesses.schemas import (
    BusinessCreateIn,
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
