"""HTTP routes for the catalog context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.catalog.dependencies import get_catalog_service
from app.catalog.schemas import (
    VehicleBrandListOut,
    VehicleBrandOut,
    VehicleCountryListOut,
    VehicleCountryOut,
    VehicleModelListOut,
    VehicleModelOut,
)
from app.catalog.service import CatalogService

router = APIRouter(tags=["catalog"])


@router.get(
    "/catalog/countries",
    response_model=VehicleCountryListOut,
    summary="List vehicle countries of origin",
)
async def list_countries(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> VehicleCountryListOut:
    rows = await service.list_countries()
    return VehicleCountryListOut(items=[VehicleCountryOut.model_validate(r) for r in rows])


@router.get(
    "/catalog/brands",
    response_model=VehicleBrandListOut,
    summary="List vehicle brands (optionally filtered by country)",
)
async def list_brands(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    country_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter to brands whose country_id matches"),
    ] = None,
) -> VehicleBrandListOut:
    rows = await service.list_brands(country_id=country_id)
    return VehicleBrandListOut(items=[VehicleBrandOut.model_validate(r) for r in rows])


@router.get(
    "/catalog/models",
    response_model=VehicleModelListOut,
    summary="List vehicle models (optionally filtered by brand)",
)
async def list_models(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    brand_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter to models whose brand_id matches"),
    ] = None,
) -> VehicleModelListOut:
    rows = await service.list_models(brand_id=brand_id)
    return VehicleModelListOut(items=[VehicleModelOut.model_validate(r) for r in rows])
