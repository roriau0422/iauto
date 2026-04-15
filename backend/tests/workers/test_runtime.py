"""Outbox-worker runtime/lifecycle coverage.

`tests/platform/test_outbox.py` already exercises `run_once()` end-to-end
against a real DB engine. This file plugs the remaining gap identified in
session 1's review: whether the Arq entry point (`WorkerSettings`, the
`startup`/`shutdown` lifecycle hooks, the polling cron schedule) is itself
correctly wired. Without this, `arq app.workers.outbox_consumer.WorkerSettings`
can boot into an idle state where `tick` is defined but never fires.
"""

from __future__ import annotations

import uuid

import pytest
from arq.connections import RedisSettings
from arq.cron import CronJob
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.events import DomainEvent
from app.platform.outbox import (
    OutboxEvent,
    clear_handlers,
    register_handler,
    write_outbox_event,
)
from app.workers.outbox_consumer import (
    POLL_SECONDS,
    WorkerSettings,
    shutdown,
    startup,
    tick,
)


class _PingEvent(DomainEvent):
    event_type: str = "tests.worker_runtime_ping"
    aggregate_type: str = "tests"


# ---------------------------------------------------------------------------
# WorkerSettings shape — no DB needed
# ---------------------------------------------------------------------------


def test_worker_settings_declares_tick_function() -> None:
    assert tick in WorkerSettings.functions


def test_worker_settings_has_polling_cron() -> None:
    """The spine is useless without a schedule that actually fires tick.

    `cron_jobs = []` would boot the worker into an idle state, which was
    the exact regression session 1 flagged as a follow-up."""
    jobs = WorkerSettings.cron_jobs
    assert len(jobs) >= 1
    outbox_jobs = [j for j in jobs if isinstance(j, CronJob) and j.name == "outbox_tick"]
    assert len(outbox_jobs) == 1
    job = outbox_jobs[0]
    # The cron must cover the full `POLL_SECONDS` set so skew between
    # machine clocks can't accidentally miss a window.
    assert set(job.second) == set(POLL_SECONDS)
    assert job.run_at_startup is True
    assert job.coroutine is tick


def test_worker_settings_redis_settings_is_valid() -> None:
    """`redis_settings` is a property — if the accessor crashes on import
    the worker boots into a stack trace, so we exercise it here."""
    rs = WorkerSettings().redis_settings
    assert isinstance(rs, RedisSettings)
    assert rs.host  # non-empty
    assert rs.port > 0


# ---------------------------------------------------------------------------
# startup / tick / shutdown lifecycle — against the real test DB
# ---------------------------------------------------------------------------


async def test_startup_tick_shutdown_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    """Boot the worker's lifecycle hooks the way Arq would and dispatch
    one real event through the ctx-built session factory.

    We can't reuse the fixture's transactional session because `startup()`
    builds its own engine — that's the whole point of testing it. Instead,
    we point `DATABASE_URL` at the test DB (the same DB the fixture uses,
    just without the rollback-only outer transaction) and manually clean
    up the rows we insert.
    """
    test_db_url = settings.database_test_url_str
    if test_db_url is None:
        pytest.skip("DATABASE_TEST_URL not configured")

    # `startup()` calls `get_settings()` internally, and `get_settings()`
    # is lru_cached. Swap the env var and bust the cache so the engine
    # it builds points at the test DB.
    from app.platform.config import get_settings as _get_settings

    monkeypatch.setenv("DATABASE_URL", test_db_url)
    _get_settings.cache_clear()

    received: list[DomainEvent] = []

    async def _handler(event: DomainEvent, _session: AsyncSession) -> None:
        received.append(event)

    register_handler("tests.worker_runtime_ping", _handler)

    ctx: dict[str, object] = {}
    aggregate_id = uuid.uuid4()

    try:
        await startup(ctx)
        assert "engine" in ctx
        assert "session_factory" in ctx
        session_factory = ctx["session_factory"]

        # Seed an outbox row via the worker's own session factory — this
        # is what proves `startup()` built something that can actually
        # write to the DB.
        async with session_factory() as session, session.begin():  # type: ignore[operator]
            write_outbox_event(
                session,
                _PingEvent(aggregate_id=aggregate_id),
            )

        dispatched = await tick(ctx)
        assert dispatched >= 1
        assert any(e.aggregate_id == aggregate_id for e in received)

        # Confirm the archive row made it through the full pipeline.
        async with session_factory() as check:  # type: ignore[operator]
            outbox_row = (
                await check.execute(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == aggregate_id)
                )
            ).scalar_one()
            assert outbox_row.dispatched_at is not None

            archive_count = (
                await check.execute(
                    text("SELECT COUNT(*) FROM events_archive WHERE aggregate_id = :aid"),
                    {"aid": str(aggregate_id)},
                )
            ).scalar_one()
            assert archive_count == 1
    finally:
        # Clean up both tables before restoring the engine — the rows are
        # committed (not savepoint-rolled-back) so the fixture won't sweep
        # them for us.
        try:
            session_factory = ctx.get("session_factory")
            if session_factory is not None:
                async with session_factory() as cleanup, cleanup.begin():  # type: ignore[operator]
                    await cleanup.execute(
                        text("DELETE FROM events_archive WHERE aggregate_id = :aid"),
                        {"aid": str(aggregate_id)},
                    )
                    await cleanup.execute(
                        text("DELETE FROM outbox_events WHERE aggregate_id = :aid"),
                        {"aid": aggregate_id},
                    )
        finally:
            await shutdown(ctx)
            clear_handlers()
            _get_settings.cache_clear()
