"""Arq job that expires past-due reservations.

Runs every minute. Each tick claims a batch of `active` reservations whose
`expires_at` is in the past, flips them to `expired`, and writes a
`marketplace.reservation_expired` outbox event for each so the analytics
pipeline + (eventual) push-notification consumer can react.

The transaction discipline mirrors the outbox consumer: one batch per
tick, `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers coexist,
all writes inside a single `session.begin()`. If anything inside the tick
raises, the transaction rolls back and the next tick re-claims the same
rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.marketplace.events import ReservationExpired
from app.marketplace.repository import ReservationRepository
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event

logger = get_logger("app.workers.reservations")

EXPIRY_BATCH_SIZE = 200


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Claim and expire one batch. Returns count flipped."""
    expired_count = 0
    async with session_factory() as session, session.begin():
        repo = ReservationRepository(session)
        rows = await repo.claim_expired(now=datetime.now(UTC), batch_size=EXPIRY_BATCH_SIZE)
        for row in rows:
            write_outbox_event(
                session,
                ReservationExpired(
                    aggregate_id=row.id,
                    tenant_id=row.tenant_id,
                    quote_id=row.quote_id,
                    part_search_id=row.part_search_id,
                    driver_id=row.driver_id,
                ),
            )
            expired_count += 1
    if expired_count:
        logger.info("reservations_expired", count=expired_count)
    return expired_count


async def tick(ctx: dict[str, Any]) -> int:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    return await run_once(session_factory)
