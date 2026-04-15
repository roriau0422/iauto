"""HTTP request/response Pydantic schemas for catalog endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class VehicleCountryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name_en: str
    name_mn: str
    sort_order: int


class VehicleCountryListOut(BaseModel):
    items: list[VehicleCountryOut]


class VehicleBrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    country_id: uuid.UUID
    slug: str
    name: str
    sort_order: int


class VehicleBrandListOut(BaseModel):
    items: list[VehicleBrandOut]


class VehicleModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_id: uuid.UUID
    slug: str
    name: str
    sort_order: int


class VehicleModelListOut(BaseModel):
    items: list[VehicleModelOut]
