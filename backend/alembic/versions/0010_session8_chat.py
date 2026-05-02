"""phase 1 session 8: chat threads + messages.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-02

Session 8 introduces:

1. `chat_threads` — one per quote. Auto-created from the
   `marketplace.quote_sent` outbox event so the driver and the selling
   business can negotiate before the driver hits reserve.

2. `chat_messages` — append-only. Three kinds: `text` (free-form body),
   `media` (FK to a confirmed `media_assets` row), `system` (server-
   generated, e.g. "Thread created", "Reservation started").

The thread is naturally tenant-scoped (by `businesses.id`). The
`last_message_at` column is updated on every message append so the
inbox feeds can sort cheaply without a subselect.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # chat_threads
    # ------------------------------------------------------------------
    op.create_table(
        "chat_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_chat_threads_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_chat_threads_quote_id_quotes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["part_search_id"],
            ["part_search_requests.id"],
            name="fk_chat_threads_part_search_id_part_search_requests",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["users.id"],
            name="fk_chat_threads_driver_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_threads"),
        sa.UniqueConstraint("quote_id", name="uq_chat_threads_quote_id"),
    )
    op.create_index("ix_chat_threads_tenant_id", "chat_threads", ["tenant_id"])
    op.create_index(
        "ix_chat_threads_tenant_id_last_message_at",
        "chat_threads",
        ["tenant_id", sa.text("last_message_at DESC NULLS LAST")],
    )
    op.create_index(
        "ix_chat_threads_driver_id_last_message_at",
        "chat_threads",
        ["driver_id", sa.text("last_message_at DESC NULLS LAST")],
    )

    # ------------------------------------------------------------------
    # chat_messages
    # ------------------------------------------------------------------
    chat_message_kind_enum = postgresql.ENUM(
        "text",
        "media",
        "system",
        name="chat_message_kind",
        create_type=False,
    )
    chat_message_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", chat_message_kind_enum, nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_threads.id"],
            name="fk_chat_messages_thread_id_chat_threads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_chat_messages_author_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_chat_messages_media_asset_id_media_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        # System messages have no human author (kind='system' AND
        # author_user_id IS NULL) but text/media messages must have one.
        sa.CheckConstraint(
            "(kind = 'system') OR (author_user_id IS NOT NULL)",
            name="ck_chat_messages_author_for_non_system",
        ),
        # Media messages require a media_asset_id; non-media must not have one.
        sa.CheckConstraint(
            "(kind = 'media') = (media_asset_id IS NOT NULL)",
            name="ck_chat_messages_media_xor",
        ),
        # Text and system require a body; media may or may not have one.
        sa.CheckConstraint(
            "(kind = 'media') OR (body IS NOT NULL)",
            name="ck_chat_messages_body_for_text_system",
        ),
    )
    op.create_index(
        "ix_chat_messages_thread_id_created_at",
        "chat_messages",
        ["thread_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_thread_id_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    chat_message_kind_enum = postgresql.ENUM(
        "text",
        "media",
        "system",
        name="chat_message_kind",
    )
    chat_message_kind_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        "ix_chat_threads_driver_id_last_message_at", table_name="chat_threads"
    )
    op.drop_index(
        "ix_chat_threads_tenant_id_last_message_at", table_name="chat_threads"
    )
    op.drop_index("ix_chat_threads_tenant_id", table_name="chat_threads")
    op.drop_table("chat_threads")
