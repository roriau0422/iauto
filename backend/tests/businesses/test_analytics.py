"""Sales analytics — trailing-window aggregation for the business home screen."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.models import User, UserRole
from app.marketplace.models import (
    PartSearchRequest,
    PartSearchStatus,
    Quote,
    QuoteCondition,
    Reservation,
    ReservationStatus,
    Sale,
)
from app.platform.errors import ValidationError
from app.vehicles.models import (
    SteeringSide,
    Vehicle,
    VehicleOwnership,
    VerificationSource,
)
from app.warehouse.models import (
    WarehouseMovementKind,
    WarehouseSku,
    WarehouseStockMovement,
)


@pytest.fixture
def service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


async def _make_user(
    db_session: AsyncSession, *, phone: str, role: UserRole = UserRole.driver
) -> User:
    user = User(phone=phone, role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_business(
    *, db_session: AsyncSession, service: BusinessesService, owner_phone: str
) -> tuple[User, uuid.UUID]:
    owner = await _make_user(db_session, phone=owner_phone, role=UserRole.business)
    business = await service.create(owner=owner, payload=BusinessCreateIn(display_name="Shop"))
    return owner, business.id


async def _make_vehicle(db_session: AsyncSession, *, owner: User, plate: str) -> Vehicle:
    vehicle = Vehicle(
        plate=plate,
        verification_source=VerificationSource.manual,
        steering_side=SteeringSide.LHD,
        build_year=2018,
    )
    db_session.add(vehicle)
    await db_session.flush()
    db_session.add(VehicleOwnership(user_id=owner.id, vehicle_id=vehicle.id))
    await db_session.flush()
    return vehicle


async def _make_search(
    db_session: AsyncSession, *, driver: User, vehicle: Vehicle
) -> PartSearchRequest:
    request = PartSearchRequest(
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        description="brake pads",
        media_asset_ids=[],
        status=PartSearchStatus.fulfilled,
    )
    db_session.add(request)
    await db_session.flush()
    return request


async def _make_quote(
    db_session: AsyncSession,
    *,
    request: PartSearchRequest,
    business_id: uuid.UUID,
    price_mnt: int,
) -> Quote:
    quote = Quote(
        part_search_id=request.id,
        tenant_id=business_id,
        price_mnt=price_mnt,
        condition=QuoteCondition.new,
        notes=None,
        media_asset_ids=[],
    )
    db_session.add(quote)
    await db_session.flush()
    return quote


async def _make_reservation(
    db_session: AsyncSession, *, quote: Quote, request: PartSearchRequest, driver: User
) -> Reservation:
    res = Reservation(
        quote_id=quote.id,
        part_search_id=request.id,
        driver_id=driver.id,
        tenant_id=quote.tenant_id,
        status=ReservationStatus.completed,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(res)
    await db_session.flush()
    return res


async def _make_sale(
    db_session: AsyncSession,
    *,
    business_id: uuid.UUID,
    driver: User,
    vehicle: Vehicle,
    price_mnt: int,
    created_at: datetime,
) -> Sale:
    """Wire a complete sale chain: search → quote → reservation → sale.

    Sales' `created_at` is server_default=now(); to test windowed queries
    we set it explicitly post-flush.
    """
    request = await _make_search(db_session, driver=driver, vehicle=vehicle)
    quote = await _make_quote(
        db_session, request=request, business_id=business_id, price_mnt=price_mnt
    )
    reservation = await _make_reservation(db_session, quote=quote, request=request, driver=driver)
    sale = Sale(
        tenant_id=business_id,
        reservation_id=reservation.id,
        quote_id=quote.id,
        part_search_id=request.id,
        driver_id=driver.id,
        price_mnt=price_mnt,
    )
    db_session.add(sale)
    await db_session.flush()
    sale.created_at = created_at
    await db_session.flush()
    return sale


async def _make_sku(
    db_session: AsyncSession,
    *,
    business_id: uuid.UUID,
    sku_code: str,
    display_name: str,
) -> WarehouseSku:
    sku = WarehouseSku(
        tenant_id=business_id,
        sku_code=sku_code,
        display_name=display_name,
        description=None,
        condition=QuoteCondition.new,
        vehicle_brand_id=None,
        vehicle_model_id=None,
        unit_price_mnt=None,
        low_stock_threshold=None,
    )
    db_session.add(sku)
    await db_session.flush()
    return sku


async def _record_issue(
    db_session: AsyncSession,
    *,
    business_id: uuid.UUID,
    sku: WarehouseSku,
    sale: Sale,
    actor: User,
    quantity: int,
) -> WarehouseStockMovement:
    move = WarehouseStockMovement(
        tenant_id=business_id,
        sku_id=sku.id,
        kind=WarehouseMovementKind.issue,
        quantity=quantity,
        signed_quantity=-quantity,
        note="sale dispense",
        actor_user_id=actor.id,
        sale_id=sale.id,
    )
    db_session.add(move)
    await db_session.flush()
    return move


# ---------------------------------------------------------------------------
# Service-layer behaviour
# ---------------------------------------------------------------------------


async def test_empty_business_returns_zero_window(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    _, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112501"
    )
    business = await service.businesses.get_by_id(business_id)
    assert business is not None

    result = await service.get_sales_analytics(business=business, window_days=7)
    assert result.window_days == 7
    assert len(result.daily) == 7
    assert all(b.sales_count == 0 and b.revenue_mnt == 0 for b in result.daily)
    assert result.total_sales == 0
    assert result.total_revenue_mnt == 0
    assert result.top_skus == []
    # Days are contiguous + ascending.
    diffs = {
        (result.daily[i + 1].date - result.daily[i].date).days for i in range(len(result.daily) - 1)
    }
    assert diffs == {1}


async def test_window_aggregates_sales_by_day(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    _, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112502"
    )
    driver = await _make_user(db_session, phone="+97688112503")
    vehicle = await _make_vehicle(db_session, owner=driver, plate="9987УБӨ")
    business = await service.businesses.get_by_id(business_id)
    assert business is not None

    today = datetime.now(UTC)
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=100_000,
        created_at=today,
    )
    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=50_000,
        created_at=yesterday,
    )
    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=70_000,
        created_at=yesterday,
    )
    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=200_000,
        created_at=two_days_ago,
    )

    result = await service.get_sales_analytics(business=business, window_days=7)
    assert result.window_days == 7
    assert len(result.daily) == 7
    assert result.total_sales == 4
    assert result.total_revenue_mnt == 100_000 + 50_000 + 70_000 + 200_000

    by_date = {b.date: b for b in result.daily}
    assert by_date[today.date()].sales_count == 1
    assert by_date[today.date()].revenue_mnt == 100_000
    assert by_date[yesterday.date()].sales_count == 2
    assert by_date[yesterday.date()].revenue_mnt == 120_000
    assert by_date[two_days_ago.date()].sales_count == 1
    assert by_date[two_days_ago.date()].revenue_mnt == 200_000


async def test_top_skus_orders_by_units_sold(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112504"
    )
    driver = await _make_user(db_session, phone="+97688112505")
    vehicle = await _make_vehicle(db_session, owner=driver, plate="9987УБӨ")
    business = await service.businesses.get_by_id(business_id)
    assert business is not None

    sku_pads = await _make_sku(
        db_session,
        business_id=business_id,
        sku_code="BP-001",
        display_name="Brake pads",
    )
    sku_oil = await _make_sku(
        db_session,
        business_id=business_id,
        sku_code="OIL-5W30",
        display_name="Engine oil 5W30",
    )
    sku_filter = await _make_sku(
        db_session,
        business_id=business_id,
        sku_code="FLT-A1",
        display_name="Air filter",
    )

    today = datetime.now(UTC)
    sale_a = await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=120_000,
        created_at=today,
    )
    sale_b = await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=60_000,
        created_at=today,
    )
    sale_c = await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=20_000,
        created_at=today,
    )

    await _record_issue(
        db_session, business_id=business_id, sku=sku_oil, sale=sale_a, actor=owner, quantity=4
    )
    await _record_issue(
        db_session, business_id=business_id, sku=sku_pads, sale=sale_b, actor=owner, quantity=2
    )
    await _record_issue(
        db_session, business_id=business_id, sku=sku_filter, sale=sale_c, actor=owner, quantity=1
    )

    result = await service.get_sales_analytics(business=business, window_days=7)
    leaderboard = [(row.sku_code, row.units_sold) for row in result.top_skus]
    assert leaderboard == [
        ("OIL-5W30", 4),
        ("BP-001", 2),
        ("FLT-A1", 1),
    ]
    assert result.top_skus[0].display_name == "Engine oil 5W30"


async def test_window_excludes_older_rows(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    """A sale older than `window_days` doesn't enter any aggregate."""
    _, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112506"
    )
    driver = await _make_user(db_session, phone="+97688112507")
    vehicle = await _make_vehicle(db_session, owner=driver, plate="9987УБӨ")
    business = await service.businesses.get_by_id(business_id)
    assert business is not None

    long_ago = datetime.now(UTC) - timedelta(days=30)
    today = datetime.now(UTC)
    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=999_000,
        created_at=long_ago,
    )
    await _make_sale(
        db_session,
        business_id=business_id,
        driver=driver,
        vehicle=vehicle,
        price_mnt=10_000,
        created_at=today,
    )

    result = await service.get_sales_analytics(business=business, window_days=7)
    assert result.total_sales == 1
    assert result.total_revenue_mnt == 10_000


