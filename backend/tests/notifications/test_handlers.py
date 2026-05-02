"""Each registered handler produces exactly one dispatch row."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.marketplace.events import (
    QuoteSent,
    ReservationStarted,
    ReviewSubmitted,
    SaleCompleted,
)
from app.notifications.handlers import (
    on_payment_settled,
    on_quote_sent,
    on_reservation_started,
    on_review_submitted,
    on_sale_completed,
)
from app.notifications.models import (
    NotificationDispatch,
    NotificationProvider,
    NotificationStatus,
)
from app.payments.events import PaymentSettled


async def _make_driver(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def driver_id() -> uuid.UUID:
    return uuid.uuid4()


async def _list_dispatches(db_session: AsyncSession) -> list[NotificationDispatch]:
    return list((await db_session.execute(select(NotificationDispatch))).scalars())


async def test_quote_sent_creates_dispatch_for_driver(
    db_session: AsyncSession,
) -> None:
    driver = await _make_driver(db_session, "+97688112001")
    event = QuoteSent(
        aggregate_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        part_search_id=uuid.uuid4(),
        driver_id=driver.id,
        price_mnt=100_000,
        condition="new",
    )
    await on_quote_sent(event, db_session)

    rows = await _list_dispatches(db_session)
    assert len(rows) == 1
    assert rows[0].user_id == driver.id
    assert rows[0].kind == "quote_sent"
    assert rows[0].provider == NotificationProvider.console
    assert rows[0].status == NotificationStatus.sent
    assert "100000" in rows[0].body_text
    assert rows[0].payload["quote_id"] == str(event.aggregate_id)


async def test_reservation_started_creates_dispatch(db_session: AsyncSession) -> None:
    driver = await _make_driver(db_session, "+97688112002")
    event = ReservationStarted(
        aggregate_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        quote_id=uuid.uuid4(),
        part_search_id=uuid.uuid4(),
        driver_id=driver.id,
        expires_at=datetime.now(UTC),
        price_mnt=99_000,
    )
    await on_reservation_started(event, db_session)
    rows = await _list_dispatches(db_session)
    assert len(rows) == 1
    assert rows[0].kind == "reservation_started"


async def test_sale_completed_creates_dispatch(db_session: AsyncSession) -> None:
    driver = await _make_driver(db_session, "+97688112003")
    event = SaleCompleted(
        aggregate_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        reservation_id=uuid.uuid4(),
        quote_id=uuid.uuid4(),
        part_search_id=uuid.uuid4(),
        driver_id=driver.id,
        price_mnt=120_000,
    )
    await on_sale_completed(event, db_session)
    rows = await _list_dispatches(db_session)
    assert len(rows) == 1
    assert rows[0].kind == "sale_completed"


async def test_review_submitted_creates_dispatch(db_session: AsyncSession) -> None:
    author = await _make_driver(db_session, "+97688112004")
    event = ReviewSubmitted(
        aggregate_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        sale_id=uuid.uuid4(),
        direction="buyer_to_seller",
        author_user_id=author.id,
        rating=5,
    )
    await on_review_submitted(event, db_session)
    rows = await _list_dispatches(db_session)
    assert len(rows) == 1
    assert rows[0].user_id == author.id
    assert rows[0].kind == "review_submitted"


async def test_payment_settled_no_sale_no_dispatch(db_session: AsyncSession) -> None:
    """No matching sale row → handler returns silently without a dispatch."""
    event = PaymentSettled(
        aggregate_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        sale_id=uuid.uuid4(),
        amount_mnt=50_000,
        settled_at=datetime.now(UTC),
    )
    await on_payment_settled(event, db_session)
    rows = await _list_dispatches(db_session)
    assert rows == []
