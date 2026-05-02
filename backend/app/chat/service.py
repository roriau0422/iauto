"""Chat service — thread auto-create, message append, party gates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.repository import BusinessRepository
from app.chat.events import ChatMessagePosted
from app.chat.models import ChatMessage, ChatMessageKind, ChatThread
from app.chat.pubsub import publish_message
from app.chat.repository import ChatMessageRepository, ChatThreadRepository
from app.marketplace.repository import QuoteRepository
from app.media.models import MediaAssetPurpose
from app.media.service import MediaService
from app.platform.errors import ForbiddenError, NotFoundError, ValidationError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event

logger = get_logger("app.chat.service")


@dataclass(slots=True)
class ThreadListResult:
    items: list[ChatThread]
    total: int


@dataclass(slots=True)
class MessageListResult:
    items: list[ChatMessage]
    has_more: bool


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        media_svc: MediaService,
    ) -> None:
        self.session = session
        self.redis = redis
        self.threads = ChatThreadRepository(session)
        self.messages = ChatMessageRepository(session)
        self.quotes = QuoteRepository(session)
        self.businesses = BusinessRepository(session)
        self.media_svc = media_svc

    # ---- thread auto-create -------------------------------------------

    async def ensure_thread_for_quote(self, *, quote_id: uuid.UUID) -> ChatThread:
        """Create the thread for a quote if it doesn't exist; idempotent.

        Called from the outbox handler on `marketplace.quote_sent`. The
        unique constraint on `quote_id` is the canonical race-guard:
        if two outbox-consumer instances fire the handler concurrently,
        the loser catches an IntegrityError and re-reads.
        """
        existing = await self.threads.get_by_quote_id(quote_id)
        if existing is not None:
            return existing

        quote = await self.quotes.get_by_id(quote_id)
        if quote is None:
            raise NotFoundError("Quote not found")

        # part_search.driver_id is the chat counterparty.
        from app.marketplace.repository import PartSearchRepository

        searches = PartSearchRepository(self.session)
        search = await searches.get_by_id(quote.part_search_id)
        if search is None:
            raise NotFoundError("Search not found")

        try:
            thread = await self.threads.create(
                tenant_id=quote.tenant_id,
                quote_id=quote.id,
                part_search_id=search.id,
                driver_id=search.driver_id,
            )
        except IntegrityError:
            # Lost the race; re-read.
            await self.session.rollback()
            existing = await self.threads.get_by_quote_id(quote_id)
            if existing is None:
                raise
            return existing

        # System welcome message inside the same transaction.
        await self.messages.create(
            thread_id=thread.id,
            author_user_id=None,
            kind=ChatMessageKind.system,
            body=f"Quote sent for {quote.price_mnt} MNT.",
            media_asset_id=None,
        )
        await self.threads.touch_last_message_at(thread)
        logger.info("chat_thread_created", thread_id=str(thread.id), quote_id=str(quote.id))
        return thread

    # ---- read access ---------------------------------------------------

    async def get_thread_for_party(
        self,
        *,
        thread_id: uuid.UUID,
        user_id: uuid.UUID,
        business_id: uuid.UUID | None,
    ) -> ChatThread:
        thread = await self.threads.get_by_id(thread_id)
        if thread is None:
            raise NotFoundError("Thread not found")
        if thread.driver_id == user_id:
            return thread
        if business_id is not None and thread.tenant_id == business_id:
            return thread
        raise NotFoundError("Thread not found")

    async def list_threads_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> ThreadListResult:
        items, total = await self.threads.list_for_driver(
            driver_id=driver_id, limit=limit, offset=offset
        )
        return ThreadListResult(items=items, total=total)

    async def list_threads_for_business(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> ThreadListResult:
        items, total = await self.threads.list_for_business(
            business_id=business_id, limit=limit, offset=offset
        )
        return ThreadListResult(items=items, total=total)

    async def list_messages(
        self,
        *,
        thread: ChatThread,
        limit: int,
        before_id: uuid.UUID | None,
    ) -> MessageListResult:
        items, has_more = await self.messages.list_for_thread(
            thread_id=thread.id, limit=limit, before_id=before_id
        )
        return MessageListResult(items=items, has_more=has_more)

    # ---- message append ------------------------------------------------

    async def post_message(
        self,
        *,
        thread: ChatThread,
        author_user_id: uuid.UUID,
        kind: ChatMessageKind,
        body: str | None,
        media_asset_id: uuid.UUID | None,
    ) -> ChatMessage:
        """Append a message and fan it out via Redis Pub/Sub."""
        if kind == ChatMessageKind.system:
            # System messages are server-only.
            raise ForbiddenError("Cannot post system messages from API")
        if kind == ChatMessageKind.media and media_asset_id is None:
            raise ValidationError("media messages require media_asset_id")

        if media_asset_id is not None:
            await self.media_svc.validate_asset_ids(
                owner_id=author_user_id,
                asset_ids=[media_asset_id],
                purpose=MediaAssetPurpose.review,
            )

        message = await self.messages.create(
            thread_id=thread.id,
            author_user_id=author_user_id,
            kind=kind,
            body=body,
            media_asset_id=media_asset_id,
        )
        await self.threads.touch_last_message_at(thread)

        write_outbox_event(
            self.session,
            ChatMessagePosted(
                aggregate_id=message.id,
                tenant_id=thread.tenant_id,
                thread_id=thread.id,
                author_user_id=author_user_id,
                kind=kind.value,
            ),
        )

        # Live fan-out: serialize the persisted shape so downstream WS
        # consumers don't have to re-query the row. Best-effort — a
        # Redis blip doesn't block the API response.
        try:
            await publish_message(
                redis=self.redis,
                thread_id=thread.id,
                payload={
                    "type": "message",
                    "message": {
                        "id": str(message.id),
                        "thread_id": str(message.thread_id),
                        "author_user_id": (
                            str(message.author_user_id)
                            if message.author_user_id is not None
                            else None
                        ),
                        "kind": message.kind.value,
                        "body": message.body,
                        "media_asset_id": (
                            str(message.media_asset_id)
                            if message.media_asset_id is not None
                            else None
                        ),
                        "created_at": message.created_at.isoformat(),
                    },
                },
            )
        except Exception as exc:
            logger.warning("chat_pubsub_publish_failed", error=str(exc))

        logger.info(
            "chat_message_posted",
            message_id=str(message.id),
            thread_id=str(thread.id),
            kind=kind.value,
        )
        return message
