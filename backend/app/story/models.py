"""ORM models for the story context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class StoryAuthorKind(StrEnum):
    """Whether a story post was published by a driver or a business.

    Drivers post personal updates to the public feed; businesses post on
    behalf of their tenant. The `author_kind = 'business'` ↔ `tenant_id IS
    NOT NULL` invariant is enforced in the DB by a CHECK constraint
    declared in migration 0021.
    """

    driver = "driver"
    business = "business"


class StoryPost(UuidPrimaryKey, Timestamped, Base):
    """One post on the public timeline.

    Authored by either a driver (no `tenant_id`) or a business member
    (`tenant_id = business.id`). The `author_kind` enum makes the
    distinction explicit so feed renderers don't have to do
    "tenant_id IS NULL" gymnastics.

    Denormalized counters (`like_count`, `comment_count`) are bumped in
    the same transaction as the like/comment so the feed renders without
    a per-post subselect. The pivot tables are still the source of
    truth — counters are a perf optimization, not the audit.

    NOTE: `StoryPost` no longer inherits the `TenantScoped` mixin
    because driver posts don't have a tenant. Tenant-scoped queries
    (e.g. "all posts by this business") still work — they just take the
    plain `tenant_id` column as a required filter, the same way
    repository methods do everywhere else.
    """

    __tablename__ = "story_posts"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    author_kind: Mapped[StoryAuthorKind] = mapped_column(
        SAEnum(StoryAuthorKind, name="story_author_kind", native_enum=True),
        nullable=False,
    )
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
