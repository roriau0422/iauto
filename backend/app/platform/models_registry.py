"""Single import point for every ORM model in the project.

Alembic's `env.py` imports this module so that `Base.metadata` contains every
table before autogenerate runs. Adding a new model? Import it here.
"""

from __future__ import annotations

# -- identity ----------------------------------------------------------------
from app.identity.models import Device, RefreshToken, User

# -- platform-owned tables (outbox, event archive) ---------------------------
from app.platform.outbox import OutboxEvent

# -- vehicles ----------------------------------------------------------------
from app.vehicles.models import (
    Vehicle,
    VehicleLookupPlan,
    VehicleLookupReport,
    VehicleOwnership,
)

__all__: list[str] = [
    "Device",
    "OutboxEvent",
    "RefreshToken",
    "User",
    "Vehicle",
    "VehicleLookupPlan",
    "VehicleLookupReport",
    "VehicleOwnership",
]
