"""FastAPI dependencies for the warehouse context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.db import get_session
from app.warehouse.service import WarehouseService


def get_warehouse_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WarehouseService:
    return WarehouseService(session=session)
