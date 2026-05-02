"""Story service — posts, likes, flat comments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.repository import BusinessMemberRepository
from app.media.models import MediaAssetPurpose
from app.media.service import MediaService
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event
from app.story.events import (
    StoryPostCommented,
    StoryPostDeleted,
    StoryPostLiked,
    StoryPostPublished,
)
from app.story.models import StoryAuthorKind, StoryComment, StoryPost
from app.story.repository import (
    StoryCommentRepository,
    StoryLikeRepository,
    StoryPostRepository,
)
from app.story.schemas import StoryCommentCreateIn, StoryPostCreateIn

logger = get_logger("app.story.service")


@dataclass(slots=True)
class FeedResult:
    items: list[StoryPost]
    has_more: bool


@dataclass(slots=True)
class CommentListResult:
    items: list[StoryComment]
    has_more: bool


@dataclass(slots=True)
class LikeResult:
    post: StoryPost
    like_count: int
    already_liked: bool


class StoryService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        media_svc: MediaService,
    ) -> None:
        self.session = session
        self.posts = StoryPostRepository(session)
        self.likes = StoryLikeRepository(session)
        self.comments = StoryCommentRepository(session)
        self.members = BusinessMemberRepository(session)
        self.media_svc = media_svc

    # ---- posts ----------------------------------------------------------

    async def publish_as_business(
        self,
        *,
        tenant_id: uuid.UUID,
        author_user_id: uuid.UUID,
        payload: StoryPostCreateIn,
    ) -> StoryPost:
        """A business member publishes on behalf of the tenant."""
        return await self._publish(
            author_kind=StoryAuthorKind.business,
            tenant_id=tenant_id,
            author_user_id=author_user_id,
            payload=payload,
        )

    async def publish_as_driver(
        self,
        *,
        author_user_id: uuid.UUID,
        payload: StoryPostCreateIn,
    ) -> StoryPost:
        """A driver publishes a personal post — no tenant binding."""
        return await self._publish(
            author_kind=StoryAuthorKind.driver,
            tenant_id=None,
            author_user_id=author_user_id,
            payload=payload,
        )

    async def _publish(
        self,
        *,
        author_kind: StoryAuthorKind,
        tenant_id: uuid.UUID | None,
        author_user_id: uuid.UUID,
        payload: StoryPostCreateIn,
    ) -> StoryPost:
        await self.media_svc.validate_asset_ids(
            owner_id=author_user_id,
            asset_ids=payload.media_asset_ids,
            purpose=MediaAssetPurpose.story,
        )
        post = await self.posts.create(
            author_kind=author_kind,
            tenant_id=tenant_id,
            author_user_id=author_user_id,
            body=payload.body,
            media_asset_ids=payload.media_asset_ids,
        )
        write_outbox_event(
            self.session,
            StoryPostPublished(
                aggregate_id=post.id,
                tenant_id=tenant_id,
                author_user_id=author_user_id,
                author_kind=author_kind.value,
            ),
        )
        logger.info(
            "story_post_published",
            post_id=str(post.id),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            author_kind=author_kind.value,
        )
        return post

    async def get(self, post_id: uuid.UUID) -> StoryPost:
        post = await self.posts.get_by_id(post_id)
        if post is None:
            raise NotFoundError("Post not found")
        return post

    async def list_feed(self, *, limit: int, before_id: uuid.UUID | None) -> FeedResult:
        items, has_more = await self.posts.list_feed(limit=limit, before_id=before_id)
        return FeedResult(items=items, has_more=has_more)

    async def delete(
        self,
        *,
        post_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> None:
        post = await self.get(post_id)
        # Author can always delete. For business-authored posts, the
        # business owner can also delete (moderation safety net). Driver
        # posts have no co-author concept — only the author can remove.
        if post.author_user_id != actor_user_id:
            if post.tenant_id is None:
                raise ForbiddenError("Only the author can delete")
            member = await self.members.get(post.tenant_id, actor_user_id)
            from app.businesses.models import BusinessMemberRole

            if member is None or member.role != BusinessMemberRole.owner:
                raise ForbiddenError("Only the author or business owner can delete")
        tenant_id = post.tenant_id
        await self.posts.delete(post)
        write_outbox_event(
            self.session,
            StoryPostDeleted(aggregate_id=post_id, tenant_id=tenant_id),
        )
        logger.info("story_post_deleted", post_id=str(post_id))

    # ---- likes ----------------------------------------------------------

    async def like(self, *, post_id: uuid.UUID, user_id: uuid.UUID) -> LikeResult:
        post = await self.get(post_id)
        if await self.likes.exists(post_id=post.id, user_id=user_id):
            raise ConflictError("You have already liked this post")
        try:
            async with self.session.begin_nested():
                await self.likes.create(post_id=post.id, user_id=user_id)
        except IntegrityError as exc:
            raise ConflictError("You have already liked this post") from exc
        await self.posts.increment_like_count(post, 1)
        write_outbox_event(
            self.session,
            StoryPostLiked(
                aggregate_id=post.id,
                tenant_id=post.tenant_id,
                user_id=user_id,
            ),
        )
        return LikeResult(post=post, like_count=post.like_count, already_liked=False)

    async def unlike(self, *, post_id: uuid.UUID, user_id: uuid.UUID) -> LikeResult:
        post = await self.get(post_id)
        deleted = await self.likes.delete(post_id=post.id, user_id=user_id)
        if deleted == 0:
            return LikeResult(post=post, like_count=post.like_count, already_liked=False)
        await self.posts.increment_like_count(post, -1)
        return LikeResult(post=post, like_count=post.like_count, already_liked=True)

    # ---- comments -------------------------------------------------------

    async def comment(
        self,
        *,
        post_id: uuid.UUID,
        author_user_id: uuid.UUID,
        payload: StoryCommentCreateIn,
    ) -> StoryComment:
        post = await self.get(post_id)
        comment = await self.comments.create(
            post_id=post.id,
            author_user_id=author_user_id,
            body=payload.body,
        )
        await self.posts.increment_comment_count(post, 1)
        write_outbox_event(
            self.session,
            StoryPostCommented(
                aggregate_id=post.id,
                tenant_id=post.tenant_id,
                comment_id=comment.id,
                author_user_id=author_user_id,
            ),
        )
        return comment

    async def list_comments(
        self,
        *,
        post_id: uuid.UUID,
        limit: int,
        before_id: uuid.UUID | None,
    ) -> CommentListResult:
        await self.get(post_id)
        items, has_more = await self.comments.list_for_post(
            post_id=post_id, limit=limit, before_id=before_id
        )
        return CommentListResult(items=items, has_more=has_more)

    async def delete_comment(
        self,
        *,
        comment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> None:
        comment = await self.comments.get_by_id(comment_id)
        if comment is None:
            raise NotFoundError("Comment not found")
        post = await self.posts.get_by_id(comment.post_id)
        if post is None:
            # Shouldn't happen — FK CASCADE on comment.post_id — but
            # the type checker doesn't know that.
            raise NotFoundError("Post not found")
        if comment.author_user_id != actor_user_id:
            # Non-author: only the post's business owner can delete. Driver
            # posts have no business owner — comments on them can only be
            # removed by their own author.
            if post.tenant_id is None:
                raise ForbiddenError("Only the comment author can delete")
            from app.businesses.models import BusinessMemberRole

            member = await self.members.get(post.tenant_id, actor_user_id)
            if member is None or member.role != BusinessMemberRole.owner:
                raise ForbiddenError("Only the comment author or business owner can delete")
        await self.comments.delete(comment)
        await self.posts.increment_comment_count(post, -1)
        logger.info("story_comment_deleted", comment_id=str(comment_id))
