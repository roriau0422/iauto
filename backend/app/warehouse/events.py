"""Domain events emitted by the warehouse context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.platform.events import DomainEvent


class SkuCreated(DomainEvent):
    event_type: Literal["warehouse.sku_created"] = "warehouse.sku_created"
    aggregate_type: Literal["warehouse_sku"] = "warehouse_sku"
    sku_code: str
    display_name: str


class StockMoved(DomainEvent):
    """Inventory ledger entry posted.

    Subscribers: notifications handler that fires `warehouse_low_stock`
    push when `on_hand_after <= threshold`. Analytics flywheel can
    reconstruct on_hand history from these events without scanning the
    `warehouse_stock_movements` table at read time.
    """

    event_type: Literal["warehouse.stock_moved"] = "warehouse.stock_moved"
    aggregate_type: Literal["warehouse_stock_movement"] = "warehouse_stock_movement"
    sku_id: uuid.UUID
    kind: str
    quantity: int
    signed_quantity: int
    on_hand_after: int
    sale_id: uuid.UUID | None = None
