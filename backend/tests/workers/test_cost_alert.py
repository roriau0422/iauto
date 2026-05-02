"""Cost-alert cron tests.

The aggregation queries are exercised directly against the test
session; the orchestration logic in `run_once` is tested with a
fake session factory + monkeypatched dependencies so we don't need
to coerce the savepoint-bound conftest connection into an
`async_sessionmaker`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from arq.cron import CronJob
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.models import AiSpendEvent
from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import Settings
from app.workers import cost_alert as cost_alert_worker
from app.workers.outbox_consumer import WorkerSettings, ai_cost_alert_tick


def test_cost_alert_cron_registered() -> None:
    """The cost-alert cron must be in WorkerSettings."""
    jobs = WorkerSettings.cron_jobs
    matches = [j for j in jobs if isinstance(j, CronJob) and j.name == "ai_cost_alert_tick"]
    assert len(matches) == 1
    job = matches[0]
    assert job.coroutine is ai_cost_alert_tick
    assert set(job.hour) == {5}
    assert set(job.minute) == {0}


def test_alert_body_fits_messagepro_budget() -> None:
    """MessagePro auto-appends ' Navi market' (12 chars). Body must
    fit in 168 chars to leave room and not be silently truncated."""
    body = cost_alert_worker._build_alert_body(
        total_micro_mnt=10_000_000_000, budget_micro_mnt=5_000_000_000
    )
    assert len(body) <= 168
    assert "10,000" in body
    assert "5,000" in body


async def _seed_spend(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    micro_mnt: int,
    age_hours: float = 0.5,
) -> None:
    db_session.add(
        AiSpendEvent(
            user_id=user_id,
            session_id=None,
            model="gemini/gemini-3-flash-preview",
            prompt_tokens=0,
            completion_tokens=0,
            audio_seconds=0,
            est_cost_micro_mnt=micro_mnt,
            created_at=datetime.now(UTC) - timedelta(hours=age_hours),
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_trailing_24h_total_excludes_old_rows(db_session: AsyncSession) -> None:
    user = User(phone="+97688119901", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()

    await _seed_spend(db_session, user_id=user.id, micro_mnt=42, age_hours=0.5)
    await _seed_spend(db_session, user_id=user.id, micro_mnt=999_999, age_hours=72)

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    total = await cost_alert_worker._trailing_24h_total(db_session, cutoff)
    assert total == 42

    per_model = await cost_alert_worker._trailing_24h_per_model(db_session, cutoff)
    assert per_model == {"gemini/gemini-3-flash-preview": 42}


class _FakeSessionCm:
    """Shim that yields the test's AsyncSession from the factory.

    The cron's `run_once` opens `async with session_factory() as session`
    and runs read-only queries — no explicit `session.begin()`. The
    fake just returns the existing session so seeded rows are visible
    inside the savepoint.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_a: Any) -> None:
        return None


def _factory_for(session: AsyncSession) -> Any:
    def _factory() -> _FakeSessionCm:
        return _FakeSessionCm(session)

    return _factory


@pytest.mark.asyncio
async def test_below_budget_no_sms_sent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    user = User(phone="+97688119902", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    await _seed_spend(db_session, user_id=user.id, micro_mnt=100_000)

    sms_log = InMemorySmsProvider()
    monkeypatch.setattr(cost_alert_worker, "make_sms_provider", lambda _s: sms_log)
    monkeypatch.setattr(
        cost_alert_worker,
        "get_settings",
        lambda: settings.model_copy(
            update={
                "ai_daily_spend_budget_micro_mnt": 1_000_000,
                "operator_phone": "+97688119000",
                "messagepro_api_key": "fake",
            }
        ),
    )

    total = await cost_alert_worker.run_once(_factory_for(db_session))
    assert total == 100_000
    assert sms_log.sent == []


@pytest.mark.asyncio
async def test_over_budget_pages_operator(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    user = User(phone="+97688119903", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    await _seed_spend(db_session, user_id=user.id, micro_mnt=10_000_000)

    sms_log = InMemorySmsProvider()
    monkeypatch.setattr(cost_alert_worker, "make_sms_provider", lambda _s: sms_log)
    monkeypatch.setattr(
        cost_alert_worker,
        "get_settings",
        lambda: settings.model_copy(
            update={
                "ai_daily_spend_budget_micro_mnt": 1_000_000,
                "operator_phone": "+97688119000",
                "messagepro_api_key": "fake",
            }
        ),
    )

    total = await cost_alert_worker.run_once(_factory_for(db_session))
    assert total == 10_000_000
    assert len(sms_log.sent) == 1
    to, body = sms_log.sent[0]
    assert to == "+97688119000"
    assert "iAuto AI" in body


@pytest.mark.asyncio
async def test_over_budget_skips_sms_when_creds_missing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    user = User(phone="+97688119904", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    await _seed_spend(db_session, user_id=user.id, micro_mnt=99_999_999)

    factory_calls: list[tuple[Any, ...]] = []

    def _fake_factory(*a: Any, **k: Any) -> InMemorySmsProvider:
        factory_calls.append((a, k))
        return InMemorySmsProvider()

    monkeypatch.setattr(cost_alert_worker, "make_sms_provider", _fake_factory)
    monkeypatch.setattr(
        cost_alert_worker,
        "get_settings",
        lambda: settings.model_copy(
            update={
                "ai_daily_spend_budget_micro_mnt": 1,
                "operator_phone": "",
                "messagepro_api_key": "",
            }
        ),
    )

    total = await cost_alert_worker.run_once(_factory_for(db_session))
    assert total == 99_999_999
    # No SMS factory call when destination is unset.
    assert factory_calls == []


@pytest.mark.asyncio
async def test_zero_budget_disables_alert(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    """`ai_daily_spend_budget_micro_mnt = 0` means 'cron logs but never
    pages'. Useful when the operator wants the daily summary without
    the SMS overhead."""

    user = User(phone="+97688119905", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    await _seed_spend(db_session, user_id=user.id, micro_mnt=99_999_999)

    sms_log = InMemorySmsProvider()
    monkeypatch.setattr(cost_alert_worker, "make_sms_provider", lambda _s: sms_log)
    monkeypatch.setattr(
        cost_alert_worker,
        "get_settings",
        lambda: settings.model_copy(update={"ai_daily_spend_budget_micro_mnt": 0}),
    )

    total = await cost_alert_worker.run_once(_factory_for(db_session))
    assert total == 99_999_999
    assert sms_log.sent == []
