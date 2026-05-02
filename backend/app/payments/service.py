"""Payments service — invoice creation, settlement, ledger posting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.repository import BusinessRepository
from app.marketplace.repository import SaleRepository
from app.payments.events import (
    PaymentFailed,
    PaymentIntentCreated,
    PaymentSettled,
)
from app.payments.models import (
    LedgerAccount,
    PaymentEventKind,
    PaymentIntent,
    PaymentIntentStatus,
)
from app.payments.providers.qpay import QpayClient
from app.payments.repository import (
    LedgerRepository,
    PaymentEventRepository,
    PaymentIntentRepository,
)
from app.platform.config import Settings
from app.platform.errors import (
    DomainError,
    NotFoundError,
)
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event

logger = get_logger("app.payments.service")


# Status strings QPay returns on the v2/payment/check response that we
# treat as definitively paid. Real values per QPay v2 docs:
#   - PAID       — invoice settled
#   - PARTIAL    — partial payment received (treated as still pending)
#   - REFUNDED   — refund posted
# We're conservative: only "PAID" flips an intent to settled.
QPAY_PAID_STATUSES: frozenset[str] = frozenset({"PAID"})


@dataclass(slots=True)
class InvoiceCreated:
    intent: PaymentIntent
    qr_text: str | None
    qr_image_base64: str | None
    deeplink: str | None
    urls: list[dict[str, Any]] | None


class PaymentsService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        qpay: QpayClient,
        settings: Settings,
    ) -> None:
        self.session = session
        self.intents = PaymentIntentRepository(session)
        self.events = PaymentEventRepository(session)
        self.ledger = LedgerRepository(session)
        self.sales = SaleRepository(session)
        self.businesses = BusinessRepository(session)
        self.qpay = qpay
        self.settings = settings

    # ---- intent creation -----------------------------------------------

    async def create_intent_for_sale(
        self,
        *,
        driver_id: uuid.UUID,
        sale_id: uuid.UUID,
    ) -> InvoiceCreated:
        """Driver requests a QPay invoice for one of their sales."""
        sale = await self.sales.get_by_id(sale_id)
        # Opaque 404 across sale ownership.
        if sale is None or sale.driver_id != driver_id:
            raise NotFoundError("Sale not found")

        existing = await self.intents.get_by_sale_id(sale.id)
        if existing is not None:
            # We've already attempted an invoice. Don't double-create at
            # QPay — return the existing one so the client can resume.
            return InvoiceCreated(
                intent=existing,
                qr_text=None,
                qr_image_base64=None,
                deeplink=None,
                urls=None,
            )

        invoice_code = self.settings.qpay_invoice_code
        if not invoice_code:
            raise DomainError("QPAY_INVOICE_CODE not configured")

        intent = await self.intents.create(
            tenant_id=sale.tenant_id,
            sale_id=sale.id,
            amount_mnt=sale.price_mnt,
            invoice_code=invoice_code,
        )

        # Build the QPay invoice payload. `invoice_receiver_code` is the
        # buyer-facing identifier — we use the driver's user id since the
        # driver is unauthenticated to QPay.
        callback_url = self.settings.qpay_callback_url or ""
        payload = {
            "invoice_code": invoice_code,
            "sender_invoice_no": intent.sender_invoice_no,
            "invoice_receiver_code": str(driver_id),
            "invoice_description": f"iAuto sale {sale.id}",
            "amount": sale.price_mnt,
            "callback_url": callback_url,
        }
        result = await self.qpay.create_invoice(payload=payload)
        await self.events.append(
            payment_intent_id=intent.id,
            kind=PaymentEventKind.invoice_created,
            qpay_payload=result.body,
        )

        if not result.ok:
            intent.status = PaymentIntentStatus.failed
            intent.last_qpay_status = "create_invoice_failed"
            await self.session.flush()
            write_outbox_event(
                self.session,
                PaymentFailed(
                    aggregate_id=intent.id,
                    tenant_id=intent.tenant_id,
                    sale_id=sale.id,
                    reason=f"create_invoice status={result.status}",
                ),
            )
            logger.warning(
                "qpay_invoice_create_failed",
                intent_id=str(intent.id),
                status=result.status,
            )
            return InvoiceCreated(
                intent=intent,
                qr_text=None,
                qr_image_base64=None,
                deeplink=None,
                urls=None,
            )

        body = result.body
        intent.qpay_invoice_id = str(body.get("invoice_id")) if body.get("invoice_id") else None
        await self.session.flush()

        write_outbox_event(
            self.session,
            PaymentIntentCreated(
                aggregate_id=intent.id,
                tenant_id=intent.tenant_id,
                sale_id=sale.id,
                amount_mnt=sale.price_mnt,
            ),
        )
        logger.info(
            "qpay_invoice_created",
            intent_id=str(intent.id),
            sale_id=str(sale.id),
            qpay_invoice_id=intent.qpay_invoice_id,
        )

        return InvoiceCreated(
            intent=intent,
            qr_text=_optional_str(body.get("qr_text")),
            qr_image_base64=_optional_str(body.get("qr_image")),
            deeplink=_optional_str(body.get("qPay_shortUrl")),
            urls=body.get("urls") if isinstance(body.get("urls"), list) else None,
        )

    # ---- read -----------------------------------------------------------

    async def get_for_party(
        self,
        *,
        intent_id: uuid.UUID,
        user_id: uuid.UUID | None,
        business_id: uuid.UUID | None,
    ) -> PaymentIntent:
        intent = await self.intents.get_by_id(intent_id)
        if intent is None:
            raise NotFoundError("Payment intent not found")
        sale = await self.sales.get_by_id(intent.sale_id)
        if sale is None:
            raise NotFoundError("Payment intent not found")
        # Either the buying driver or the selling business may read.
        if user_id is not None and sale.driver_id == user_id:
            return intent
        if business_id is not None and intent.tenant_id == business_id:
            return intent
        raise NotFoundError("Payment intent not found")

    # ---- settlement -----------------------------------------------------

    async def check_payment(self, *, intent: PaymentIntent) -> str | None:
        """Force a /v2/payment/check poll. Returns the QPay status string."""
        if intent.qpay_invoice_id is None:
            return None

        result = await self.qpay.check_payment(qpay_invoice_id=intent.qpay_invoice_id)
        await self.events.append(
            payment_intent_id=intent.id,
            kind=PaymentEventKind.check,
            qpay_payload=result.body,
        )
        status = self._resolve_payment_status(result.body)
        intent.last_qpay_status = status
        await self.session.flush()

        if status in QPAY_PAID_STATUSES and intent.status != PaymentIntentStatus.settled:
            await self._mark_settled(intent=intent, source=PaymentEventKind.check)
        return status

    async def handle_callback(
        self,
        *,
        body: dict[str, Any],
        signature_ok: bool | None,
    ) -> None:
        """Persist a QPay callback and flip the intent to settled if paid.

        Signature is checked at the router; we record `signature_ok` on
        the audit row and refuse to flip status when it failed (defense
        in depth — the router already 200s on bad sigs but doesn't act).
        """
        invoice_id = body.get("invoice_id") or body.get("object_id")
        intent: PaymentIntent | None = None
        if invoice_id:
            intent = await self.intents.get_by_qpay_invoice_id(str(invoice_id))
        if intent is None:
            sender_no = body.get("sender_invoice_no")
            if sender_no:
                intent = await self.intents.get_by_sender_invoice_no(str(sender_no))
        if intent is None:
            logger.warning("qpay_callback_no_match", body=str(body)[:500])
            return

        await self.events.append(
            payment_intent_id=intent.id,
            kind=(
                PaymentEventKind.webhook_signature_failed
                if signature_ok is False
                else PaymentEventKind.callback
            ),
            qpay_payload=body,
            signature_ok=signature_ok,
        )
        if signature_ok is False:
            return

        status = self._resolve_payment_status(body)
        intent.last_qpay_status = status
        await self.session.flush()
        if status in QPAY_PAID_STATUSES and intent.status != PaymentIntentStatus.settled:
            await self._mark_settled(intent=intent, source=PaymentEventKind.callback)

    @staticmethod
    def _resolve_payment_status(body: dict[str, Any]) -> str | None:
        """Pull the human-readable payment status string out of a QPay body.

        QPay v2 sometimes returns `payment_status` directly (callback) and
        sometimes wraps it in `rows[]` (check response). Try both.
        """
        direct = body.get("payment_status")
        if direct:
            return str(direct)
        rows = body.get("rows")
        if isinstance(rows, list) and rows:
            row = rows[0]
            if isinstance(row, dict):
                inner = row.get("payment_status") or row.get("paymentStatus")
                if inner:
                    return str(inner)
        return None

    async def _mark_settled(self, *, intent: PaymentIntent, source: PaymentEventKind) -> None:
        """Atomically flip status, post the ledger pair, emit the event."""
        intent.status = PaymentIntentStatus.settled
        intent.settled_at = datetime.now(UTC)
        await self.session.flush()

        await self.ledger.post_pair(
            tenant_id=intent.tenant_id,
            amount_mnt=intent.amount_mnt,
            debit_account=LedgerAccount.cash,
            credit_account=LedgerAccount.business_revenue,
            payment_intent_id=intent.id,
            sale_id=intent.sale_id,
            description=f"Sale {intent.sale_id} via QPay",
        )

        await self.events.append(
            payment_intent_id=intent.id,
            kind=PaymentEventKind.status_change,
            qpay_payload={"to": PaymentIntentStatus.settled.value, "source": source.value},
        )

        write_outbox_event(
            self.session,
            PaymentSettled(
                aggregate_id=intent.id,
                tenant_id=intent.tenant_id,
                sale_id=intent.sale_id,
                amount_mnt=intent.amount_mnt,
                settled_at=intent.settled_at or datetime.now(UTC),
            ),
        )
        logger.info(
            "payment_settled",
            intent_id=str(intent.id),
            sale_id=str(intent.sale_id),
            amount_mnt=intent.amount_mnt,
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
