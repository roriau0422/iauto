"""Single import point for every ORM model in the project.

Alembic's `env.py` imports this module so that `Base.metadata` contains every
table before autogenerate runs. Adding a new model? Import it here.
"""

from __future__ import annotations

# -- ads ---------------------------------------------------------------------
from app.ads.models import AdCampaign, AdClick, AdImpression

# -- ai_mechanic -------------------------------------------------------------
from app.ai_mechanic.models import (
    AiKbChunk,
    AiKbDocument,
    AiMessage,
    AiSession,
    AiSpendEvent,
    AiVoiceTranscript,
)

# -- businesses --------------------------------------------------------------
from app.businesses.models import Business, BusinessMember, BusinessVehicleBrand

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

# -- notifications -----------------------------------------------------------
from app.notifications.models import NotificationDispatch

# -- payments ----------------------------------------------------------------
from app.payments.models import LedgerEntry, PaymentEvent, PaymentIntent

# -- platform-owned tables (outbox, event archive) ---------------------------
from app.platform.outbox import OutboxEvent

# -- story -------------------------------------------------------------------
from app.story.models import StoryComment, StoryLike, StoryPost

# -- vehicles ----------------------------------------------------------------
from app.vehicles.models import (
    Vehicle,
    VehicleLookupPlan,
    VehicleLookupReport,
    VehicleOwnership,
    VehicleServiceLog,
)

# -- warehouse ---------------------------------------------------------------
from app.warehouse.models import WarehouseSku, WarehouseStockMovement

__all__: list[str] = [
    "AdCampaign",
    "AdClick",
    "AdImpression",
    "AiKbChunk",
    "AiKbDocument",
    "AiMessage",
    "AiSession",
    "AiSpendEvent",
    "AiVoiceTranscript",
    "Business",
    "BusinessMember",
    "BusinessVehicleBrand",
    "ChatMessage",
    "ChatThread",
    "Device",
    "LedgerEntry",
    "MediaAsset",
    "NotificationDispatch",
    "OutboxEvent",
    "PartSearchRequest",
    "PaymentEvent",
    "PaymentIntent",
    "Quote",
    "RefreshToken",
    "Reservation",
    "Review",
    "Sale",
    "StoryComment",
    "StoryLike",
    "StoryPost",
    "User",
    "Vehicle",
    "VehicleBrand",
    "VehicleCountry",
    "VehicleLookupPlan",
    "VehicleLookupReport",
    "VehicleModel",
    "VehicleOwnership",
    "VehicleServiceLog",
    "WarehouseSku",
    "WarehouseStockMovement",
]
