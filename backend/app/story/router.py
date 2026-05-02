"""HTTP routes for the story context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.businesses.dependencies import (
    BusinessContext,
    get_current_business_member,
)
from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.story.dependencies import get_story_service
from app.story.schemas import (
    StoryCommentCreateIn,
    StoryCommentDeleteOut,
    StoryCommentListOut,
    StoryCommentOut,
    StoryFeedOut,
    StoryLikeOut,
    StoryPostCreateIn,
    StoryPostDeleteOut,
    StoryPostOut,
    StoryUnlikeOut,
)
from app.story.service import StoryService

router = APIRouter(tags=["story"])


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------


@router.get(
    "/story/feed",
    response_model=StoryFeedOut,
    summary="Public timeline of business posts, newest first",
)
async def get_feed(
    service: Annotated[StoryService, Depends(get_story_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before_id: Annotated[uuid.UUID | None, Query()] = None,
) -> StoryFeedOut:
    result = await service.list_feed(limit=limit, before_id=before_id)
    return StoryFeedOut(
        items=[StoryPostOut.model_validate(p) for p in result.items],
        has_more=result.has_more,
    )


@router.get(
    "/story/posts/{post_id}",
    response_model=StoryPostOut,
    summary="Single post detail",
)
async def get_post(
    post_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
) -> StoryPostOut:
    post = await service.get(post_id)
    return StoryPostOut.model_validate(post)


@router.get(
    "/story/posts/{post_id}/comments",
    response_model=StoryCommentListOut,
    summary="Flat list of comments on a post, newest first",
)
async def list_comments(
    post_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_id: Annotated[uuid.UUID | None, Query()] = None,
) -> StoryCommentListOut:
    result = await service.list_comments(post_id=post_id, limit=limit, before_id=before_id)
    return StoryCommentListOut(
        items=[StoryCommentOut.model_validate(c) for c in result.items],
        has_more=result.has_more,
    )


# ---------------------------------------------------------------------------
# Business writes
# ---------------------------------------------------------------------------


@router.post(
    "/story/posts",
    response_model=StoryPostOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a story post (any business member)",
)
async def publish_post(
    body: StoryPostCreateIn,
    service: Annotated[StoryService, Depends(get_story_service)],
    ctx: Annotated[BusinessContext, Depends(get_current_business_member)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryPostOut:
    post = await service.publish(
        tenant_id=ctx.business.id,
        author_user_id=user.id,
        payload=body,
    )
    return StoryPostOut.model_validate(post)


@router.delete(
    "/story/posts/{post_id}",
    response_model=StoryPostDeleteOut,
    summary="Delete a story post (author or business owner only)",
)
async def delete_post(
    post_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryPostDeleteOut:
    await service.delete(post_id=post_id, actor_user_id=user.id)
    return StoryPostDeleteOut()


# ---------------------------------------------------------------------------
# Likes + comments (any authenticated user)
# ---------------------------------------------------------------------------


@router.post(
    "/story/posts/{post_id}/like",
    response_model=StoryLikeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Like a post (idempotent — 409 on second like)",
)
async def like_post(
    post_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryLikeOut:
    result = await service.like(post_id=post_id, user_id=user.id)
    return StoryLikeOut(post_id=post_id, user_id=user.id, like_count=result.like_count)


@router.delete(
    "/story/posts/{post_id}/like",
    response_model=StoryUnlikeOut,
    summary="Remove your like (idempotent)",
)
async def unlike_post(
    post_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryUnlikeOut:
    result = await service.unlike(post_id=post_id, user_id=user.id)
    return StoryUnlikeOut(post_id=post_id, like_count=result.like_count)


@router.post(
    "/story/posts/{post_id}/comments",
    response_model=StoryCommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a post",
)
async def add_comment(
    post_id: uuid.UUID,
    body: StoryCommentCreateIn,
    service: Annotated[StoryService, Depends(get_story_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryCommentOut:
    comment = await service.comment(post_id=post_id, author_user_id=user.id, payload=body)
    return StoryCommentOut.model_validate(comment)


@router.delete(
    "/story/comments/{comment_id}",
    response_model=StoryCommentDeleteOut,
    summary="Delete a comment (author or post-business-owner only)",
)
async def delete_comment(
    comment_id: uuid.UUID,
    service: Annotated[StoryService, Depends(get_story_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StoryCommentDeleteOut:
    await service.delete_comment(comment_id=comment_id, actor_user_id=user.id)
    return StoryCommentDeleteOut()
