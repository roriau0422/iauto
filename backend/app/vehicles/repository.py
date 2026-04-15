"""Database access for the vehicles context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.crypto import get_search_index
from app.vehicles.models import (
    Vehicle,
    VehicleLookupPlan,
    VehicleLookupReport,
    VehicleOwnership,
    VerificationSource,
    normalize_vin,
)


class VehicleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        return await self.session.get(Vehicle, vehicle_id)

    async def get_by_vin(self, vin: str) -> Vehicle | None:
        # Equality lookup against the encrypted column → blind index.
        search = get_search_index().compute(normalize_vin(vin))
        result = await self.session.execute(select(Vehicle).where(Vehicle.vin_search == search))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        vin: str | None,
        plate: str,
        make: str | None,
        model: str | None,
        vehicle_brand_id: uuid.UUID | None,
        vehicle_model_id: uuid.UUID | None,
        build_year: int | None,
        color: str | None,
        engine_number: str | None,
        capacity_cc: int | None,
        raw_xyp: dict[str, Any] | None,
        verification_source: VerificationSource,
    ) -> Vehicle:
        vehicle = Vehicle(
            vin=vin,
            plate=plate,
            make=make,
            model=model,
            vehicle_brand_id=vehicle_brand_id,
            vehicle_model_id=vehicle_model_id,
            build_year=build_year,
            color=color,
            engine_number=engine_number,
            capacity_cc=capacity_cc,
            raw_xyp=raw_xyp,
            verification_source=verification_source,
        )
        self.session.add(vehicle)
        await self.session.flush()
        return vehicle

    async def touch_last_seen(
        self,
        vehicle: Vehicle,
        *,
        plate: str | None = None,
        raw_xyp: dict[str, Any] | None = None,
    ) -> None:
        """Refresh `last_seen_at` on an existing vehicle.

        Optionally update the plate or raw XYP snapshot when the new lookup
        returns fresher data.
        """
        vehicle.last_seen_at = datetime.now(UTC)
        if plate is not None:
            vehicle.plate = plate
        if raw_xyp is not None:
            vehicle.raw_xyp = raw_xyp
        await self.session.flush()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Vehicle]:
        stmt = (
            select(Vehicle)
            .join(VehicleOwnership, VehicleOwnership.vehicle_id == Vehicle.id)
            .where(VehicleOwnership.user_id == user_id)
            .order_by(VehicleOwnership.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())


class OwnershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> bool:
        stmt = select(VehicleOwnership).where(
            and_(
                VehicleOwnership.user_id == user_id,
                VehicleOwnership.vehicle_id == vehicle_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def add(self, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> VehicleOwnership:
        row = VehicleOwnership(user_id=user_id, vehicle_id=vehicle_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove(self, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> int:
        stmt = delete(VehicleOwnership).where(
            and_(
                VehicleOwnership.user_id == user_id,
                VehicleOwnership.vehicle_id == vehicle_id,
            )
        )
        result = await self.session.execute(stmt)
        # CursorResult.rowcount is an int; the base Result type from mypy's
        # perspective doesn't expose it, so we narrow explicitly.
        rowcount = getattr(result, "rowcount", 0) or 0
        return int(rowcount)


class LookupPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self) -> VehicleLookupPlan | None:
        stmt = select(VehicleLookupPlan).where(VehicleLookupPlan.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def activate(self, plan_version: str) -> VehicleLookupPlan:
        """Switch the active plan atomically.

        Flips every row to `is_active=false`, then flips the target row on.
        Runs inside the caller's transaction so rollback is safe.
        """
        await self.session.execute(update(VehicleLookupPlan).values(is_active=False))
        stmt = (
            update(VehicleLookupPlan)
            .where(VehicleLookupPlan.plan_version == plan_version)
            .values(is_active=True)
            .returning(VehicleLookupPlan)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"plan version {plan_version!r} not found")
        return row


class LookupReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        plate_masked: str,
        status_code: int,
        error_snippet: str | None,
        reported_by_user_id: uuid.UUID | None,
        plan_version: str | None,
    ) -> VehicleLookupReport:
        row = VehicleLookupReport(
            plate_masked=plate_masked,
            status_code=status_code,
            error_snippet=error_snippet,
            reported_by_user_id=reported_by_user_id,
            plan_version=plan_version,
        )
        self.session.add(row)
        await self.session.flush()
        return row
