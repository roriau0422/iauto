"""Domain events emitted by the marketplace context.

Events are the fuel for the data flywheel. Emit them even when no
subscriber reads them yet — ARCHITECTURE.md decision 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from app.platform.events import DomainEvent


class PartSearchSubmitted(DomainEvent):
    """A driver submitted an RFQ for parts that fit one of their vehicles.

    Brand / model FKs are denormalized onto the payload so downstream
    routing (session 5's incoming feed) doesn't need to re-join against
    vehicles at read time.
    """

    event_type: Literal["marketplace.part_search_submitted"] = "marketplace.part_search_submitted"
    aggregate_type: Literal["part_search_request"] = "part_search_request"
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    vehicle_brand_id: uuid.UUID | None
    vehicle_model_id: uuid.UUID | None
    description: str
    media_asset_ids: list[Any]


class PartSearchCancelled(DomainEvent):
    event_type: Literal["marketplace.part_search_cancelled"] = "marketplace.part_search_cancelled"
    aggregate_type: Literal["part_search_request"] = "part_search_request"
    driver_id: uuid.UUID


class QuoteSent(DomainEvent):
    """A business submitted a price quote against a driver's part search.

    `aggregate_id` = quote.id; `tenant_id` = business_id. Downstream
    subscribers (session 8 chat auto-thread, session 6 reservation
    conversion, analytics flywheel) pick this up via the outbox worker.
    `condition` is the string form of `QuoteCondition` so the archived
    event stays decoupled from the enum type.
    """

    event_type: Literal["marketplace.quote_sent"] = "marketplace.quote_sent"
    aggregate_type: Literal["quote"] = "quote"
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    price_mnt: int
    condition: str


# ---------------------------------------------------------------------------
# Session 6 — reservations, sales, reviews
# ---------------------------------------------------------------------------


class ReservationStarted(DomainEvent):
    event_type: Literal["marketplace.reservation_started"] = "marketplace.reservation_started"
    aggregate_type: Literal["reservation"] = "reservation"
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    expires_at: datetime
    price_mnt: int


class ReservationCancelled(DomainEvent):
    event_type: Literal["marketplace.reservation_cancelled"] = "marketplace.reservation_cancelled"
    aggregate_type: Literal["reservation"] = "reservation"
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID


class ReservationExpired(DomainEvent):
    """Emitted by the Arq cron when a hold runs past `expires_at`.

    `tenant_id` is set on the envelope so the analytics consumer can
    bucket expirations by business without joining against the row.
    """

    event_type: Literal["marketplace.reservation_expired"] = "marketplace.reservation_expired"
    aggregate_type: Literal["reservation"] = "reservation"
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID


class SaleCompleted(DomainEvent):
    event_type: Literal["marketplace.sale_completed"] = "marketplace.sale_completed"
    aggregate_type: Literal["sale"] = "sale"
    reservation_id: uuid.UUID
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    price_mnt: int


class ReviewSubmitted(DomainEvent):
    event_type: Literal["marketplace.review_submitted"] = "marketplace.review_submitted"
    aggregate_type: Literal["review"] = "review"
    sale_id: uuid.UUID
    direction: str
    author_user_id: uuid.UUID
    rating: int
