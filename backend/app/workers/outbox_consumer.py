"""Outbox consumer — dispatches undispatched events to in-process handlers.

This is the Arq job that realises the transactional-outbox pattern. Every
tick the worker claims a batch of undispatched rows from `outbox_events`,
runs each registered handler for the event type, inserts the event into
`events_archive`, and marks the outbox row dispatched. Failures increment
`attempts` and stash `last_error`; they retry on the next tick.

No concrete handlers are registered yet — this is the pre-wiring so that the
first context to care (identity, vehicles, ...) can subscribe without having
to build the spine first.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.platform.config import get_settings
from app.platform.db import build_engine, build_sessionmaker
from app.platform.events import DomainEvent
from app.platform.logging import configure_logging, get_logger
from app.platform.outbox import OutboxEvent, get_handlers
from app.workers import reservations as reservations_worker

logger = get_logger("app.workers.outbox")

BATCH_SIZE = 100


async def _dispatch_one(session: AsyncSession, row: OutboxEvent) -> None:
    # Reconstruct a DomainEvent from the stored payload. The base class is
    # enough for handler signatures; handlers that need concrete subclass
    # fields can re-parse from `row.payload` as needed.
    event = DomainEvent.model_validate(row.payload)

    for handler in get_handlers(row.event_type):
        await handler(event, session)

    # Archive to the partitioned events_archive table. Raw SQL because
    # partitioned tables don't play nicely with plain ORM inserts and we want
    # the archive path to be cheap.
    await session.execute(
        text(
            """
            INSERT INTO events_archive
                (id, event_type, aggregate_type, aggregate_id, tenant_id,
                 payload, occurred_at)
            VALUES
                (:id, :event_type, :aggregate_type, :aggregate_id, :tenant_id,
                 CAST(:payload AS jsonb), :occurred_at)
            """
        ),
        {
            "id": row.id,
            "event_type": row.event_type,
            "aggregate_type": row.aggregate_type,
            "aggregate_id": row.aggregate_id,
            "tenant_id": row.tenant_id,
            # asyncpg expects a string for JSONB params bound via text() —
            # SA's JSONB Column handles dict↔str automatically, but raw
            # parameters don't, so we serialise here.
            "payload": json.dumps(row.payload),
            "occurred_at": row.occurred_at,
        },
    )

    row.dispatched_at = datetime.now(UTC)


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Claim a batch and dispatch. Returns the number of events dispatched.

    Uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers can coexist.
    Each event is processed inside its own savepoint, so a single handler
    failure only reverts that event — the rest of the batch still commits.
    """
    dispatched = 0
    async with session_factory() as session, session.begin():
        result = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None))
            .order_by(OutboxEvent.occurred_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars())

        for row in rows:
            try:
                async with session.begin_nested():
                    await _dispatch_one(session, row)
                dispatched += 1
            except Exception as exc:
                logger.exception(
                    "outbox_handler_failed",
                    event_type=row.event_type,
                    event_id=str(row.id),
                )
                # Savepoint already rolled back; use a fresh one for the
                # attempts/error update so it survives the outer commit.
                async with session.begin_nested():
                    await session.execute(
                        update(OutboxEvent)
                        .where(OutboxEvent.id == row.id)
                        .values(
                            attempts=OutboxEvent.attempts + 1,
                            last_error=str(exc)[:1000],
                        )
                    )

    if dispatched:
        logger.info("outbox_batch_dispatched", count=dispatched)
    return dispatched


async def tick(ctx: dict[str, Any]) -> int:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    return await run_once(session_factory)


async def reservation_expiry_tick(ctx: dict[str, Any]) -> int:
    """Cron entry point that expires past-due marketplace reservations.

    The job is in its own module (`app.workers.reservations`) so the
    business logic is unit-testable without standing up arq. This thin
    shim adapts the arq context shape.
    """
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    return await reservations_worker.run_once(session_factory)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = build_engine(settings)
    ctx["engine"] = engine
    ctx["session_factory"] = build_sessionmaker(engine)
    logger.info("outbox_worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    logger.info("outbox_worker_stopped")


def _poll_seconds() -> set[int]:
    """Outbox poll cadence — fresh set every call so arq.cron() owns its own.

    `tick` fires every 5 seconds (12× per minute). Arq cron matches exact
    second values, so we hand it the full set rather than trying to
    express "every 5s" as a delta. Keep this cadence in sync with any SLA
    on event→reader latency. Returned as a new set per call so callers
    can't accidentally mutate a module-level singleton arq is using.
    """
    return set(range(0, 60, 5))


POLL_SECONDS: frozenset[int] = frozenset(_poll_seconds())
"""Immutable cadence constant, exposed for test assertions."""


class WorkerSettings:
    """Arq worker entry point.

    Run with:
        arq app.workers.outbox_consumer.WorkerSettings
    """

    functions: ClassVar[list[Any]] = [tick, reservation_expiry_tick]
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(
            tick,
            name="outbox_tick",
            second=_poll_seconds(),
            run_at_startup=True,
            # Per-fire timeout. If a single tick takes longer than this,
            # Arq cancels it and retries on the next schedule slot.
            timeout=30,
            # keep_result=0 → don't bloat Redis with per-tick job results,
            # we don't consult them from anywhere.
            keep_result=0,
        ),
        cron(
            reservation_expiry_tick,
            name="reservation_expiry_tick",
            # Once a minute is plenty — reservations have hour-scale TTLs.
            # second=0 is the deterministic minute boundary; arq doesn't
            # mind if multiple ticks coincide.
            second={0},
            run_at_startup=True,
            timeout=30,
            keep_result=0,
        ),
    ]

    @property
    def redis_settings(self) -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url_str)
