"""Domain events emitted by the payments context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.platform.events import DomainEvent


class PaymentIntentCreated(DomainEvent):
    event_type: Literal["payments.intent_created"] = "payments.intent_created"
    aggregate_type: Literal["payment_intent"] = "payment_intent"
    sale_id: uuid.UUID
    amount_mnt: int


class PaymentSettled(DomainEvent):
    """Emitted exactly once per intent when it transitions to `settled`.

    Idempotency: the service guards against a second emission by checking
    the prior status before flipping. Subscribers that fire side-effects
    (chat-thread auto-create, push notification, accounting export) can
    rely on at-most-once delivery per intent.
    """

    event_type: Literal["payments.payment_settled"] = "payments.payment_settled"
    aggregate_type: Literal["payment_intent"] = "payment_intent"
    sale_id: uuid.UUID
    amount_mnt: int
    settled_at: datetime


class PaymentFailed(DomainEvent):
    event_type: Literal["payments.payment_failed"] = "payments.payment_failed"
    aggregate_type: Literal["payment_intent"] = "payment_intent"
    sale_id: uuid.UUID
    reason: str
