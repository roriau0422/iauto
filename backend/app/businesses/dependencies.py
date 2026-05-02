"""FastAPI dependencies for the businesses context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business, BusinessMember, BusinessMemberRole
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


@dataclass(slots=True)
class BusinessContext:
    """Resolved tuple of (business, member, role) for the calling user.

    Returned by `get_current_business_member`. The dataclass keeps the
    three pieces colocated so warehouse handlers can authz on `role`
    without re-querying the membership.
    """

    business: Business
    member: BusinessMember
    role: BusinessMemberRole


async def get_current_business_member(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> BusinessContext:
    """Resolve the caller's business membership (owner / manager / staff).

    Differs from `get_current_business` in two ways:
      1. Works for any user with at least one membership, not just the
         user with `role='business'` who originally created the business.
      2. Returns the membership row so the handler can authz on role.

    Raises 403 if the caller is not a member of any business. If the
    caller is a member of multiple businesses (Phase 2+ multi-tenant
    invite story), we pick the one matching `users.role='business'`'s
    owner row, falling back to the first membership.
    """
    memberships = await service.members.list_for_user(user.id)
    if not memberships:
        raise ForbiddenError("Business membership required")
    # Prefer the owner_id-linked business if the caller created one.
    owned = None
    if user.role == UserRole.business:
        owned = await service.businesses.get_by_owner(user.id)
    if owned is not None:
        for m in memberships:
            if m.business_id == owned.id:
                return BusinessContext(business=owned, member=m, role=m.role)
    # Fallback: the first membership in stable order.
    member = memberships[0]
    business = await service.businesses.get_by_id(member.business_id)
    if business is None:
        # Pivot row pointing at a deleted business — shouldn't happen,
        # but the type checker doesn't know that.
        raise NotFoundError("Business not found")
    return BusinessContext(business=business, member=member, role=member.role)
