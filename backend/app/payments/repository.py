"""Database access for the payments context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import (
    LedgerAccount,
    LedgerDirection,
    LedgerEntry,
    PaymentEvent,
    PaymentEventKind,
    PaymentIntent,
    PaymentIntentStatus,
)


class PaymentIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, intent_id: uuid.UUID) -> PaymentIntent | None:
        return await self.session.get(PaymentIntent, intent_id)

    async def get_by_sale_id(self, sale_id: uuid.UUID) -> PaymentIntent | None:
        stmt = select(PaymentIntent).where(PaymentIntent.sale_id == sale_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_qpay_invoice_id(self, qpay_invoice_id: str) -> PaymentIntent | None:
        stmt = select(PaymentIntent).where(PaymentIntent.qpay_invoice_id == qpay_invoice_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_sender_invoice_no(self, sender_invoice_no: str) -> PaymentIntent | None:
        stmt = select(PaymentIntent).where(PaymentIntent.sender_invoice_no == sender_invoice_no)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        sale_id: uuid.UUID,
        amount_mnt: int,
        invoice_code: str,
    ) -> PaymentIntent:
        intent = PaymentIntent(
            tenant_id=tenant_id,
            sale_id=sale_id,
            amount_mnt=amount_mnt,
            qpay_invoice_code=invoice_code,
            # Deterministic merchant-side idempotency key. QPay's contract
            # treats it as unique per merchant; we use the intent id so
            # retries from the same caller don't create duplicates.
            sender_invoice_no="",
            status=PaymentIntentStatus.pending,
        )
        self.session.add(intent)
        await self.session.flush()
        # Once the row has its UUID, set the sender_invoice_no to match.
        intent.sender_invoice_no = str(intent.id)
        await self.session.flush()
        return intent

    async def list_for_business(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[PaymentIntent], int]:
        base = select(PaymentIntent).where(PaymentIntent.tenant_id == business_id)
        stmt = base.order_by(PaymentIntent.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(PaymentIntent.id)).where(
            PaymentIntent.tenant_id == business_id
        )
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total


class PaymentEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        payment_intent_id: uuid.UUID,
        kind: PaymentEventKind,
        qpay_payload: dict[str, Any],
        signature_ok: bool | None = None,
    ) -> PaymentEvent:
        event = PaymentEvent(
            payment_intent_id=payment_intent_id,
            kind=kind,
            qpay_payload=qpay_payload,
            signature_ok=signature_ok,
        )
        self.session.add(event)
        await self.session.flush()
        return event


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def post_pair(
        self,
        *,
        tenant_id: uuid.UUID,
        amount_mnt: int,
        debit_account: LedgerAccount,
        credit_account: LedgerAccount,
        payment_intent_id: uuid.UUID | None,
        sale_id: uuid.UUID | None,
        description: str,
    ) -> tuple[LedgerEntry, LedgerEntry]:
        """Insert the matching debit and credit rows for one transaction.

        Both rows carry the same `amount_mnt`; the `direction` column
        encodes the sign. Sums per `(payment_intent_id, sale_id)` should
        always be zero across the two directions — easy invariant to
        spot-check in tests.
        """
        if amount_mnt <= 0:
            raise ValueError("amount_mnt must be positive")
        debit = LedgerEntry(
            tenant_id=tenant_id,
            account=debit_account,
            direction=LedgerDirection.debit,
            amount_mnt=amount_mnt,
            payment_intent_id=payment_intent_id,
            sale_id=sale_id,
            description=description,
        )
        credit = LedgerEntry(
            tenant_id=tenant_id,
            account=credit_account,
            direction=LedgerDirection.credit,
            amount_mnt=amount_mnt,
            payment_intent_id=payment_intent_id,
            sale_id=sale_id,
            description=description,
        )
        self.session.add_all([debit, credit])
        await self.session.flush()
        return debit, credit

    async def list_for_intent(self, intent_id: uuid.UUID) -> list[LedgerEntry]:
        stmt = (
            select(LedgerEntry)
            .where(LedgerEntry.payment_intent_id == intent_id)
            .order_by(LedgerEntry.created_at)
        )
        return list((await self.session.execute(stmt)).scalars())
