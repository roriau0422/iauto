"""Business profile service."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business
from app.businesses.repository import BusinessRepository
from app.businesses.schemas import BusinessCreateIn, BusinessUpdateIn
from app.identity.models import User, UserRole
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.logging import get_logger

logger = get_logger("app.businesses.service")


class BusinessesService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.businesses = BusinessRepository(session)

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
