"""Domain events emitted by the identity context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.identity.models import UserRole
from app.platform.events import DomainEvent


class UserRegistered(DomainEvent):
    event_type: Literal["identity.user_registered"] = "identity.user_registered"
    aggregate_type: Literal["user"] = "user"
    phone_masked: str
    role: UserRole


class SessionStarted(DomainEvent):
    event_type: Literal["identity.session_started"] = "identity.session_started"
    aggregate_type: Literal["user"] = "user"
    device_id: uuid.UUID
    platform: str


class SessionRefreshed(DomainEvent):
    event_type: Literal["identity.session_refreshed"] = "identity.session_refreshed"
    aggregate_type: Literal["user"] = "user"
    device_id: uuid.UUID


class SessionRevoked(DomainEvent):
    event_type: Literal["identity.session_revoked"] = "identity.session_revoked"
    aggregate_type: Literal["user"] = "user"
    device_id: uuid.UUID
    reason: Literal["logout", "refresh_rotation", "admin"] = "logout"
