"""FastAPI dependencies for the marketplace context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.service import MarketplaceService
from app.platform.db import get_session
from app.vehicles.dependencies import get_vehicles_service
from app.vehicles.service import VehiclesService


def get_marketplace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    vehicles_svc: Annotated[VehiclesService, Depends(get_vehicles_service)],
) -> MarketplaceService:
    return MarketplaceService(session=session, vehicles_svc=vehicles_svc)
