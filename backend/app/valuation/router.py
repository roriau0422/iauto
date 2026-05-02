"""HTTP routes for the valuation context."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.platform.errors import NotFoundError
from app.valuation.dependencies import get_valuation_service
from app.valuation.schemas import (
    ValuationEstimateIn,
    ValuationEstimateOut,
    ValuationModelOut,
)
from app.valuation.service import ValuationService

router = APIRouter(tags=["valuation"])


@router.post(
    "/valuation/estimate",
    response_model=ValuationEstimateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Estimate a vehicle's market price (CatBoost or heuristic fallback)",
)
async def estimate(
    body: ValuationEstimateIn,
    service: Annotated[ValuationService, Depends(get_valuation_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> ValuationEstimateOut:
    result = await service.estimate(user_id=user.id, payload=body)
    return ValuationEstimateOut(
        predicted_mnt=result.prediction.predicted_mnt,
        low_mnt=result.prediction.low_mnt,
        high_mnt=result.prediction.high_mnt,
        model_version=result.model_version,
        is_heuristic_fallback=result.is_heuristic_fallback,
    )


@router.get(
    "/valuation/models/active",
    response_model=ValuationModelOut,
    summary="Return the currently-active CatBoost model row, if any",
)
async def active_model(
    service: Annotated[ValuationService, Depends(get_valuation_service)],
) -> ValuationModelOut:
    row = await service.get_active_model()
    if row is None:
        raise NotFoundError("No active valuation model — heuristic in use")
    return ValuationModelOut.model_validate(row)
