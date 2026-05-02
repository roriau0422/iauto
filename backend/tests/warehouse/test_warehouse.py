"""Warehouse: SKUs, movements, member-role gates, low-stock alerts."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import BusinessMemberRole
from app.businesses.schemas import BusinessCreateIn
from app.businesses.service import BusinessesService
from app.identity.models import User, UserRole
from app.marketplace.models import QuoteCondition
from app.notifications.handlers import on_stock_moved
from app.notifications.models import NotificationDispatch
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.outbox import OutboxEvent
from app.warehouse.models import WarehouseMovementKind
from app.warehouse.schemas import (
    SkuCreateIn,
    SkuUpdateIn,
    StockMovementCreateIn,
)
from app.warehouse.service import WarehouseService


@pytest.fixture
def businesses_service(db_session: AsyncSession) -> BusinessesService:
    return BusinessesService(session=db_session)


@pytest.fixture
def warehouse(db_session: AsyncSession) -> WarehouseService:
    return WarehouseService(session=db_session)


async def _make_business_with_members(
    *,
    db_session: AsyncSession,
    businesses_service: BusinessesService,
    owner_phone: str,
    staff_phone: str | None = None,
) -> tuple[User, User | None, uuid.UUID]:
    owner = User(phone=owner_phone, role=UserRole.business)
    db_session.add(owner)
    await db_session.flush()
    business = await businesses_service.create(
        owner=owner, payload=BusinessCreateIn(display_name="Shop")
    )
    staff = None
    if staff_phone:
        staff = User(phone=staff_phone, role=UserRole.driver)
        db_session.add(staff)
        await db_session.flush()
        await businesses_service.add_member(
            business=business,
            actor_role=BusinessMemberRole.owner,
            user_phone=staff_phone,
            role=BusinessMemberRole.staff,
        )
    return owner, staff, business.id


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


async def test_create_business_seeds_owner_membership(
    businesses_service: BusinessesService, db_session: AsyncSession
) -> None:
    owner, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112501",
    )
    members = await businesses_service.members.list_for_business(business_id)
    assert len(members) == 1
    assert members[0].user_id == owner.id
    assert members[0].role == BusinessMemberRole.owner


async def test_add_member_owner_only(
    businesses_service: BusinessesService, db_session: AsyncSession
) -> None:
    owner, staff, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112502",
        staff_phone="+97688112503",
    )
    business = await businesses_service.businesses.get_by_id(business_id)
    assert business is not None
    assert staff is not None

    # Staff trying to add another member → 403.
    other = User(phone="+97688112504", role=UserRole.driver)
    db_session.add(other)
    await db_session.flush()
    with pytest.raises(ForbiddenError):
        await businesses_service.add_member(
            business=business,
            actor_role=BusinessMemberRole.staff,
            user_phone="+97688112504",
            role=BusinessMemberRole.staff,
        )

    # Owner can.
    member = await businesses_service.add_member(
        business=business,
        actor_role=BusinessMemberRole.owner,
        user_phone="+97688112504",
        role=BusinessMemberRole.staff,
    )
    assert member.user_id == other.id

    members = await businesses_service.members.list_for_business(business_id)
    assert len(members) == 3  # owner + staff + new staff
    _ = owner  # used for ownership context


async def test_remove_owner_blocked(
    businesses_service: BusinessesService, db_session: AsyncSession
) -> None:
    owner, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112505",
    )
    business = await businesses_service.businesses.get_by_id(business_id)
    assert business is not None
    with pytest.raises(ConflictError):
        await businesses_service.remove_member(
            business=business,
            actor_role=BusinessMemberRole.owner,
            user_id=owner.id,
        )


# ---------------------------------------------------------------------------
# SKU CRUD
# ---------------------------------------------------------------------------


async def test_create_sku_emits_event(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112506",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(
            sku_code="BRAKE-001",
            display_name="Front brake pad",
            condition=QuoteCondition.new,
            unit_price_mnt=120_000,
            low_stock_threshold=2,
        ),
    )
    assert sku.tenant_id == business_id
    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    created = [e for e in events if e.event_type == "warehouse.sku_created"]
    assert len(created) == 1


async def test_create_sku_staff_forbidden(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112507",
        staff_phone="+97688112508",
    )
    with pytest.raises(ForbiddenError):
        await warehouse.create_sku(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.staff,
            payload=SkuCreateIn(
                sku_code="X-1",
                display_name="X",
                condition=QuoteCondition.new,
            ),
        )


async def test_create_sku_dup_code_409(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112509",
    )
    payload = SkuCreateIn(
        sku_code="DUP",
        display_name="A",
        condition=QuoteCondition.new,
    )
    await warehouse.create_sku(
        tenant_id=business_id, actor_role=BusinessMemberRole.owner, payload=payload
    )
    with pytest.raises(ConflictError):
        await warehouse.create_sku(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.owner,
            payload=payload,
        )


async def test_update_sku_owner_or_manager(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    _, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112510",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(sku_code="ABC", display_name="Original", condition=QuoteCondition.new),
    )
    updated = await warehouse.update_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.manager,
        sku_id=sku.id,
        payload=SkuUpdateIn(display_name="Renamed"),
    )
    assert updated.display_name == "Renamed"
    with pytest.raises(ForbiddenError):
        await warehouse.update_sku(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.staff,
            sku_id=sku.id,
            payload=SkuUpdateIn(display_name="No"),
        )


async def test_delete_sku_blocked_when_nonzero_stock(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112511",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(
            sku_code="DEL-1",
            display_name="Has stock",
            condition=QuoteCondition.new,
        ),
    )
    await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.receive, quantity=5),
    )
    with pytest.raises(ConflictError):
        await warehouse.delete_sku(
            tenant_id=business_id,
            actor_role=BusinessMemberRole.owner,
            sku_id=sku.id,
        )

    # Issue everything → can delete.
    await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.issue, quantity=5),
    )
    await warehouse.delete_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        sku_id=sku.id,
    )
    with pytest.raises(NotFoundError):
        await warehouse.get_sku(tenant_id=business_id, sku_id=sku.id)


# ---------------------------------------------------------------------------
# Stock movements
# ---------------------------------------------------------------------------


async def test_movements_compute_on_hand(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112512",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(sku_code="OH-1", display_name="OH", condition=QuoteCondition.new),
    )
    a = await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.receive, quantity=10),
    )
    b = await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.issue, quantity=3),
    )
    c = await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(
            kind=WarehouseMovementKind.adjust, quantity=2, direction="up"
        ),
    )
    assert a.on_hand_after == 10
    assert b.on_hand_after == 7
    assert c.on_hand_after == 9
    assert a.movement.signed_quantity == 10
    assert b.movement.signed_quantity == -3
    assert c.movement.signed_quantity == 2


async def test_issue_blocked_when_balance_insufficient(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, _, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112513",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(sku_code="LO-1", display_name="LO", condition=QuoteCondition.new),
    )
    with pytest.raises(ConflictError):
        await warehouse.record_movement(
            tenant_id=business_id,
            actor_user_id=owner.id,
            sku_id=sku.id,
            payload=StockMovementCreateIn(kind=WarehouseMovementKind.issue, quantity=1),
        )


# ---------------------------------------------------------------------------
# Low-stock alerting
# ---------------------------------------------------------------------------


async def test_low_stock_alert_fires_when_threshold_crossed(
    warehouse: WarehouseService,
    businesses_service: BusinessesService,
    db_session: AsyncSession,
) -> None:
    owner, staff, business_id = await _make_business_with_members(
        db_session=db_session,
        businesses_service=businesses_service,
        owner_phone="+97688112514",
        staff_phone="+97688112515",
    )
    sku = await warehouse.create_sku(
        tenant_id=business_id,
        actor_role=BusinessMemberRole.owner,
        payload=SkuCreateIn(
            sku_code="LST-1",
            display_name="Low stock test",
            condition=QuoteCondition.new,
            low_stock_threshold=2,
        ),
    )
    await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.receive, quantity=5),
    )
    # Issue down to 1 — under the threshold of 2.
    await warehouse.record_movement(
        tenant_id=business_id,
        actor_user_id=owner.id,
        sku_id=sku.id,
        payload=StockMovementCreateIn(kind=WarehouseMovementKind.issue, quantity=4),
    )

    # Pull the stock_moved events and replay the handler — production runs
    # them via the outbox consumer; here we drive directly so the test
    # doesn't need a worker process.
    from app.platform.events import DomainEvent

    events = (
        (
            await db_session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "warehouse.stock_moved")
            )
        )
        .scalars()
        .all()
    )
    for row in events:
        await on_stock_moved(DomainEvent.model_validate(row.payload), db_session)

    rows = (
        (
            await db_session.execute(
                select(NotificationDispatch).where(
                    NotificationDispatch.kind == "warehouse_low_stock"
                )
            )
        )
        .scalars()
        .all()
    )
    # One dispatch per member when the post-issue movement crossed the
    # threshold; the receive movement above the threshold doesn't fire.
    assert {r.user_id for r in rows} == {owner.id, staff.id if staff else owner.id}
