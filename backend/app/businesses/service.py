"""Business profile service."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business, BusinessVehicleBrand
from app.businesses.repository import (
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
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.platform.logging import get_logger

logger = get_logger("app.businesses.service")


class BusinessesService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.businesses = BusinessRepository(session)
        self.coverage = BusinessVehicleBrandRepository(session)

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
