"""Outbox subscribers for the chat context.

`on_quote_sent` registers against `marketplace.quote_sent` so a thread
auto-creates the moment a business posts a quote. Runs inside the
outbox-consumer's per-event savepoint, so any failure here only rolls
back this event — the rest of the batch still commits.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import ChatService
from app.media.client import S3MediaClient
from app.media.service import MediaService
from app.platform.cache import get_redis
from app.platform.config import get_settings
from app.platform.events import DomainEvent
from app.platform.logging import get_logger
from app.platform.outbox import register_handler

logger = get_logger("app.chat.handlers")


def _build_chat_service(session: AsyncSession, redis: Redis) -> ChatService:
    settings = get_settings()
    media = MediaService(
        session=session,
        client=S3MediaClient(settings),
        bucket=settings.s3_bucket_media,
    )
    return ChatService(session=session, redis=redis, media_svc=media)


async def on_quote_sent(event: DomainEvent, session: AsyncSession) -> None:
    """Auto-create the chat thread for every quote_sent event.

    `aggregate_id` on the event is the quote's UUID (see
    `marketplace.events.QuoteSent`).
    """
    quote_id_raw = event.aggregate_id
    quote_id = quote_id_raw if isinstance(quote_id_raw, uuid.UUID) else uuid.UUID(str(quote_id_raw))
    redis = get_redis()
    service = _build_chat_service(session, redis)
    thread = await service.ensure_thread_for_quote(quote_id=quote_id)
    logger.info(
        "chat_thread_autocreated_from_quote",
        thread_id=str(thread.id),
        quote_id=str(quote_id),
    )


def register() -> None:
    """Register all chat outbox handlers. Called from app lifespan."""
    register_handler("marketplace.quote_sent", on_quote_sent)
