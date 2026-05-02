"""Outbox subscribers for the notifications context.

Each handler maps a domain event to a `NotificationsService.dispatch`
call. Body text is human-readable English for now; localization lands
when the mobile app ships and we know the language preference of each
user.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.providers import ConsolePushProvider
from app.notifications.service import NotificationsService
from app.platform.events import DomainEvent
from app.platform.logging import get_logger
from app.platform.outbox import register_handler

logger = get_logger("app.notifications.handlers")


def _build_service(session: AsyncSession) -> NotificationsService:
    return NotificationsService(session=session, provider=ConsolePushProvider())


def _to_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def on_quote_sent(event: DomainEvent, session: AsyncSession) -> None:
    """Notify the driver that a business sent them a quote."""
    payload = event.model_dump(mode="json")
    driver_id = _to_uuid(payload.get("driver_id"))
    if driver_id is None:
        return
    service = _build_service(session)
    await service.dispatch(
        user_id=driver_id,
        kind="quote_sent",
        body_text=f"You received a quote for {payload.get('price_mnt', '?')} MNT.",
        payload={
            "quote_id": str(event.aggregate_id),
            "part_search_id": payload.get("part_search_id"),
        },
    )


async def on_reservation_started(event: DomainEvent, session: AsyncSession) -> None:
    payload = event.model_dump(mode="json")
    driver_id = _to_uuid(payload.get("driver_id"))
    if driver_id is None:
        return
    service = _build_service(session)
    await service.dispatch(
        user_id=driver_id,
        kind="reservation_started",
        body_text="Your reservation is active for 24 hours.",
        payload={"reservation_id": str(event.aggregate_id)},
    )


async def on_sale_completed(event: DomainEvent, session: AsyncSession) -> None:
    payload = event.model_dump(mode="json")
    driver_id = _to_uuid(payload.get("driver_id"))
    if driver_id is None:
        return
    service = _build_service(session)
    await service.dispatch(
        user_id=driver_id,
        kind="sale_completed",
        body_text="Your purchase is marked complete. Leave a review!",
        payload={"sale_id": str(event.aggregate_id)},
    )


async def on_review_submitted(event: DomainEvent, session: AsyncSession) -> None:
    payload = event.model_dump(mode="json")
    author_id = _to_uuid(payload.get("author_user_id"))
    if author_id is None:
        return
    service = _build_service(session)
    # Author ack — confirms their review landed.
    await service.dispatch(
        user_id=author_id,
        kind="review_submitted",
        body_text="Thanks for your review.",
        payload={"sale_id": payload.get("sale_id")},
    )


async def on_payment_settled(event: DomainEvent, session: AsyncSession) -> None:
    payload = event.model_dump(mode="json")
    # The driver is the payer; we want to ack that the payment landed.
    sale_id = _to_uuid(payload.get("sale_id"))
    if sale_id is None:
        return
    # Look up the sale to find the driver_id (the event payload doesn't
    # carry it — events.py keeps PaymentSettled small on purpose).
    from app.marketplace.repository import SaleRepository

    sales = SaleRepository(session)
    sale = await sales.get_by_id(sale_id)
    if sale is None:
        return
    service = _build_service(session)
    await service.dispatch(
        user_id=sale.driver_id,
        kind="payment_settled",
        body_text=f"Payment of {payload.get('amount_mnt', '?')} MNT received.",
        payload={"sale_id": str(sale_id), "intent_id": str(event.aggregate_id)},
    )


def register() -> None:
    """Register all notifications outbox handlers."""
    register_handler("marketplace.quote_sent", on_quote_sent)
    register_handler("marketplace.reservation_started", on_reservation_started)
    register_handler("marketplace.sale_completed", on_sale_completed)
    register_handler("marketplace.review_submitted", on_review_submitted)
    register_handler("payments.payment_settled", on_payment_settled)
