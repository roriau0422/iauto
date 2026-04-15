"""FastAPI dependencies for the catalog context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import CatalogService
from app.platform.db import get_session


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogService:
    return CatalogService(session)
