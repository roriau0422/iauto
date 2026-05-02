"""FastAPI dependencies for the admin context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.service import AdminSpendService
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole
from app.platform.db import get_session
from app.platform.errors import ForbiddenError


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Gate every admin endpoint behind `UserRole.admin`."""
    if user.role != UserRole.admin:
        raise ForbiddenError("Admin role required")
    return user


def get_admin_spend_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSpendService:
    return AdminSpendService(session=session)
