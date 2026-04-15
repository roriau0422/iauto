"""FastAPI dependencies for the businesses context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business
from app.businesses.service import BusinessesService
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole
from app.platform.db import get_session
from app.platform.errors import ForbiddenError, NotFoundError


def get_businesses_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BusinessesService:
    return BusinessesService(session=session)


async def get_current_business(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> Business:
    """Resolve the `Business` for the authenticated user.

    Raises 403 for non-business roles, 404 if the user hasn't created a
    profile yet. Use this on any endpoint that must operate inside a
    business tenant boundary — quotes, warehouse, stories, ads.
    """
    if user.role != UserRole.business:
        raise ForbiddenError("Business account required")
    business = await service.businesses.get_by_owner(user.id)
    if business is None:
        raise NotFoundError("No business profile exists for this user")
    return business
