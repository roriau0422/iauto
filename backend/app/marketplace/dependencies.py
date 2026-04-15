"""FastAPI dependencies for the marketplace context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.service import MarketplaceService
from app.platform.db import get_session


def get_marketplace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MarketplaceService:
    return MarketplaceService(session=session)
