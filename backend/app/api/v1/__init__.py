"""/v1/ API surface.

Context routers attach to `api_router` here. Keep additions alphabetical.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health
from app.businesses.router import router as businesses_router
from app.catalog.router import router as catalog_router
from app.identity.router import router as identity_router
from app.marketplace.router import router as marketplace_router
from app.media.router import router as media_router
from app.payments.router import router as payments_router
from app.vehicles.router import router as vehicles_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(businesses_router)
api_router.include_router(catalog_router)
api_router.include_router(identity_router)
api_router.include_router(marketplace_router)
api_router.include_router(media_router)
api_router.include_router(payments_router)
api_router.include_router(vehicles_router)

__all__ = ["api_router"]
