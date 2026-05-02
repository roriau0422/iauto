"""Single import point for every ORM model in the project.

Alembic's `env.py` imports this module so that `Base.metadata` contains every
table before autogenerate runs. Adding a new model? Import it here.
"""

from __future__ import annotations

# -- businesses --------------------------------------------------------------
from app.businesses.models import Business, BusinessVehicleBrand

# -- catalog -----------------------------------------------------------------
from app.catalog.models import VehicleBrand, VehicleCountry, VehicleModel

# -- chat --------------------------------------------------------------------
from app.chat.models import ChatMessage, ChatThread

# -- identity ----------------------------------------------------------------
from app.identity.models import Device, RefreshToken, User

# -- marketplace -------------------------------------------------------------
from app.marketplace.models import (
    PartSearchRequest,
    Quote,
    Reservation,
    Review,
    Sale,
)

# -- media -------------------------------------------------------------------
from app.media.models import MediaAsset

# -- payments ----------------------------------------------------------------
from app.payments.models import LedgerEntry, PaymentEvent, PaymentIntent

# -- platform-owned tables (outbox, event archive) ---------------------------
from app.platform.outbox import OutboxEvent

# -- vehicles ----------------------------------------------------------------
from app.vehicles.models import (
    Vehicle,
    VehicleLookupPlan,
    VehicleLookupReport,
    VehicleOwnership,
    VehicleServiceLog,
)

__all__: list[str] = [
    "Business",
    "BusinessVehicleBrand",
    "ChatMessage",
    "ChatThread",
    "Device",
    "LedgerEntry",
    "MediaAsset",
    "OutboxEvent",
    "PartSearchRequest",
    "PaymentEvent",
    "PaymentIntent",
    "Quote",
    "RefreshToken",
    "Reservation",
    "Review",
    "Sale",
    "User",
    "Vehicle",
    "VehicleBrand",
    "VehicleCountry",
    "VehicleLookupPlan",
    "VehicleLookupReport",
    "VehicleModel",
    "VehicleOwnership",
    "VehicleServiceLog",
]
