"""Domain events emitted by the story context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.platform.events import DomainEvent


class StoryPostPublished(DomainEvent):
    event_type: Literal["story.post_published"] = "story.post_published"
    aggregate_type: Literal["story_post"] = "story_post"
    author_user_id: uuid.UUID
    author_kind: str


class StoryPostLiked(DomainEvent):
    event_type: Literal["story.post_liked"] = "story.post_liked"
    aggregate_type: Literal["story_post"] = "story_post"
    user_id: uuid.UUID


class StoryPostCommented(DomainEvent):
    event_type: Literal["story.post_commented"] = "story.post_commented"
    aggregate_type: Literal["story_post"] = "story_post"
    comment_id: uuid.UUID
    author_user_id: uuid.UUID


class StoryPostDeleted(DomainEvent):
    event_type: Literal["story.post_deleted"] = "story.post_deleted"
    aggregate_type: Literal["story_post"] = "story_post"
