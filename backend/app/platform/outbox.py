"""Transactional outbox: ORM model + the helper that services call.

Every domain mutation is expected to call `write_outbox_event` through the
same `AsyncSession` that performed the mutation. The row lands in the
`outbox_events` table inside the same transaction — if the domain insert
rolls back, the outbox row goes with it.

A separate Arq worker (app.workers.outbox_consumer) polls `outbox_events`,
runs registered in-process handlers for each event type, appends to
`events_archive`, and marks the row dispatched.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base
from app.platform.events import DomainEvent
from app.platform.ids import new_id


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


def write_outbox_event(session: AsyncSession, event: DomainEvent) -> OutboxEvent:
    """Append a domain event to the outbox on the caller's session.

    The caller is responsible for the surrounding transaction; this function
    only stages the row. If the caller's transaction rolls back, the outbox
    row rolls back with it, which is exactly the desired guarantee.
    """
    row = OutboxEvent(
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        tenant_id=event.tenant_id,
        payload=event.model_dump(mode="json"),
        occurred_at=event.occurred_at,
    )
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# In-process handler registry.
# Consumers call `register_handler` at import time to subscribe to events.
# The outbox worker uses `get_handlers` when dispatching.
# ---------------------------------------------------------------------------

EventHandler = Callable[[DomainEvent, AsyncSession], Awaitable[None]]

_handlers: dict[str, list[EventHandler]] = {}


def register_handler(event_type: str, handler: EventHandler) -> None:
    _handlers.setdefault(event_type, []).append(handler)


def get_handlers(event_type: str) -> list[EventHandler]:
    return list(_handlers.get(event_type, ()))


def clear_handlers() -> None:
    """Test-only helper: wipe the handler registry."""
    _handlers.clear()
