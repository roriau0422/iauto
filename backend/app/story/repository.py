"""Database access for the story context."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, literal, select, tuple_ as sa_tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.story.models import StoryComment, StoryLike, StoryPost


class StoryPostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, post_id: uuid.UUID) -> StoryPost | None:
        return await self.session.get(StoryPost, post_id)

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        author_user_id: uuid.UUID,
        body: str,
        media_asset_ids: list[uuid.UUID],
    ) -> StoryPost:
        post = StoryPost(
            tenant_id=tenant_id,
            author_user_id=author_user_id,
            body=body,
            media_asset_ids=[str(i) for i in media_asset_ids],
        )
        self.session.add(post)
        await self.session.flush()
        return post

    async def list_feed(
        self,
        *,
        limit: int,
        before_id: uuid.UUID | None,
    ) -> tuple[list[StoryPost], bool]:
        """Newest-first cursor pagination.

        Tie-break on `(created_at, id)` so co-timestamped posts are
        deterministically ordered. Mirrors the chat-message cursor
        pattern from session 8.
        """
        stmt = (
            select(StoryPost)
            .order_by(StoryPost.created_at.desc(), StoryPost.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            cursor = await self.session.get(StoryPost, before_id)
            if cursor is not None:
                stmt = (
                    select(StoryPost)
                    .where(
                        sa_tuple(StoryPost.created_at, StoryPost.id)
                        < sa_tuple(literal(cursor.created_at), literal(cursor.id))
                    )
                    .order_by(StoryPost.created_at.desc(), StoryPost.id.desc())
                    .limit(limit + 1)
                )
        rows = list((await self.session.execute(stmt)).scalars())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def delete(self, post: StoryPost) -> None:
        await self.session.delete(post)
        await self.session.flush()

    async def increment_like_count(self, post: StoryPost, delta: int) -> None:
        post.like_count = max(0, post.like_count + delta)
        await self.session.flush()

    async def increment_comment_count(self, post: StoryPost, delta: int) -> None:
        post.comment_count = max(0, post.comment_count + delta)
        await self.session.flush()


class StoryLikeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, *, post_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        like = await self.session.get(StoryLike, (post_id, user_id))
        return like is not None

    async def create(self, *, post_id: uuid.UUID, user_id: uuid.UUID) -> StoryLike:
        like = StoryLike(post_id=post_id, user_id=user_id)
        self.session.add(like)
        await self.session.flush()
        return like

    async def delete(self, *, post_id: uuid.UUID, user_id: uuid.UUID) -> int:
        from sqlalchemy.engine import CursorResult

        raw = await self.session.execute(
            delete(StoryLike).where(
                StoryLike.post_id == post_id,
                StoryLike.user_id == user_id,
            )
        )
        await self.session.flush()
        return raw.rowcount if isinstance(raw, CursorResult) else 0


class StoryCommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, comment_id: uuid.UUID) -> StoryComment | None:
        return await self.session.get(StoryComment, comment_id)

    async def create(
        self,
        *,
        post_id: uuid.UUID,
        author_user_id: uuid.UUID,
        body: str,
    ) -> StoryComment:
        comment = StoryComment(
            post_id=post_id,
            author_user_id=author_user_id,
            body=body,
        )
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def list_for_post(
        self,
        *,
        post_id: uuid.UUID,
        limit: int,
        before_id: uuid.UUID | None,
    ) -> tuple[list[StoryComment], bool]:
        stmt = (
            select(StoryComment)
            .where(StoryComment.post_id == post_id)
            .order_by(StoryComment.created_at.desc(), StoryComment.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            cursor = await self.session.get(StoryComment, before_id)
            if cursor is not None:
                stmt = (
                    select(StoryComment)
                    .where(
                        StoryComment.post_id == post_id,
                        sa_tuple(StoryComment.created_at, StoryComment.id)
                        < sa_tuple(literal(cursor.created_at), literal(cursor.id)),
                    )
                    .order_by(StoryComment.created_at.desc(), StoryComment.id.desc())
                    .limit(limit + 1)
                )
        rows = list((await self.session.execute(stmt)).scalars())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def count_for_post(self, post_id: uuid.UUID) -> int:
        stmt = select(func.count(StoryComment.id)).where(StoryComment.post_id == post_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def delete(self, comment: StoryComment) -> None:
        await self.session.delete(comment)
        await self.session.flush()
