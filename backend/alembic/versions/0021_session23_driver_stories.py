"""phase 5 session 23: driver-authored stories.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-03

Stories used to be tenant-only — `story_posts.tenant_id NOT NULL` with a FK to
`businesses`. The mobile design wants the same feed to carry personal posts
from drivers too, so we relax `tenant_id` to nullable and stamp the row's
authorship intent with a fresh enum.

Adds:

1. `story_author_kind` enum: `driver` | `business`.

2. `story_posts.author_kind` column — required, with an `XOR`-style CHECK
   constraint binding it to `tenant_id`:

       (author_kind = 'business') = (tenant_id IS NOT NULL)

   Drivers MUST NOT carry a `tenant_id` (they aren't a tenant); businesses
   MUST. Backfill the existing rows with `author_kind='business'` because
   today every story_post has a tenant_id (see migration 0013).

3. `tenant_id` flips to nullable. The FK to `businesses` keeps its
   ON DELETE RESTRICT — a driver row will simply pass NULL.

The existing `(tenant_id, created_at DESC)` index keeps working: Postgres
B-tree indexes drop NULL keys by default, so business-tenant pagination
still scans only their rows. Driver feed reads scan the un-indexed branch
or the global `(created_at DESC)` index — fine for the scale we expect
in the launch year.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. story_author_kind enum
    # ------------------------------------------------------------------
    author_kind_enum = postgresql.ENUM(
        "driver",
        "business",
        name="story_author_kind",
        create_type=False,
    )
    author_kind_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Add author_kind column. Existing rows are all business posts —
    #    backfill with that value before flipping NOT NULL.
    # ------------------------------------------------------------------
    op.add_column(
        "story_posts",
        sa.Column("author_kind", author_kind_enum, nullable=True),
    )
    op.execute("UPDATE story_posts SET author_kind = 'business' WHERE author_kind IS NULL")
    op.alter_column("story_posts", "author_kind", nullable=False)

    # ------------------------------------------------------------------
    # 3. Relax tenant_id to nullable. The FK keeps its RESTRICT ON DELETE
    #    semantics; null rows simply have no FK target to enforce.
    # ------------------------------------------------------------------
    op.alter_column(
        "story_posts",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # 4. CHECK constraint: business posts must carry a tenant_id, driver
    #    posts must not.
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_story_posts_author_kind_tenant_xor",
        "story_posts",
        "(author_kind = 'business') = (tenant_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Drop the CHECK first — flipping tenant_id back to NOT NULL while it
    # is bound to a CHECK that references it would fail on rows where the
    # author_kind='driver' (and therefore tenant_id is null). Best-effort:
    # if any driver-authored rows exist, the operator must clean them
    # before downgrading.
    op.drop_constraint(
        "ck_story_posts_author_kind_tenant_xor",
        "story_posts",
        type_="check",
    )
    op.alter_column(
        "story_posts",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("story_posts", "author_kind")
    author_kind_enum = postgresql.ENUM(
        "driver",
        "business",
        name="story_author_kind",
    )
    author_kind_enum.drop(op.get_bind(), checkfirst=True)
