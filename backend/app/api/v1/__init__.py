"""/v1/ API surface.

Context routers attach to `api_router` here. Keep additions alphabetical.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health
from app.identity.router import router as identity_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(identity_router)

__all__ = ["api_router"]
