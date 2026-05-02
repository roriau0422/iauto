"""Outbox subscribers for the vehicles context.

Today this owns one handler: when QPay settles a `vehicle_due_payment`
intent, flip the matching `vehicle_dues` row to `paid`. The handler
mutates `VehicleDue` directly via the repository to avoid spinning up a
full `VehiclesService` (which expects Redis + SMS + settings) inside an
event-loop hot path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.events import DomainEvent
from app.platform.logging import get_logger
from app.platform.outbox import register_handler, write_outbox_event
from app.vehicles.events import VehicleDuePaid
from app.vehicles.models import VehicleDueStatus
from app.vehicles.repository import VehicleDueRepository

logger = get_logger("app.vehicles.handlers")


def _to_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime:
    """Coerce an ISO-8601 string from the archived event payload to a tz-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


async def on_payment_settled(event: DomainEvent, session: AsyncSession) -> None:
    """When QPay confirms a due payment, flip the due to `paid`.

    Branches on the payload's `kind` field — `sale_payment` events are
    handled by the marketplace + notifications subscribers and we ignore
    them here.

    Idempotent: a due that's already `paid` short-circuits without
    re-emitting the `vehicles.due_paid` event.
    """
    payload = event.model_dump(mode="json")
    if payload.get("kind") != "vehicle_due_payment":
        return

    due_id = _to_uuid(payload.get("vehicle_due_id"))
    if due_id is None:
        logger.warning("vehicle_due_payment_missing_due_id", event_id=str(event.aggregate_id))
        return

    intent_id = _to_uuid(event.aggregate_id)
    if intent_id is None:
        return

    paid_at = _to_datetime(payload.get("settled_at"))

    dues = VehicleDueRepository(session)
    due = await dues.get_by_id(due_id)
    if due is None:
        logger.warning("vehicle_due_paid_for_unknown", due_id=str(due_id))
        return
    if due.status == VehicleDueStatus.paid:
        return

    due.status = VehicleDueStatus.paid
    due.paid_at = paid_at
    due.payment_intent_id = intent_id
    await session.flush()

    write_outbox_event(
        session,
        VehicleDuePaid(
            aggregate_id=due.id,
            vehicle_id=due.vehicle_id,
            payment_intent_id=intent_id,
            amount_mnt=due.amount_mnt,
            kind=due.kind.value,
        ),
    )
    logger.info(
        "vehicle_due_paid",
        due_id=str(due.id),
        kind=due.kind.value,
        amount_mnt=due.amount_mnt,
    )


def register() -> None:
    """Register the vehicles outbox subscribers."""
    register_handler("payments.payment_settled", on_payment_settled)
