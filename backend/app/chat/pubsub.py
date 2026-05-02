"""Redis Pub/Sub fan-out for chat messages.

A single FastAPI process can serve many WebSocket connections; many
processes can serve a single thread. Redis Pub/Sub bridges the two:
every persisted message is published to `chat:thread:{thread_id}` and
every subscribed connection on any process picks it up.

We never write to Pub/Sub for durability — that's `chat_messages`'s
job. Pub/Sub is the live-delivery side channel only.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis.asyncio import Redis


def _channel_for(thread_id: uuid.UUID) -> str:
    return f"chat:thread:{thread_id}"


async def publish_message(
    *,
    redis: Redis,
    thread_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Fan out a serialized message to every subscriber of this thread."""
    await redis.publish(_channel_for(thread_id), json.dumps(payload))


def channel_for(thread_id: uuid.UUID) -> str:
    """Public helper for the WebSocket subscriber to know what to listen on."""
    return _channel_for(thread_id)
