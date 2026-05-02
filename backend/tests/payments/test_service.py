"""Service-level tests for the payments context."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn, VehicleBrandCoverageIn
from app.businesses.service import BusinessesService
from app.catalog.models import VehicleBrand
from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.marketplace.models import QuoteCondition
from app.marketplace.schemas import PartSearchCreateIn, QuoteCreateIn
from app.marketplace.service import MarketplaceService
from app.media.service import MediaService
from app.payments.models import (
    LedgerAccount,
    LedgerDirection,
    PaymentEventKind,
    PaymentIntentStatus,
)
from app.payments.service import PaymentsService
from app.platform.config import Settings
from app.platform.errors import NotFoundError
from app.platform.outbox import OutboxEvent
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from tests.media.test_service import BUCKET, FakeMediaClient
from tests.payments.fakes import FakeQpayClient

PLATE_A = "9987УБӨ"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU777777",
    colorName="White",
    capacity=2500,
    wheelPosition="Зүүн",
)


@pytest.fixture
def vehicles_service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> VehiclesService:
    return VehiclesService(session=db_session, redis=redis, sms=sms, settings=settings)


@pytest.fixture
def businesses_service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


@pytest.fixture
def media_service(db_session: AsyncSession) -> MediaService:
    return MediaService(session=db_session, client=FakeMediaClient(), bucket=BUCKET)


@pytest.fixture
def marketplace(
    db_session: AsyncSession,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    media_service: MediaService,
) -> MarketplaceService:
    return MarketplaceService(
        session=db_session,
        vehicles_svc=vehicles_service,
        businesses_svc=businesses_service,
        media_svc=media_service,
    )


@pytest.fixture
def fake_qpay() -> FakeQpayClient:
    return FakeQpayClient()


@pytest.fixture
def payments_settings(settings: Settings) -> Settings:
    """Ensure the QPay invoice code is set so service-level tests can run.

    The real .env may leave it blank; we patch a deterministic value via
    Pydantic's `model_copy` for the duration of the fixture.
    """
    return settings.model_copy(update={"qpay_invoice_code": "TEST_INVOICE_CODE"})


@pytest.fixture
def payments(
    db_session: AsyncSession,
    fake_qpay: FakeQpayClient,
    payments_settings: Settings,
) -> PaymentsService:
    return PaymentsService(session=db_session, qpay=fake_qpay, settings=payments_settings)


async def _make_driver(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_business_owner(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.business)
    db_session.add(user)
    await db_session.flush()
    return user


async def _toyota_brand(db_session: AsyncSession) -> uuid.UUID:
    return (
        await db_session.execute(select(VehicleBrand.id).where(VehicleBrand.slug == "toyota"))
    ).scalar_one()


async def _make_sale(
    *,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
    driver_phone: str,
    owner_phone: str,
    price_mnt: int = 150_000,
) -> tuple[User, uuid.UUID, uuid.UUID]:
    """Helper: produce (driver, business_id, sale_id) ready for payment."""
    driver = await _make_driver(db_session, driver_phone)
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE_A, xyp=XYP_CAMRY)
    request = await marketplace.submit_search(
        driver_id=driver.id,
        payload=PartSearchCreateIn(vehicle_id=reg.vehicle.id, description="brake pads"),
    )
    owner = await _make_business_owner(db_session, owner_phone)
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    toyota = await _toyota_brand(db_session)
    await businesses_service.replace_vehicle_coverage(
        business=business, entries=[VehicleBrandCoverageIn(vehicle_brand_id=toyota)]
    )
    quote = await marketplace.submit_quote(
        business_id=business.id,
        owner_user_id=owner.id,
        search_id=request.id,
        payload=QuoteCreateIn(price_mnt=price_mnt, condition=QuoteCondition.new),
    )
    reservation = await marketplace.reserve(driver_id=driver.id, quote_id=quote.id)
    sale = await marketplace.complete_reservation(
        business_id=business.id, reservation_id=reservation.id
    )
    return driver, business.id, sale.id


# ---------------------------------------------------------------------------
# Intent creation
# ---------------------------------------------------------------------------


async def test_create_intent_calls_qpay_and_persists(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver, business_id, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110801",
        owner_phone="+97688110802",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    assert result.intent.tenant_id == business_id
    assert result.intent.amount_mnt == 150_000
    assert result.intent.status == PaymentIntentStatus.pending
    assert result.intent.qpay_invoice_id == "qpay-inv-1"
    assert result.qr_text == "00020101021232550...0000"
    assert result.deeplink == "https://qpay.mn/q/abc123"

    # QPay call shape — payload should match the Laravel reference contract.
    assert len(fake_qpay.create_calls) == 1
    payload = fake_qpay.create_calls[0]
    assert payload["invoice_code"] == "TEST_INVOICE_CODE"
    assert payload["amount"] == 150_000
    assert payload["sender_invoice_no"] == str(result.intent.id)
    assert payload["invoice_receiver_code"] == str(driver.id)

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    created = [e for e in events if e.event_type == "payments.intent_created"]
    assert len(created) == 1
    assert created[0].tenant_id == business_id


async def test_create_intent_idempotent_per_sale(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110803",
        owner_phone="+97688110804",
    )
    first = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    second = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    assert first.intent.id == second.intent.id
    # Second call should NOT create another QPay invoice — that would
    # double-charge the customer in real life.
    assert len(fake_qpay.create_calls) == 1


async def test_create_intent_404_for_stranger_driver(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110805",
        owner_phone="+97688110806",
    )
    stranger = await _make_driver(db_session, "+97688110807")
    with pytest.raises(NotFoundError):
        await payments.create_intent_for_sale(driver_id=stranger.id, sale_id=sale_id)


async def test_create_intent_marks_failed_on_qpay_error(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    fake_qpay.fail_create = True
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110808",
        owner_phone="+97688110809",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    assert result.intent.status == PaymentIntentStatus.failed
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    failed = [e for e in events if e.event_type == "payments.payment_failed"]
    assert len(failed) == 1


# ---------------------------------------------------------------------------
# Settlement via /v2/payment/check
# ---------------------------------------------------------------------------


async def test_check_payment_settles_intent_and_posts_ledger(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver, business_id, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110810",
        owner_phone="+97688110811",
        price_mnt=200_000,
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    intent = result.intent

    fake_qpay.next_check_status = "PAID"
    qpay_status = await payments.check_payment(intent=intent)
    assert qpay_status == "PAID"

    # `intent` is the live ORM row — service-level flush in _mark_settled
    # has already updated the in-memory attributes.
    assert intent.status == PaymentIntentStatus.settled
    assert intent.settled_at is not None

    ledger = await payments.ledger.list_for_intent(intent.id)
    assert len(ledger) == 2
    by_account = {row.account: row for row in ledger}
    assert by_account[LedgerAccount.cash].direction == LedgerDirection.debit
    assert by_account[LedgerAccount.cash].amount_mnt == 200_000
    assert by_account[LedgerAccount.business_revenue].direction == LedgerDirection.credit
    assert by_account[LedgerAccount.business_revenue].amount_mnt == 200_000
    assert all(row.tenant_id == business_id for row in ledger)

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    settled = [e for e in events if e.event_type == "payments.payment_settled"]
    assert len(settled) == 1
    assert settled[0].tenant_id == business_id


async def test_check_payment_pending_does_not_settle(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110812",
        owner_phone="+97688110813",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    intent = result.intent
    fake_qpay.next_check_status = "PENDING"
    await payments.check_payment(intent=intent)
    assert intent.status == PaymentIntentStatus.pending
    assert intent.settled_at is None
    ledger = await payments.ledger.list_for_intent(intent.id)
    assert ledger == []


async def test_check_payment_idempotent_when_already_settled(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110814",
        owner_phone="+97688110815",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    intent = result.intent
    fake_qpay.next_check_status = "PAID"
    await payments.check_payment(intent=intent)
    await payments.check_payment(intent=intent)
    ledger = await payments.ledger.list_for_intent(intent.id)
    # Exactly one settlement → exactly one ledger pair.
    assert len(ledger) == 2


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------


async def test_handle_callback_settles_via_invoice_id(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110816",
        owner_phone="+97688110817",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    intent = result.intent
    await payments.handle_callback(
        body={
            "invoice_id": intent.qpay_invoice_id,
            "payment_status": "PAID",
            "payment_amount": intent.amount_mnt,
        },
        signature_ok=True,
    )
    assert intent.status == PaymentIntentStatus.settled


async def test_handle_callback_signature_failed_records_but_does_not_settle(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110818",
        owner_phone="+97688110819",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    intent = result.intent
    await payments.handle_callback(
        body={"invoice_id": intent.qpay_invoice_id, "payment_status": "PAID"},
        signature_ok=False,
    )
    assert intent.status == PaymentIntentStatus.pending
    # Audit row exists, marked as a failed signature.
    from app.payments.models import PaymentEvent

    events = (
        (
            await db_session.execute(
                select(PaymentEvent).where(PaymentEvent.payment_intent_id == intent.id)
            )
        )
        .scalars()
        .all()
    )
    kinds = [e.kind for e in events]
    assert PaymentEventKind.webhook_signature_failed in kinds


async def test_handle_callback_unknown_invoice_silently_drops(
    payments: PaymentsService, db_session: AsyncSession
) -> None:
    # No intent in the DB. Should not raise.
    await payments.handle_callback(
        body={"invoice_id": "does-not-exist", "payment_status": "PAID"},
        signature_ok=True,
    )


# ---------------------------------------------------------------------------
# Read access (driver / business / stranger)
# ---------------------------------------------------------------------------


async def test_get_for_party_either_side_can_read(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, business_id, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110820",
        owner_phone="+97688110821",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    by_driver = await payments.get_for_party(
        intent_id=result.intent.id, user_id=driver.id, business_id=None
    )
    assert by_driver.id == result.intent.id

    by_biz = await payments.get_for_party(
        intent_id=result.intent.id, user_id=uuid.uuid4(), business_id=business_id
    )
    assert by_biz.id == result.intent.id


async def test_get_for_party_rejects_stranger(
    payments: PaymentsService,
    marketplace: MarketplaceService,
    vehicles_service: VehiclesService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    driver, _, sale_id = await _make_sale(
        marketplace=marketplace,
        vehicles_service=vehicles_service,
        businesses_service=businesses_service,
        db_session=db_session,
        driver_phone="+97688110822",
        owner_phone="+97688110823",
    )
    result = await payments.create_intent_for_sale(driver_id=driver.id, sale_id=sale_id)
    with pytest.raises(NotFoundError):
        await payments.get_for_party(
            intent_id=result.intent.id, user_id=uuid.uuid4(), business_id=None
        )
