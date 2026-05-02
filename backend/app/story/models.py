"""ORM models for the story context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


class StoryPost(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """One business-authored post on the public timeline.

    Denormalized counters (`like_count`, `comment_count`) are bumped in
    the same transaction as the like/comment so the feed renders
    without a per-post subselect. The pivot tables are still the
    source of truth — counters are a perf optimization, not the audit.
    """

    __tablename__ = "story_posts"

    author_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    media_asset_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class StoryLike(Base):
    """Pivot — composite PK on (post_id, user_id). At most one like per user."""

    __tablename__ = "story_likes"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("story_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StoryComment(UuidPrimaryKey, Base):
    """Flat comment on a post.

    No `parent_id` — Phase 2 ships flat comments only. If product wants
    threading later, an additive migration adds the column.
    """

    __tablename__ = "story_comments"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("story_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
