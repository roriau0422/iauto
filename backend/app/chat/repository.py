"""Database access for the chat context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ChatMessage, ChatMessageKind, ChatThread


class ChatThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, thread_id: uuid.UUID) -> ChatThread | None:
        return await self.session.get(ChatThread, thread_id)

    async def get_by_quote_id(self, quote_id: uuid.UUID) -> ChatThread | None:
        stmt = select(ChatThread).where(ChatThread.quote_id == quote_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        quote_id: uuid.UUID,
        part_search_id: uuid.UUID,
        driver_id: uuid.UUID,
    ) -> ChatThread:
        thread = ChatThread(
            tenant_id=tenant_id,
            quote_id=quote_id,
            part_search_id=part_search_id,
            driver_id=driver_id,
        )
        self.session.add(thread)
        await self.session.flush()
        return thread

    async def list_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatThread], int]:
        base = select(ChatThread).where(ChatThread.driver_id == driver_id)
        stmt = (
            base.order_by(ChatThread.last_message_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count(ChatThread.id)).where(ChatThread.driver_id == driver_id)
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def list_for_business(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatThread], int]:
        base = select(ChatThread).where(ChatThread.tenant_id == business_id)
        stmt = (
            base.order_by(ChatThread.last_message_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count(ChatThread.id)).where(ChatThread.tenant_id == business_id)
        rows = list((await self.session.execute(stmt)).scalars())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def touch_last_message_at(self, thread: ChatThread) -> None:
        thread.last_message_at = datetime.now(UTC)
        await self.session.flush()


class ChatMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        thread_id: uuid.UUID,
        author_user_id: uuid.UUID | None,
        kind: ChatMessageKind,
        body: str | None,
        media_asset_id: uuid.UUID | None,
    ) -> ChatMessage:
        message = ChatMessage(
            thread_id=thread_id,
            author_user_id=author_user_id,
            kind=kind,
            body=body,
            media_asset_id=media_asset_id,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_for_thread(
        self,
        *,
        thread_id: uuid.UUID,
        limit: int,
        before_id: uuid.UUID | None,
    ) -> tuple[list[ChatMessage], bool]:
        """Paginated newest-first list. `before_id` cursors backwards.

        Returns `(items, has_more)`. `has_more` is True iff a row exists
        older than the last returned message — used by the client to
        know whether to keep paging.

        Cursor predicate: messages older than the cursor row's
        `(created_at, id)` tuple. Lexicographic compare on the pair
        breaks timestamp ties (a fast test loop can plant two messages
        with identical `created_at` resolution).
        """
        # Fetch limit+1 to know `has_more` cheaply.
        from sqlalchemy import literal, tuple_ as sa_tuple

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            cursor = await self.session.get(ChatMessage, before_id)
            if cursor is not None:
                stmt = (
                    select(ChatMessage)
                    .where(
                        ChatMessage.thread_id == thread_id,
                        sa_tuple(ChatMessage.created_at, ChatMessage.id)
                        < sa_tuple(literal(cursor.created_at), literal(cursor.id)),
                    )
                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                    .limit(limit + 1)
                )

        rows = list((await self.session.execute(stmt)).scalars())
        has_more = len(rows) > limit
        return rows[:limit], has_more
