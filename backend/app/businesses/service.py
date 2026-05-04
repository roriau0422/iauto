"""Business profile service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberRole,
    BusinessVehicleBrand,
)
from app.businesses.repository import (
    BusinessAnalyticsRepository,
    BusinessMemberRepository,
    BusinessRepository,
    BusinessVehicleBrandRepository,
)
from app.businesses.schemas import (
    BusinessCreateIn,
    BusinessUpdateIn,
    CoverageFilter,
    VehicleBrandCoverageIn,
)
from app.identity.models import User, UserRole
from app.identity.repository import UserRepository
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.platform.logging import get_logger

# Top-N leaderboard for the analytics endpoint. The number is fixed for
# the launch — businesses get five SKUs, mobile renders five rows.
_TOP_SKUS_LIMIT = 5

# Hard ceiling on `window_days`. The caller's Pydantic validation should
# reject larger values, but the service re-asserts the bound so a
# repository call with stale settings can't silently scan a full year of
# rows.
ANALYTICS_MAX_WINDOW_DAYS = 90


@dataclass(slots=True)
class DailyBucket:
    date: date
    sales_count: int
    revenue_mnt: int


@dataclass(slots=True)
class TopSkuRow:
    sku_id: uuid.UUID
    sku_code: str
    display_name: str
    units_sold: int


@dataclass(slots=True)
class AnalyticsResult:
    window_days: int
    daily: list[DailyBucket]
    total_sales: int
    total_revenue_mnt: int
    top_skus: list[TopSkuRow]


logger = get_logger("app.businesses.service")


class BusinessesService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.businesses = BusinessRepository(session)
        self.coverage = BusinessVehicleBrandRepository(session)
        self.members = BusinessMemberRepository(session)
        self.users = UserRepository(session)
        self.analytics = BusinessAnalyticsRepository(session)

    async def create(self, *, owner: User, payload: BusinessCreateIn) -> Business:
        if owner.role != UserRole.business:
            raise ForbiddenError("Only users with role='business' can create a business profile")
        existing = await self.businesses.get_by_owner(owner.id)
        if existing is not None:
            raise ConflictError("This user already has a business profile")
        try:
            business = await self.businesses.create(
                owner_id=owner.id,
                display_name=payload.display_name,
                description=payload.description,
                address=payload.address,
                contact_phone=payload.contact_phone,
            )
        except IntegrityError as exc:
            # Race: two concurrent POSTs for the same owner. The partial
            # unique index catches it even if the pre-check missed.
            raise ConflictError("This user already has a business profile") from exc

        # Seed the membership pivot with the owner so multi-staff lookups
        # don't have to special-case the owner_id column.
        await self.members.upsert(
            business_id=business.id,
            user_id=owner.id,
            role=BusinessMemberRole.owner,
        )
        logger.info(
            "business_created",
            business_id=str(business.id),
            owner_id=str(owner.id),
        )
        return business

    async def get_for_owner(self, owner: User) -> Business:
        if owner.role != UserRole.business:
            raise ForbiddenError("Only business users have a business profile")
        business = await self.businesses.get_by_owner(owner.id)
        if business is None:
            raise NotFoundError("No business profile exists for this user")
        return business

    async def update(self, *, owner: User, payload: BusinessUpdateIn) -> Business:
        business = await self.get_for_owner(owner)
        data = payload.model_dump(exclude_unset=True)
        if "display_name" in data and data["display_name"] is not None:
            business.display_name = data["display_name"]
        if "description" in data:
            business.description = data["description"]
        if "address" in data:
            business.address = data["address"]
        if "contact_phone" in data:
            business.contact_phone = data["contact_phone"]
        await self.session.flush()
        # Onupdate-driven `updated_at` is expired by flush; refresh so the
        # response model can read it without a lazy load on a closed
        # greenlet (same class of bug as warehouse.update_sku).
        await self.session.refresh(business)
        logger.info("business_updated", business_id=str(business.id))
        return business

    # ---- vehicle brand coverage -------------------------------------------

    async def get_vehicle_coverage(self, business: Business) -> list[BusinessVehicleBrand]:
        return await self.coverage.list_for_business(business.id)

    async def replace_vehicle_coverage(
        self,
        *,
        business: Business,
        entries: list[VehicleBrandCoverageIn],
    ) -> list[BusinessVehicleBrand]:
        """Atomically replace the business's coverage set.

        Validates every `vehicle_brand_id` against the catalog before
        deleting anything; unknown brand IDs reject the whole batch with
        422. Empty list clears coverage.
        """
        brand_ids = [e.vehicle_brand_id for e in entries]
        if brand_ids:
            known = await self.coverage.filter_known_brand_ids(brand_ids)
            missing = [bid for bid in brand_ids if bid not in known]
            if missing:
                raise ValidationError(
                    f"Unknown vehicle_brand_id(s): {sorted(str(b) for b in missing)}"
                )

        rows = [(e.vehicle_brand_id, e.year_start, e.year_end, e.steering_side) for e in entries]
        result = await self.coverage.replace_all(business_id=business.id, entries=rows)
        logger.info(
            "business_vehicle_coverage_replaced",
            business_id=str(business.id),
            count=len(result),
        )
        return result

    async def get_coverage_filters(self, business_id: uuid.UUID) -> list[CoverageFilter]:
        """Return coverage as a list of filter tuples for marketplace matching."""
        rows = await self.coverage.list_for_business(business_id)
        return [
            CoverageFilter(
                brand_id=row.vehicle_brand_id,
                year_start=row.year_start,
                year_end=row.year_end,
                steering_side=row.steering_side,
            )
            for row in rows
        ]

    # ---- members (session 10) ---------------------------------------------

    async def list_members(self, business: Business) -> list[BusinessMember]:
        return await self.members.list_for_business(business.id)

    async def add_member(
        self,
        *,
        business: Business,
        actor_role: BusinessMemberRole,
        user_phone: str,
        role: BusinessMemberRole,
    ) -> BusinessMember:
        if actor_role != BusinessMemberRole.owner:
            raise ForbiddenError("Only the owner can add members")
        if role == BusinessMemberRole.owner:
            raise ConflictError("A business has exactly one owner")
        target = await self.users.get_by_phone(user_phone)
        if target is None:
            raise NotFoundError("User not found")
        member = await self.members.upsert(business_id=business.id, user_id=target.id, role=role)
        logger.info(
            "business_member_added",
            business_id=str(business.id),
            user_id=str(target.id),
            role=role.value,
        )
        return member

    async def remove_member(
        self,
        *,
        business: Business,
        actor_role: BusinessMemberRole,
        user_id: uuid.UUID,
    ) -> None:
        if actor_role != BusinessMemberRole.owner:
            raise ForbiddenError("Only the owner can remove members")
        existing = await self.members.get(business.id, user_id)
        if existing is None:
            raise NotFoundError("Member not found")
        if existing.role == BusinessMemberRole.owner:
            raise ConflictError("Cannot remove the owner")
        await self.members.delete(business_id=business.id, user_id=user_id)
        logger.info(
            "business_member_removed",
            business_id=str(business.id),
            user_id=str(user_id),
        )

    async def get_membership(
        self, *, business_id: uuid.UUID, user_id: uuid.UUID
    ) -> BusinessMember | None:
        return await self.members.get(business_id, user_id)

    # ---- analytics --------------------------------------------------------

    async def get_sales_analytics(
        self,
        *,
        business: Business,
        window_days: int,
    ) -> AnalyticsResult:
        """Trailing-window sales analytics for a single business tenant.

        - `daily` is gap-filled to `window_days` consecutive UTC days,
          oldest first.
        - `total_sales` and `total_revenue_mnt` are over the same window.
        - `top_skus` is the top-5 SKUs by units sold during the window
          (joined through `warehouse_stock_movements`).

        Window is clamped at ANALYTICS_MAX_WINDOW_DAYS as a defence in
        depth — the route schema also rejects larger inputs.
        """
        if window_days < 1 or window_days > ANALYTICS_MAX_WINDOW_DAYS:
            raise ValidationError(f"window_days must be between 1 and {ANALYTICS_MAX_WINDOW_DAYS}")

        now = datetime.now(UTC)
        # Anchor the window at midnight UTC `window_days` days ago, so a
        # 7-day window covers exactly 7 calendar days regardless of when
        # the request lands.
        today = now.date()
        first_day = today - timedelta(days=window_days - 1)
        cutoff = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)

        sparse = await self.analytics.daily_buckets(tenant_id=business.id, cutoff=cutoff)
        sparse_by_day = {row[0]: (row[1], row[2]) for row in sparse}
        daily: list[DailyBucket] = []
        for offset in range(window_days):
            day = first_day + timedelta(days=offset)
            sales_count, revenue_mnt = sparse_by_day.get(day, (0, 0))
            daily.append(DailyBucket(date=day, sales_count=sales_count, revenue_mnt=revenue_mnt))

        total_sales, total_revenue_mnt = await self.analytics.totals(
            tenant_id=business.id, cutoff=cutoff
        )

        top_rows = await self.analytics.top_skus(
            tenant_id=business.id, cutoff=cutoff, limit=_TOP_SKUS_LIMIT
        )
        top_skus = [
            TopSkuRow(
                sku_id=row[0],
                sku_code=row[1],
                display_name=row[2],
                units_sold=row[3],
            )
            for row in top_rows
        ]

        return AnalyticsResult(
            window_days=window_days,
            daily=daily,
            total_sales=total_sales,
            total_revenue_mnt=total_revenue_mnt,
            top_skus=top_skus,
        )
