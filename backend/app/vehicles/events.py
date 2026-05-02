"""Domain events emitted by the vehicles context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.platform.events import DomainEvent


class VehicleRegistered(DomainEvent):
    """A brand-new physical car (new VIN) has entered the platform.

    Fires once per VIN, not once per ownership. The analytics flywheel uses
    this to count distinct cars; `ownership_added` is the event that fires
    for every successful user-side registration.
    """

    event_type: Literal["vehicles.vehicle_registered"] = "vehicles.vehicle_registered"
    aggregate_type: Literal["vehicle"] = "vehicle"
    plate_masked: str
    verification_source: str


class VehicleOwnershipAdded(DomainEvent):
    event_type: Literal["vehicles.ownership_added"] = "vehicles.ownership_added"
    aggregate_type: Literal["vehicle"] = "vehicle"
    user_id: uuid.UUID
    was_new_vehicle: bool


class VehicleOwnershipRemoved(DomainEvent):
    event_type: Literal["vehicles.ownership_removed"] = "vehicles.ownership_removed"
    aggregate_type: Literal["vehicle"] = "vehicle"
    user_id: uuid.UUID


class VehicleLookupFailed(DomainEvent):
    """Emitted when a mobile client reports a 3xx/4xx/5xx from the XYP gateway."""

    event_type: Literal["vehicles.lookup_failed"] = "vehicles.lookup_failed"
    aggregate_type: Literal["vehicle_lookup"] = "vehicle_lookup"
    status_code: int
    plan_version: str | None
    plate_masked: str


class VehicleServiceLogged(DomainEvent):
    """A service-history entry was added to a vehicle (spec §9.3)."""

    event_type: Literal["vehicles.service_logged"] = "vehicles.service_logged"
    aggregate_type: Literal["vehicle_service_log"] = "vehicle_service_log"
    vehicle_id: uuid.UUID
    user_id: uuid.UUID
    kind: str
