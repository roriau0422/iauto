"""Domain event base class.

Domain events are Pydantic models written through the outbox. Concrete events
override `event_type` and `aggregate_type` with `Literal` values so they act
as discriminators on the serialized payload, and add whatever event-specific
fields they need.

Events must be immutable — set model_config.frozen=True on subclasses if you
need to be absolutely sure, though the outbox writer never mutates them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DomainEvent(BaseModel):
    """Envelope every concrete event subclasses.

    `event_type` follows `<context>.<verb>` convention (e.g.
    `identity.user_registered`). `aggregate_type` is the short name of the
    entity (`user`, `vehicle`, `part_search`, ...).

    Extra fields are allowed at the base level so that the outbox worker can
    re-hydrate any subclass's payload into a base `DomainEvent` without
    knowing the concrete type. Producer-side subclasses should override
    `model_config` with `extra="forbid"` if they want strict input validation.
    """

    model_config = ConfigDict(extra="allow")

    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    occurred_at: datetime = Field(default_factory=_utc_now)
