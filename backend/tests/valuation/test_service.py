"""Service-level tests for the valuation context.

These cover the served path — heuristic prediction with audit row,
fallback flag toggling, and active-model promotion via the repo. The
real CatBoost trainer cron is exercised with a tiny fake corpus in
test_worker.py; here we keep the runtime stub deterministic so the
tests stay fast and don't pull in catboost at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.marketplace.models import QuoteCondition
from app.valuation.models import (
    ValuationEstimate,
    ValuationModel,
    ValuationModelStatus,
)
from app.valuation.models_runtime import (
    HeuristicValuationModel,
    ValuationPrediction,
    ValuationRuntime,
)
from app.valuation.repository import ValuationModelRepository
from app.valuation.schemas import ValuationEstimateIn
from app.valuation.service import ValuationService


class StubBoosterRuntime:
    """Stand-in for `CatBoostValuationModel` that doesn't need catboost."""

    version = "stub-catboost-v1"

    def __init__(self, predicted_mnt: int = 22_000_000) -> None:
        self._predicted = predicted_mnt

    def predict(self, *, features: dict[str, object]) -> ValuationPrediction:
        return ValuationPrediction(
            predicted_mnt=self._predicted,
            low_mnt=int(self._predicted * 0.9),
            high_mnt=int(self._predicted * 1.1),
        )


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


def _payload() -> ValuationEstimateIn:
    return ValuationEstimateIn(
        vehicle_brand_id=uuid.uuid4(),
        vehicle_model_id=uuid.uuid4(),
        build_year=2018,
        mileage_km=120_000,
        fuel_type="petrol",
        condition=QuoteCondition.used,
    )


def test_heuristic_band_is_well_formed() -> None:
    """Heuristic returns deterministic, monotonically-ordered values."""
    runtime = HeuristicValuationModel()
    out = runtime.predict(
        features={
            "build_year": 2015,
            "mileage_km": 200_000,
            "condition": "used",
        }
    )
    assert out.low_mnt < out.predicted_mnt < out.high_mnt
    # Floor — never quote less than 2M MNT, even on garbage input.
    junk = runtime.predict(
        features={"build_year": 1980, "mileage_km": 5_000_000, "condition": "used"}
    )
    assert junk.predicted_mnt >= 2_000_000


def test_new_condition_outprices_used() -> None:
    """Sanity check on the condition factor sign."""
    runtime = HeuristicValuationModel()
    used = runtime.predict(features={"build_year": 2022, "mileage_km": 10_000, "condition": "used"})
    new = runtime.predict(features={"build_year": 2022, "mileage_km": 10_000, "condition": "new"})
    assert new.predicted_mnt > used.predicted_mnt


@pytest.mark.asyncio
async def test_estimate_persists_audit_row_and_flags_fallback(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "+97688118801")
    runtime: ValuationRuntime = HeuristicValuationModel()
    service = ValuationService(session=db_session, runtime=runtime)

    result = await service.estimate(user_id=user.id, payload=_payload())

    # Heuristic served + no active row → fallback flag is on.
    assert result.is_heuristic_fallback is True
    assert result.model_version == "heuristic-v1"
    assert result.prediction.low_mnt < result.prediction.predicted_mnt
    assert result.prediction.predicted_mnt < result.prediction.high_mnt

    # Audit row written.
    rows = (await db_session.execute(select(ValuationEstimate))).scalars().all()
    assert len(rows) == 1
    audit = rows[0]
    assert audit.user_id == user.id
    assert audit.predicted_mnt == result.prediction.predicted_mnt
    assert audit.features["build_year"] == 2018
    assert audit.features["condition"] == "used"
    # No active model yet → audit's model_id is null.
    assert audit.model_id is None


@pytest.mark.asyncio
async def test_active_promotion_demotes_previous(db_session: AsyncSession) -> None:
    repo = ValuationModelRepository(db_session)
    first = await repo.create(
        version="v1",
        sample_count=100,
        mae_mnt=3_000_000,
        artifact_object_key="valuation-models/v1.cbm",
        feature_columns=["build_year"],
    )
    await repo.promote(model_id=first.id)

    second = await repo.create(
        version="v2",
        sample_count=200,
        mae_mnt=2_500_000,
        artifact_object_key="valuation-models/v2.cbm",
        feature_columns=["build_year"],
    )
    await repo.promote(model_id=second.id)

    # Exactly one active row, and it's the second one.
    actives = (
        (
            await db_session.execute(
                select(ValuationModel).where(ValuationModel.status == ValuationModelStatus.active)
            )
        )
        .scalars()
        .all()
    )
    assert len(actives) == 1
    assert actives[0].version == "v2"

    # First was demoted to retired (not deleted).
    retired = await db_session.get(ValuationModel, first.id)
    assert retired is not None
    assert retired.status == ValuationModelStatus.retired


@pytest.mark.asyncio
async def test_estimate_uses_active_model_when_present(
    db_session: AsyncSession,
) -> None:
    """When an active row exists AND the runtime is non-heuristic, the
    fallback flag flips off and the audit row points at the model."""
    user = await _make_user(db_session, "+97688118802")
    repo = ValuationModelRepository(db_session)
    row = await repo.create(
        version="stub-catboost-v1",
        sample_count=500,
        mae_mnt=2_800_000,
        artifact_object_key="valuation-models/stub.cbm",
        feature_columns=["build_year", "mileage_km"],
    )
    await repo.promote(model_id=row.id)

    service = ValuationService(session=db_session, runtime=StubBoosterRuntime())
    result = await service.estimate(user_id=user.id, payload=_payload())

    assert result.is_heuristic_fallback is False
    assert result.model_version == "stub-catboost-v1"
    assert result.prediction.predicted_mnt == 22_000_000

    # Audit row is wired to the active model.
    audit = (await db_session.execute(select(ValuationEstimate))).scalars().one()
    assert audit.model_id == row.id


@pytest.mark.asyncio
async def test_estimate_anonymous_user_id_allowed(db_session: AsyncSession) -> None:
    """The schema allows anonymous estimates — audit row carries NULL user_id."""
    service = ValuationService(session=db_session, runtime=HeuristicValuationModel())
    result = await service.estimate(user_id=None, payload=_payload())
    assert result.prediction.predicted_mnt > 0

    audit = (await db_session.execute(select(ValuationEstimate))).scalars().one()
    assert audit.user_id is None


@pytest.mark.asyncio
async def test_get_active_model_none_when_unset(db_session: AsyncSession) -> None:
    service = ValuationService(session=db_session, runtime=HeuristicValuationModel())
    assert await service.get_active_model() is None
