"""ORM models for the payments context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


class PaymentIntentStatus(StrEnum):
    """Lifecycle of a QPay invoice attempt.

    - `pending`   — invoice exists at QPay; awaiting customer payment.
    - `settled`   — QPay reports paid; ledger debit/credit pair posted.
    - `failed`    — QPay reports a permanent failure (rare in practice).
    - `cancelled` — driver/business cancelled before settlement.
    - `expired`   — QPay invoice TTL elapsed without payment.
    """

    pending = "pending"
    settled = "settled"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


class PaymentEventKind(StrEnum):
    """What produced this `payment_events` row."""

    invoice_created = "invoice_created"
    callback = "callback"
    check = "check"
    status_change = "status_change"
    webhook_signature_failed = "webhook_signature_failed"


class LedgerAccount(StrEnum):
    """Account chart for the double-entry ledger.

    Kept narrow on purpose — every account here maps to a single
    accounting concept the platform owns. Adding new accounts is an
    additive migration; renaming or merging needs a migration that
    rewrites historical rows.
    """

    cash = "cash"
    business_revenue = "business_revenue"
    platform_fee = "platform_fee"
    refund_payable = "refund_payable"


class LedgerDirection(StrEnum):
    debit = "debit"
    credit = "credit"


class PaymentIntent(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """One QPay invoice attempt for a sale.

    Unique on `sale_id` for now — refunds will get their own `refunds`
    table later (additive migration). `sender_invoice_no` is unique
    too: that's the merchant-side idempotency key QPay deduplicates on.
    """

    __tablename__ = "payment_intents"

    sale_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_mnt: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="MNT")
    qpay_invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    qpay_invoice_code: Mapped[str] = mapped_column(Text, nullable=False)
    sender_invoice_no: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PaymentIntentStatus] = mapped_column(
        SAEnum(PaymentIntentStatus, name="payment_intent_status", native_enum=True),
        nullable=False,
        default=PaymentIntentStatus.pending,
    )
    last_qpay_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("sale_id", name="uq_payment_intents_sale_id"),
        UniqueConstraint("sender_invoice_no", name="uq_payment_intents_sender_invoice_no"),
    )


class PaymentEvent(UuidPrimaryKey, Base):
    """Append-only audit row for every QPay interaction we logged."""

    __tablename__ = "payment_events"

    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[PaymentEventKind] = mapped_column(
        SAEnum(PaymentEventKind, name="payment_event_kind", native_enum=True),
        nullable=False,
    )
    qpay_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    signature_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LedgerEntry(UuidPrimaryKey, TenantScoped, Base):
    """One side of a double-entry transaction.

    Every settlement creates two rows (debit cash, credit business_revenue);
    the pair sums to zero per (intent_id, direction). Refunds insert two
    more rows (debit refund_payable, credit cash). The platform-fee
    account is reserved for phase-2 monetization — currently unused.
    """

    __tablename__ = "ledger_entries"

    account: Mapped[LedgerAccount] = mapped_column(
        SAEnum(LedgerAccount, name="ledger_account", native_enum=True),
        nullable=False,
    )
    direction: Mapped[LedgerDirection] = mapped_column(
        SAEnum(LedgerDirection, name="ledger_direction", native_enum=True),
        nullable=False,
    )
    amount_mnt: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payment_intents.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sale_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sales.id", ondelete="RESTRICT"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (CheckConstraint("amount_mnt > 0", name="ck_ledger_entries_amount_positive"),)