async def test_other_business_sales_are_excluded(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    """Tenant isolation: business A never sees business B's revenue."""
    _, business_a = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112508"
    )
    _, business_b = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112509"
    )
    driver = await _make_user(db_session, phone="+97688112510")
    vehicle = await _make_vehicle(db_session, owner=driver, plate="1234УБА")

    today = datetime.now(UTC)
    await _make_sale(
        db_session,
        business_id=business_a,
        driver=driver,
        vehicle=vehicle,
        price_mnt=100_000,
        created_at=today,
    )
    await _make_sale(
        db_session,
        business_id=business_b,
        driver=driver,
        vehicle=vehicle,
        price_mnt=999_000,
        created_at=today,
    )

    biz_a = await service.businesses.get_by_id(business_a)
    biz_b = await service.businesses.get_by_id(business_b)
    assert biz_a is not None
    assert biz_b is not None

    a_result = await service.get_sales_analytics(business=biz_a, window_days=7)
    b_result = await service.get_sales_analytics(business=biz_b, window_days=7)
    assert a_result.total_revenue_mnt == 100_000
    assert b_result.total_revenue_mnt == 999_000


async def test_window_days_validation(service: BusinessesService, db_session: AsyncSession) -> None:
    _, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112511"
    )
    business = await service.businesses.get_by_id(business_id)
    assert business is not None
    with pytest.raises(ValidationError):
        await service.get_sales_analytics(business=business, window_days=0)
    with pytest.raises(ValidationError):
        await service.get_sales_analytics(business=business, window_days=91)


