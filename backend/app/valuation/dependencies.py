"""FastAPI dependencies for the valuation context."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.db import get_session
from app.valuation.models_runtime import HeuristicValuationModel, ValuationRuntime
from app.valuation.service import ValuationService


@lru_cache(maxsize=1)
def _build_runtime_singleton() -> ValuationRuntime:
    """Phase 4 ships with the heuristic until the retrain cron has
    produced a CatBoost artifact. The dependency override lets phase 5
    swap in the loaded CatBoost model at runtime without touching
    callers.
    """
    return HeuristicValuationModel()


def get_valuation_runtime() -> ValuationRuntime:
    return _build_runtime_singleton()


def get_valuation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    runtime: Annotated[ValuationRuntime, Depends(get_valuation_runtime)],
) -> ValuationService:
    return ValuationService(session=session, runtime=runtime)
