"""HTTP schemas for the payments context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.payments.models import PaymentIntentStatus


class PaymentIntentCreateIn(BaseModel):
    sale_id: uuid.UUID


class PaymentIntentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    sale_id: uuid.UUID
    amount_mnt: int
    currency: str
    qpay_invoice_id: str | None
    sender_invoice_no: str
    status: PaymentIntentStatus
    last_qpay_status: str | None
    created_at: datetime
    updated_at: datetime
    settled_at: datetime | None


class PaymentIntentCreatedOut(BaseModel):
    """Response for `POST /v1/payments/intents`.

    Echoes the intent plus the QPay-issued payment surface (QR code text
    + deeplink) so the client can immediately render either form factor.
    Both fields are nullable because in dev with a fake QPay client we
    skip the real network round-trip.
    """

    intent: PaymentIntentOut
    qr_text: str | None = None
    qr_image_base64: str | None = None
    deeplink: str | None = None
    urls: list[dict[str, Any]] | None = None


class PaymentCheckOut(BaseModel):
    intent: PaymentIntentOut
    qpay_status: str | None
