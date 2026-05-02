"""Vehicles service — registration, listing, lookup plan, error reports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import CatalogService
from app.identity.providers.sms import SmsProvider
from app.platform.config import Settings
from app.platform.errors import ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event
from app.vehicles.alerts import AlertOutcome, XypAlerter
from app.vehicles.events import (
    VehicleLookupFailed,
    VehicleOwnershipAdded,
    VehicleOwnershipRemoved,
    VehicleRegistered,
)
from app.vehicles.models import (
    Vehicle,
    VehicleLookupPlan,
    VerificationSource,
    parse_import_month,
    parse_wheel_position,
)
from app.vehicles.repository import (
    LookupPlanRepository,
    LookupReportRepository,
    OwnershipRepository,
    VehicleRepository,
)
from app.vehicles.schemas import XypPayloadIn, mask_plate

logger = get_logger("app.vehicles.service")


# Body substrings that identify a classifiable user-input failure from the
# XYP gateway. Reports matching any of these are recorded for audit but do
# NOT page the operator — they're user typos, not outages. The plan's
# `expected.error_signatures` ships the same rules to the mobile client so
# those reports never reach us in the first place; this list exists as a
# second line of defence against buggy clients.
NOT_FOUND_SNIPPETS: tuple[str, ...] = ("олдсонгүй",)


@dataclass(slots=True)
class RegisterResult:
    vehicle: Vehicle
    was_new_vehicle: bool
    already_owned: bool


@dataclass(slots=True)
class ReportResult:
    alert: AlertOutcome


class VehiclesService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        sms: SmsProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vehicles = VehicleRepository(session)
        self.ownerships = OwnershipRepository(session)
        self.plans = LookupPlanRepository(session)
        self.reports = LookupReportRepository(session)
        self.catalog = CatalogService(session)
        self.alerter = XypAlerter(redis=redis, sms=sms, settings=settings)

    # ---- lookup plan -------------------------------------------------------

    async def get_active_plan(self) -> VehicleLookupPlan:
        plan = await self.plans.get_active()
        if plan is None:
            raise NotFoundError("No active vehicle lookup plan configured")
        return plan

    # ---- registration ------------------------------------------------------

    async def register_from_xyp(
        self,
        *,
        user_id: uuid.UUID,
        plate: str,
        xyp: XypPayloadIn,
    ) -> RegisterResult:
        vin = self._normalize_vin(xyp.cabinNumber)
        parsed = self._parse_xyp(xyp)

        resolved = await self.catalog.resolve_brand_model(
            make=parsed["make"], model=parsed["model"]
        )
        parsed["vehicle_brand_id"] = resolved.brand_id
        parsed["vehicle_model_id"] = resolved.model_id

        vehicle, was_new = await self._get_or_create_vehicle(
            plate=plate,
            vin=vin,
            parsed=parsed,
            raw_xyp=xyp.model_dump(mode="json", exclude_none=False),
        )

        already_owned = await self.ownerships.exists(user_id, vehicle.id)
        if not already_owned:
            await self.ownerships.add(user_id, vehicle.id)

        if was_new:
            write_outbox_event(
                self.session,
                VehicleRegistered(
                    aggregate_id=vehicle.id,
                    plate_masked=mask_plate(plate),
                    verification_source=VerificationSource.xyp_public.value,
                ),
            )
        if not already_owned:
            write_outbox_event(
                self.session,
                VehicleOwnershipAdded(
                    aggregate_id=vehicle.id,
                    user_id=user_id,
                    was_new_vehicle=was_new,
                ),
            )

        logger.info(
            "vehicle_registered",
            vehicle_id=str(vehicle.id),
            user_id=str(user_id),
            plate=mask_plate(plate),
            was_new=was_new,
            already_owned=already_owned,
        )
        return RegisterResult(
            vehicle=vehicle,
            was_new_vehicle=was_new,
            already_owned=already_owned,
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[Vehicle]:
        return await self.vehicles.list_for_user(user_id)

    async def get_vehicle(self, vehicle_id: uuid.UUID) -> Vehicle:
        """Return a Vehicle by id, 404 if it doesn't exist.

        Public accessor for other contexts (marketplace) that need vehicle
        facts (brand, build_year, steering_side) without reaching into the
        vehicles repository directly.
        """
        vehicle = await self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found")
        return vehicle

    async def check_ownership(self, *, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
        """Return the Vehicle if the user owns it, else opaque 404.

        Matches the `unregister` security convention: we never distinguish
        "vehicle doesn't exist" from "vehicle exists but you don't own it"
        — callers outside this context get one error message for both.
        """
        vehicle = await self.vehicles.get_by_id(vehicle_id)
        if vehicle is None or not await self.ownerships.exists(user_id, vehicle_id):
            raise NotFoundError("Vehicle not found")
        return vehicle

    async def list_service_history(self, *, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> list[Any]:
        """Return service-history entries for a vehicle the user owns.

        Session 7 ships this as a stub — the table exists and the
        endpoint returns whatever rows are present (empty for now). The
        full create flow ships in session 9.
        """
        from sqlalchemy import select as _select

        from app.vehicles.models import VehicleServiceLog

        await self.check_ownership(user_id=user_id, vehicle_id=vehicle_id)
        result = await self.session.execute(
            _select(VehicleServiceLog)
            .where(VehicleServiceLog.vehicle_id == vehicle_id)
            .order_by(VehicleServiceLog.noted_at.desc())
        )
        return list(result.scalars())

    async def unregister(self, *, user_id: uuid.UUID, vehicle_id: uuid.UUID) -> None:
        vehicle = await self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found")
        if not await self.ownerships.exists(user_id, vehicle_id):
            raise ForbiddenError("You do not own this vehicle")
        removed = await self.ownerships.remove(user_id, vehicle_id)
        if removed == 0:
            # Race: ownership vanished between exists() and remove().
            raise NotFoundError("Ownership already removed")
        write_outbox_event(
            self.session,
            VehicleOwnershipRemoved(
                aggregate_id=vehicle_id,
                user_id=user_id,
            ),
        )
        logger.info(
            "vehicle_unregistered",
            vehicle_id=str(vehicle_id),
            user_id=str(user_id),
        )

    # ---- error report / alerting ------------------------------------------

    async def record_lookup_failure(
        self,
        *,
        user_id: uuid.UUID | None,
        plate: str,
        status_code: int,
        error_snippet: str | None,
        plan_version: str | None,
    ) -> ReportResult:
        masked = mask_plate(plate)
        await self.reports.create(
            plate_masked=masked,
            status_code=status_code,
            error_snippet=error_snippet,
            reported_by_user_id=user_id,
            plan_version=plan_version,
        )
        write_outbox_event(
            self.session,
            VehicleLookupFailed(
                aggregate_id=uuid.uuid4(),
                status_code=status_code,
                plan_version=plan_version,
                plate_masked=masked,
            ),
        )

        if self._is_user_input_error(status_code, error_snippet):
            logger.info(
                "xyp_report_classified_as_user_error",
                status=status_code,
                masked_plate=masked,
            )
            return ReportResult(
                alert=AlertOutcome(fired=False, window_count=0, operator_notified=False)
            )

        outcome = await self.alerter.record_and_maybe_page(
            status_code=status_code,
            masked_plate=masked,
        )
        return ReportResult(alert=outcome)

    @staticmethod
    def _is_user_input_error(status_code: int, error_snippet: str | None) -> bool:
        """Return True when the reported failure looks like a user typo.

        smartcar.mn returns HTTP 400 with a Mongolian text body containing
        `олдсонгүй` ("not found") when the plate doesn't exist in the
        registry. That's a user mistake, not a gateway outage — we record
        the report for audit but suppress the operator page.
        """
        if status_code != 400 or not error_snippet:
            return False
        return any(pat in error_snippet for pat in NOT_FOUND_SNIPPETS)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _normalize_vin(raw: str | None) -> str | None:
        if raw is None:
            return None
        stripped = raw.strip().upper()
        return stripped or None

    @staticmethod
    def _coerce_int(raw: int | float | str | None) -> int | None:
        """Tolerant integer coercion.

        Handles int, float (XYP returns capacity as `3956.0`), string, None.
        Returns None for anything that can't be parsed.
        """
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):  # bool is an int subclass — reject
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float):
            return int(raw)
        try:
            return int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_xyp(cls, xyp: XypPayloadIn) -> dict[str, Any]:
        return {
            "make": xyp.markName,
            "model": xyp.modelName,
            "build_year": cls._coerce_int(xyp.buildYear),
            "engine_number": (
                xyp.motorNumber.strip()
                if xyp.motorNumber is not None and xyp.motorNumber.strip()
                else None
            ),
            "color": xyp.colorName,
            "capacity_cc": cls._coerce_int(xyp.capacity),
            "class_code": (
                xyp.className.strip()
                if xyp.className is not None and xyp.className.strip()
                else None
            ),
            "fuel_type": (
                xyp.fuelType.strip() if xyp.fuelType is not None and xyp.fuelType.strip() else None
            ),
            "import_month": parse_import_month(xyp.importDate),
            "steering_side": parse_wheel_position(xyp.wheelPosition),
        }

    async def _get_or_create_vehicle(
        self,
        *,
        plate: str,
        vin: str | None,
        parsed: dict[str, Any],
        raw_xyp: dict[str, Any],
    ) -> tuple[Vehicle, bool]:
        if vin is not None:
            existing = await self.vehicles.get_by_vin(vin)
            if existing is not None:
                await self.vehicles.touch_last_seen(existing, plate=plate, raw_xyp=raw_xyp)
                return existing, False

        created = await self.vehicles.create(
            vin=vin,
            plate=plate,
            make=parsed["make"],
            model=parsed["model"],
            vehicle_brand_id=parsed.get("vehicle_brand_id"),
            vehicle_model_id=parsed.get("vehicle_model_id"),
            build_year=parsed["build_year"],
            color=parsed["color"],
            engine_number=parsed["engine_number"],
            capacity_cc=parsed["capacity_cc"],
            class_code=parsed["class_code"],
            fuel_type=parsed["fuel_type"],
            import_month=parsed["import_month"],
            steering_side=parsed["steering_side"],
            raw_xyp=raw_xyp,
            verification_source=VerificationSource.xyp_public,
        )
        return created, True
