"""HTTP request/response Pydantic schemas for the businesses endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.businesses.models import BusinessMemberRole
from app.identity.schemas import normalize_phone
from app.vehicles.models import SteeringSide


def _optional_normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return normalize_phone(stripped)


class BusinessCreateIn(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=500)
    contact_phone: str | None = None

    @field_validator("display_name")
    @classmethod
    def _trim_display_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("display_name must not be blank")
        return trimmed

    @field_validator("contact_phone")
    @classmethod
    def _normalize_contact(cls, v: str | None) -> str | None:
        return _optional_normalize_phone(v)


class BusinessUpdateIn(BaseModel):
    """Partial update. Only provided fields are applied.

    `contact_phone` accepts an explicit empty string or None to clear the
    override, since a business might want to fall back to the owner's phone
    later. We represent that as a sentinel in the service layer.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=500)
    contact_phone: str | None = None

    @field_validator("display_name")
    @classmethod
    def _trim_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("display_name must not be blank")
        return trimmed

    @field_validator("contact_phone")
    @classmethod
    def _normalize_contact(cls, v: str | None) -> str | None:
        return _optional_normalize_phone(v)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    display_name: str
    description: str | None
    address: str | None
    contact_phone: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Vehicle brand coverage
# ---------------------------------------------------------------------------


# Upper bound on how many brands a single business can declare in one PUT.
# A shop touching all Japanese brands is ~15; the 50 cap is roomy for
# multi-brand chains without letting a client flood the pivot table.
MAX_COVERAGE_ENTRIES = 50
# Mongolia imported its first cars in the 1920s; nothing predates that on
# Mongolian roads. Anything above the current year + a small buffer is
# almost certainly a typo.
COVERAGE_YEAR_MIN = 1900
COVERAGE_YEAR_MAX = 2100


class VehicleBrandCoverageIn(BaseModel):
    """One entry in a business's coverage set.

    `year_start`/`year_end` are inclusive bounds on vehicle.build_year.
    Either can be NULL; NULL-NULL means "every year this brand has ever
    been made". `steering_side` NULL accepts both LHD and RHD.
    """

    vehicle_brand_id: uuid.UUID
    year_start: int | None = Field(
        default=None,
        ge=COVERAGE_YEAR_MIN,
        le=COVERAGE_YEAR_MAX,
    )
    year_end: int | None = Field(
        default=None,
        ge=COVERAGE_YEAR_MIN,
        le=COVERAGE_YEAR_MAX,
    )
    steering_side: SteeringSide | None = None

    @model_validator(mode="after")
    def _validate_year_range(self) -> Self:
        if (
            self.year_start is not None
            and self.year_end is not None
            and self.year_start > self.year_end
        ):
            raise ValueError("year_start must not exceed year_end")
        return self


class VehicleBrandCoverageReplaceIn(BaseModel):
    items: list[VehicleBrandCoverageIn] = Field(
        default_factory=list, max_length=MAX_COVERAGE_ENTRIES
    )

    @field_validator("items")
    @classmethod
    def _no_duplicate_brands(cls, v: list[VehicleBrandCoverageIn]) -> list[VehicleBrandCoverageIn]:
        brand_ids = [e.vehicle_brand_id for e in v]
        if len(brand_ids) != len(set(brand_ids)):
            raise ValueError("Each vehicle_brand_id must appear at most once")
        return v


class VehicleBrandCoverageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_brand_id: uuid.UUID
    year_start: int | None
    year_end: int | None
    steering_side: SteeringSide | None
    created_at: datetime
    updated_at: datetime


class VehicleBrandCoverageListOut(BaseModel):
    items: list[VehicleBrandCoverageOut]


# ---------------------------------------------------------------------------
# Members (session 10)
# ---------------------------------------------------------------------------


class BusinessMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: uuid.UUID
    user_id: uuid.UUID
    role: BusinessMemberRole
    created_at: datetime
    updated_at: datetime


class BusinessMemberListOut(BaseModel):
    items: list[BusinessMemberOut]


class BusinessMemberAddIn(BaseModel):
    """Body for `POST /businesses/me/members`.

    The owner identifies a user by phone (the same identifier they use
    for OTP login). `role` is constrained to manager/staff — owner is
    set during business creation and cannot be added or changed via
    this endpoint.
    """

    user_phone: str
    role: Literal["manager", "staff"]

    @field_validator("user_phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class BusinessMemberDeleteOut(BaseModel):
    ok: Literal[True] = True


# ---------------------------------------------------------------------------
# Sales analytics (session 25)
# ---------------------------------------------------------------------------


class AnalyticsDailyOut(BaseModel):
    """One bucket in the trailing-window sales sparkline.

    `date` is the UTC calendar date the bucket covers (server-side
    `date_trunc('day', sales.created_at)`). Days inside the window with
    zero sales are still emitted so the mobile chart renders contiguous
    bars without client-side gap-filling.
    """

    date: date
    sales_count: int
    revenue_mnt: int


class AnalyticsTopSkuOut(BaseModel):
    """One row in the top-N SKUs leaderboard."""

    sku_id: uuid.UUID
    sku_code: str
    display_name: str
    units_sold: int


class BusinessAnalyticsOut(BaseModel):
    window_days: int
    daily: list[AnalyticsDailyOut]
    total_sales: int
    total_revenue_mnt: int
    top_skus: list[AnalyticsTopSkuOut]


class CoverageFilter(NamedTuple):
    """Value type for a single coverage entry passed across context boundaries.

    Carried from `BusinessesService.get_coverage_filters()` into
    `MarketplaceService.list_incoming()` / `submit_quote()` and down to
    `PartSearchRepository` for the SQL WHERE construction. A NamedTuple
    keeps the hop lightweight and picklable and dodges the alembic
    `@dataclass` trap noted in lessons.md.
    """

    brand_id: uuid.UUID
    year_start: int | None
    year_end: int | None
    steering_side: SteeringSide | None
