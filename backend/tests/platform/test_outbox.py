"""Outbox round-trip tests.

We prove three things:
1. `write_outbox_event` stages a row that lands in `outbox_events` when the
   caller's transaction commits.
2. If the caller's transaction rolls back, the outbox row goes with it.
3. The worker `run_once` dispatches undispatched events, runs any registered
   handler, and writes to `events_archive`.
"""

from __future__ import annotations

import uuid
from typing import Literal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.platform.events import DomainEvent
from app.platform.outbox import (
    OutboxEvent,
    register_handler,
    write_outbox_event,
)
from app.workers.outbox_consumer import run_once


class _UserRegisteredEvent(DomainEvent):
    event_type: Literal["identity.user_registered"] = "identity.user_registered"
    aggregate_type: Literal["user"] = "user"
    phone_masked: str


async def test_write_outbox_event_lands_in_table(db_session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    event = _UserRegisteredEvent(
        aggregate_id=user_id,
        phone_masked="+976***10921",
    )

    row = write_outbox_event(db_session, event)
    await db_session.flush()

    found = (
        await db_session.execute(
            select(OutboxEvent).where(OutboxEvent.id == row.id)
        )
    ).scalar_one()

    assert found.event_type == "identity.user_registered"
    assert found.aggregate_type == "user"
    assert found.aggregate_id == user_id
    assert found.tenant_id is None
    assert found.dispatched_at is None
    assert found.attempts == 0
    assert found.payload["phone_masked"] == "+976***10921"
    assert found.payload["event_type"] == "identity.user_registered"


async def test_outbox_rollback_leaves_no_row(engine) -> None:
    # Use a disposable transaction on a fresh connection, not the shared
    # db_session fixture, so we can observe both the pre-rollback state and
    # the post-rollback state with a different session.
    user_id = uuid.uuid4()
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with factory() as session:
        await session.begin()
        write_outbox_event(
            session,
            _UserRegisteredEvent(aggregate_id=user_id, phone_masked="+976***00000"),
        )
        await session.flush()
        # Confirm it's staged inside the txn before we roll back.
        staged = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == user_id)
            )
        ).scalar_one_or_none()
        assert staged is not None
        await session.rollback()

    # Brand new session — verify the row is gone.
    async with factory() as verify:
        missing = (
            await verify.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == user_id)
            )
        ).scalar_one_or_none()
        assert missing is None


async def test_worker_dispatches_and_archives(engine) -> None:
    received: list[DomainEvent] = []

    async def _handler(event: DomainEvent, _session: AsyncSession) -> None:
        received.append(event)

    register_handler("identity.user_registered", _handler)

    user_id = uuid.uuid4()
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with factory() as session:
        write_outbox_event(
            session,
            _UserRegisteredEvent(
                aggregate_id=user_id,
                phone_masked="+976***11111",
            ),
        )
        await session.commit()

    try:
        dispatched = await run_once(factory)
        assert dispatched >= 1
        assert any(
            e.aggregate_id == user_id
            for e in received
        )

        async with factory() as check:
            outbox_row = (
                await check.execute(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == user_id)
                )
            ).scalar_one()
            assert outbox_row.dispatched_at is not None

            archive_count = (
                await check.execute(
                    text(
                        "SELECT COUNT(*) FROM events_archive "
                        "WHERE aggregate_id = :aid"
                    ),
                    {"aid": str(user_id)},
                )
            ).scalar_one()
            assert archive_count == 1
    finally:
        # Clean up the committed rows so later test runs start from a clean
        # archive. conftest's db_session fixture can't help here because we
        # intentionally committed outside of it.
        async with factory() as cleanup:
            await cleanup.execute(
                text("DELETE FROM events_archive WHERE aggregate_id = :aid"),
                {"aid": str(user_id)},
            )
            await cleanup.execute(
                text("DELETE FROM outbox_events WHERE aggregate_id = :aid"),
                {"aid": str(user_id)},
            )
            await cleanup.commit()


@pytest.mark.parametrize("extra_field", ["", "unknown"])
def test_event_type_is_frozen_literal(extra_field: str) -> None:
    # Subclasses must use Literal for event_type; attempting to instantiate
    # with a different event_type raises.
    with pytest.raises(ValueError):
        _UserRegisteredEvent(
            aggregate_id=uuid.uuid4(),
            phone_masked="+976***22222",
            event_type=f"identity.user_registered{extra_field}_wrong",  # type: ignore[arg-type]
        )
