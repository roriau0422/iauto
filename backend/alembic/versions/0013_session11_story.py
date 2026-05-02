"""phase 2 session 11: iAuto Story feed.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-02

Spec section 10. Public Instagram-style timeline of business posts.
Flat comments (no parent_id), likes, chronological newest-first.

Adds:

1. `story` value to the existing `media_asset_purpose` enum so story
   posts can carry confirmed media assets.

2. `story_posts` — one post per business author. Denormalized
   `like_count` and `comment_count` are bumped in the same
   transaction as the like/comment so the feed can render counters
   without per-post subselects.

3. `story_likes` — composite PK pivot.

4. `story_comments` — flat list keyed by post_id.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend media_asset_purpose with `story`.
    #    ALTER TYPE ADD VALUE cannot run inside a transaction in
    #    Postgres, so we COMMIT before issuing it. Alembic 1.x's online
    #    migrations open a transaction by default; the explicit COMMIT
    #    + BEGIN dance keeps the migration atomic-enough at the row
    #    level (the enum extension is the only thing outside the txn).
    # ------------------------------------------------------------------
    op.execute("COMMIT")
    op.execute("ALTER TYPE media_asset_purpose ADD VALUE IF NOT EXISTS 'story'")
    op.execute("BEGIN")

    # ------------------------------------------------------------------
    # 2. story_posts
    # ------------------------------------------------------------------
    op.create_table(
        "story_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "media_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
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
            name="fk_story_posts_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_story_posts_author_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_posts"),
    )
    op.create_index(
        "ix_story_posts_created_at",
        "story_posts",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_story_posts_tenant_id_created_at",
        "story_posts",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 3. story_likes
    # ------------------------------------------------------------------
    op.create_table(
        "story_likes",
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["story_posts.id"],
            name="fk_story_likes_post_id_story_posts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_story_likes_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id", name="pk_story_likes"),
    )
    op.create_index("ix_story_likes_user_id", "story_likes", ["user_id"])

    # ------------------------------------------------------------------
    # 4. story_comments
    # ------------------------------------------------------------------
    op.create_table(
        "story_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["story_posts.id"],
            name="fk_story_comments_post_id_story_posts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_story_comments_author_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_comments"),
    )
    op.create_index(
        "ix_story_comments_post_id_created_at",
        "story_comments",
        ["post_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_story_comments_post_id_created_at", table_name="story_comments"
    )
    op.drop_table("story_comments")

    op.drop_index("ix_story_likes_user_id", table_name="story_likes")
    op.drop_table("story_likes")

    op.drop_index(
        "ix_story_posts_tenant_id_created_at", table_name="story_posts"
    )
    op.drop_index("ix_story_posts_created_at", table_name="story_posts")
    op.drop_table("story_posts")

    # `media_asset_purpose` keeps the `story` value — Postgres can't
    # drop a single enum value safely. Future migration that removes it
    # would need a full enum-recreate dance; we accept the dangling
    # value as the cost of the additive forward path.
