"""Retrain cron tests.

The "skip when corpus is too thin" branch is what the test suite locks
down — running real CatBoost training in CI is overkill. We exercise
that path via a stand-in session factory that hands back an empty rows
list, which is the day-one production state.
"""

from __future__ import annotations

from typing import Any

import pytest
from arq.cron import CronJob

from app.workers import valuation as valuation_worker
from app.workers.outbox_consumer import WorkerSettings, valuation_retrain_tick


def test_retrain_constants_sane() -> None:
    """Guards against accidental config drift."""
    assert valuation_worker.MIN_SAMPLES_FOR_TRAIN >= 10
    assert 0 < valuation_worker.HOLDOUT_FRACTION < 1
    assert valuation_worker.MODEL_BUCKET_KEY_PREFIX == "valuation-models"


def test_retrain_cron_registered() -> None:
    """The retrain cron must be in WorkerSettings — otherwise the worker
    boots without ever firing the job and the model never updates."""
    jobs = WorkerSettings.cron_jobs
    matches = [j for j in jobs if isinstance(j, CronJob) and j.name == "valuation_retrain_tick"]
    assert len(matches) == 1
    job = matches[0]
    assert job.coroutine is valuation_retrain_tick
    assert set(job.hour) == {2}
    assert set(job.minute) == {0}
    # Heavy CPU job — generous timeout but still bounded.
    assert 60 < job.timeout_s <= 3600


@pytest.mark.asyncio
async def test_retrain_skips_when_no_sales(monkeypatch: pytest.MonkeyPatch) -> None:
    """No sale rows → cron should bail out and return 0 without ever
    pulling in catboost.

    `run_once` opens its own session from the factory; the savepoint
    fixture's bind isn't reusable as an `AsyncEngine`, so we monkeypatch
    the gather-rows helper instead. That's the cleanest seam — the rest
    of the cron is validated by the model-promotion unit tests in
    test_service.py.
    """

    async def _fake_gather(_session: Any) -> list[Any]:
        return []

    monkeypatch.setattr(valuation_worker, "_gather_training_rows", _fake_gather)

    class _FakeAsyncCM:
        async def __aenter__(self) -> "object":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        def begin(self) -> "_FakeAsyncCM":
            return self

    def _factory() -> _FakeAsyncCM:
        return _FakeAsyncCM()

    promoted = await valuation_worker.run_once(_factory)  # type: ignore[arg-type]
    assert promoted == 0
