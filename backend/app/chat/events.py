"""Domain events emitted by the chat context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.platform.events import DomainEvent


class ChatMessagePosted(DomainEvent):
    """A new chat message was appended to a thread.

    Subscribers (notifications context, eventually) use this for push
    delivery to the offline party. Real-time delivery to connected WS
    clients goes through Redis pubsub directly — that path doesn't
    touch the outbox because the dispatch latency budget is tighter
    than one outbox-tick interval.
    """

    event_type: Literal["chat.message_posted"] = "chat.message_posted"
    aggregate_type: Literal["chat_message"] = "chat_message"
    thread_id: uuid.UUID
    author_user_id: uuid.UUID | None
    kind: str
