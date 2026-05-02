"""In-memory test doubles for the payments context."""

from __future__ import annotations

from typing import Any

from app.payments.providers.qpay import QpayClient, QpayInvoiceResult


class FakeQpayClient(QpayClient):
    """Records every call; returns canned responses.

    Defaults are tuned for the happy path: `create_invoice` returns a
    realistic-looking body with a fresh fake `invoice_id`, `qr_text`,
    and `qPay_shortUrl`. `check_payment` returns "PENDING" by default —
    tests can override `next_check_status` to simulate settlement.
    """

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.check_calls: list[str] = []
        self.next_create: QpayInvoiceResult | None = None
        self.next_check_status: str = "PENDING"
        self.fail_create: bool = False

    async def create_invoice(self, *, payload: dict[str, Any]) -> QpayInvoiceResult:
        self.create_calls.append(payload)
        if self.next_create is not None:
            return self.next_create
        if self.fail_create:
            return QpayInvoiceResult(ok=False, status=502, body={"error": "upstream"})
        # Realistic-ish body.
        return QpayInvoiceResult(
            ok=True,
            status=200,
            body={
                "invoice_id": f"qpay-inv-{len(self.create_calls)}",
                "qr_text": "00020101021232550...0000",
                "qPay_shortUrl": "https://qpay.mn/q/abc123",
                "qr_image": "iVBORw0KGgoAAAANSUhEUgAA...",
                "urls": [
                    {"name": "qPay", "logo": "...", "link": "qpay://..."},
                ],
            },
        )

    async def check_payment(self, *, qpay_invoice_id: str) -> QpayInvoiceResult:
        self.check_calls.append(qpay_invoice_id)
        return QpayInvoiceResult(
            ok=True,
            status=200,
            body={
                "count": 1,
                "rows": [
                    {
                        "payment_id": "pay-1",
                        "payment_status": self.next_check_status,
                        "payment_amount": 150_000,
                    }
                ],
            },
        )
