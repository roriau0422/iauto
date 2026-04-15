"""/v1/ API surface.

Context routers attach to `api_router` here. Keep additions alphabetical.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)

__all__ = ["api_router"]
