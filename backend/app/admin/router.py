"""HTTP routes for the admin context."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.admin.dependencies import get_admin_spend_service, require_admin
from app.admin.schemas import SpendReportOut
from app.admin.service import AdminSpendService
from app.identity.models import User

router = APIRouter(tags=["admin"])


@router.get(
    "/admin/spend",
    response_model=SpendReportOut,
    summary="Trailing-window AI spend report (admin only)",
)
async def spend_report(
    service: Annotated[AdminSpendService, Depends(get_admin_spend_service)],
    _admin: Annotated[User, Depends(require_admin)],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> SpendReportOut:
    return await service.report(window_hours=window_hours)
