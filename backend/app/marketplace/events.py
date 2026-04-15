"""Domain events emitted by the marketplace context.

Events are the fuel for the data flywheel. Emit them even when no
subscriber reads them yet — ARCHITECTURE.md decision 3.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from app.platform.events import DomainEvent


class PartSearchSubmitted(DomainEvent):
    """A driver submitted an RFQ for parts that fit one of their vehicles.

    Brand / model FKs are denormalized onto the payload so downstream
    routing (session 5's incoming feed) doesn't need to re-join against
    vehicles at read time.
    """

    event_type: Literal["marketplace.part_search_submitted"] = (
        "marketplace.part_search_submitted"
    )
    aggregate_type: Literal["part_search_request"] = "part_search_request"
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    vehicle_brand_id: uuid.UUID | None
    vehicle_model_id: uuid.UUID | None
    description: str
    media_urls: list[Any]


class PartSearchCancelled(DomainEvent):
    event_type: Literal["marketplace.part_search_cancelled"] = (
        "marketplace.part_search_cancelled"
    )
    aggregate_type: Literal["part_search_request"] = "part_search_request"
    driver_id: uuid.UUID
