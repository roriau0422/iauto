"""Valuation service — predict, audit, expose model-registry helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.logging import get_logger
from app.valuation.models import ValuationModel
from app.valuation.models_runtime import (
    HeuristicValuationModel,
    ValuationPrediction,
    ValuationRuntime,
)
from app.valuation.repository import (
    ValuationEstimateRepository,
    ValuationModelRepository,
)
from app.valuation.schemas import ValuationEstimateIn

logger = get_logger("app.valuation.service")


@dataclass(slots=True)
class ValuationResult:
    prediction: ValuationPrediction
    model_version: str
    is_heuristic_fallback: bool


class ValuationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        runtime: ValuationRuntime,
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.models = ValuationModelRepository(session)
        self.estimates = ValuationEstimateRepository(session)

    async def estimate(
        self,
        *,
        user_id: uuid.UUID | None,
        payload: ValuationEstimateIn,
    ) -> ValuationResult:
        features: dict[str, Any] = payload.model_dump(mode="json", exclude_none=False)
        prediction = self.runtime.predict(features=features)

        active = await self.models.get_active()
        is_fallback = isinstance(self.runtime, HeuristicValuationModel) or active is None

        await self.estimates.create(
            user_id=user_id,
            model_id=active.id if active is not None else None,
            features=features,
            predicted_mnt=prediction.predicted_mnt,
            low_mnt=prediction.low_mnt,
            high_mnt=prediction.high_mnt,
        )
        version = active.version if active is not None else self.runtime.version
        logger.info(
            "valuation_estimated",
            user_id=str(user_id) if user_id else None,
            predicted_mnt=prediction.predicted_mnt,
            model_version=version,
            is_fallback=is_fallback,
        )
        return ValuationResult(
            prediction=prediction,
            model_version=version,
            is_heuristic_fallback=is_fallback,
        )

    async def get_active_model(self) -> ValuationModel | None:
        return await self.models.get_active()
