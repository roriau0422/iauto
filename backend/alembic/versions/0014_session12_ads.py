"""phase 2 session 12: paid ads system.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-02

Spec section 13. Self-served paid ads: a business creates a campaign,
pays via QPay (reusing the session-7 payment_intent flow), and the ad
goes live when the payment settles. Impressions and clicks count
against the budget at the bid CPM until the campaign is exhausted.

Adds:

1. `ad` value to the existing `media_asset_purpose` enum so campaigns
   can carry confirmed media assets.

2. `ad_campaigns` — one campaign per ad slot purchase. Status enum
   tracks the lifecycle (draft / pending_payment / active / paused /
   exhausted / cancelled).

3. `ad_impressions` — append-only impression log.

4. `ad_clicks` — append-only click log.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Extend media_asset_purpose with `ad`. Same COMMIT/BEGIN dance as
    # the session-11 `story` value extension.
    op.execute("COMMIT")
    op.execute("ALTER TYPE media_asset_purpose ADD VALUE IF NOT EXISTS 'ad'")
    op.execute("BEGIN")

    ad_placement_enum = postgresql.ENUM(
        "story_feed",
        "search_results",
        name="ad_placement",
        create_type=False,
    )
    ad_placement_enum.create(op.get_bind(), checkfirst=True)

    ad_status_enum = postgresql.ENUM(
        "draft",
        "pending_payment",
        "active",
        "paused",
        "exhausted",
        "cancelled",
        name="ad_campaign_status",
        create_type=False,
    )
    ad_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ad_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("placement", ad_placement_enum, nullable=False),
        sa.Column("budget_mnt", sa.Integer(), nullable=False),
        sa.Column("cpm_mnt", sa.Integer(), nullable=False),
        sa.Column("status", ad_status_enum, nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spent_mnt", sa.Integer(), nullable=False, server_default="0"),
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
            name="fk_ad_campaigns_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_ad_campaigns_media_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"],
            ["payment_intents.id"],
            name="fk_ad_campaigns_payment_intent_id_payment_intents",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ad_campaigns"),
        sa.CheckConstraint("budget_mnt > 0", name="ck_ad_campaigns_budget_positive"),
        sa.CheckConstraint("cpm_mnt > 0", name="ck_ad_campaigns_cpm_positive"),
    )
    op.create_index("ix_ad_campaigns_tenant_id", "ad_campaigns", ["tenant_id"])
    op.create_index(
        "ix_ad_campaigns_status_placement",
        "ad_campaigns",
        ["status", "placement"],
        # Partial index — the public `/active` query is the hot path
        # and only cares about active campaigns.
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_ad_campaigns_payment_intent_id",
        "ad_campaigns",
        ["payment_intent_id"],
        postgresql_where=sa.text("payment_intent_id IS NOT NULL"),
    )

    op.create_table(
        "ad_impressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["ad_campaigns.id"],
            name="fk_ad_impressions_campaign_id_ad_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["viewer_user_id"],
            ["users.id"],
            name="fk_ad_impressions_viewer_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ad_impressions"),
    )
    op.create_index(
        "ix_ad_impressions_campaign_id_created_at",
        "ad_impressions",
        ["campaign_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "ad_clicks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["ad_campaigns.id"],
            name="fk_ad_clicks_campaign_id_ad_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["viewer_user_id"],
            ["users.id"],
            name="fk_ad_clicks_viewer_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ad_clicks"),
    )
    op.create_index(
        "ix_ad_clicks_campaign_id_created_at",
        "ad_clicks",
        ["campaign_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_ad_clicks_campaign_id_created_at", table_name="ad_clicks")
    op.drop_table("ad_clicks")

    op.drop_index(
        "ix_ad_impressions_campaign_id_created_at", table_name="ad_impressions"
    )
    op.drop_table("ad_impressions")

    op.drop_index("ix_ad_campaigns_payment_intent_id", table_name="ad_campaigns")
    op.drop_index("ix_ad_campaigns_status_placement", table_name="ad_campaigns")
    op.drop_index("ix_ad_campaigns_tenant_id", table_name="ad_campaigns")
    op.drop_table("ad_campaigns")

    ad_status_enum = postgresql.ENUM(
        "draft",
        "pending_payment",
        "active",
        "paused",
        "exhausted",
        "cancelled",
        name="ad_campaign_status",
    )
    ad_status_enum.drop(op.get_bind(), checkfirst=True)

    ad_placement_enum = postgresql.ENUM(
        "story_feed",
        "search_results",
        name="ad_placement",
    )
    ad_placement_enum.drop(op.get_bind(), checkfirst=True)

    # `media_asset_purpose` keeps the `ad` value (same as session 11 — Postgres
    # can't drop enum values without a full recreate dance).
