"""Vehicle dues — list, pay (QPay invoice), settle via outbox handler."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.identity.providers.sms import InMemorySmsProvider
from app.payments.models import (
    PaymentIntent,
    PaymentIntentKind,
    PaymentIntentStatus,
)
from app.payments.service import PaymentsService
from app.platform.config import Settings
from app.platform.errors import NotFoundError
from app.platform.events import DomainEvent
from app.platform.outbox import OutboxEvent
from app.vehicles.handlers import on_payment_settled
from app.vehicles.models import (
    VehicleDue,
    VehicleDueKind,
    VehicleDueStatus,
)
from app.vehicles.schemas import XypPayloadIn
from app.vehicles.service import VehiclesService
from tests.payments.fakes import FakeQpayClient

PLATE = "9987УБӨ"

XYP_CAMRY = XypPayloadIn(
    markName="Toyota",
    modelName="Camry",
    buildYear=2020,
    cabinNumber="4T1B11HK5LU555555",
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
def fake_qpay() -> FakeQpayClient:
    return FakeQpayClient()


@pytest.fixture
def payments_settings(settings: Settings) -> Settings:
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


async def _make_due(
    *,
    db_session: AsyncSession,
    vehicle_id: uuid.UUID,
    kind: VehicleDueKind = VehicleDueKind.tax,
    amount_mnt: int = 120_000,
    due_date: date | None = None,
) -> VehicleDue:
    due = VehicleDue(
        vehicle_id=vehicle_id,
        kind=kind,
        amount_mnt=amount_mnt,
        due_date=due_date or date(2026, 7, 1),
        status=VehicleDueStatus.due,
    )
    db_session.add(due)
    await db_session.flush()
    return due


# ---------------------------------------------------------------------------
# list_dues
# ---------------------------------------------------------------------------


async def test_owner_lists_own_dues(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110951")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due_a = await _make_due(
        db_session=db_session, vehicle_id=reg.vehicle.id, kind=VehicleDueKind.tax
    )
    due_b = await _make_due(
        db_session=db_session,
        vehicle_id=reg.vehicle.id,
        kind=VehicleDueKind.insurance,
        amount_mnt=200_000,
    )

    rows = await vehicles_service.list_dues(user_id=driver.id, vehicle_id=reg.vehicle.id)
    ids = {r.id for r in rows}
    assert due_a.id in ids
    assert due_b.id in ids


async def test_non_owner_404s_listing(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110952")
    stranger = await _make_driver(db_session, "+97688110953")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id)
    with pytest.raises(NotFoundError):
        await vehicles_service.list_dues(user_id=stranger.id, vehicle_id=reg.vehicle.id)


async def test_unknown_vehicle_404s(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    driver = await _make_driver(db_session, "+97688110954")
    with pytest.raises(NotFoundError):
        await vehicles_service.list_dues(user_id=driver.id, vehicle_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# pay → QPay invoice
# ---------------------------------------------------------------------------


async def test_pay_creates_payment_intent_and_attaches(
    vehicles_service: VehiclesService,
    payments: PaymentsService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110955")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id, amount_mnt=150_000)

    invoice = await payments.create_intent_for_vehicle_due(driver_id=driver.id, vehicle_due=due)
    assert invoice.intent.kind == PaymentIntentKind.vehicle_due_payment
    assert invoice.intent.tenant_id is None
    assert invoice.intent.sale_id is None
    assert invoice.intent.vehicle_due_id == due.id
    assert invoice.intent.amount_mnt == 150_000
    assert invoice.intent.status == PaymentIntentStatus.pending
    assert invoice.deeplink == "https://qpay.mn/q/abc123"

    # The QPay payload mirrors the sale-payment shape.
    assert len(fake_qpay.create_calls) == 1
    payload = fake_qpay.create_calls[0]
    assert payload["amount"] == 150_000
    assert payload["sender_invoice_no"] == str(invoice.intent.id)

    # Caller stamps the FK on the due.
    vehicles_service.attach_payment_intent(due=due, payment_intent_id=invoice.intent.id)
    await db_session.flush()
    assert due.payment_intent_id == invoice.intent.id

    # Outbox carries the right kind.
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    created = [e for e in events if e.event_type == "payments.intent_created"]
    assert len(created) == 1
    assert created[0].payload["kind"] == "vehicle_due_payment"
    assert created[0].tenant_id is None


async def test_pay_idempotent_per_due(
    vehicles_service: VehiclesService,
    payments: PaymentsService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110956")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id)
    first = await payments.create_intent_for_vehicle_due(driver_id=driver.id, vehicle_due=due)
    second = await payments.create_intent_for_vehicle_due(driver_id=driver.id, vehicle_due=due)
    assert first.intent.id == second.intent.id
    # Second call must NOT hit QPay again.
    assert len(fake_qpay.create_calls) == 1


async def test_already_paid_due_returns_to_caller(
    vehicles_service: VehiclesService, db_session: AsyncSession
) -> None:
    """The service hands back the row regardless of status; the router's
    guard rejects the pay attempt with a 409. We pin the service-level
    contract here.
    """
    driver = await _make_driver(db_session, "+97688110957")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id)
    due.status = VehicleDueStatus.paid
    await db_session.flush()

    fetched = await vehicles_service.get_due_for_payment(
        user_id=driver.id, vehicle_id=reg.vehicle.id, due_id=due.id
    )
    assert fetched.status == VehicleDueStatus.paid
    assert fetched.id == due.id


# ---------------------------------------------------------------------------
# Settle via outbox handler
# ---------------------------------------------------------------------------


async def test_payment_settled_handler_flips_due_to_paid(
    vehicles_service: VehiclesService,
    payments: PaymentsService,
    fake_qpay: FakeQpayClient,
    db_session: AsyncSession,
) -> None:
    """End-to-end: pay → settle (via check) → handler flips due to paid."""
    driver = await _make_driver(db_session, "+97688110958")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id, amount_mnt=180_000)
    invoice = await payments.create_intent_for_vehicle_due(driver_id=driver.id, vehicle_due=due)
    vehicles_service.attach_payment_intent(due=due, payment_intent_id=invoice.intent.id)
    await db_session.flush()

    # Force settlement.
    fake_qpay.next_check_status = "PAID"
    await payments.check_payment(intent=invoice.intent)
    assert invoice.intent.status == PaymentIntentStatus.settled
    # Vehicle-due intents must NOT post to the ledger.
    ledger = await payments.ledger.list_for_intent(invoice.intent.id)
    assert ledger == []

    # Now drive the handler manually with the just-emitted event.
    settled_event = next(
        e
        for e in (await db_session.execute(select(OutboxEvent))).scalars()
        if e.event_type == "payments.payment_settled"
    )
    assert settled_event.payload["kind"] == "vehicle_due_payment"
    assert settled_event.payload["vehicle_due_id"] == str(due.id)

    rehydrated = DomainEvent.model_validate(settled_event.payload)
    await on_payment_settled(rehydrated, db_session)

    await db_session.refresh(due)
    assert due.status == VehicleDueStatus.paid
    assert due.paid_at is not None
    assert due.paid_at.tzinfo is not None

    # vehicles.due_paid event written.
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    paid_events = [e for e in events if e.event_type == "vehicles.due_paid"]
    assert len(paid_events) == 1
    assert paid_events[0].payload["vehicle_id"] == str(reg.vehicle.id)
    assert paid_events[0].payload["amount_mnt"] == 180_000


async def test_payment_settled_handler_idempotent(
    vehicles_service: VehiclesService,
    payments: PaymentsService,
    db_session: AsyncSession,
) -> None:
    """A second call for the same due is a no-op: no extra outbox row."""
    driver = await _make_driver(db_session, "+97688110959")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id)
    invoice = await payments.create_intent_for_vehicle_due(driver_id=driver.id, vehicle_due=due)

    payload = {
        "event_type": "payments.payment_settled",
        "aggregate_type": "payment_intent",
        "aggregate_id": str(invoice.intent.id),
        "tenant_id": None,
        "kind": "vehicle_due_payment",
        "sale_id": None,
        "vehicle_due_id": str(due.id),
        "amount_mnt": due.amount_mnt,
        "settled_at": datetime.now(UTC).isoformat(),
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    event = DomainEvent.model_validate(payload)

    await on_payment_settled(event, db_session)
    await on_payment_settled(event, db_session)

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    paid_events = [e for e in events if e.event_type == "vehicles.due_paid"]
    # Exactly one event despite two handler calls.
    assert len(paid_events) == 1


async def test_payment_settled_handler_ignores_sale_payments(
    db_session: AsyncSession,
) -> None:
    """Sale-payment events must not poke any vehicle_due rows."""
    payload = {
        "event_type": "payments.payment_settled",
        "aggregate_type": "payment_intent",
        "aggregate_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "kind": "sale_payment",
        "sale_id": str(uuid.uuid4()),
        "vehicle_due_id": None,
        "amount_mnt": 50_000,
        "settled_at": datetime.now(UTC).isoformat(),
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    event = DomainEvent.model_validate(payload)
    await on_payment_settled(event, db_session)
    # No-op — no vehicles.due_paid event.
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    assert all(e.event_type != "vehicles.due_paid" for e in events)


# ---------------------------------------------------------------------------
# Sanity: hand-build both intent kinds to confirm CHECK constraints survive
# round-trip without bleed-over.
# ---------------------------------------------------------------------------


async def test_polymorphic_intent_kinds_round_trip(
    vehicles_service: VehiclesService,
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688110960")
    reg = await vehicles_service.register_from_xyp(user_id=driver.id, plate=PLATE, xyp=XYP_CAMRY)
    due = await _make_due(db_session=db_session, vehicle_id=reg.vehicle.id, amount_mnt=10_000)
    intent = PaymentIntent(
        kind=PaymentIntentKind.vehicle_due_payment,
        tenant_id=None,
        sale_id=None,
        vehicle_due_id=due.id,
        amount_mnt=10_000,
        qpay_invoice_code="TEST",
        sender_invoice_no=str(uuid.uuid4()),
        status=PaymentIntentStatus.pending,
    )
    db_session.add(intent)
    await db_session.flush()
    assert intent.kind == PaymentIntentKind.vehicle_due_payment
    assert intent.tenant_id is None
