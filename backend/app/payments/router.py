"""HTTP routes for the payments context."""

from __future__ import annotations

import hmac
import uuid
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse

from app.businesses.dependencies import get_businesses_service
from app.businesses.service import BusinessesService
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole
from app.payments.dependencies import get_payments_service
from app.payments.schemas import (
    PaymentCheckOut,
    PaymentIntentCreatedOut,
    PaymentIntentCreateIn,
    PaymentIntentOut,
)
from app.payments.service import PaymentsService
from app.platform.config import Settings, get_settings

router = APIRouter(tags=["payments"])


@router.post(
    "/payments/intents",
    response_model=PaymentIntentCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Driver requests a QPay invoice for one of their sales",
)
async def create_intent(
    body: PaymentIntentCreateIn,
    service: Annotated[PaymentsService, Depends(get_payments_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> PaymentIntentCreatedOut:
    if user.role != UserRole.driver:
        # Business / admin accounts can't be the buyer on a sale.
        from app.platform.errors import ForbiddenError

        raise ForbiddenError("Only drivers can request a payment intent")
    result = await service.create_intent_for_sale(driver_id=user.id, sale_id=body.sale_id)
    return PaymentIntentCreatedOut(
        intent=PaymentIntentOut.model_validate(result.intent),
        qr_text=result.qr_text,
        qr_image_base64=result.qr_image_base64,
        deeplink=result.deeplink,
        urls=result.urls,
    )


@router.get(
    "/payments/intents/{intent_id}",
    response_model=PaymentIntentOut,
    summary="Read a payment intent (driver or selling business only)",
)
async def get_intent(
    intent_id: uuid.UUID,
    service: Annotated[PaymentsService, Depends(get_payments_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> PaymentIntentOut:
    business_id = await _resolve_business_id(user, businesses)
    intent = await service.get_for_party(
        intent_id=intent_id, user_id=user.id, business_id=business_id
    )
    return PaymentIntentOut.model_validate(intent)


@router.post(
    "/payments/intents/{intent_id}/check",
    response_model=PaymentCheckOut,
    summary="Force a /v2/payment/check poll against QPay (driver or business)",
)
async def check_intent(
    intent_id: uuid.UUID,
    service: Annotated[PaymentsService, Depends(get_payments_service)],
    user: Annotated[User, Depends(get_current_user)],
    businesses: Annotated[BusinessesService, Depends(get_businesses_service)],
) -> PaymentCheckOut:
    business_id = await _resolve_business_id(user, businesses)
    intent = await service.get_for_party(
        intent_id=intent_id, user_id=user.id, business_id=business_id
    )
    qpay_status = await service.check_payment(intent=intent)
    return PaymentCheckOut(
        intent=PaymentIntentOut.model_validate(intent),
        qpay_status=qpay_status,
    )


@router.post(
    "/payments/qpay/callback",
    summary="QPay v2 callback receiver — verifies signature, persists, settles",
    include_in_schema=False,  # public webhook, not part of the client API
)
async def qpay_callback(
    request: Request,
    service: Annotated[PaymentsService, Depends(get_payments_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_qpay_signature: Annotated[str | None, Header(alias="X-QPay-Signature")] = None,
) -> JSONResponse:
    """Always 200 — QPay retries on non-2xx, and we never want to lose a
    settlement to a transient backend bug. The status flip itself is
    inside the service, behind the signature check.
    """
    raw_body = await request.body()
    try:
        parsed = await request.json()
        body = parsed if isinstance(parsed, dict) else {}
    except ValueError:
        body = {}

    signature_ok = _verify_callback_signature(
        raw_body=raw_body,
        signature=x_qpay_signature,
        secret=settings.qpay_callback_secret,
    )
    await service.handle_callback(body=body, signature_ok=signature_ok)
    # QPay v2 expects an empty 200 — return a tiny JSON ack to be defensive.
    return JSONResponse(status_code=200, content={"ok": True})


def _verify_callback_signature(
    *,
    raw_body: bytes,
    signature: str | None,
    secret: str,
) -> bool | None:
    """Return True/False if signed, None if signing isn't configured.

    Until we confirm the QPay v2 signing scheme via the public docs,
    `qpay_callback_secret` defaults to empty — the receiver runs in
    log-only mode (`signature_ok=None`) and persists every callback.
    Once the doc check lands, swap this for the real algorithm and
    require `signature_ok is True` to act on the body.
    """
    if not secret:
        return None
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _resolve_business_id(user: User, businesses: BusinessesService) -> uuid.UUID | None:
    if user.role != UserRole.business:
        return None
    business = await businesses.businesses.get_by_owner(user.id)
    return business.id if business is not None else None
