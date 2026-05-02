"""ORM models for the chat context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


class ChatMessageKind(StrEnum):
    """Three kinds of chat messages.

    - `text`   — free-form body, written by a human party (driver or business).
    - `media`  — body may or may not be set; payload is the FK to a confirmed
                 media_asset.
    - `system` — server-generated notice (thread auto-created, reservation
                 started, etc). No author.
    """

    text = "text"
    media = "media"
    system = "system"


class ChatThread(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    """One thread per quote — the natural conversation anchor.

    `last_message_at` is bumped on every append so the inbox feeds
    (driver: `/chat/threads`, business: same) can sort cheaply on the
    indexed column without a join + max() against `chat_messages`.
    """

    __tablename__ = "chat_threads"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    part_search_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("part_search_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("quote_id", name="uq_chat_threads_quote_id"),)


class ChatMessage(UuidPrimaryKey, Base):
    """Append-only chat message.

    Author is null for system messages. Media messages require a
    `media_asset_id`; the CHECK constraints in the migration enforce
    these invariants at the DB level so a buggy code path can't insert
    an inconsistent row.
    """

    __tablename__ = "chat_messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[ChatMessageKind] = mapped_column(
        SAEnum(ChatMessageKind, name="chat_message_kind", native_enum=True),
        nullable=False,
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(kind = 'system') OR (author_user_id IS NOT NULL)",
            name="ck_chat_messages_author_for_non_system",
        ),
        CheckConstraint(
            "(kind = 'media') = (media_asset_id IS NOT NULL)",
            name="ck_chat_messages_media_xor",
        ),
        CheckConstraint(
            "(kind = 'media') OR (body IS NOT NULL)",
            name="ck_chat_messages_body_for_text_system",
        ),
    )