async def test_top_skus_capped_at_five(
    service: BusinessesService, db_session: AsyncSession
) -> None:
    owner, business_id = await _make_business(
        db_session=db_session, service=service, owner_phone="+97688112512"
    )
    driver = await _make_user(db_session, phone="+97688112513")
    vehicle = await _make_vehicle(db_session, owner=driver, plate="9987УБӨ")
    business = await service.businesses.get_by_id(business_id)
    assert business is not None

    today = datetime.now(UTC)
    for i in range(7):
        sku = await _make_sku(
            db_session,
            business_id=business_id,
            sku_code=f"X-{i}",
            display_name=f"Part {i}",
        )
        sale = await _make_sale(
            db_session,
            business_id=business_id,
            driver=driver,
            vehicle=vehicle,
            price_mnt=10_000,
            created_at=today,
        )
        # Ensure stable order: sku-0 has 7 units, sku-1 has 6, etc.
        await _record_issue(
            db_session,
            business_id=business_id,
            sku=sku,
            sale=sale,
            actor=owner,
            quantity=7 - i,
        )

    result = await service.get_sales_analytics(business=business, window_days=7)
    assert len(result.top_skus) == 5
    # Top entry is the 7-unit row, last is the 3-unit row.
    assert result.top_skus[0].units_sold == 7
    assert result.top_skus[-1].units_sold == 3
