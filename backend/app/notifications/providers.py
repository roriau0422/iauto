"""Push providers — Console (dev/test) + protocol for FCM/APNs.

Production wiring lands in phase 5 alongside the rest of the
production-hardening work. Today's worker uses ConsolePushProvider so
the entire pipeline is exercised end-to-end without an external
service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.notifications.models import NotificationProvider, NotificationStatus
from app.platform.logging import get_logger

logger = get_logger("app.notifications.providers")


@dataclass(slots=True)
class PushResult:
    status: NotificationStatus
    error: str | None = None


class PushProvider(Protocol):
    """Surface every concrete provider implements.

    `send` MUST be idempotent at the receiver's level (the notifications
    service writes the dispatch row before calling send, so a retry
    can't create duplicate audit entries).
    """

    name: NotificationProvider

    async def send(
        self,
        *,
        user_id: uuid.UUID,
        device_id: uuid.UUID | None,
        body_text: str,
        payload: dict[str, Any],
    ) -> PushResult: ...


class ConsolePushProvider:
    """Logs the push and returns `sent`.

    This is the dev/test default — useful for proving the wiring works
    without any external dependency. Production swaps it for FCM or
    APNs at composition time via the `get_push_provider` dependency.
    """

    name: NotificationProvider = NotificationProvider.console

    async def send(
        self,
        *,
        user_id: uuid.UUID,
        device_id: uuid.UUID | None,
        body_text: str,
        payload: dict[str, Any],
    ) -> PushResult:
        logger.info(
            "notification_console_send",
            user_id=str(user_id),
            device_id=str(device_id) if device_id is not None else None,
            body=body_text,
            payload=payload,
        )
        return PushResult(status=NotificationStatus.sent)
